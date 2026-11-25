#!/usr/bin/env python3
"""SoDEX Safety Guardian — per-minute autonomous protection for live positions & orders.

INDEPENDEN dari Claude/Codex. Berjalan 24/7 via systemd (Restart=always). Tujuan:
bila Claude tidak berjalan (limit), engine hang, atau watchdog gagal, posisi &
open-order di sodex.com TETAP aman, terjaga, dan terkendali.

Invariant yang ditegakkan tiap ≤60 detik:
  1. KILL-SWITCH  — file data/SAFETY_HALT ada → cancel SEMUA open order + alert.
  2. UNMANAGED    — engine mati > GRACE_SEC DAN ada open order → cancel semua
                    (order yang tak ada yang mengelola bisa terisi merugikan).
  3. STALE ORDER  — order umur > STALE_SEC saat engine HIDUP tapi tak ter-refresh
                    → cancel (engine seharusnya rotasi; order basi = risiko).
  4. MARGIN RISK  — perps margin usage > HARD_MARGIN_PCT → ALERT (tidak auto-flatten;
                    flatten otomatis terlalu berisiko — operator yang putuskan).
  5. HEARTBEAT    — tulis data/safety_guardian_heartbeat.json tiap siklus (bukti hidup).

Desain konservatif: default read-only; hanya CANCEL pada kondisi jelas (halt /
unmanaged / stale). TIDAK pernah auto-flatten posisi. Stdlib-only + bin/sodex CLI.

ponytail: satu loop, satu file. Aksi proteksi = cancel order (reversible-aman),
bukan flatten posisi (irreversible-berisiko).
"""
import fcntl, json, os, subprocess, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _normalize_systemd_environment() -> None:
    """Strip shell-style inline comments from SoDEX numeric settings.

    systemd's ``EnvironmentFile`` keeps inline comments as part of a value.
    Normalizing the project-owned prefixes prevents numeric configuration from
    crashing the independent guardian at import time.
    """
    prefixes = ("TE_", "PVE_", "HONEST_", "GUARDIAN_", "SODEX_")
    for key, value in list(os.environ.items()):
        if key.startswith(prefixes) and "#" in value:
            os.environ[key] = value.split("#", 1)[0].strip()


_normalize_systemd_environment()

PROJECT = Path(os.environ.get("ANANTARA_DIR", str(Path(__file__).resolve().parent.parent)))
SODEX_CLI = str(PROJECT / "bin" / "sodex")
SODEX_API = os.environ.get("SODEX_BASE_URL", "https://mainnet-gw.sodex.dev/api/v1").rstrip("/")
LOG = PROJECT / "logs" / "safety_guardian.log"
HEARTBEAT = PROJECT / "data" / "safety_guardian_heartbeat.json"
HALT_FILE = PROJECT / "data" / "SAFETY_HALT"
ENGINE_ALIVE_TS = PROJECT / "data" / "engine_last_alive.json"
SODEX_CLI_LOCK = Path("/tmp/sodex_cli.lock")

CHECK_INTERVAL = 60          # detik — per-menit
GRACE_SEC = 180              # engine mati > 3 mnt + ada order → unmanaged → cancel
STALE_SEC = 600             # order umur > 10 mnt saat engine hidup → cancel (basi)
HARD_MARGIN_PCT = 90.0       # margin usage > 90% → alert
ALERT_COOLDOWN = 300         # detik antara alert sejenis (anti-spam)

# ── Per-engine cumulative-PnL circuit breaker (anti death-by-thousand-cuts) ──
# Pelajaran E2: 605 RT, WR 3.5%, rugi -$35.90 menetes pelan (avg -$0.06/RT) tanpa
# satu trade pun memicu alarm per-posisi → bleed tak terdeteksi 8 hari. Diskriminan
# yang memisahkan engine rusak (E2 WR 3.5%) dari engine sehat (E1 WR 93.5%) adalah
# WIN RATE, bukan rugi-per-volume (notional perp E2 besar → rugi hanya ~1 bps).
# Window auto-scope ke engine LIVE: engine mati tak punya RT baru → tak dievaluasi.
TE_DB = PROJECT / os.environ.get("TE_DB", "twin_engine.db")
PNL_BREAKER_ON = os.environ.get("GUARDIAN_PNL_BREAKER", "1") == "1"
PNL_WINDOW_H   = float(os.environ.get("GUARDIAN_PNL_WINDOW_H", "24"))   # rolling lookback
PNL_MIN_N      = int(os.environ.get("GUARDIAN_PNL_MIN_N", "30"))        # sampel minimum
PNL_WR_FLOOR   = float(os.environ.get("GUARDIAN_PNL_WR_FLOOR", "0.35")) # WR < ini = rusak
PNL_LOSS_USD   = float(os.environ.get("GUARDIAN_PNL_LOSS_USD", "10"))   # rugi window pemicu
# backstop: bleed lambat dgn WR sedang
PNL_BLEED_N    = int(os.environ.get("GUARDIAN_PNL_BLEED_N", "50"))
PNL_BLEED_USD  = float(os.environ.get("GUARDIAN_PNL_BLEED_USD", "25"))
PNL_BLEED_WR   = float(os.environ.get("GUARDIAN_PNL_BLEED_WR", "0.55"))

# ── Ratio floor (Opsi B: bounded-cost volume farming) ──────────────────────────
# User mandate 2026-07-04: farm volume, but keep REAL ratio volume/cost >= 8650,
# i.e. realized cost must stay <= volume/8650. Rolling 7d. Current state is
# profit-funded (cost=0 → ratio infinite → never trips). This guard only fires if
# the edge turns negative enough that cost exceeds the volume/8650 budget.
# Ratio breaches pause only the volume engine. E1 has a separate statistical PnL
# breaker; a tiny negative E1 sample must not turn a PVE efficiency breach into a
# global halt and prevent the profit lane from repairing the ratio.
RATIO_FLOOR    = float(os.environ.get("GUARDIAN_RATIO_FLOOR", "8650"))
RATIO_WINDOW_H = float(os.environ.get("GUARDIAN_RATIO_WINDOW_H", "168"))  # 7d
RATIO_MIN_VOL  = float(os.environ.get("GUARDIAN_RATIO_MIN_VOL", "7000"))  # need real volume first
HONEST_RATIO_STATE = PROJECT / "data" / "honest_ratio_experiment.json"

