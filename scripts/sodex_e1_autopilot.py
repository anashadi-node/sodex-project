#!/usr/bin/env python3
"""SoDEX E1 Autopilot — Monitor + Evaluate + Repair otonom per-menit (24/7).

INDEPENDEN dari Claude. systemd Restart=always. Fokus: kesehatan STRATEGI E1
(profitabilitas, volume, kesehatan per-pair) — melengkapi:
  - watchdog (liveness/restart engine)
  - safety_guardian (keamanan posisi & open-order, cancel)
  - sodex_monitor_eval (weekly volume/win-rate targets — TIDAK diduplikasi di sini)
Autopilot ini = otak evaluasi farming: apakah E1 untung? volume on-track? ada pair
macet? lalu PERBAIKAN aman + laporan.

Per ≤60 detik:
  MONITOR  — engine hidup? E1 net rate (rolling)? volume rate? fills per-pair? equity?
  EVALUATE — No-Loss (net≥0)? volume vs target mingguan? tulis eval JSON + history.
  REPAIR   — (aman, konservatif): bersihkan cooldown E2 basi (housekeeping); deteksi
             pair macet (ada inventori tapi 0 fill lama) → alert; engine mati >3m →
             CRITICAL (watchdog yg restart, autopilot tak duplikasi). TIDAK pasang
             order, TIDAK lawan logika pause/flush engine.
  HEARTBEAT— tulis data/e1_autopilot_heartbeat.json + Telegram ringkasan tiap 30m.

Per 30 menit (SCIENCE):
  scientific_eval() — Wilson CI per-pair (XLM LOSING?), Mann-Kendall trend 7d,
  dead-hour detection (BH-FDR corrected). Tulis data/e1_scientific_eval.json.

Per 1 jam (REGIME):
  regime_accuracy_check() — log regime+PEPE price, verify 1h kemudian, track hit-rate.
  Tulis data/e1_regime_accuracy.jsonl. Alert jika accuracy < 50%.

Per 6 jam (IMPROVE):
  auto_improve() — saran perbaikan berbasis data ke data/e1_improve_suggestions.jsonl
  + Telegram. TIDAK PERNAH auto-apply — operator yang memutuskan.

Tidak overlap dengan:
  sodex_monitor_eval (weekly targets), safety_guardian (order/posisi cancel),
  sodex_autonomous_research (Pre-Gain scan), sodex_84h_supervisor (koordinasi).

ponytail: satu loop, baca DB (sumber kebenaran), repair = housekeeping+alert saja.
"""
import json, math, os, sqlite3, subprocess, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(os.environ.get("ANANTARA_DIR", str(Path(__file__).resolve().parent.parent)))
DB = PROJECT / "twin_engine.db"
LOG = PROJECT / "logs" / "e1_autopilot.log"
HEARTBEAT = PROJECT / "data" / "e1_autopilot_heartbeat.json"
LATEST = PROJECT / "data" / "e1_autopilot_latest.json"
HISTORY = PROJECT / "data" / "e1_autopilot_history.jsonl"
SCIENCE_OUT = PROJECT / "data" / "e1_scientific_eval.json"
IMPROVE_LOG = PROJECT / "data" / "e1_improve_suggestions.jsonl"
REGIME_LOG = PROJECT / "data" / "e1_regime_accuracy.jsonl"

CHECK_INTERVAL = 60
REPORT_INTERVAL = 1800          # Telegram tiap 30 menit
SCIENCE_INTERVAL = 1800         # Statistical eval tiap 30 menit
REGIME_INTERVAL = 3600          # Regime accuracy tiap 1 jam
IMPROVE_INTERVAL = 21600        # Auto-improve tiap 6 jam
WEEKLY_VOLUME_TARGET = 550_000  # target user REVISI 2026-07-22 (USD/minggu)
NET_LOSS_ALERT = -0.0005        # net rate < -0.05% → alert
ENGINE_DEAD_ALERT_S = 180       # engine mati >3m → CRITICAL
ALERT_COOLDOWN = 600
DAEMON_STUCK_RT_MINUTES = 20    # fills >= 5 tapi 0 RT selesai → STUCK
ZERO_FILL_MINUTES = 12          # 0 fills untuk N menit → CRITICAL
CRITICAL_NET_RATE = -0.001      # net rate < -0.1% for 2h → CRITICAL escalate

# Signal file — autopilot & guardian share same restart signal for watchdog
RESTART_SIGNAL = PROJECT / "data" / "GUARDIAN_RESTART_SIGNAL"

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
_last_alert: dict = {}
_last_report = 0.0
_last_science = 0.0
_last_regime = 0.0
_last_improve = 0.0


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def tg(msg: str, key: str = "") -> None:
    if not (TG_TOKEN and TG_CHAT):
        return
    if key:
        if time.time() - _last_alert.get(key, 0.0) < ALERT_COOLDOWN:
            return
        _last_alert[key] = time.time()
    try:
        data = json.dumps({"chat_id": TG_CHAT, "text": ("🤖 E1 AUTOPILOT\n" + msg)[:4000]}).encode()
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        urllib.request.urlopen(
            urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}),
            timeout=10)
    except Exception:
        pass


def _q(sql: str, args=()):
    try:
        c = sqlite3.connect(str(DB), timeout=5)
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()
    except Exception:
        return []


def _target_policy_expects_fills() -> bool:
    """Whether current weekly policy expects live fills.

    If policy blocks E2/no-trade, zero-fill is not automatically a daemon hang.
    """
    try:
        import importlib.util

        path = PROJECT / "scripts" / "sodex_target_policy.py"
        spec = importlib.util.spec_from_file_location("sodex_target_policy", path)
        if spec is None or spec.loader is None:
            return True
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        report_path = PROJECT / "data" / "sodex_monitor_eval" / "latest.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
        policy = mod.evaluate_target_policy(report)
        decision = str(policy.get("decision") or "")
        limits = policy.get("limits") or {}
        if decision.startswith("BLOCK") or decision.startswith("PAUSE"):
            return False
        return float(limits.get("max_e2_hourly_volume_usd") or 0.0) > 0.0
    except Exception:
        return True


def engine_alive() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", "sodex_twin_engine.py run"],
                           capture_output=True, text=True, timeout=5)
        return bool(r.stdout.strip())
    except Exception:
        return False


# ─── STATISTICAL HELPERS (stdlib-only, no numpy) ──────────────────────────────

