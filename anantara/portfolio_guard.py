#!/usr/bin/env python3
"""PORTFOLIO GUARD — rem tingkat portofolio lintas-track (2026-09-28).

Akar masalah yang diukur dari audit 24 jam 28-Sep (akurasi: file state + candle riil):
  * 100% (50/50) trade rugi 24 jam: harga KEMBALI ke harga entry dalam 12 jam
    -> SL kena NOISE, bukan karena arah salah (regime whipsaw).
  * 57 dari 75 trade rugi punya pasangan yang SAMA dipegang track lain bersamaan;
    BTC dipegang 15 posisi & ETH 13 posisi pada saat yang sama -> satu gerakan
    pasar men-stop-out belasan posisi (duplikasi, bukan diversifikasi).
  * Puncak posisi terbuka portfolio: 68 (rata-rata 11,7 dalam 24 jam).
  * Track yang rugi besar terus membuka entry baru di hari yang sama
    (swing: 5 SL beruntun; klaster jam 01-05 & 14 UTC = -$60 dan -$60).

Guard ini dijalankan SEBELUM entry. Lima aturan, semuanya berbasis angka audit:
  R1 pair_cap      : maks 2 posisi sepasang bersamaan di SELURUH track
  R2 total_cap     : maks 15 posisi terbuka bersamaan di seluruh track
  R3 daily_halt    : track berhenti untuk sisa hari UTC bila rugi hari ini
                     <= -3x risiko-per-trade-nya (risiko = exposure x SL%)
  R4 whipsaw_gate  : blokir LONG saat pasar chop/bergejolak
                     (|ret 24j BTC| < 1,5% DAN vol 1 jam pasangan > 1,2%)
  R5 anti_chase    : blokir entry yang mengejar candle (ret 1 jam terakhir
                     > +2,0% untuk long, < -2,0% untuk short)

Fail-closed untuk uang nyata (data pasar gagal -> TIDAK entry).
Fail-open untuk paper (data gagal -> izinkan) supaya bukti riset tidak kelaparan.
"""
from __future__ import annotations
import json, glob, os, time, datetime as dt

# --- ambang (dapat di-override lewat env, tanpa mengubah kode) -----------------
PAIR_CAP = int(os.environ.get("PG_PAIR_CAP", "2"))
TOTAL_CAP = int(os.environ.get("PG_TOTAL_CAP", "15"))

# Buku kapital terpisah: lane UANG NYATA dihitung terpisah dari track PAPER.
# Paper tidak mengonsumsi dana riil, jadi tidak boleh mengunci lane live
# (dan sebaliknya: cap paper antar-track tetap berlaku penuh).
REAL_MONEY_LANES = {"realwide_micro_live", "twoway_micro_live",
                    "sodex_spot_live_test", "pve", "beardown"}
DAILY_HALT_X = float(os.environ.get("PG_DAILY_HALT_X", "3.0"))   # x risiko/trade
WHIPSAW_BTC_RET = float(os.environ.get("PG_WHIPSAW_BTC_RET", "0.015"))
WHIPSAW_VOL = float(os.environ.get("PG_WHIPSAW_VOL", "0.012"))
CHASE_PCT = float(os.environ.get("PG_CHASE_PCT", "0.020"))
ENABLED = os.environ.get("PORTFOLIO_GUARD", "1") == "1"

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")

_POS_KEYS = ("open", "positions", "open_positions")

_SEPARATORS = ("/", "-", "_", ":", " ")
_SUFFIXES = ("USDT", "USDC", "PERP", "USD")


def norm_pair(pair: str) -> str:
    """Nama pasangan diseragamkan: 'BTCUSDT'/'BTC-USD'/'BTC/USDC' -> 'BTC'.

    Bukti audit: state track memakai penamaan berbeda; tanpa normalisasi,
    duplikasi lintas-track (inti masalah) tidak terhitung oleh cap.
    Pemisah dibuang DULU, baru sufatan quote dibuang (kalau tidak, 'BTC/USDC'
    jadi 'BTC/' dan cap bocor — bug ini pernah lolos ke test dan ditangkap test).
    """
    p = str(pair).upper().strip()
    for sep in _SEPARATORS:
        p = p.replace(sep, "")
    for s in _SUFFIXES:
        if p.endswith(s) and len(p) > len(s):
            return p[: -len(s)]
    return p