# ── Perps OPEN-position early-warning (blind-spot PnL breaker: hanya lihat RT yang
# SUDAH ditutup; posisi terbuka tak terpantau). Insiden WLD: open leg terisi, close
# leg telat, klip baru dibuka → notional terarah menumpuk jadi ~3× klip; rugi $ membesar
# walau gerak % kecil (5x leverage). Dua sinyal dini, ALERT-only (read-only, TIDAK
# auto-close — aturan: alert/cancel, bukan flatten irreversible):
#   drift : notional 1 pair > MULT × klip PVE  (inventory menumpuk)
#   roe   : unrealized ROE per posisi < ROE_FLOOR%  (rugi dalam karena leverage)
POS_RISK_ON       = os.environ.get("GUARDIAN_POS_RISK", "1") == "1"
POS_CLIP_USD      = float(os.environ.get("TE_PVE_MAX_NOTIONAL", "30"))    # klip PVE (shared)
POS_NOTIONAL_MULT = float(os.environ.get("GUARDIAN_POS_NOTIONAL_MULT", "2.5"))
POS_ROE_FLOOR     = float(os.environ.get("GUARDIAN_POS_ROE_FLOOR", "-15"))  # ROE% pemicu

# ── Engine STALL detector (blind-spot ke-3: PnL breaker BUTUH RT utk dievaluasi —
# engine yang BEKU/HANG berhenti menghasilkan RT → tak terlihat breaker secara
# struktural. Insiden E1: seluruh modal terkunci di resting sell, sell-only, idle —
# butuh 30 mnt baca log utk tahu "draining, bukan beku". Sinyal: engine yang BARU
# aktif (RT terakhir dalam LOOKBACK) tapi mendadak diam > STALL_H. ALERT-only
# (pasar sepi / drain inventory sah bisa berjeda; halt akan batalkan resting order
# sehat & hentikan drain). Engine mati lama (E2 176h) → IDLE, bukan STALLED → tak spam.
STALL_ON         = os.environ.get("GUARDIAN_STALL", "1") == "1"
STALL_H          = float(os.environ.get("GUARDIAN_STALL_H", "6"))          # diam > ini = stall
STALL_LOOKBACK_H = float(os.environ.get("GUARDIAN_STALL_LOOKBACK_H", "48"))  # "baru aktif" window

# ── Weekly PVE NET floor kill-switch (FIX: kill-switch tidak terpicu saat NET < floor) ──
# Analisis insiden: weekly NET PVE -$26 < floor -$25 tapi kill-switch TIDAK terpicu.
# Root cause: safety_guardian hanya punya WR-based breaker (T1/T2); TIDAK ada cek weekly
# NET total PVE vs floor absolut. Solusi: check_weekly_pve_floor() di setiap cycle.
# PVE_PAUSE_FILE bukan SAFETY_HALT — E1 spot TETAP berjalan, hanya PVE dihentikan.
WEEKLY_PVE_FLOOR   = float(os.environ.get("GUARDIAN_WEEKLY_PVE_FLOOR", "-25"))  # USD/week
WEEKLY_PVE_MIN_N   = int(os.environ.get("GUARDIAN_WEEKLY_PVE_MIN_N", "20"))     # min RTs sebelum trigger
PVE_PAUSE_FILE     = PROJECT / "data" / "PVE_PAUSE"
RESTART_SIGNAL     = PROJECT / "data" / "GUARDIAN_RESTART_SIGNAL"  # watchdog polls → restart engine

# ── PVE health thresholds (monitoring 24h) ──
PVE_WR_FLOOR_24H   = float(os.environ.get("GUARDIAN_PVE_WR_FLOOR_24H", "0.40"))    # WR < 40% → alert
PVE_FEE_RATIO_MAX  = float(os.environ.get("GUARDIAN_PVE_FEE_RATIO_MAX", "0.0002")) # fee/vol > 0.02% → alert

# Symbol → symbol-id (selaras dengan engine _SYMBOL_MAP; untuk cancel standalone)
SYMBOL_ID = {
    "PEPE": 5, "SHIB": 15, "SOL": 7, "XLM": 22, "DOGE": 8, "ADA": 11,
    "BTC": 1, "ETH": 2, "HYPE": 12, "XAUT": 11, "ENA": 25, "XPL": 21, "TON": 79, "SPCX": 81,
    "ZEC": 18,  # BUG-K: was missing → cancel_order() silently skipped ZEC perp orphans
}

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
_last_alert: dict[str, float] = {}


def log(msg: str) -> None:
    # BUG-L fix: print() alone is sufficient — systemd StandardOutput=append: handles file write.
    # Direct open(LOG,"a") was doubling every line when run under systemd.
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] {msg}"
    print(line, flush=True)


def tg_send(msg: str, key: str = "") -> None:
    if not (TG_TOKEN and TG_CHAT):
        return
    if key:
        if time.time() - _last_alert.get(key, 0.0) < ALERT_COOLDOWN:
            return
        _last_alert[key] = time.time()
    try:
        data = json.dumps({"chat_id": TG_CHAT, "text": ("🛡️ GUARDIAN\n" + msg)[:4000]}).encode()
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        urllib.request.urlopen(
            urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}),
            timeout=10,
        )
    except Exception:
        pass


def _env_address() -> str:
    addr = os.environ.get("SODEX_ADDRESS", "")
    if addr:
        return addr
    try:
        for line in (PROJECT / ".env").read_text().splitlines():
            if line.startswith("SODEX_ADDRESS="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _cli(args: list[str], timeout: float = 20.0) -> object:
    """Jalankan bin/sodex, kembalikan JSON parsed atau None."""
    try:
        with SODEX_CLI_LOCK.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            r = subprocess.run([SODEX_CLI, *args], cwd=str(PROJECT), capture_output=True,
                               text=True, timeout=timeout, env=dict(os.environ))
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout)
    except Exception:
        return None


def _api_get(path: str) -> object:
    try:
        with urllib.request.urlopen(SODEX_API + path, timeout=12) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def list_open_orders() -> list[dict]:
    """Open order spot + perps via CLI (read-only)."""
    out: list[dict] = []
    for market in ("spot", "perps"):
        j = _cli(["orders", "list", market, "--format", "json"])
        rows = j if isinstance(j, list) else (j.get("data") if isinstance(j, dict) else None) or []
        for o in rows:
            if isinstance(o, dict):
                o["_market"] = market
                out.append(o)
    return out


def _symbol_id_for(sym: str) -> int | None:
    s = sym.upper()
    for base, sid in SYMBOL_ID.items():
        if base in s:
            return sid
    return None


def cancel_order(o: dict) -> bool:
    market = o.get("_market", "spot")
    oid = str(o.get("orderID") or o.get("orderId") or "")
    cl_id = str(o.get("clOrdID") or o.get("clOrdId") or "")
    sym = str(o.get("symbol") or "")
    sid = _symbol_id_for(sym)
    if sid is None or (not oid and not cl_id):
        log(f"cancel skip: tak bisa derive sid/oid utk {o}")
        return False
    args = ["orders", "cancel", market, "--symbol-id", str(sid), "--format", "json"]
    if oid:
        args += ["--order-id", oid]
    if cl_id and market == "spot":  # spot butuh cl-ord-id juga
        args += ["--cl-ord-id", cl_id]
    res = _cli(args, timeout=15)
    ok = res is not None
    log(f"cancel {market} {sym} oid={oid} → {'OK' if ok else 'GAGAL'}")
    return ok