def _norm_cdf(z: float) -> float:
    """Standard normal CDF via math.erf (exact, stdlib since Python 2.7)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _binom_p_lower(wins: int, n: int, p0: float = 0.5) -> float:
    """One-tailed lower binomial p-value via normal approx + continuity correction.
    Returns 1.0 when n<10 (insufficient data guard).
    """
    if n < 10:
        return 1.0
    mu = n * p0
    sigma = math.sqrt(n * p0 * (1.0 - p0))
    if sigma == 0:
        return 1.0
    z = (wins + 0.5 - mu) / sigma  # continuity correction
    return _norm_cdf(z)


def _wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple:
    """Wilson score confidence interval for proportion. Returns (lo, hi, center)."""
    if n == 0:
        return 0.0, 1.0, 0.5
    p = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / denom
    return max(0.0, center - margin), min(1.0, center + margin), center


def _sharpe_daily(daily_pnl: list) -> float:
    """Annualized Sharpe ratio dari seri PnL harian (stdlib-only, no numpy).

    Digunakan untuk deteksi edge degradasi yang lebih nuansikal dari Mann-Kendall:
    Sharpe < 0 = rugi dikala volatil, Sharpe > 0.5 = edge solid secara risk-adjusted.
    """
    n = len(daily_pnl)
    if n < 3:
        return 0.0
    mean = sum(daily_pnl) / n
    var = sum((x - mean) ** 2 for x in daily_pnl) / max(n - 1, 1)
    std = math.sqrt(var) if var > 0 else 1e-9
    return round(mean / std * math.sqrt(365), 4)


def _mann_kendall(series: list) -> tuple:
    """Mann-Kendall trend test. Returns (tau, z_stat, p_val).
    tau > 0 = uptrend, tau < 0 = downtrend. p_val < 0.10 = significant.
    """
    n = len(series)
    if n < 4:
        return 0.0, 0.0, 1.0
    S = sum(
        (1 if series[j] > series[i] else -1 if series[j] < series[i] else 0)
        for i in range(n - 1) for j in range(i + 1, n)
    )
    var_s = n * (n - 1) * (2 * n + 5) / 18.0
    z = ((S - 1) / math.sqrt(var_s)) if S > 0 else ((S + 1) / math.sqrt(var_s)) if S < 0 else 0.0
    p = 2.0 * (1.0 - _norm_cdf(abs(z)))
    tau = S / (n * (n - 1) / 2.0)
    return round(tau, 4), round(z, 4), round(p, 4)


# ─── EXISTING CORE FUNCTIONS (UNCHANGED) ──────────────────────────────────────

def monitor() -> dict:
    """Kumpulkan metrik E1 + PVE dari DB (sumber kebenaran).

    v4 additions (monitoring lebih sensitif):
      - 30m PnL window (deteksi bleeding lebih cepat dari 1h/2h)
      - Fee efficiency: fee/volume ratio + SoPoints ratio (target 1:6000)
      - Volume acceleration: 4h now vs prior 4h (early warning volume drop)
      - Per-pair 30m fills (lebih sensitif dari 15m snapshot untuk pair macet)
      - PVE 7d stats (floor awareness untuk kill-switch guardian)
      - Spot balance proxy: equity dari fills notional (trend capital)
    """
    m: dict = {"ts": datetime.now(timezone.utc).isoformat(), "engine_alive": engine_alive()}

    # ── E1 net rate: multi-window (30m / 1h / 2h) ──
    for window, key in [("30 minutes", "30m"), ("1 hour", "1h"), ("2 hours", "2h")]:
        r = _q(f"SELECT COALESCE(SUM(CAST(net_pnl AS REAL)),0), COALESCE(SUM(CAST(volume AS REAL)),0), COUNT(*) "
               f"FROM rts WHERE engine='E1' AND ts_close>=datetime('now','-{window}')")
        pnl, vol, n = (r[0] if r else (0, 0, 0))
        m[f"e1_net_pnl_{key}"] = round(float(pnl), 4)
        m[f"e1_rt_volume_{key}"] = round(float(vol), 2)
        m[f"e1_rts_{key}"] = int(n)
        m[f"e1_net_rate_{key}"] = round(float(pnl) / float(vol), 6) if vol else 0.0
    # Backward compat alias (code yang pakai m["e1_net_rate"] dan m["e1_rts_2h"])
    m["e1_net_rate"] = m["e1_net_rate_2h"]
    m["e1_rts_2h"] = m["e1_rts_2h"]

    # ── PNL GUARD: 1h net (PnL - fee) — bleeding detection ──
    f1h = _q("SELECT COALESCE(SUM(CAST(fee AS REAL)),0) FROM fills WHERE engine='E1' AND ts>=datetime('now','-1 hour')")
    fee1h = float(f1h[0][0] if f1h and f1h[0] else 0)
    m["pnl_1h_net"] = round(m["e1_net_pnl_1h"] - fee1h, 4)
    m["e1_fee_1h"] = round(fee1h, 4)
    # SoPoints ratio: vol/fee (target ≥ 6000; lebih tinggi = lebih efisien)
    vol1h_e1 = m["e1_rt_volume_1h"]
    m["e1_fee_ratio"] = round(fee1h / vol1h_e1, 6) if vol1h_e1 else 0.0
    m["e1_sopoints_ratio"] = round(vol1h_e1 / fee1h if fee1h else 0.0, 0)

    # ── Per-pair 1h net + 30m fills ──
    m["pair_pnl_1h"] = {}
    for row in _q("SELECT pair, COALESCE(SUM(CAST(net_pnl AS REAL)),0) "
                  "FROM rts WHERE ts_close>=datetime('now','-1 hour') GROUP BY pair"):
        m["pair_pnl_1h"][row[0]] = round(float(row[1]), 4)

    # ── Fill volume (1h) → weekly projection + fee efficiency ──
    rf = _q("SELECT COALESCE(SUM(CAST(notional AS REAL)),0), COUNT(*) "
            "FROM fills WHERE engine='E1' AND ts>=datetime('now','-1 hour')")
    vol1h, fills1h = (rf[0] if rf else (0, 0))
    m["e1_fill_volume_1h"] = round(float(vol1h), 2)
    m["e1_fills_1h"] = int(fills1h)
    m["volume_weekly_proj"] = round(float(vol1h) * 24 * 7, 0)
    m["volume_target_pct"] = round(float(vol1h) * 24 * 7 / WEEKLY_VOLUME_TARGET * 100, 1)

    # ── Volume acceleration: 4h now vs prior 4h (early warning) ──
    r_now4h = _q("SELECT COALESCE(SUM(CAST(notional AS REAL)),0) FROM fills "
                 "WHERE engine='E1' AND ts>=datetime('now','-4 hours')")
    r_prev4h = _q("SELECT COALESCE(SUM(CAST(notional AS REAL)),0) FROM fills "
                  "WHERE engine='E1' AND ts>=datetime('now','-8 hours') AND ts<datetime('now','-4 hours')")
    vol4h_now = float(r_now4h[0][0] if r_now4h and r_now4h[0] else 0)
    vol4h_prev = float(r_prev4h[0][0] if r_prev4h and r_prev4h[0] else 0)
    m["volume_acceleration"] = round(
        (vol4h_now - vol4h_prev) / vol4h_prev if vol4h_prev else 0.0, 4)
    m["e1_fill_volume_4h"] = round(vol4h_now, 2)

    # ── Per-pair fills (15m + 30m) — deteksi pair macet lebih awal ──
    pairs_15m, pairs_30m = {}, {}
    for row in _q("SELECT pair, COUNT(*) FROM fills WHERE engine='E1' AND ts>=datetime('now','-15 minutes') GROUP BY pair"):
        pairs_15m[row[0]] = row[1]
    for row in _q("SELECT pair, COUNT(*) FROM fills WHERE engine='E1' AND ts>=datetime('now','-30 minutes') GROUP BY pair"):
        pairs_30m[row[0]] = row[1]
    m["pair_fills_15m"] = pairs_15m
    m["pair_fills_30m"] = pairs_30m

    # ── PVE 7d stats (floor awareness, kill-switch guardian sync) ──
    rpve = _q("SELECT COUNT(*), COALESCE(SUM(CAST(net_pnl AS REAL)),0), "
              "SUM(CASE WHEN CAST(net_pnl AS REAL)>0 THEN 1 ELSE 0 END) "
              "FROM rts WHERE engine='PVE' AND ts_close>=datetime('now','-7 days')")
    if rpve and rpve[0]:
        pve_n, pve_cum, pve_wins = (int(rpve[0][0] or 0), float(rpve[0][1] or 0), int(rpve[0][2] or 0))
        m["pve"] = {"n_7d": pve_n, "cum_7d": round(pve_cum, 4),
                    "wr_7d": round(pve_wins / pve_n if pve_n else 0, 4)}

    # ── PVE per-pair 1h stats (early bleed detection per pair) ──
    pve_1h: dict = {}
    for row in _q("""
        SELECT pair, COUNT(*) n, SUM(CAST(net_pnl AS REAL)) pnl,
               SUM(CASE WHEN CAST(net_pnl AS REAL)>0 THEN 1 ELSE 0 END) wins
        FROM rts WHERE engine='PVE' AND ts_close>=datetime('now','-1 hour')
        GROUP BY pair
    """):
        pair, n, pnl, wins = row[0], int(row[1] or 0), float(row[2] or 0), int(row[3] or 0)
        pve_1h[pair] = {"n": n, "pnl": round(pnl, 4), "wr": round(wins/n if n else 0, 3)}
    m["pve_1h"] = pve_1h

    # ── ENV drift: detect if running engine pairs differ from .env ──
    m["env_drift"] = _detect_env_drift()

    return m


def _detect_env_drift() -> dict:
    """Deteksi perbedaan antara .env config dan process env engine yang sedang jalan.
    Root cause: engine restart tidak reload .env → pair hilang / min_spread salah.
    """
    try:
        import os as _os
        # Read .env
        env_path = PROJECT / ".env"
        env_cfg: dict = {}
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.startswith("TE_"):
                    env_cfg[k] = v.split("#")[0].strip()

        # Find running engine process
        proc_cfg: dict = {}
        for pid in _os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                raw = (_os.path.join("/proc", pid, "environ"))
                with open(raw, "rb") as f:
                    env_raw = f.read()
                env_str = env_raw.decode(errors="replace")
                if "TE_E1_ENABLED" in env_str and "SODEX_API_KEY" in env_str:
                    for var in env_str.split("\0"):
                        if "=" in var:
                            k2, v2 = var.split("=", 1)
                            if k2.startswith("TE_"):
                                proc_cfg[k2] = v2
                    break
            except (PermissionError, FileNotFoundError):
                continue

        if not proc_cfg:
            return {"detected": False, "note": "engine process not found"}

        # Compare key TE_ vars for drift
        drift_keys = []
        WATCH_KEYS = ["TE_SPOT_PAIR", "TE_SPOT_PAIR_2", "TE_SPOT_PAIR_3",
                      "TE_E1_MIN_SPREAD", "TE_PVE_PAIRS", "TE_E1_HEDGE_PAIRS"]
        for k in WATCH_KEYS:
            env_val = env_cfg.get(k, "")
            proc_val = proc_cfg.get(k, "")
            if env_val != proc_val:
                drift_keys.append({"key": k, "env": env_val, "running": proc_val})

        return {"detected": bool(drift_keys), "diffs": drift_keys}
    except Exception as e:
        return {"detected": False, "error": str(e)}


def evaluate(m: dict) -> dict:
    """Nilai No-Loss + volume vs target + fee efficiency + trend signals.

    v4: tambah fee efficiency, sopoints ratio, volume acceleration, 30m bleed detection.
    """
    # ponytail: fall back to legacy e1_net_rate key so old tests + monitor() still work
    nr2h  = m.get("e1_net_rate_2h",  m.get("e1_net_rate", 0.0))
    nr30m = m.get("e1_net_rate_30m", nr2h)
    sopoints = m.get("e1_sopoints_ratio", 0)
    vol_accel = m.get("volume_acceleration", 0)

    ev = {
        "no_loss_ok": nr2h >= 0,
        "net_rate_pct": round(nr2h * 100, 4),
        "net_rate_pct_30m": round(nr30m * 100, 4),
        "volume_target_pct": m["volume_target_pct"],
        "on_track_volume": m["volume_target_pct"] >= 100,
        # Fee efficiency: SoPoints ratio (target ≥ 6000, audited rata-rata 6363)
        "sopoints_ratio": sopoints,
        "fee_efficiency_ok": sopoints >= 7000,  # hard floor: 1:7000
        # Volume acceleration trend (+= growing, -= shrinking)
        "volume_accelerating": vol_accel > 0.05,
        "volume_decelerating": vol_accel < -0.20,
        # 30m bleed: bleeding cepat terdeteksi lebih awal
        "bleeding_30m": (m.get("e1_rts_30m", 0) >= 10 and nr30m < -0.0005),
        # PVE floor pct
        "pve_cum_7d": m.get("pve", {}).get("cum_7d", 0),
        "pve_floor_pct": round(m.get("pve", {}).get("cum_7d", 0) / 25 * 100, 1),  # floor = -25
        # PVE per-pair early bleed: pair dengan n≥10 dan WR<40% dalam 1h
        "pve_pair_bleeding": {p: s for p, s in m.get("pve_1h", {}).items()
                              if s["n"] >= 10 and s["wr"] < 0.40},
        # Volume gap: E1 proyeksi mingguan vs target
        "volume_gap_pct": 100.0 - m.get("volume_target_pct", 0),
        "volume_critical": m.get("volume_target_pct", 0) < 5.0,  # <5% target = CRITICAL
        # Env drift: engine sedang jalan dengan config berbeda dari .env
        "env_drift_detected": m.get("env_drift", {}).get("detected", False),
        "env_drift_diffs": m.get("env_drift", {}).get("diffs", []),
    }
    m["eval"] = ev
    return ev


def repair(m: dict) -> list:
    """Perbaikan AMAN (housekeeping + alert + restart signal).

    v4: cek SAFETY_HALT/PNL_HALT di awal — saat halted, skip semua alert kecuali
    daemon-stuck (halt seharusnya menyetop engine, bukan bikin alert palsu).
    TIDAK pasang order / TIDAK lawan engine — hanya signal restart via file.
    Watchdog yang membaca signal file & melakukan restart.
    """
    actions = []
    halt_active = (PROJECT / "data" / "SAFETY_HALT").exists() or \
                  (PROJECT / "data" / "PNL_HALT").exists()
    if halt_active:
        # Saat halted: hanya cek daemon-stuck (watchdog gagal kill?) lalu kembali.
        stuck_action = _check_daemon_stuck(m)
        if stuck_action:
            actions.append(stuck_action)
        return actions
    now = time.time()
    
    # 0) CRITICAL: Daemon stuck detection (CEK PALING AWAL)
    stuck_action = _check_daemon_stuck(m)
    if stuck_action:
        actions.append(stuck_action)
        return actions  # Skip other checks — restart is top priority
    
    # 0.5) PNL GUARD: 1h net bleeding — escalate + optional auto-pause signal
    pnl_action = _check_pnl_guard(m)
    if pnl_action:
        actions.append(pnl_action)
    
    # 1) Engine mati > 3m → CRITICAL (watchdog yg restart)
    if not m["engine_alive"]:
        last = 0.0
        try:
            last = float(json.loads(HEARTBEAT.read_text()).get("engine_last_alive", now))
        except Exception:
            last = now
        if now - last > ENGINE_DEAD_ALERT_S:
            tg("🔴 ENGINE MATI >3m — watchdog seharusnya restart. Cek manual bila berlanjut.", key="engine_dead")
            actions.append("engine_dead_alert")
    # 2) Net rate rugi signifikan → alert (escalate jika kritis)
    if m["e1_rts_2h"] >= 20 and m["e1_net_rate"] < NET_LOSS_ALERT:
        is_critical = m["e1_net_rate"] < CRITICAL_NET_RATE
        emoji = "🔴🔴" if is_critical else "⚠️"
        tg(f"{emoji} E1 net rate {m['e1_net_rate']*100:+.3f}% (rugi) atas {m['e1_rts_2h']} RT. "
           f"Pause-floor otomatis -0.2% melindungi. {'⚠️ ESCALATE: >0.1% loss rate!' if is_critical else 'Pantau.'}", 
           key="net_loss_critical" if is_critical else "net_loss")
        actions.append("net_loss_critical" if is_critical else "net_loss_alert")
    # 2.5) 30m bleed detection (lebih sensitif dari 2h window)
    if m["eval"].get("bleeding_30m"):
        tg(f"⚠️ E1 30m BLEEDING: net rate {m['e1_net_rate_30m']*100:+.3f}% atas {m['e1_rts_30m']} RT. "
           f"Early warning — 2h rate belum tentu muncul.", key="net_loss_30m")
        actions.append("net_loss_alert_30m")

    # 3) Pair macet: 0 fill 30m (lebih awal dari 15m false alarm) padahal pair aktif
    # Dynamic pair list from DB instead of hardcoded
    cfg_pairs = _get_active_spot_pairs()
    for p in cfg_pairs:
        fills_30m = m["pair_fills_30m"].get(p, 0)
        fills_15m = m["pair_fills_15m"].get(p, 0)
        if fills_30m == 0:
            # 0 fills dalam 30m: lebih definitif dari 15m
            tg(f"⚠️ Pair {p}: 0 fill dalam 30m — spread terlalu sempit / quote terblokir. Pantau.", key=f"deadpair30:{p}")
            actions.append(f"dead_pair_30m:{p}")
        elif fills_15m == 0 and fills_30m > 0:
            # Ada fills 30m tapi berhenti 15m terakhir: early warning
            tg(f"🟡 Pair {p}: 0 fill 15m terakhir (ada {fills_30m} fill 30m). Monitor.", key=f"slowpair15:{p}")
            actions.append(f"slow_pair_15m:{p}")
    # 3.5) PVE per-pair 1h bleed (early warning — pair losing >60% WR threshold)
    for pair, stats in m.get("pve_1h", {}).items():
        if stats.get("n", 0) >= 15 and stats.get("wr", 1.0) < 0.40:
            tg(f"⚠️ PVE {pair}: 1h WR={stats['wr']:.0%} n={stats['n']} pnl={stats['pnl']:+.4f}$ — "
               f"below 40% floor. Pair ini sedang bleeding. Pertimbangkan disable pair.",
               key=f"pve_bleed_1h:{pair}")
            actions.append(f"pve_bleed_1h:{pair}")

    # 4) Housekeeping: bersihkan cooldown E2 basi
    try:
        c = sqlite3.connect(str(DB), timeout=5)
        c.execute("UPDATE state SET v='0' WHERE (k LIKE '%route_disabled%' OR k LIKE '%blacklist%') AND CAST(v AS REAL) < strftime('%s','now')-3600")
        c.commit(); c.close()
    except Exception:
        pass
    return actions


def _check_daemon_stuck(m: dict) -> str:
    """Detect daemon stuck patterns & signal restart if needed.
    Returns action string if stuck, empty string if healthy.
    
    TWO PATTERNS:
      A. STUCK-RT: fills >= 5 dalam 20 menit TAPI 0 RT selesai
         → daemon "sibuk" tapi tidak bisa menyelesaikan round-trip
         → ROOT CAUSE: orderID=0 pada SELL / inventory drift parah
      B. ZERO-FILL: daemon alive TAPI 0 fills > ZERO_FILL_MINUTES
         → daemon HANG / loop error tanpa quote
    """
    if not m["engine_alive"]:
        return ""  # Watchdog handles dead daemon
    
    # Pattern A: STUCK-RT
    # B55: fills use ISO timestamp ('2026-07-02T16:56:50+00:00') but datetime('now') returns
    # space-separated ('2026-07-02 17:02:24'). SQLite string compare: 'T'(84) > ' '(32) so
    # ALL ISO fills appear "future" → fills_20m always ≥ real fills count. Fix: use Python
    # datetime cutoff in ISO format so both sides match.
    _cutoff_20m = (datetime.now(timezone.utc) - timedelta(minutes=DAEMON_STUCK_RT_MINUTES)).isoformat()
    frows = _q("SELECT COUNT(*) FROM fills WHERE ts >= ?", (_cutoff_20m,))
    fills_20m = frows[0][0] if frows and frows[0] else 0

    rrows = _q("SELECT COUNT(*) FROM rts WHERE ts_close >= ?", (_cutoff_20m,))
    rts_20m = rrows[0][0] if rrows and rrows[0] else 0
    
    if fills_20m >= 5 and rts_20m == 0:
        msg = (f"🔴 STUCK-RT: {fills_20m} fills dalam 20 menit tapi 0 RT selesai. "
               f"Root cause: orderID=0 / SELL gagal / inventory drift. "
               f"Mengirim restart signal ke watchdog.")
        log(msg)
        tg(msg, key="stuck_rt")
        _write_restart_signal("stuck-rt", fills_20m, rts_20m)
        return "auto_restart_stuck_rt"
    
    # Pattern B: ZERO-FILL
    frows2 = _q("SELECT MAX(ts) FROM fills")
    fills_age = 999
    if frows2 and frows2[0][0]:
        try:
            last_dt = datetime.fromisoformat(frows2[0][0])
            fills_age = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
        except Exception:
            pass
    
    if fills_age > ZERO_FILL_MINUTES:
        # Double-check: count fills in last 30 min (B55: use ISO cutoff, not datetime('now'))
        _cutoff_30m = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        frows3 = _q("SELECT COUNT(*) FROM fills WHERE ts >= ?", (_cutoff_30m,))
        fills_30m = frows3[0][0] if frows3 and frows3[0] else 0
        if fills_30m == 0:
            if not _target_policy_expects_fills():
                msg = (f"🟡 ZERO-FILL {fills_age:.0f} menit tetapi target policy sedang block/no-trade. "
                       f"Tidak restart; pantau heartbeat dan policy.")
                log(msg)
                tg(msg, key="zero_fill_policy_blocked")
                return "zero_fill_policy_blocked"
            msg = (f"🔴 ZERO-FILL: daemon alive tapi 0 fill selama {fills_age:.0f} menit. "
                   f"Daemon HANG / loop error tanpa quote. Mengirim restart signal.")
            log(msg)
            tg(msg, key="zero_fill")
            _write_restart_signal("zero-fill", fills_age, 0)
            return "auto_restart_zero_fill"
    
    return ""


def _check_pnl_guard(m: dict) -> str:
    """PNL GUARD: protect capital from bleeding.
    
    Thresholds (1h net = PnL - fee):
      -$5  → WARNING Telegram
      -$15 → CRITICAL Telegram + write PNL_HALT signal
      -$30 → EMERGENCY: write PNL_HALT + RESTART_SIGNAL (force stop)
    
    Per-pair threshold (1h):
      -$3  → auto-pause recommendation for that pair
    
    Returns action string if guard triggered, empty string if OK.
    """
    net_1h = m.get("pnl_1h_net", 0)
    pair_pnl = m.get("pair_pnl_1h", {})
    
    # EMERGENCY: $30+ loss in 1 hour — force stop everything
    if net_1h < -30:
        msg = (f"🚨🚨 PNL EMERGENCY: 1h net -${abs(net_1h):.2f}! "
               f"Capital protection triggered. Writing HALT + RESTART signals.")
        log(msg)
        tg(msg, key="pnl_emergency")
        # Write both halt and restart signals
        try:
            HALT_FILE = PROJECT / "data" / "PNL_HALT"
            HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
            HALT_FILE.write_text(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "net_1h": net_1h,
                "reason": "1h loss > $30 emergency threshold"
            }))
        except Exception:
            pass
        _write_restart_signal("pnl-emergency", net_1h, 0)
        return "pnl_emergency_halt"
    
    # CRITICAL: $15+ loss in 1 hour
    if net_1h < -15:
        msg = (f"🔴🔴 PNL CRITICAL: 1h net -${abs(net_1h):.2f}! "
               f"Fee menggerus profit. Review pair performance.")
        log(msg)
        tg(msg, key="pnl_critical")
        return "pnl_critical_alert"
    
    # WARNING: $5+ loss in 1 hour
    if net_1h < -5:
        msg = (f"⚠️ PNL WARNING: 1h net -${abs(net_1h):.2f}. "
               f"Pantau ketat. Pair PnL: {pair_pnl}")
        log(msg)
        tg(msg, key="pnl_warning")
        return "pnl_warning_alert"
    
    # Per-pair check: any pair losing > $3/hour?
    for pair, pnl in pair_pnl.items():
        if pnl < -3:
            msg = (f"🔴 PAIR BLEEDING: {pair} 1h PnL -${abs(pnl):.2f}. "
                   f"Pertimbangkan disable atau naikkan spread.")
            log(msg)
            tg(msg, key=f"pair_bleed_{pair}")
    
    return ""


def _write_restart_signal(stuck_type: str, fills: int, rts: int) -> None:
    """Write restart signal file — watchdog polls & restarts daemon."""
    try:
        RESTART_SIGNAL.parent.mkdir(parents=True, exist_ok=True)
        RESTART_SIGNAL.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": "e1_autopilot",
            "type": stuck_type,
            "fills_20m": fills,
            "rts_20m": rts,
            "message": f"Autopilot detected {stuck_type} — restart required"
        }))
        log(f"RESTART SIGNAL written: {RESTART_SIGNAL}")
    except Exception as e:
        log(f"GAGAL tulis restart signal: {e}")


def _get_active_spot_pairs() -> list:
    """Get active spot pairs from DB (dynamic, not hardcoded)."""
    try:
        rows = _q("SELECT DISTINCT pair FROM fills WHERE pair LIKE '%/%' AND ts >= datetime('now', '-6 hours') ORDER BY pair")
        return [r[0] for r in rows] if rows else ["PEPE/USDC", "SHIB/USDC"]
    except Exception:
        return ["PEPE/USDC", "SHIB/USDC"]


def write_outputs(m: dict, actions: list) -> None:
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        hb = {"ts": m["ts"], "engine_alive": m["engine_alive"],
              "engine_last_alive": time.time() if m["engine_alive"] else
              (json.loads(HEARTBEAT.read_text()).get("engine_last_alive", time.time())
               if HEARTBEAT.exists() else time.time())}
        HEARTBEAT.write_text(json.dumps(hb))
        m["repairs"] = actions
        LATEST.write_text(json.dumps(m, indent=2))
        with open(HISTORY, "a") as f:
            f.write(json.dumps(m) + "\n")
    except Exception:
        pass


def report(m: dict) -> None:
    """30m Telegram report — komprehensif: E1 + PVE + fee efficiency + signals."""
    ev = m["eval"]
    pve = m.get("pve", {})
    sopoints = ev.get("sopoints_ratio", 0)
    fee_ok = "✅" if ev.get("fee_efficiency_ok") else "⚠️"
    vol_trend = ("📈" if ev.get("volume_accelerating") else
                 "📉" if ev.get("volume_decelerating") else "→")
    pve_cum = pve.get("cum_7d", 0)
    pve_status = ("🔴" if pve_cum < -20 else "🟡" if pve_cum < -10 else "✅")

    # PVE 1h per-pair summary
    pve_1h = m.get("pve_1h", {})
    pve_1h_lines = ""
    if pve_1h:
        pve_1h_lines = "\nPVE 1h: " + " | ".join(
            f"{p} WR={s['wr']:.0%} n={s['n']} pnl={s['pnl']:+.3f}$"
            for p, s in pve_1h.items()
        )

    # Env drift warning
    drift = m.get("env_drift", {})
    drift_line = ""
    if drift.get("detected"):
        diffs = drift.get("diffs", [])
        drift_line = f"\n⚠️ ENV DRIFT DETECTED: {', '.join(diffs[:3])}"

    # Halt status
    halt_active = (PROJECT / "data" / "SAFETY_HALT").exists() or \
                  (PROJECT / "data" / "PNL_HALT").exists()
    halt_line = "\n🛑 HALT AKTIF — engine tidak bisa restart" if halt_active else ""

    tg(f"📊 E1+PVE STATUS\n"
       f"E1 2h: {ev['net_rate_pct']:+.3f}% | 30m: {ev['net_rate_pct_30m']:+.3f}% "
       f"({'✅' if ev['no_loss_ok'] else '🔴'})\n"
       f"Vol proj: ${m['volume_weekly_proj']:,.0f}/wk ({ev['volume_target_pct']:.0f}%) {vol_trend}\n"
       f"SoPoints: 1:{sopoints:.0f} {fee_ok} (target 1:6000) | fee 1h: ${m.get('e1_fee_1h',0):.3f}\n"
       f"Fills 1h: {m['e1_fills_1h']} | 15m: {m['pair_fills_15m']}\n"
       f"PVE 7d: cum=${pve_cum:+.2f} WR={pve.get('wr_7d',0)*100:.1f}% n={pve.get('n_7d',0)} {pve_status}"
       f"{pve_1h_lines}{drift_line}{halt_line}"
       )


# ─── SCIENTIFIC EVALUATION (tiap 30 menit) ────────────────────────────────────

def scientific_eval() -> dict:
    """Statistical analysis: Wilson CI per-pair, Mann-Kendall trend, dead hours BH-FDR.

    Tidak overlap dengan sodex_monitor_eval (weekly target) atau safety_guardian (order cancel).
    Output: data/e1_scientific_eval.json
    """
    result: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pairs": {}, "trend": {}, "dead_hours": {}, "warnings": [],
    }

    # 1. Per-pair all-time Wilson CI
    pair_rows = _q("""
        SELECT pair, COUNT(*) AS n,
               SUM(CASE WHEN CAST(net_pnl AS REAL) > 0 THEN 1 ELSE 0 END) AS wins,
               SUM(CAST(net_pnl AS REAL)) AS total_pnl,
               SUM(CAST(volume AS REAL)) AS total_vol
        FROM rts WHERE engine='E1' GROUP BY pair
    """)
    for pair, n, wins, pnl, vol in pair_rows:
        n, wins = int(n or 0), int(wins or 0)
        pnl, vol = float(pnl or 0), float(vol or 0)
        lo, hi, _ = _wilson_ci(wins, n)
        net_rate = pnl / vol if vol else 0.0
        verdict = "PROFITABLE" if lo > 0.5 else "LOSING" if hi < 0.5 else "UNCERTAIN"
        result["pairs"][pair] = {
            "n": n, "wins": wins,
            "win_rate": round(wins / n if n else 0, 4),
            "wilson_lo": round(lo, 4), "wilson_hi": round(hi, 4),
            "net_rate": round(net_rate, 6), "net_pnl": round(pnl, 4),
            "verdict": verdict,
        }
        if verdict == "LOSING" and n >= 30:
            result["warnings"].append(f"{pair} LOSING (Wilson CI upper {hi:.3f} < 0.5, n={n})")

    # 2. Mann-Kendall 7d daily net_pnl trend + Sharpe per pair (dynamic, bukan hardcoded)
    active_pairs = [r[0] for r in _q(
        "SELECT DISTINCT pair FROM rts WHERE engine='E1' AND pair LIKE '%/%' "
        "AND ts_close>=datetime('now','-30 days') ORDER BY pair"
    )] or ["PEPE/USDC", "SHIB/USDC"]
    for pair in active_pairs:
        daily = _q("""
            SELECT DATE(ts_close), SUM(CAST(net_pnl AS REAL))
            FROM rts WHERE engine='E1' AND pair=? AND ts_close>=datetime('now','-7 days')
            GROUP BY DATE(ts_close) ORDER BY DATE(ts_close)
        """, (pair,))
        if len(daily) < 4:
            continue
        pnl_series = [float(r[1] or 0) for r in daily]
        tau, z, p = _mann_kendall(pnl_series)
        direction = "IMPROVING" if tau > 0 and p < 0.10 else "DEGRADING" if tau < 0 and p < 0.10 else "STABLE"
        # Sharpe ratio (annualized, daily PnL series)
        sharpe = _sharpe_daily(pnl_series)
        result["trend"][pair] = {
            "tau": tau, "z_stat": z, "p_val": p,
            "n_days": len(daily), "direction": direction,
            "sharpe_ann": sharpe,
        }
        if direction == "DEGRADING":
            result["warnings"].append(f"{pair} trend DEGRADING (tau={tau:.3f}, p={p:.3f}, sharpe={sharpe:.2f})")

    # 3. Dead hours BH-FDR q=0.10 per pair (dynamic)
    for pair in active_pairs:
        hour_rows = _q("""
            SELECT CAST(strftime('%H', ts_close) AS INT) AS h,
                   COUNT(*) AS n,
                   SUM(CASE WHEN CAST(net_pnl AS REAL) > 0 THEN 1 ELSE 0 END) AS wins
            FROM rts WHERE engine='E1' AND pair=? GROUP BY h HAVING COUNT(*) >= 10
        """, (pair,))
        if not hour_rows:
            continue
        p_list = [(int(h), int(n), int(wins or 0), _binom_p_lower(int(wins or 0), int(n)))
                  for h, n, wins in hour_rows]
        # Benjamini-Hochberg FDR procedure
        m_tests = len(p_list)
        sorted_ps = sorted(enumerate(p_list), key=lambda x: x[1][3])
        max_sig_rank = 0
        for rank, (_, (h, n, wins, p)) in enumerate(sorted_ps, 1):
            if p <= rank / m_tests * 0.10:
                max_sig_rank = rank
        dead = []
        for rank, (_, (h, n, wins, p)) in enumerate(sorted_ps, 1):
            if rank <= max_sig_rank:
                dead.append({"hour_utc": h, "n": n, "wr": round(wins / n, 3), "p_bh": round(p, 4)})
        result["dead_hours"][pair] = sorted(dead, key=lambda x: x["hour_utc"])
        if dead:
            result["warnings"].append(f"{pair} dead UTC hours: {[d['hour_utc'] for d in dead]}")

    try:
        SCIENCE_OUT.parent.mkdir(parents=True, exist_ok=True)
        SCIENCE_OUT.write_text(json.dumps(result, indent=2))
    except Exception:
        pass
    return result


# ─── REGIME ACCURACY TRACKING (tiap 1 jam) ────────────────────────────────────

def _read_intel_regime() -> str:
    """Baca regime dari Intel JSONL (sama sumber yang dipakai engine).
    Mirrors engine logic: high-confidence BTC DOWN and red event risk are BEAR;
    composite score is fallback because it may be an opportunity score.
    """
    intel_dir = PROJECT / "freqtrade_user_data" / "data" / "binance" / "intelligence"
    now_ts = time.time()
    for delta_d in [0, 1]:
        d = (datetime.now(timezone.utc) - timedelta(days=delta_d)).strftime("%Y%m%d")
        f = intel_dir / f"intel_{d}.jsonl"
        if not f.exists():
            continue
        try:
            for line in reversed(f.read_text().strip().splitlines()):
                if not line:
                    continue
                row = json.loads(line)
                age = now_ts - float(row.get("ts", 0))
                if age < 7200:  # max 2h stale
                    score = float(row.get("composite_score", 50))
                    btc_dir = int(row.get("fc_BTC_dir_enc", 1))
                    btc_conf = float(row.get("fc_BTC_conf", 0.0) or 0.0)
                    btc_agree = float(row.get("fc_BTC_agreement", btc_conf) or btc_conf)
                    event_level = str(row.get("event_risk_level", ""))
                    event_score = float(row.get("event_risk_score", 0.0) or 0.0)
                    if btc_conf >= 0.55 and btc_agree >= 0.55 and btc_dir < 0:
                        return "BEAR"
                    if event_level == "RED" and (event_score >= 80 or score < 55):
                        return "BEAR"
                    if btc_conf >= 0.55 and btc_agree >= 0.55 and btc_dir > 0 and score >= 50:
                        return "BULL"
                    return "BULL" if score >= 55 else "BEAR" if score <= 45 else "NEUTRAL"
        except Exception:
            pass
    return "UNKNOWN"


def regime_accuracy_check() -> None:
    """Log regime prediction + PEPE price. Setelah 1h, verifikasi hit-rate.
    Alert bila accuracy < 50% (regime detector tidak berguna).
    Output: data/e1_regime_accuracy.jsonl
    """
    try:
        now_ts = datetime.now(timezone.utc)
        # PEPE price dari fill terbaru
        px_rows = _q("SELECT CAST(price AS REAL) FROM fills WHERE pair='PEPE/USDC' AND engine='E1' ORDER BY ts DESC LIMIT 1")
        pepe_px = float(px_rows[0][0]) if px_rows and px_rows[0][0] else None
        if not pepe_px:
            return

        regime = _read_intel_regime()

        # Load existing log
        entries = []
        if REGIME_LOG.exists():
            try:
                for line in REGIME_LOG.read_text().strip().splitlines():
                    if line:
                        entries.append(json.loads(line))
            except Exception:
                pass

        # Verify unverified entries ≥1h old
        verified_total = 0
        correct_total = 0
        for e in entries:
            if e.get("verified"):
                verified_total += 1
                if e.get("correct"):
                    correct_total += 1
                continue
            try:
                entry_ts = datetime.fromisoformat(e["ts"]).replace(tzinfo=timezone.utc)
                age_s = (now_ts - entry_ts).total_seconds()
            except Exception:
                continue
            if age_s < 3600:
                continue
            pct = (pepe_px - e["pepe_px"]) / e["pepe_px"] if e.get("pepe_px") else 0.0
            e["price_now"] = round(pepe_px, 8)
            e["pct_chg_1h"] = round(pct * 100, 4)
            e["verified"] = True
            # ponytail: ±0.3% threshold separates signal from noise
            if e["regime"] == "BEAR":
                e["correct"] = pct < -0.003
            elif e["regime"] == "BULL":
                e["correct"] = pct > 0.003
            else:
                e["correct"] = abs(pct) < 0.010  # NEUTRAL: price stayed flat
            if e["correct"]:
                correct_total += 1
            verified_total += 1

        # Alert if accuracy < 50%
        if verified_total >= 20:
            acc = correct_total / verified_total
            if acc < 0.50:
                tg(f"⚠️ Regime accuracy {acc*100:.1f}% ({correct_total}/{verified_total}) "
                   f"< 50%. Intelligence recalibration mungkin diperlukan.", key="regime_acc_low")

        # Log new entry
        entries.append({
            "ts": now_ts.isoformat(), "regime": regime,
            "pepe_px": round(pepe_px, 8), "verified": False, "correct": None,
        })

        REGIME_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(REGIME_LOG, "w") as f:
            for e in entries[-500:]:  # keep last 500 entries
                f.write(json.dumps(e) + "\n")

        log(f"REGIME_ACC regime={regime} pepe_px={pepe_px:.8f} verified={verified_total} "
            f"correct={correct_total} acc={'N/A' if verified_total < 20 else f'{correct_total/verified_total*100:.1f}%'}")
    except Exception as exc:
        log(f"regime_accuracy_check error: {exc}")


# ─── AUTO-IMPROVEMENT SUGGESTIONS (tiap 6 jam) ────────────────────────────────

def auto_improve() -> list:
    """Generate data-driven improvement suggestions. TIDAK PERNAH auto-apply.
    Operator yang memutuskan. Output: data/e1_improve_suggestions.jsonl + Telegram.
    """
    suggestions = []
    now = datetime.now(timezone.utc).isoformat()

    # Load latest scientific eval
    science: dict = {}
    try:
        if SCIENCE_OUT.exists():
            science = json.loads(SCIENCE_OUT.read_text())
    except Exception:
        pass

    pairs = science.get("pairs") or {}
    dead_hours = science.get("dead_hours") or {}
    trend = science.get("trend") or {}

    # 1. Pair LOSING dengan confidence tinggi → saran disable atau naikkan min_spread
    for pair, stats in pairs.items():
        if stats.get("verdict") == "LOSING" and stats.get("n", 0) >= 50:
            hi = stats.get("wilson_hi", 1.0)
            suggestions.append({
                "ts": now, "type": "PAIR_LOSING", "pair": pair, "priority": "HIGH",
                "evidence": f"Wilson CI 95% upper={hi:.3f} < 0.5, n={stats['n']}, "
                            f"net_rate={stats['net_rate']*100:+.4f}%",
                "suggestion": (
                    f"XLM/USDC: set TE_SPOT_PAIR_3='' atau naikkan TE_E1_PAIR2_MIN_SPREAD > 0.0012. "
                    if "XLM" in pair else
                    f"{pair}: review min_spread konfigurasi. Pair beroperasi di bawah break-even."
                ),
                "DO_NOT_AUTO_APPLY": True,
            })

    # 2. Dead hours per pair → saran time-gating
    for pair, dead in dead_hours.items():
        if len(dead) >= 2:
            dead_h = sorted(d["hour_utc"] for d in dead)
            suggestions.append({
                "ts": now, "type": "DEAD_HOURS_DETECTED", "pair": pair, "priority": "MEDIUM",
                "evidence": f"BH-FDR significant dead UTC hours: {dead_h} "
                            f"(WR signifikan di bawah 50%, n≥10 per jam)",
                "suggestion": f"Engine E1 belum support per-pair time-gating. "
                              f"Saat didukung: tambah TE_E1_{pair.replace('/', '_').upper()}_DEAD_HOURS={','.join(str(h) for h in dead_h)}. "
                              f"Alternatif: raise min_spread pair ini saat jam tersebut.",
                "DO_NOT_AUTO_APPLY": True,
            })

    # 3. Mann-Kendall degradation signifikan
    for pair, t in trend.items():
        if t.get("direction") == "DEGRADING" and float(t.get("p_val", 1.0)) < 0.10:
            suggestions.append({
                "ts": now, "type": "EDGE_DEGRADING", "pair": pair, "priority": "MEDIUM",
                "evidence": f"Mann-Kendall tau={t['tau']:.3f} z={t['z_stat']:.3f} p={t['p_val']:.3f} "
                            f"(7d net_pnl daily trend DOWN, statistically significant)",
                "suggestion": f"{pair}: 7d edge trend menurun. Review spread conditions & fee tier. "
                              f"Pertimbangkan reduce size sementara sambil monitor.",
                "DO_NOT_AUTO_APPLY": True,
            })

    # 4. Regime accuracy < 50% (dari log)
    try:
        if REGIME_LOG.exists():
            entries = [json.loads(l) for l in REGIME_LOG.read_text().strip().splitlines() if l]
            verified = [e for e in entries if e.get("verified")]
            correct = sum(1 for e in verified if e.get("correct"))
            if len(verified) >= 30 and correct / len(verified) < 0.50:
                acc = correct / len(verified)
                suggestions.append({
                    "ts": now, "type": "REGIME_LOW_ACCURACY", "priority": "MEDIUM",
                    "evidence": f"Regime detector accuracy {acc*100:.1f}% < 50% (n={len(verified)} verified 1h windows)",
                    "suggestion": "Pertimbangkan: (1) reduce hedge aggressiveness; (2) recalibrate Intelligence weights; "
                                  "(3) cek apakah Intel JSONL fresh (max-age 7200s).",
                    "DO_NOT_AUTO_APPLY": True,
                })
    except Exception:
        pass

    # 5. Pair SHIB: jika n kecil (< 100) masih uncertain → saran akumulasi data
    shib = pairs.get("SHIB/USDC", {})
    if 0 < shib.get("n", 0) < 100 and shib.get("verdict") == "UNCERTAIN":
        suggestions.append({
            "ts": now, "type": "INSUFFICIENT_DATA", "pair": "SHIB/USDC", "priority": "LOW",
            "evidence": f"n={shib['n']} RTs, Wilson CI [{shib.get('wilson_lo', 0):.3f},{shib.get('wilson_hi', 1):.3f}] — belum konklusif",
            "suggestion": "SHIB/USDC: lanjutkan akumulasi data. Keputusan valid setelah n≥100 RTs.",
            "DO_NOT_AUTO_APPLY": True,
        })

    # Simpan ke log — "w" (bukan "a") utk cegah duplikasi pada setiap 6h cycle
    if suggestions:
        try:
            IMPROVE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(IMPROVE_LOG, "w") as f:
                for s in suggestions:
                    f.write(json.dumps(s) + "\n")
        except Exception:
            pass
        summary = "\n".join(
            f"[{s['priority']}] {s['type']} {s.get('pair', '')}: {s['suggestion'][:70]}..."
            for s in suggestions[:4]
        )
        tg(f"🔬 AUTO-IMPROVE ({len(suggestions)} saran):\n{summary}\n"
           f"Detail: data/e1_improve_suggestions.jsonl\n"
           f"⚠️ DO_NOT_AUTO_APPLY — semua keputusan manual operator.",
           key="auto_improve")

    return suggestions


# ─── MAIN LOOP ─────────────────────────────────────────────────────────────────

def cycle() -> None:
    global _last_report, _last_science, _last_regime, _last_improve
    m = monitor()
    evaluate(m)
    actions = repair(m)
    write_outputs(m, actions)
    now = time.time()

    # Scientific eval: 30 menit
    if now - _last_science >= SCIENCE_INTERVAL:
        try:
            science = scientific_eval()
            _last_science = now
            warns = science.get("warnings") or []
            pairs_v = {p: d.get("verdict") for p, d in science.get("pairs", {}).items()}
            dead = {p: [d["hour_utc"] for d in hrs] for p, hrs in science.get("dead_hours", {}).items() if hrs}
            log(f"SCIENCE pairs={pairs_v} dead={dead} warns={len(warns)}")
        except Exception as e:
            log(f"scientific_eval error: {e}")

    # Regime accuracy: 1 jam
    if now - _last_regime >= REGIME_INTERVAL:
        regime_accuracy_check()
        _last_regime = now

    # Auto-improve: 6 jam
    if now - _last_improve >= IMPROVE_INTERVAL:
        try:
            suggs = auto_improve()
            _last_improve = now
            if suggs:
                log(f"AUTO_IMPROVE {len(suggs)} saran → {IMPROVE_LOG}")
        except Exception as e:
            log(f"auto_improve error: {e}")

    if now - _last_report >= REPORT_INTERVAL:
        report(m)
        _last_report = now

    log(f"net={m['e1_net_rate']*100:+.3f}% vol_proj=${m['volume_weekly_proj']:,.0f} "
        f"({m['volume_target_pct']:.0f}%) fills1h={m['e1_fills_1h']} repairs={actions}")


def main() -> int:
    log(f"🤖 E1 AUTOPILOT START — interval={CHECK_INTERVAL}s target=${WEEKLY_VOLUME_TARGET:,}/wk")
    tg("🤖 E1 Autopilot aktif — monitor+eval+repair per-menit + scientific 30m + regime 1h + improve 6h (24/7).", key="boot")
    once = "--once" in os.sys.argv
    while True:
        try:
            cycle()
        except Exception as e:
            log(f"cycle error: {e}")
        if once:
            return 0
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    import sys
    os.sys = sys
    raise SystemExit(main())