def snapshot_positions(data_dir: str = DATA, scope: set[str] | None = None) -> list[dict]:
    """Semua posisi terbuka dari seluruh file state -> [{pair, dir, track}].

    scope: bila diisi, hanya posisi dari lane yang namanya termasuk scope yang
    dihitung. Wajib ada karena PAPER (belasan track riset) tidak boleh memblokir
    lane UANG NYATA — dana/kapitalnya berbeda buku; tanpa pemisahan ini, lane live
    bisa terkunci selamanya oleh 17 posisi paper (bug nyata, ditemukan saat uji).
    """
    out: list[dict] = []
    for f in sorted(glob.glob(os.path.join(data_dir, "*state*.json"))):
        try:
            doc = json.load(open(f))
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        track = os.path.basename(f)[:32]
        if ".DRY" in os.path.basename(f):
            continue          # state dry-run bukan posisi nyata (jangan ikut dihitung)
        if scope is not None and not any(s in track for s in scope):
            continue
        for k in _POS_KEYS:
            v = doc.get(k)
            if isinstance(v, dict):
                for pair, pos in v.items():
                    if not isinstance(pos, dict):
                        continue
                    raw = str(pos.get("pair") or pair)
                    out.append({"pair": raw, "key": norm_pair(raw),
                                "dir": str(pos.get("side") or pos.get("direction") or "long").lower(),
                                "track": track})
            elif isinstance(v, list):
                for pos in v:
                    if isinstance(pos, dict):
                        raw = str(pos.get("pair") or "?")
                        out.append({"pair": raw, "key": norm_pair(raw),
                                    "dir": str(pos.get("side") or pos.get("direction") or "long").lower(),
                                    "track": track})
    return out