def cancel_all(reason: str) -> int:
    orders = list_open_orders()
    if not orders:
        return 0
    n = sum(1 for o in orders if cancel_order(o))
    log(f"CANCEL-ALL ({reason}): {n}/{len(orders)} order dibatalkan")
    tg_send(f"⚠️ CANCEL-ALL ({reason}): {n}/{len(orders)} order dibatalkan demi keamanan.", key=f"cancelall:{reason}")
    return n


def engine_alive() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", "sodex_twin_engine.py run"],
                           capture_output=True, text=True, timeout=5)
        return bool(r.stdout.strip())
    except Exception:
        return False


def engine_dead_secs() -> float:
    """Detik sejak engine terakhir terlihat hidup (persist lintas restart guardian)."""
    now = time.time()
    if engine_alive():
        try:
            HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
            ENGINE_ALIVE_TS.write_text(json.dumps({"ts": now}))
        except Exception:
            pass
        return 0.0
    try:
        last = float(json.loads(ENGINE_ALIVE_TS.read_text()).get("ts", now))
    except Exception:
        last = now
    return now - last


def check_margin(address: str) -> None:
    state = _api_get(f"/perps/accounts/{address}/state")
    if not isinstance(state, dict):
        return
    d = state.get("data", state)
    try:
        mu = d.get("marginUsage") or d.get("margin_usage")
        if mu is None:
            used = float(d.get("marginUsed", 0) or 0)
            equity = float(d.get("accountValue", 0) or d.get("equity", 0) or 0)
            mu = (used / equity * 100.0) if equity > 0 else 0.0
        mu = float(mu)
        if mu <= 1.5:  # beberapa API kembalikan fraksi (0..1)
            mu *= 100.0
        if mu > HARD_MARGIN_PCT:
            tg_send(f"🔴 MARGIN RISK: usage {mu:.1f}% > {HARD_MARGIN_PCT:.0f}%. "
                    f"Posisi perps berisiko likuidasi — operator harap cek.", key="margin")
            log(f"MARGIN RISK: {mu:.1f}%")
    except Exception:
        pass