def _ts_of(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v < 1e11 else float(v) / 1000
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def today_pnl(track_file: str, day: str | None = None) -> float:
    """Realized PnL track pada hari UTC berjalan (dari file state-nya)."""
    day = day or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    try:
        doc = json.load(open(track_file))
    except Exception:
        return 0.0
    tot = 0.0
    for k in ("closed", "closed_trades"):
        for t in (doc.get(k) or []):
            if not isinstance(t, dict):
                continue
            ts = _ts_of(t.get("exit_ts") or t.get("exit_time") or t.get("exit_iso"))
            u = t.get("pnl_usd", t.get("net_usd"))
            if ts is None or not isinstance(u, (int, float)):
                continue
            if dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d") == day:
                tot += float(u)
    return tot


def nowcast_regime(max_age_s: float = 600) -> dict | None:
    """Baca hasil regime nowcast TERBARU (data/regime_nowcast.json).

    Basa (lebih tua dari max_age_s) dianggap tidak ada -> guard jatuh ke
    perhitungan sendiri, jadi keputusan tidak pernah bergantung data basi.

    Path bisa di-override dg env PGUARD_NOWCAST_PATH (AUDIT 29-Sep-2026): tanpa ini,
    unit test yang menjalankan lane nyata membaca file nowcast PRODUKSI yang di-refresh
    tiap 2 menit → hasil test non-deterministik (mis. test "BEAR harus buka short"
    gagal hanya karena nowcast live sedang CHOP). Bukan melonggarkan guard: hanya
    sumber data yang bisa diisolasi.
    """
    try:
        path = os.environ.get("PGUARD_NOWCAST_PATH") or os.path.join(DATA, "regime_nowcast.json")
        d = json.load(open(path))
        if not isinstance(d, dict):
            return None
        if time.time() - float(d.get("ts", 0)) > max_age_s:
            return None
        return d
    except Exception:
        return None


def allow_entry(pair: str, direction: str, track: str,
                open_positions: list[dict], *,
                track_day_pnl_usd: float = 0.0,
                risk_per_trade_usd: float = 0.0,
                btc_ret_24h: float | None = None,
                pair_ret_1h: float | None = None,
                pair_vol_1h: float | None = None,
                regime: dict | None = None,
                fail_closed: bool = False) -> tuple[bool, str]:
    """True = boleh entry. Mengembalikan (izin, alasan) agar bisa dilog apa adanya."""
    if not ENABLED:
        return True, "guard-off"
    d = str(direction).lower()

    # R1 pair cap (pasangan dinormalkan: BTCUSDT == BTC-USD == BTC)
    want = norm_pair(pair)
    same = sum(1 for p in open_positions if p.get("key", norm_pair(p.get("pair", ""))) == want)
    if same >= PAIR_CAP:
        return False, f"R1 pair_cap: {want} sudah {same} posisi (cap {PAIR_CAP})"

    # R2 total cap
    if len(open_positions) >= TOTAL_CAP:
        return False, f"R2 total_cap: {len(open_positions)} posisi terbuka (cap {TOTAL_CAP})"

    # R3 daily halt per track
    if risk_per_trade_usd > 0 and track_day_pnl_usd <= -DAILY_HALT_X * risk_per_trade_usd:
        return False, (f"R3 daily_halt: rugi hari ini ${track_day_pnl_usd:.2f} "
                       f"<= -{DAILY_HALT_X}x risiko ${risk_per_trade_usd:.2f}")

    # R4a REGIME NOWCAST (sensor cepat 5m/15m/1h, sumber tunggal)
    if regime:
        adv = regime.get("advice") or {}
        rg = regime.get("regime", "UNKNOWN")
        if adv.get("entry_blocked"):
            return False, f"R4 regime {rg}: {adv.get('note', 'entry diblokir')}"
        dirs = [str(x).lower() for x in (adv.get("directions") or [])]
        if dirs and d not in dirs:
            return False, f"R4 regime {rg} hanya mengizinkan {dirs} (diminta {d})"

    # R4b whipsaw gate (perlu data pasar; live = fail-closed)
    if btc_ret_24h is None or pair_vol_1h is None:
        if fail_closed:
            return False, "R4 data pasar tidak tersedia (fail-closed)"
    else:
        if (d == "long" and abs(btc_ret_24h) < WHIPSAW_BTC_RET
                and pair_vol_1h > WHIPSAW_VOL):
            return False, (f"R4 whipsaw: BTC 24j {btc_ret_24h*100:+.2f}% (chop) & "
                           f"vol 1j {pair_vol_1h*100:.2f}% > {WHIPSAW_VOL*100:.1f}%")

    # R5 anti-chase
    if pair_ret_1h is None:
        if fail_closed:
            return False, "R5 data 1j tidak tersedia (fail-closed)"
    else:
        if d == "long" and pair_ret_1h > CHASE_PCT:
            return False, f"R5 anti_chase: candle 1j {pair_ret_1h*100:+.2f}% > +{CHASE_PCT*100:.1f}%"
        if d == "short" and pair_ret_1h < -CHASE_PCT:
            return False, f"R5 anti_chase: candle 1j {pair_ret_1h*100:+.2f}% < -{CHASE_PCT*100:.1f}%"

    return True, "ok"


# --- pembungkus untuk dipakai lane: bangun konteks otomatis --------------------
def market_context(binance_symbol: str, cache: dict | None = None) -> dict:
    """Ambil metrik pasar dari Binance (spot, fallback futures). Nol dependensi baru."""
    import urllib.request
    cache = cache if cache is not None else {}
    key = f"mkt:{binance_symbol}"
    if key in cache and time.time() - cache[key][0] < 240:
        return cache[key][1]
    out: dict[str, float | None] = {"btc_ret_24h": None, "pair_ret_1h": None, "pair_vol_1h": None}
    def kl(sym, interval="1h", limit=26):
        for base in ("https://api.binance.com/api/v3/klines",
                     "https://fapi.binance.com/fapi/v1/klines"):
            try:
                u = f"{base}?symbol={sym}&interval={interval}&limit={limit}"
                with urllib.request.urlopen(u, timeout=8) as r:
                    k = json.load(r)
                if isinstance(k, list) and len(k) >= 2:
                    return k
            except Exception:
                continue
        return []
    try:
        b = kl("BTCUSDT")
        if b:
            out["btc_ret_24h"] = float(b[-1][4]) / float(b[-25][4]) - 1
        p = kl(binance_symbol)
        if p:
            i = len(p) - 2                      # bar tertutup terakhir
            out["pair_ret_1h"] = float(p[i][4]) / float(p[i][1]) - 1
            rng = [abs(float(c[4]) / float(c[1]) - 1) for c in p[i - 5:i + 1]]
            out["pair_vol_1h"] = sum(rng) / len(rng)
    except Exception:
        pass
    cache[key] = (time.time(), out)
    return out


def guard_entry(binance_symbol: str, pair: str, direction: str, track: str,
                *, risk_per_trade_usd: float = 0.0, track_state_file: str | None = None,
                fail_closed: bool = False, log=print) -> bool:
    """API ringkas untuk lane: cek semua aturan, log bila ditolak.

    Scope posisi mengikuti buku kapital track: lane UANG NYATA hanya dihitung
    terhadap lane uang nyata lain; track PAPER dihitung terhadap semua track
    (cap antar-track justru inti perbaikannya).
    """
    try:
        scope = REAL_MONEY_LANES if track in REAL_MONEY_LANES else None
        pos = snapshot_positions(scope=scope)
        ctx = market_context(binance_symbol)
        day_pnl = today_pnl(track_state_file) if track_state_file else 0.0
        ok, why = allow_entry(pair, direction, track, pos,
                              track_day_pnl_usd=day_pnl,
                              risk_per_trade_usd=risk_per_trade_usd,
                              btc_ret_24h=ctx["btc_ret_24h"],
                              pair_ret_1h=ctx["pair_ret_1h"],
                              pair_vol_1h=ctx["pair_vol_1h"],
                              regime=nowcast_regime(),
                              fail_closed=fail_closed)
        if not ok:
            log(f"[PORTFOLIO-GUARD] TOLAK {pair} {direction} [{track}]: {why}")
        return ok
    except Exception as e:            # guard tidak boleh mematikan lane
        log(f"[PORTFOLIO-GUARD] error {e} -> {'TOLAK (fail-closed)' if fail_closed else 'izinkan'}")
        return not fail_closed