def _pnum(d: dict, *keys) -> float:
    """Ambil field numerik pertama yg ada (toleran: raw API s/sz/ep/ur/iw atau ternormalisasi)."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except Exception:
                pass
    return 0.0


def evaluate_position_risk(positions, clip_usd: float, mult: float, roe_floor: float):
    """Pure: positions = list dict posisi perps → {symbol: reason} early-warning (ALERT-only).

    Dua pemicu independen (read-only — TIDAK menutup posisi):
      drift : notional 1 pair > mult × clip_usd  (inventory menumpuk > N klip)
      roe   : unrealized ROE per posisi < roe_floor%  (uPnL/margin, rugi dalam karena leverage)
    Toleran raw API (s/sz/ep/ur/iw) maupun ternormalisasi (symbol/quantity/entryPrice/...).
    """
    alerts: dict[str, str] = {}
    trip = max(clip_usd * mult, 0.0)
    for p in positions or []:
        if not isinstance(p, dict) or p.get("warning"):  # sentinel api_unverified → skip
            continue
        sym = p.get("s") or p.get("symbol") or "?"
        sz = abs(_pnum(p, "sz", "quantity", "size"))
        if sz < 1e-9:
            continue
        ep = _pnum(p, "ep", "entryPrice", "entry")
        ur = _pnum(p, "ur", "unrealizedPnl", "unrealized")
        iw = _pnum(p, "iw", "margin", "isolatedMargin")
        notional = sz * ep
        reasons = []
        if trip > 0 and notional > trip:
            reasons.append(f"inventory_drift notional=${notional:.0f}>{mult:g}×clip(${clip_usd:.0f})")
        if iw > 0:
            roe = ur / iw * 100.0
            if roe < roe_floor:
                reasons.append(f"roe={roe:.1f}%<{roe_floor:.0f}% (uPnL=${ur:.2f})")
        if reasons:
            alerts[sym] = "; ".join(reasons)
    return alerts


def check_position_risk(address: str) -> None:
    """Early-warning posisi perps terbuka (drift inventory / uPnL dalam). ALERT-only, read-only."""
    if not (POS_RISK_ON and address):
        return
    state = _api_get(f"/perps/accounts/{address}/state")
    if not isinstance(state, dict):
        return
    P = (state.get("data", state) or {}).get("P")
    if not isinstance(P, list):
        return
    alerts = evaluate_position_risk(P, POS_CLIP_USD, POS_NOTIONAL_MULT, POS_ROE_FLOOR)
    if not alerts:
        return
    detail = " | ".join(f"{s}: {r}" for s, r in sorted(alerts.items()))
    log(f"POSITION RISK — {detail}")
    tg_send(f"🟠 POSISI PERPS perlu dilihat (read-only, guardian TIDAK auto-close):\n{detail}\n"
            f"Cek drift inventory / unrealized PnL.", key="pos_risk")


def _pve_weekly_stats() -> dict:
    """Baca PVE 7d stats dari DB (untuk heartbeat & report). Fail-silent → {}."""
    if not TE_DB.exists():
        return {}
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True, timeout=5)
        r = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(CAST(net_pnl AS REAL)),0), "
            "SUM(CASE WHEN CAST(net_pnl AS REAL)>0 THEN 1 ELSE 0 END), "
            "COALESCE(SUM(CAST(volume AS REAL)),0) "
            "FROM rts WHERE engine='PVE' AND ts_close>=datetime('now','-7 days')"
        ).fetchone()
        con.close()
        n, cum, wins, vol = (int(r[0] or 0), float(r[1] or 0),
                             int(r[2] or 0), float(r[3] or 0)) if r else (0, 0, 0, 0)
        wr = wins / n if n else 0.0
        return {
            "n_7d": n, "cum_7d": round(cum, 4), "wr_7d": round(wr, 4),
            "vol_7d": round(vol, 2), "floor_usd": WEEKLY_PVE_FLOOR,
            "pct_to_floor": round(cum / abs(WEEKLY_PVE_FLOOR) * 100, 1) if WEEKLY_PVE_FLOOR else 0,
        }
    except Exception:
        return {}


def write_heartbeat(orders_n: int, eng_dead: float) -> None:
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "open_orders": orders_n,
            "engine_dead_secs": round(eng_dead, 1),
            "halt_active": HALT_FILE.exists(),
            "pve_pause_active": PVE_PAUSE_FILE.exists(),
            "pve_7d": _pve_weekly_stats(),
        }, indent=2))
    except Exception:
        pass


def _ts_epoch(ts) -> float:
    """ts_close di rts = ISO-8601 string; fallback epoch float."""
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        try:
            return float(ts)
        except Exception:
            return 0.0


def evaluate_pnl_breaches(rows, now_ts: float):
    """Pure: rows = [(engine, ts_close, net_pnl), ...] → {engine: reason} yang melanggar.

    Pemicu (keduanya butuh rugi nyata; tak bisa false-fire engine sehat WR tinggi):
      T1 'broken_signal' : n>=MIN_N  & WR<WR_FLOOR  & cum<=-LOSS_USD
      T2 'sustained_bleed': n>=BLEED_N & WR<BLEED_WR & cum<=-BLEED_USD
    """
    cutoff = now_ts - PNL_WINDOW_H * 3600.0
    agg: dict[str, list] = {}
    for eng, ts, pnl in rows:
        if _ts_epoch(ts) < cutoff:
            continue
        e = eng or "?"
        p = float(pnl) if pnl not in (None, "") else 0.0
        a = agg.setdefault(e, [0, 0.0, 0])  # n, cum, wins
        a[0] += 1; a[1] += p; a[2] += (1 if p > 0 else 0)
    breaches = {}
    for e, (n, cum, wins) in agg.items():
        wr = wins / n if n else 0.0
        if n >= PNL_MIN_N and wr < PNL_WR_FLOOR and cum <= -PNL_LOSS_USD:
            breaches[e] = f"broken_signal n={n} WR={wr*100:.1f}% cum=${cum:.2f}"
        elif n >= PNL_BLEED_N and wr < PNL_BLEED_WR and cum <= -PNL_BLEED_USD:
            breaches[e] = f"sustained_bleed n={n} WR={wr*100:.1f}% cum=${cum:.2f}"
    return breaches


def check_pnl_breaker() -> bool:
    """Baca ledger live, halt engine yang nge-bleed sebelum rugi membesar. → True jika halt."""
    if not (PNL_BREAKER_ON and TE_DB.exists()):
        return False
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True, timeout=5)
        rows = con.execute("SELECT engine, ts_close, net_pnl FROM rts").fetchall()
        con.close()
    except Exception as e:
        log(f"pnl_breaker db error: {e}")
        return False
    breaches = evaluate_pnl_breaches(rows, time.time())
    if not breaches:
        return False
    detail = " | ".join(f"{e}: {r}" for e, r in sorted(breaches.items()))
    log(f"PNL BREAKER TRIP — {detail}")
    if not HALT_FILE.exists():
        try:
            HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
            HALT_FILE.write_text(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "source": "sodex_safety_guardian",
                "reason": f"pnl_breaker {detail}",
            }, indent=2))
        except Exception as e:
            log(f"pnl_breaker halt-write error: {e}")
    tg_send(f"🔴 PNL BREAKER — engine nge-bleed, SAFETY_HALT ditulis:\n{detail}\n"
            f"Order akan dibatalkan; operator harap review sebelum re-enable.",
            key="pnl_breaker")
    return True


def _load_rts():
    """Baca ledger live (read-only) → list[(engine, ts_close, net_pnl)] atau None."""
    if not TE_DB.exists():
        return None
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True, timeout=5)
        rows = con.execute("SELECT engine, ts_close, net_pnl FROM rts").fetchall()
        con.close()
        return rows
    except Exception as e:
        log(f"rts load error: {e}")
        return None


def evaluate_engine_health(rows, now_ts: float):
    """Pure: rows=[(engine, ts_close, net_pnl),...] → {engine: {...}} evaluasi per-engine.

    Stats di window PNL_WINDOW_H; last_age_h = umur RT terakhir (kapan pun).
    Verdict (terburuk-dulu):
      BLEEDING : lolos kriteria PnL-breaker (rugi nyata + WR rendah)
      STALLED  : baru aktif (RT terakhir dalam LOOKBACK) tapi diam > STALL_H
                 → blind-spot breaker (engine beku tak punya RT utk dievaluasi)
      IDLE     : tak ada RT dalam window (engine mati/disabled) — bukan masalah
      HEALTHY  : selain itu
    """
    cutoff = now_ts - PNL_WINDOW_H * 3600.0
    agg: dict[str, list] = {}   # engine -> [n, cum, wins, last_ts]
    for eng, ts, pnl in rows:
        e = eng or "?"
        t = _ts_epoch(ts)
        p = float(pnl) if pnl not in (None, "") else 0.0
        a = agg.setdefault(e, [0, 0.0, 0, 0.0])
        if t >= cutoff:
            a[0] += 1; a[1] += p; a[2] += (1 if p > 0 else 0)
        if t > a[3]:
            a[3] = t
    out: dict[str, dict] = {}
    for e, (n, cum, wins, last_ts) in agg.items():
        wr = wins / n if n else 0.0
        age_h = (now_ts - last_ts) / 3600.0 if last_ts else float("inf")
        if (n >= PNL_MIN_N and wr < PNL_WR_FLOOR and cum <= -PNL_LOSS_USD) or \
           (n >= PNL_BLEED_N and wr < PNL_BLEED_WR and cum <= -PNL_BLEED_USD):
            verdict = "BLEEDING"
        elif STALL_H < age_h <= STALL_LOOKBACK_H:
            verdict = "STALLED"
        elif n == 0:
            verdict = "IDLE"
        else:
            verdict = "HEALTHY"
        out[e] = {"n": n, "wr": wr, "cum": cum, "last_age_h": age_h, "verdict": verdict}
    return out


def check_weekly_pve_floor() -> bool:
    """Kill-switch fix: PVE weekly NET < floor → tulis PVE_PAUSE + signal watchdog restart.

    Scientific rationale (insiden analisis):
      - CHZ phantom & SPCX slippage berlangsung gradual (berhari-hari), tidak terdeteksi
        T1/T2 WR-based breaker karena WR PVE masih cukup tinggi walau net negatif.
      - Weekly NET total (bukan rolling WR) adalah sinyal yang TEPAT untuk kill-switch ini.
      - Min-N guard (default 20 RT) mencegah false-fire di awal minggu (sample kecil).
      - PVE_PAUSE_FILE (bukan SAFETY_HALT) → E1 spot TETAP berjalan, only PVE paused.
      - RESTART_SIGNAL ditulis → watchdog restart engine tanpa TE_PVE_ENABLED=1.

    Returns True jika floor dilanggar (dan tindakan diambil).
    """
    if not TE_DB.exists():
        return False
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True, timeout=5)
        r = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(CAST(net_pnl AS REAL)),0), "
            "SUM(CASE WHEN CAST(net_pnl AS REAL)>0 THEN 1 ELSE 0 END), "
            "COALESCE(SUM(CAST(volume AS REAL)),0) "
            "FROM rts WHERE engine='PVE' AND ts_close>=datetime('now','-7 days')"
        ).fetchone()
        con.close()
    except Exception as e:
        log(f"weekly_pve_floor db error: {e}")
        return False

    if not r:
        return False
    n, cum, wins, vol = int(r[0] or 0), float(r[1] or 0), int(r[2] or 0), float(r[3] or 0)
    wr = wins / n if n else 0.0
    net_rate = cum / vol * 100 if vol else 0.0

    if n < WEEKLY_PVE_MIN_N:
        log(f"weekly_pve_floor: n={n} < MIN_N={WEEKLY_PVE_MIN_N} — fail-open (data insufficient)")
        return False

    if cum > WEEKLY_PVE_FLOOR:
        return False  # Floor tidak dilanggar, sehat

    if PVE_PAUSE_FILE.exists():
        return True  # Sudah paused, tidak perlu tulis ulang

    # Floor dilanggar → tulis PVE_PAUSE + sinyal restart
    detail = (f"PVE 7d: n={n} WR={wr*100:.1f}% cum=${cum:.2f} < floor=${WEEKLY_PVE_FLOOR:.0f} "
              f"net_rate={net_rate:+.4f}%/vol vol=${vol:.0f}")
    log(f"WEEKLY PVE FLOOR BREACH — {detail}")

    payload = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": "sodex_safety_guardian.check_weekly_pve_floor",
        "reason": detail,
        "n_7d": n, "cum_7d": round(cum, 4), "wr_7d": round(wr, 4),
        "floor_usd": WEEKLY_PVE_FLOOR, "vol_7d": round(vol, 2),
    }, indent=2)

    try:
        PVE_PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PVE_PAUSE_FILE.write_text(payload)
    except Exception as e:
        log(f"weekly_pve_floor write PVE_PAUSE error: {e}")

    # Signal watchdog untuk restart engine (tanpa PVE)
    try:
        RESTART_SIGNAL.parent.mkdir(parents=True, exist_ok=True)
        RESTART_SIGNAL.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": "sodex_safety_guardian.weekly_pve_floor",
            "type": "pve_floor_breach",
            "detail": detail,
            "message": "Weekly PVE NET < floor — restart engine without PVE",
        }))
    except Exception as e:
        log(f"weekly_pve_floor write RESTART_SIGNAL error: {e}")

    tg_send(
        f"🔴 WEEKLY PVE FLOOR BREACH — PVE di-PAUSE:\n{detail}\n\n"
        f"✅ E1 spot TETAP berjalan.\n"
        f"❌ PVE dihentikan (data/PVE_PAUSE ditulis).\n"
        f"⚙️ Watchdog akan restart engine tanpa PVE.\n\n"
        f"Re-enable PVE (setelah review):\n"
        f"  rm data/PVE_PAUSE && systemctl --user restart sodex-twin-watchdog\n"
        f"\nReport: python3 scripts/sodex_safety_guardian.py --report",
        key="weekly_pve_floor"
    )
    return True


def check_pve_health() -> None:
    """Monitor PVE 24h performance: WR, fee efficiency, net rate. ALERT-only, read-only.

    Melengkapi weekly floor check dengan sinyal harian yang lebih sensitif:
      - WR < 40% dalam 24h (n≥20): phantom fills / spread terlalu sempit
      - fee/volume > 0.02%: SoPoints ratio target (1:6000) terancam
      - net rate negatif: pair beroperasi di bawah break-even jangka pendek
    """
    if not (TE_DB.exists()):
        return
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True, timeout=5)
        r = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(CAST(net_pnl AS REAL)),0), "
            "SUM(CASE WHEN CAST(net_pnl AS REAL)>0 THEN 1 ELSE 0 END), "
            "COALESCE(SUM(CAST(volume AS REAL)),0) "
            "FROM rts WHERE engine='PVE' AND ts_close>=datetime('now','-24 hours')"
        ).fetchone()
        rf = con.execute(
            "SELECT COALESCE(SUM(CAST(fee AS REAL)),0) "
            "FROM fills WHERE engine='PVE' AND ts>=datetime('now','-24 hours')"
        ).fetchone()
        con.close()
    except Exception as e:
        log(f"pve_health db error: {e}")
        return

    n = int(r[0] or 0) if r else 0
    if n < 10:
        return  # Insufficient data
    cum = float(r[1] or 0)
    wins = int(r[2] or 0)
    vol = float(r[3] or 0)
    fee = float(rf[0] or 0) if rf else 0.0
    wr = wins / n
    net_rate = cum / vol if vol else 0.0
    fee_ratio = fee / vol if vol else 0.0

    alerts = []
    if wr < PVE_WR_FLOOR_24H:
        alerts.append(f"WR={wr*100:.1f}% < {PVE_WR_FLOOR_24H*100:.0f}% (n={n})")
    if fee_ratio > PVE_FEE_RATIO_MAX and vol > 500:
        alerts.append(f"fee/vol={fee_ratio*100:.4f}% > {PVE_FEE_RATIO_MAX*100:.4f}% "
                      f"(ratio 1:{vol/fee:.0f}, target 1:7000)")
    if n >= 30 and net_rate < -0.0001:  # net rate < -0.01%
        alerts.append(f"net_rate={net_rate*100:+.4f}% (di bawah break-even)")

    if not alerts:
        return
    detail = " | ".join(alerts)
    log(f"PVE HEALTH ALERT — {detail}")
    tg_send(
        f"🟠 PVE HEALTH 24h:\n{detail}\n"
        f"n={n} WR={wr*100:.1f}% cum=${cum:.2f} fee=${fee:.2f} vol=${vol:.0f}\n"
        f"Review: spread SPCX-USD & pair conditions.",
        key="pve_health"
    )


def check_engine_stall() -> None:
    """Alert dini: engine baru aktif tapi mendadak diam (beku/hang). ALERT-only, read-only."""
    if not STALL_ON:
        return
    rows = _load_rts()
    if rows is None:
        return
    stalled = {e: h for e, h in evaluate_engine_health(rows, time.time()).items()
               if h["verdict"] == "STALLED"}
    if not stalled:
        return
    detail = " | ".join(f"{e}: diam {h['last_age_h']:.1f}h" for e, h in sorted(stalled.items()))
    log(f"ENGINE STALL — {detail}")
    tg_send(f"🟡 ENGINE STALL (read-only, guardian TIDAK auto-act):\n{detail}\n"
            f"Engine beku tak terlihat PnL-breaker (tak ada RT utk dievaluasi). "
            f"Operator cek apakah hang/beku.", key="stall")


def report_engine_health() -> int:
    """On-demand evaluasi per-engine (--report): n/WR/cum/umur-RT-terakhir/verdict + PVE floor."""
    rows = _load_rts()
    if rows is None:
        print("no ledger")
        return 1
    lines = []
    for e, h in sorted(evaluate_engine_health(rows, time.time()).items()):
        age = "inf" if h["last_age_h"] == float("inf") else f"{h['last_age_h']:.1f}h"
        lines.append(f"{e:5} {h['verdict']:8} n={h['n']:<4} WR={h['wr']*100:5.1f}% "
                     f"cum=${h['cum']:+.2f} last={age}")
    # Tambah PVE weekly floor status
    pve = _pve_weekly_stats()
    floor_status = "PAUSED" if PVE_PAUSE_FILE.exists() else \
                   ("⚠️ NEAR_FLOOR" if pve.get("cum_7d", 0) < WEEKLY_PVE_FLOOR * 0.75 else "OK")
    if pve:
        lines.append(
            f"\nPVE FLOOR 7d: cum=${pve.get('cum_7d',0):+.2f} floor=${WEEKLY_PVE_FLOOR:.0f} "
            f"({pve.get('pct_to_floor',0):.0f}% used) WR={pve.get('wr_7d',0)*100:.1f}% "
            f"n={pve.get('n_7d',0)} → {floor_status}"
        )
    lines.append(f"HALT: {HALT_FILE.exists()} | PVE_PAUSE: {PVE_PAUSE_FILE.exists()}")
    body = "\n".join(lines) if lines else "(no engines)"
    print(body)
    tg_send("📊 ENGINE HEALTH + PVE FLOOR\n" + body)
    return 0


def _evaluate_ratio_floor_pure(rows, now_ts, floor, window_h, min_vol):
    """Pure: rows=[(engine, ts_close, volume, net_pnl),...] → bounded-cost decision.
    Returns (breached, vol, cost, ratio, action, detail).
      action: 'PVE_PAUSE' (perps only) | None. E1 is governed independently by
      the sample-size and loss thresholds in check_pnl_breaker().
    Ratio = volume/cost where cost=max(0,-sum(pnl)). Profit (cost=0) → ratio inf → never breach.
    """
    cutoff = now_ts - window_h * 3600.0
    vol = 0.0; pnl = 0.0; per: dict[str, float] = {}
    for eng, ts, v, p in rows:
        if _ts_epoch(ts) < cutoff:
            continue
        vv = float(v) if v not in (None, "") else 0.0
        pp = float(p) if p not in (None, "") else 0.0
        vol += vv; pnl += pp
        per[eng or "?"] = per.get(eng or "?", 0.0) + pp
    cost = max(0.0, -pnl)
    if vol < min_vol or cost <= 0.0:
        return (False, round(vol, 2), round(cost, 4),
                float("inf") if cost <= 0 else round(vol / cost, 1), None, "profit/insufficient")
    ratio = vol / cost
    if ratio >= floor:
        return (False, round(vol, 2), round(cost, 4), round(ratio, 1), None, "within budget")
    e1_net = per.get("E1", 0.0)
    action = "PVE_PAUSE"
    detail = f"ratio 1:{ratio:,.0f} < 1:{floor:,.0f} vol=${vol:,.0f} cost=${cost:.2f} E1_net=${e1_net:.2f}"
    return (True, round(vol, 2), round(cost, 4), round(ratio, 1), action, detail)


def _fixed_ratio_window_warming(now_ts: float) -> bool:
    """Return True while an operator-owned fixed ratio window is incomplete."""
    try:
        state = json.loads(HONEST_RATIO_STATE.read_text())
        if state.get("ratio_policy") != "fixed_24h_window":
            return False
        started = _ts_epoch(state.get("ts_start"))
        hours = float(state.get("window_hours", 24))
        return started > 0 and now_ts < started + hours * 3600
    except (OSError, ValueError, TypeError):
        return False


def check_ratio_floor() -> bool:
    """Enforce the ratio floor without pre-empting a fixed 24h evaluation window."""
    if not TE_DB.exists():
        return False
    now_ts = time.time()
    if _fixed_ratio_window_warming(now_ts):
        return False
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True, timeout=5)
        rows = con.execute("SELECT engine, ts_close, volume, net_pnl FROM rts").fetchall()
        con.close()
    except Exception as e:
        log(f"ratio_floor db error: {e}")
        return False
    breached, vol, cost, ratio, action, detail = _evaluate_ratio_floor_pure(
        rows, now_ts, RATIO_FLOOR, RATIO_WINDOW_H, RATIO_MIN_VOL)
    if not breached:
        return False
    log(f"RATIO FLOOR BREACH — {detail} → {action}")
    payload = json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                          "source": "sodex_safety_guardian.ratio_floor", "reason": detail}, indent=2)
    try:
        target = HALT_FILE if action == "SAFETY_HALT" else PVE_PAUSE_FILE
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload)
    except Exception as e:
        log(f"ratio_floor write error: {e}")
    tg_send(f"🟠 RATIO FLOOR — {detail}\n→ {action} (bounded-cost 1:{RATIO_FLOOR:,.0f} breached).",
            key="ratio_floor")
    return True


def check_e1_coverage() -> bool:
    """Opsi A hybrid gate: PVE only runs when E1 earns enough to cover its cost.
    If E1 dormant (fill_vol_24h < E1_MIN_FILL_USD) → PVE_PAUSE until E1 wakes up.
    Clears PVE_PAUSE automatically when E1 recovers (self-healing).
    ponytail: single-condition gate, no tracking needed — stateless per cycle.
    """
    if not TE_DB.exists():
        return False
    e1_min_fill = float(os.environ.get("GUARDIAN_E1_MIN_FILL_24H", "300"))  # $300 fills/24h needed
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True, timeout=5)
        cut = time.time() - 86400.0
        # BUGFIX audit 2026-09-27 (2 lapis):
        # (1) kolom `notional` fills SELALU 0 (pitfall known sejak 2026-08-30) →
        #     gate membaca $0 padahal E1 fill $338 → PVE_PAUSE permanen.
        #     Volume jujur = price*qty.
        # (2) profit estimasi pakai edge asumsi 6,86bps — TIDAK JUJUR: E1 riil
        #     24h justru minus. Sumber kebenaran = rts.net_pnl (sudah net fee,
        #     terverifikasi riset d9fdc15). Gate pakai profit RIIL.
        e1_fills = con.execute(
            "SELECT COALESCE(SUM(CAST(price AS REAL)*CAST(qty AS REAL)),0) FROM fills WHERE engine='E1' AND CAST(strftime('%s',ts) AS REAL)>=?",
            (cut,)).fetchone()[0]
        e1_pnl_real = con.execute(
            "SELECT COALESCE(SUM(CAST(net_pnl AS REAL)),0) FROM rts WHERE engine='E1' AND CAST(strftime('%s',ts_close) AS REAL)>=?",
            (cut,)).fetchone()[0]
        con.close()
    except Exception as e:
        log(f"e1_coverage db error: {e}")
        return False
    # JUJUR (audit 2026-09-27): profit riil dari rts.net_pnl (sudah net fee),
    # bukan estimasi edge asumsi. E1 rugi → coverage TIDAK ada → tetap paused.
    e1_profit_24h = float(e1_pnl_real)
    pve_cost_budget = e1_profit_24h  # PVE cost budget = E1 profit

    # JUJUR (29-Sep-2026): sebut klausa yang BENAR-BENAR memicu. Sebelumnya pesan selalu
    # berbunyi "fill < threshold" walau pemicunya klausa profit negatif (fill $5669 > $300
    # tapi pesan menulis '$5669 < $300') → misdiagnosis oleh operator = kelalaian.
    _fill_low = float(e1_fills) < e1_min_fill
    _profit_neg = e1_profit_24h < 0
    dormant = _fill_low or _profit_neg
    _why = " + ".join(p for p in (
        (f"fill ${e1_fills:.0f} < threshold ${e1_min_fill:.0f}/24h" if _fill_low else ""),
        (f"profit riil 24h ${e1_profit_24h:.4f} < $0 (rts.net_pnl)" if _profit_neg else ""),
    ) if p)
    pause_exists = PVE_PAUSE_FILE.exists()

    if dormant and not pause_exists:
        # E1 tidak fill cukup / rugi → pause PVE agar tidak menambah rugi
        payload = json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                              "source": "e1_coverage_gate",
                              "e1_fill_24h": float(e1_fills),
                              "e1_profit_24h": round(e1_profit_24h, 4),
                              "threshold": e1_min_fill,
                              "reason": f"E1 dormant: {_why}"}, indent=2)
        try:
            PVE_PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
            PVE_PAUSE_FILE.write_text(payload)
            log(f"E1_COVERAGE GATE: {_why} → PVE_PAUSE written")
            tg_send(f"⏸️ PVE PAUSED (E1 coverage gate)\nAlasan: {_why}\n"
                    f"E1 fills 24h: ${e1_fills:.0f} | profit riil 24h: ${e1_profit_24h:.3f}\n"
                    f"PVE resumes otomatis saat E1 sehat kembali.", key="e1_coverage_pause")
        except Exception as e:
            log(f"e1_coverage write error: {e}")
        return True

    if not dormant and pause_exists:
        # Check if pause was written by THIS gate (not ratio_floor or weekly_floor)
        try:
            reason = json.loads(PVE_PAUSE_FILE.read_text()).get("source", "")
            if reason == "e1_coverage_gate":
                PVE_PAUSE_FILE.unlink()
                log(f"E1_COVERAGE GATE: E1 sehat kembali (fill24h=${e1_fills:.0f}, profit 24h=${e1_profit_24h:.4f}) → PVE_PAUSE cleared")
                tg_send(f"▶️ PVE RESUMED (E1 coverage gate cleared)\nE1 fills 24h: ${e1_fills:.0f} | profit riil 24h: ${e1_profit_24h:.3f}\nPVE boleh jalan — coverage E1 cukup.", key="e1_coverage_resume")
        except Exception:
            pass
    return False


def cycle(address: str) -> None:
    # 0. PNL BREAKER — deteksi dini engine nge-bleed (anti death-by-thousand-cuts)
    check_pnl_breaker()
    # 0.1 RATIO FLOOR — Opsi B bounded-cost: vol/cost < 8650 → pause perps (or HALT)
    check_ratio_floor()
    # 0.1b E1 COVERAGE GATE — Opsi A hybrid: PVE paused when E1 dormant (no profit cushion)
    check_e1_coverage()
    # 0.2 WEEKLY PVE FLOOR — kill-switch: PVE NET 7d < floor → PVE_PAUSE + restart signal
    # FIX INSIDEN: weekly NET -$26 < floor -$25 tapi kill-switch tidak terpicu sebelumnya.
    check_weekly_pve_floor()
    # 0.4 PVE HEALTH — 24h WR + fee efficiency monitoring (lebih sensitif dari weekly)
    check_pve_health()
    # 0.5 ENGINE STALL — engine beku/hang tak terlihat breaker (blind-spot struktural)
    check_engine_stall()

    # 1. KILL-SWITCH
    if HALT_FILE.exists():
        n = cancel_all("SAFETY_HALT")
        write_heartbeat(0, engine_dead_secs())
        log(f"HALT aktif — {n} order dibatalkan, quoting harus berhenti via engine")
        return

    orders = list_open_orders()
    eng_dead = engine_dead_secs()

    # 2. UNMANAGED — engine mati > grace + ada order
    if eng_dead > GRACE_SEC and orders:
        cancel_all(f"engine_dead_{int(eng_dead)}s")
        write_heartbeat(0, eng_dead)
        return

    # 3. STALE ORDER — engine hidup tapi order terlalu tua (tak dirotasi)
    if eng_dead == 0.0 and orders:
        now = time.time()
        stale = []
        for o in orders:
            ts = o.get("createdAt") or o.get("ts") or o.get("timestamp")
            try:
                age = now - (float(ts) / 1000.0 if ts and float(ts) > 1e12 else float(ts or now))
            except Exception:
                age = 0.0
            if age > STALE_SEC:
                stale.append(o)
        if stale:
            n = sum(1 for o in stale if cancel_order(o))
            log(f"STALE: {n}/{len(stale)} order basi (>{STALE_SEC}s) dibatalkan")
            tg_send(f"🧹 {n} order basi (>{STALE_SEC//60}m) dibatalkan (engine hidup tapi tak rotasi).", key="stale")

    # 4. MARGIN RISK + POSITION RISK (alert only — read-only, tak auto-close)
    if address:
        check_margin(address)
        check_position_risk(address)

    write_heartbeat(len(orders), eng_dead)


def main() -> int:
    address = _env_address()
    log(f"🛡️ SAFETY GUARDIAN START — interval={CHECK_INTERVAL}s grace={GRACE_SEC}s "
        f"stale={STALE_SEC}s margin_cap={HARD_MARGIN_PCT}% addr={address[:10]}…")
    tg_send("🛡️ Safety Guardian aktif — proteksi posisi & order 24/7 (independen).", key="boot")
    once = "--once" in sys.argv
    while True:
        try:
            cycle(address)
        except Exception as e:
            log(f"cycle error: {e}")
        if once:
            return 0
        time.sleep(CHECK_INTERVAL)


def _evaluate_weekly_pve_floor_pure(rows, now_ts: float, floor: float, min_n: int) -> tuple:
    """Pure helper untuk test: rows=[(ts_close, net_pnl),...] → (breached, n, cum, wr)."""
    cutoff = now_ts - 7 * 86400.0
    wins = 0
    cum = 0.0
    n = 0
    for ts, pnl in rows:
        if _ts_epoch(ts) < cutoff:
            continue
        p = float(pnl) if pnl is not None else 0.0
        n += 1; cum += p; wins += (1 if p > 0 else 0)
    wr = wins / n if n else 0.0
    breached = (n >= min_n and cum < floor)
    return breached, n, round(cum, 4), round(wr, 4)


def _selfcheck() -> int:
    """assert-based — gagal jika logika breaker rusak. Pakai data nyata pola E2/E1/PVE."""
    now = time.time()
    iso = lambda h: datetime.fromtimestamp(now - h * 3600, timezone.utc).isoformat()
    # E2 dead 176h lalu → di luar window → TIDAK boleh halt
    e2_dead = [("E2", iso(176 + i * 0.01), -0.06) for i in range(605)]
    assert evaluate_pnl_breaches(e2_dead, now) == {}, "engine mati harus diabaikan"
    # E2 jika MASIH live: WR ~3.5%, cum << -$10 → broken_signal
    e2_live = [("E2", iso(0.1), (0.5 if i % 29 == 0 else -0.06)) for i in range(300)]
    b = evaluate_pnl_breaches(e2_live, now)
    assert "E2" in b and "broken_signal" in b["E2"], f"E2 live harus trip: {b}"
    # E1 sehat: WR 93.5% → TIDAK boleh halt walau ada drawdown kecil
    e1 = [("E1", iso(1), (0.02 if i % 16 else -0.10)) for i in range(500)]
    assert "E1" not in evaluate_pnl_breaches(e1, now), "E1 sehat tak boleh false-fire"
    # PVE net positif → TIDAK boleh halt
    pve = [("PVE", iso(2), (0.30 if i % 3 else -0.20)) for i in range(72)]
    assert "PVE" not in evaluate_pnl_breaches(pve, now), "engine net-positif tak boleh trip"
    # n < MIN_N → fail-safe diam
    assert evaluate_pnl_breaches([("X", iso(0.1), -5.0)] * 10, now) == {}, "n kecil = diam"
    # sustained_bleed: WR 50% tapi rugi besar (avg-loss>avg-win)
    bleed = [("Y", iso(1), (0.5 if i % 2 else -1.5)) for i in range(60)]
    by = evaluate_pnl_breaches(bleed, now)
    assert "Y" in by and "sustained_bleed" in by["Y"], f"bleed harus trip: {by}"
    # ── engine_health: verdict per-engine (stall detector) ──
    h = evaluate_engine_health(e1, now)
    assert h["E1"]["verdict"] == "HEALTHY", f"E1 harus HEALTHY: {h}"
    # engine beku: RT terakhir ~10h lalu (> STALL_H, < LOOKBACK) → STALLED
    frozen = [("F", iso(10 + i * 0.01), 0.02) for i in range(40)]
    hf = evaluate_engine_health(frozen, now)
    assert hf["F"]["verdict"] == "STALLED", f"engine beku harus STALLED: {hf}"
    # E2 mati 176h (> LOOKBACK) → IDLE, bukan STALLED → tak spam stall
    he = evaluate_engine_health(e2_dead, now)
    assert he["E2"]["verdict"] == "IDLE", f"engine mati lama harus IDLE: {he}"
    # e2_live nge-bleed → BLEEDING (selaras breaker)
    hb = evaluate_engine_health(e2_live, now)
    assert hb["E2"]["verdict"] == "BLEEDING", f"E2 live harus BLEEDING: {hb}"

    # ── weekly PVE floor check (FIX verifikasi) ──
    floor, min_n = -25.0, 20
    # PVE insiden: weekly -$26 → harus trip
    pve_bad = [(iso(0.1 + i * 0.01), -1.3) for i in range(20)]
    breached, n, cum, wr = _evaluate_weekly_pve_floor_pure(pve_bad, now, floor, min_n)
    assert breached, f"PVE weekly -$26 harus trip floor: n={n} cum={cum}"
    # PVE sehat: weekly +$5 → TIDAK boleh trip
    pve_ok = [(iso(0.1 + i * 0.01), 0.25) for i in range(20)]
    breached_ok, _, cum_ok, _ = _evaluate_weekly_pve_floor_pure(pve_ok, now, floor, min_n)
    assert not breached_ok, f"PVE sehat tidak boleh trip: cum={cum_ok}"
    # PVE n < MIN_N → fail-open (tidak boleh trip)
    pve_small = [(iso(0.1 + i * 0.01), -5.0) for i in range(10)]
    breached_small, n_s, _, _ = _evaluate_weekly_pve_floor_pure(pve_small, now, floor, min_n)
    assert not breached_small, f"PVE n={n_s} < min_n={min_n} harus fail-open"
    # PVE data di luar window 7d (176h lalu) → NOT counted → tidak trip
    pve_old = [(iso(176 + i * 0.01), -5.0) for i in range(30)]
    breached_old, n_old, cum_old, _ = _evaluate_weekly_pve_floor_pure(pve_old, now, floor, min_n)
    assert not breached_old, f"PVE data 176h lalu tidak boleh dihitung: n={n_old} cum={cum_old}"

    # ── ratio_floor: Opsi B bounded-cost (vol/cost >= 8650) ──
    rf = lambda rows: _evaluate_ratio_floor_pure(rows, now, 8650, 168, 7000)
    assert not rf([("E1", iso(1), 1000.0, 0.5)] * 20)[0], "profit tak boleh breach"
    assert not rf([("E1", iso(1), 100.0, -50.0)])[0], "vol < min tak boleh breach"
    assert not rf([("E1", iso(1), 50000.0, -2.5), ("PVE", iso(1), 50000.0, -2.5)])[0], "ratio 20000 dalam budget"
    b1 = rf([("E1", iso(1), 5000.0, 1.0), ("PVE", iso(1), 5000.0, -6.0)])
    assert b1[0] and b1[4] == "PVE_PAUSE", f"breach E1-positif → PVE_PAUSE: {b1}"
    b2 = rf([("E1", iso(1), 10000.0, -6.0)])
    assert b2[0] and b2[4] == "PVE_PAUSE", f"ratio breach stays PVE-scoped: {b2}"
    assert not rf([("E1", iso(200), 100000.0, -50.0)])[0], "data >168h tak dihitung"

    print("OK pnl_breaker + engine_health + weekly_pve_floor + ratio_floor self-check passed")
    return 0


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        raise SystemExit(_selfcheck())
    if "--report" in sys.argv:
        raise SystemExit(report_engine_health())
    raise SystemExit(main())
