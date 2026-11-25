#!/usr/bin/env python3
"""
ANANTARA SAKTI — Paper Test LEARNING ENGINE (wajib hasil belajar)
=================================================================
Mengukur HASIL PEMBELAJARAN dari SEMUA paper test secara ketat & ilmiah.

Prinsip (user directive 2026-08-06): setiap paper test WAJIB menghasilkan
pembelajaran signifikan — bukan sekadar "berjalan". Mesin ini:
  1. Membaca semua state track (schema berbeda dinormalisasi).
  2. Menghitung metrik belajar per track: n, WR, PF, avg PnL, avg hold,
     breakdown exit (TP/SL/TIME), per-pair, per-intel (combined).
  3. Data-gate wajib: n>=20 = SIGNIFICANT | n>=5 = EMERGING | n<5 = INSUFFICIENT
     (INSUFFICIENT = BELUM ada pembelajaran → laporan wajib menandainya + saran).
  4. Output: docs/PAPER_TEST_LEARNING_REPORT.md (rolling) + data/paper_test_learning.json.

Run:  python3 scripts/paper_test_learning.py            # tulis md + json
      python3 scripts/paper_test_learning.py --json      # hanya json
      python3 scripts/paper_test_learning.py --status    # ringkas ke stdout
"""
import argparse
import json
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests as _req

PROJECT = Path(__file__).resolve().parents[1]
DATA = PROJECT / "data"
REPORT_MD = PROJECT / "docs" / "PAPER_TEST_LEARNING_REPORT.md"
REPORT_JSON = DATA / "paper_test_learning.json"
GATE_JSON = DATA / "paper_test_edge_gate.json"

MIN_SIGNIFICANT = 20   # n closed trade utk klaim "pembelajaran signifikan"
MIN_EMERGING = 5
# Edge-gate: jumlah trade minimum per arah sebelum keputusan PAUSE/KEEP
GATE_MIN_N = 8
# Anti-predictive jika avg_fav < fraksi ini x avg_adv
ANTI_PRED_FRAC = 0.40
HAS_EDGE_FRAC = 0.80
# High-Gross-Edge filter (V2, 2026-08-11): hanya sinyal dengan pergerakan rata-rata
# >= 0.5% yang layak dikejar — karena cost riil 0.16-0.38%/RT akan menggerus edge kecil.
# Gross edge < ambang = TIDAK layak live meskipun WR tinggi (biaya > keuntungan kotor).
HIGH_EDGE_MIN_PCT = 0.50
# Cost model riil (fee + slippage + funding) untuk menilai net edge.
COST_MODEL_PCT = 0.16
# 5m-path disk cache (2026-09-10 bottleneck fix): signal_quality me-refetch
# jalur 5m utk SEMUA trade tiap run (~454 klines call, ratusan detik wall,
# tumbuh dgn n). Data klines historis IMMUTABLE -> cache disk permanen aman;
# run berikut hanya fetch trade BARU. Tanpa ini learning-gate regen lambat dan
# rentan timeout manual.
CACHE_5M_JSON = DATA / "paper_learning_5m_cache.json"
_CACHE_5M: dict | None = None
# Forced pause = hasil riset cross-track yang harus survive regenerasi gate.
# RCA 2026-09-10: paper_test_learning regen mengosongkan REAL-wide pause karena
# rule per-track n>=8 belum tercapai, padahal cross-track proof menunjukkan
# SUI/ADA/HYPE/ONDO adalah toxic drag (WR<=33%, net -$79.51); maturity tracker
# sudah mengecualikan ini. Tanpa forced pause, LIVE execution bisa diverge dari
# maturity/evidence report. Keep surgical: only REAL-wide, not global ban.
FORCED_PAIRS_PAUSE = {"REAL-wide": {"SUI", "ADA", "HYPE", "ONDO"}}
# Legacy keep-paused (2026-09-25): ARB & DOGE di-pause oleh heuristic lama (n>=8,
# WR<40%) TAPI uji bootstrap all-time tidak signifikan (DOGE p=0.292, ARB p=0.399).
# Dipertahankan demi perubahan satu-variabel (perbaikan #3 = gate statistik), akan
# ditinjau ulang saat masing-masing mencapai n>=20 dengan rule statistik baru.
LEGACY_PAIRS_PAUSE = {"REAL-wide": {"ARB", "DOGE"}}
# UJI STATISTIK PAIR-DRAG (2026-09-25, perbaikan #3):
# Rule lama "n>=8 AND pnl<0 AND WR<40%" secara statistik lemah — WR 40% berada DI ATAS
# break-even geometri TP6/SL1.5 (1.5/(6+1.5) = 20%), jadi bisa mem-pause pair ber-expectancy
# positif. Diganti uji bootstrap mean pnl_usd < 0 (one-sided, 2000 resample), min_n=5,
# window rolling 30 trade terakhir per pair, dengan BH-FDR alpha=0.05 (menguji 23 pair
# sekaligus = wajib koreksi multiplisitas).
# Validasi WALK-FORWARD (tanpa look-ahead, n=132 forward, gate hanya pakai data < t):
#   base mean +$0.514/trade → gated +$0.640/trade (Δ+$0.125, BH-FDR); tanpa BH +$0.682
#   (Δ+$0.168) — dipilih BH-FDR karena lebih konservatif & sesuai standar anti-overfit.
# Rolling window = drag yang sembuh otomatis lepas (tidak stuck seperti rule all-time).
PAIR_GATE_MIN_N = 5
PAIR_GATE_WINDOW = 30
PAIR_GATE_ALPHA = 0.05
PAIR_GATE_BOOTSTRAP_ITERS = 2000
PAIR_GATE_MAX_PAUSE_FRACTION = 0.35   # jangan lumpuhkan >35% universe (guard degenerasi)

BIN = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "DOGE": "DOGEUSDT",
       "ADA": "ADAUSDT", "LINK": "LINKUSDT", "XRP": "XRPUSDT", "AVAX": "AVAXUSDT",
       "BNB": "BNBUSDT"}

# (label, state_file, type) — type menentukan skema
TRACKS = [
    ("SWING",        "paper_test_swing_state.json",        "swing"),
    ("SWING-PARTIAL","paper_test_swing_state_partial.json","swing"),
    ("SPOT-SWING",   "paper_test_spot_swing_state.json",  "swing"),
    ("REAL-wide",    "paper_test_realwide_state.json",     "realwide"),
    ("COMBINED",     "paper_test_combined_state.json",     "combined"),
    ("COMBINED-SCS", "paper_test_combined_scs_state.json", "combined"),
    ("TWO-WAY",      "paper_test_twoway_state.json",       "swing"),
    ("FAST",         "paper_test_fast_state.json",         "swing"),
    ("DONCHIAN",     "paper_test_donchian_state.json",     "realwide"),
    ("SPOT-SWING-CEX","paper_test_spot_swing_cex.json",    "spot_swing_cex"),
    ("SPOT-LIVE",    "spot_live_test_state.json",          "live"),
    ("PERPS-SHORT",  "perps_short_live_state.json",        "live"),
]


def _f(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def _to_ts(x):
    """ISO string atau epoch → epoch detik (UTC), atau None."""
    if x is None:
        return None
    try:
        if isinstance(x, (int, float)):
            return float(x)
        return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _fetch_5m_path(sym, start_ms, end_ms):
    out, cur = [], start_ms
    try:
        while cur < end_ms:
            r = _req.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": sym, "interval": "5m",
                                 "startTime": cur, "endTime": end_ms, "limit": 1000}, timeout=12).json()
            if not isinstance(r, list) or not r:
                break
            out += r
            cur = r[-1][0] + 300000
            if len(r) < 1000:
                break
    except Exception:
        pass
    return out


def _cache_5m_load() -> dict:
    """Load disk cache sekali per proses. Key = sym:entry_ms:end_ms."""
    global _CACHE_5M
    if _CACHE_5M is None:
        try:
            _CACHE_5M = json.loads(CACHE_5M_JSON.read_text())
        except Exception:
            _CACHE_5M = {}
    if not isinstance(_CACHE_5M, dict):
        _CACHE_5M = {}
    return _CACHE_5M


def _cache_5m_save():
    if _CACHE_5M is None:
        return
    try:
        tmp = CACHE_5M_JSON.with_suffix(".tmp")
        tmp.write_text(json.dumps(_CACHE_5M))
        tmp.replace(CACHE_5M_JSON)
    except Exception:
        pass  # cache adalah optimasi — gagal simpan tidak boleh gagalkan run


def signal_quality(trades):
    """FAV/ADV per trade dari jalur harga 5m RIIL (offline, akurat).

    max_fav = ekskursi maksimum MENGUNTUNGKAN (ke arah trade) sebelum exit
    max_adv = ekskursi maksimum MERUGIKAN (melawan trade) sebelum exit
    → rasio avg_fav/avg_adv = ukuran kualitas ARAH sinyal (bukan geometri exit).
    """
    rows = []
    for t in trades:
        sym = t.get("sym", "?").split("[")[0].split("-")[0]
        if sym not in BIN:
            continue
        et = _to_ts(t.get("entry_ts") or t.get("entry_iso") or t.get("entry_time"))
        if not et:
            continue
        xt = _to_ts(t.get("exit_ts") or t.get("exit_iso") or t.get("exit_time"))
        if xt and xt > et:
            end_ms = int(xt * 1000)                 # sampai SAAT exit (akurat)
        else:
            hold_s = _f(t.get("hold_h") or t.get("hold_hours"), 48) * 3600
            end_ms = int((et + min(hold_s, 48 * 3600)) * 1000)
        # CACHE 2026-09-10: klines 5m historis immutable — fetch sekali, reuse
        # lintas run. Key memuat endpoint rentang sehingga tak ada collision.
        cache = _cache_5m_load()
        ck = f"{BIN[sym]}:{int(et * 1000)}:{end_ms}"
        path = cache.get(ck)
        if path is None:
            path = _fetch_5m_path(BIN[sym], int(et * 1000), end_ms)
            if path:
                cache[ck] = path
        if not path:
            continue
        entry = _f(t.get("entry_p") or t.get("entry_price"), 0)
        if entry <= 0:
            continue
        long = str(t.get("side") or t.get("direction") or "L").upper().startswith("L")
        fav = adv = 0.0
        for x in path:
            hi, lo = float(x[2]), float(x[3])
            if long:
                fav = max(fav, (hi - entry) / entry)
                adv = max(adv, (entry - lo) / entry)
            else:
                fav = max(fav, (entry - lo) / entry)
                adv = max(adv, (hi - entry) / entry)
        rows.append({"sym": sym, "dir": "LONG" if long else "SHORT",
                     "max_fav": round(fav, 4), "max_adv": round(adv, 4),
                     "entry_ts": et, "pnl_pct": _f(t.get("pnl_pct"))})
    return rows


def edge_temporal_report():
    """UJI STABILITAS TEMPORAL (metode = cek temporal signals.db user).

    Pool semua trade lintas track per arah, split ke 3 window waktu, hitung
    WR + FAV/ADV per window + rentang tanggal. Mengungkap confound arah↔waktu:
    "SHORT buruk" bisa jadi "window awal buruk untuk semua", bukan SHORT inheren.
    Verdict: CONSISTENT (semua window setuju, n>=6) / REGIME_DEPENDENT (tanda
    berbalik antar window) / INSUFFICIENT (belum cukup data).
    """
    rows = []
    for label, fname, stype in TRACKS:
        path = DATA / fname
        if not path.exists():
            continue
        try:
            st = json.loads(path.read_text())
        except Exception:
            continue
        trades = normalize(stype, st)
        for r in signal_quality(trades):
            r["label"] = label
            rows.append(r)

    out = {}
    for d in ("LONG", "SHORT"):
        rr = [r for r in rows if r["dir"] == d and r.get("entry_ts")]
        rr.sort(key=lambda r: r["entry_ts"])
        n = len(rr)
        if n == 0:
            out[d] = {"n": 0, "verdict": "NO_DATA", "windows": []}
            continue
        # FIX-1 (2026-08-11): window by-DATE (3 bucket waktu sama rata), bukan by-count.
        # by-count mengacaukan batas tanggal (mis. 'W3 WR14%' padahal data mentah 35%).
        t_min, t_max = rr[0]["entry_ts"], rr[-1]["entry_ts"]
        span = max(t_max - t_min, 1.0)
        windows = []
        for k in range(3):
            lo = t_min + span * k / 3
            hi = t_min + span * (k + 1) / 3
            chunk = [r for r in rr if lo <= r["entry_ts"] < (hi if k < 2 else t_max + 1)]
            if not chunk:
                continue
            nn = len(chunk)
            af = sum(r["max_fav"] for r in chunk) / nn
            aa = sum(r["max_adv"] for r in chunk) / nn
            wr = sum(1 for r in chunk if r["pnl_pct"] > 0) / nn
            t0 = datetime.fromtimestamp(chunk[0]["entry_ts"], tz=timezone.utc).strftime("%d/%m")
            t1 = datetime.fromtimestamp(chunk[-1]["entry_ts"], tz=timezone.utc).strftime("%d/%m")
            windows.append({"w": k + 1, "n": nn, "wr": round(wr, 3),
                            "avg_fav": round(af, 4), "avg_adv": round(aa, 4),
                            "fav_gt_adv": af >= aa, "range": f"{t0}-{t1}"})
        signs = {w["fav_gt_adv"] for w in windows if w["n"] >= 2}
        if len(signs) == 1 and n >= 6:
            verdict = "CONSISTENT"
        elif len(signs) == 2:
            verdict = "REGIME_DEPENDENT"
        else:
            verdict = "INSUFFICIENT"
        out[d] = {"n": n, "verdict": verdict, "windows": windows}

    # ── FIX-2 (2026-08-11): GATE pakai jendela RECENT (48h) bila cukup data →
    # mengikuti regime SAAT INI (bukan rata-rata semua-waktu yg LAG). Deteksi
    # FLAPPING (regime berbalik cepat) → STANDBY: blok SEMUA arah (tak ada arah
    # yg bisa dipercaya saat flapping) — ini koreksi kelemahan gate statis.
    now = time.time()
    RECENT_H = 48.0
    aggregate = {}
    recent_n = {"LONG": 0, "SHORT": 0}
    for d in ("LONG", "SHORT"):
        rr = [r for r in rows if r["dir"] == d and r.get("entry_ts")]
        recent = [r for r in rr if now - r["entry_ts"] <= RECENT_H * 3600]
        src = recent if len(recent) >= 4 else rr   # recent bila cukup, else all-time
        nn = len(src)
        if nn == 0:
            aggregate[d] = {"n": 0, "verdict": "NO_DATA", "action": "COLLECT"}
            continue
        af = sum(r["max_fav"] for r in src) / nn
        aa = sum(r["max_adv"] for r in src) / nn
        v = sq_verdict(af, aa, nn)
        aggregate[d] = {"n": nn, "avg_fav": round(af, 4), "avg_adv": round(aa, 4),
                        "verdict": v, "action": gate_action(v),
                        "window": "recent48h" if src is recent else "all"}
        recent_n[d] = len(recent)

    has_l = out.get("LONG", {}).get("verdict")
    has_s = out.get("SHORT", {}).get("verdict")
    # FIX-3 (2026-08-11): STANDBY hanya sah bila didukung data RECENT (48h) cukup.
    # Verdict temporal all-time (mis. 39 trades Jun-Agu) SELALU tampak
    # REGIME_DEPENDENT karena market memang berubah regime antar bulan → standby
    # permanen memblokir SEMUA paper test (kontradiksi dgn _AGGREGATE=COLLECT).
    # Sesuai komentar FIX-2 ("gate ikuti regime SAAT INI"): gunakan jendela
    # recent 48h sebagai gerbang. Bila data recent belum cukup (< GATE_MIN_N per
    # arah), verdict = INSUFFICIENT → COLLECT → paper test terus mengumpulkan
    # data pembelajaran (tujuan proyek), bukan diblokir oleh data lama.
    recent_ok = (recent_n.get("LONG", 0) >= GATE_MIN_N
                 or recent_n.get("SHORT", 0) >= GATE_MIN_N)
    if recent_ok and (has_l == "REGIME_DEPENDENT" or has_s == "REGIME_DEPENDENT"):
        reg = "FLAPPING"
    elif recent_ok and (has_l == "CONSISTENT" or has_s == "CONSISTENT"):
        reg = "STABLE"
    else:
        reg = "INSUFFICIENT"
    standby = (reg == "FLAPPING")
    regime_info = {"regime": reg, "standby": standby, "recent_h": RECENT_H,
                   "recent_n": recent_n, "recent_ok": recent_ok,
                   "note": "STANDBY hanya saat FLAPPING terbukti pd data recent 48h cukup (n>=GATE_MIN_N); data all-time tidak memblokir data collection."}
    return out, aggregate, regime_info


def sq_verdict(avg_fav, avg_adv, n):
    """Edge-gate verdict per arah. avg_fav/avg_adv positif. n>=GATE_MIN_N utk keputusan."""
    if n < GATE_MIN_N:
        return "INSUFFICIENT"
    if avg_adv <= 0:
        return "HAS_EDGE"
    if avg_fav >= avg_adv * HAS_EDGE_FRAC:
        return "HAS_EDGE"
    if avg_fav >= avg_adv * ANTI_PRED_FRAC:
        return "MARGINAL"
    return "ANTI_PREDICTIVE"


def gate_action(verdict):
    return {"HAS_EDGE": "KEEP", "MARGINAL": "WATCH", "ANTI_PREDICTIVE": "PAUSE",
            "INSUFFICIENT": "COLLECT"}[verdict]


def normalize(ttype: str, st: dict):
    """Kembalikan list trade ternormalisasi {sym, side, entry_p, exit_p,
    pnl_usd, pnl_pct, hold_h, exit_reason, extra} dari state per-track."""
    if ttype == "spot_swing_cex":
        # Skema nested: {"tracks": {"SIGNAL": [...], "RANDOM": [...]}}
        # Record: pair/direction(int 1|-1)/status OPEN|CLOSED/pnl_pct/hold_h
        # FIX UNIT (2026-11-06): lane ini menulis pnl_pct sebagai FRAKSI (0.014 = 1.4%),
        # lane lain memakai persen. Tanpa konversi mean PnL lane ini terbaca 1/100 dari
        # nilai sebenarnya → gate LONG/SHORT menerima edge palsu.
        out = []
        for arm, raw_list in (st.get("tracks") or {}).items():
            for t in raw_list or []:
                if t.get("status") != "CLOSED":
                    continue  # hanya trade tertutup yang punya PnL final
                sym = t.get("sym") or t.get("pair") or t.get("coin") or "?"
                entry_p = t.get("entry_p") or t.get("entry_price")
                exit_p = t.get("exit_p") or t.get("exit_price")
                pct = _f(t.get("pnl_pct"))
                d = t.get("direction")
                side = t.get("side") or ("L" if d == 1 else ("S" if d == -1 else None))
                if side not in ("L", "S") and entry_p and exit_p:
                    # record lama tanpa field direction: turunkan arah dari harga
                    side = "L" if float(exit_p) >= float(entry_p) else "S"
                raw_usd = t.get("pnl_usd")
                if raw_usd is not None:
                    usd = _f(raw_usd)
                elif pct is not None:
                    # lane ini tidak mencatat notional → pakai fraksi PnL sebagai proxy
                    # (SATUAN: fraksi notional, bukan USD). Menjaga tanda & besaran relatif
                    # agar gate profitabilitas tidak membaca 0.
                    usd = pct
                else:
                    usd = 0.0
                out.append({"sym": f"{sym}[{arm}]", "side": side or "?",
                            "entry_p": entry_p, "exit_p": exit_p,
                            "pnl_usd": usd, "pnl_pct": pct,
                            "hold_h": _f(t.get("hold_h") or t.get("hold_hours")),
                            "exit_reason": t.get("exit_reason") or t.get("exit_r") or t.get("reason") or "?",
                            "extra": {},
                            "entry_ts": t.get("entry_ts") or t.get("entry_iso") or t.get("entry_time"),
                            "exit_ts": t.get("exit_ts") or t.get("exit_iso") or t.get("exit_time")})
        return out
    raw = st.get("closed") or st.get("closed_trades") or []
    out = []
    for t in raw:
        sym = t.get("sym") or t.get("pair") or t.get("coin") or "?"
        side = t.get("side") or (t.get("direction") or "?").upper()[:1]
        entry = t.get("entry_p") or t.get("entry_price")
        exit_p = t.get("exit_p") or t.get("exit_price")
        pnl_usd = _f(t.get("pnl_usd"))
        pnl_pct = _f(t.get("pnl_pct"))
        hold = _f(t.get("hold_h") or t.get("hold_hours"))
        reason = t.get("exit_reason") or t.get("exit_r") or t.get("reason") or "?"
        extra = {}
        if t.get("regime"):
            extra["regime"] = t["regime"]
        if t.get("intel_label"):
            extra["intel"] = t["intel_label"]
        out.append({"sym": sym, "side": side, "entry_p": entry, "exit_p": exit_p,
                    "pnl_usd": pnl_usd, "pnl_pct": pnl_pct, "hold_h": hold,
                    "exit_reason": reason, "extra": extra,
                    "entry_ts": t.get("entry_ts") or t.get("entry_iso") or t.get("entry_time"),
                    "exit_ts": t.get("exit_ts") or t.get("exit_iso") or t.get("exit_time")})
    return out


def started_at(st: dict):
    for k in ("started_at", "created"):
        if st.get(k):
            try:
                return datetime.fromisoformat(str(st[k]).replace("Z", "+00:00"))
            except Exception:
                return None
    return None


def analyze(label, stype, st):
    trades = normalize(stype, st)
    n = len(trades)
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    gp = sum(t["pnl_usd"] for t in wins)
    gl = -sum(t["pnl_usd"] for t in losses)
    pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
    exits = {}
    for t in trades:
        r = t["exit_reason"]
        exits.setdefault(r, {"n": 0, "pnl": 0.0})
        exits[r]["n"] += 1
        exits[r]["pnl"] += t["pnl_usd"]
    def _pair_rows(ts):
        out = {}
        for t in sorted(ts, key=lambda x: x.get("exit_ts", 0) or 0):
            out.setdefault(t["sym"], []).append(float(t.get("pnl_usd", 0.0) or 0.0))
        return out

    by_sym = {}
    for t in trades:
        by_sym.setdefault(t["sym"], {"n": 0, "pnl": 0.0, "wins": 0})
        by_sym[t["sym"]]["n"] += 1
        by_sym[t["sym"]]["pnl"] += t["pnl_usd"]
        if t["pnl_usd"] > 0:
            by_sym[t["sym"]]["wins"] += 1
    by_intel = {}
    for t in trades:
        il = t["extra"].get("intel")
        if il:
            by_intel.setdefault(il, {"n": 0, "pnl": 0.0})
            by_intel[il]["n"] += 1
            by_intel[il]["pnl"] += t["pnl_usd"]
    holds = [t["hold_h"] for t in trades if t["hold_h"] > 0]
    start = started_at(st)
    days_run = ((datetime.now(timezone.utc) - start).total_seconds() / 86400.0) if start else 0.0
    if n >= MIN_SIGNIFICANT:
        verdict = "SIGNIFICANT"
    elif n >= MIN_EMERGING:
        verdict = "EMERGING"
    else:
        verdict = "INSUFFICIENT"

    # ── KUALITAS SINYAL per ARAH (akar masalah: arah entry, bukan geometri exit) ──
    sq = signal_quality(trades)
    by_dir = {}
    for r in sq:
        by_dir.setdefault(r["dir"], []).append(r)
    dir_quality = {}
    for d, rows in by_dir.items():
        nn = len(rows)
        af = sum(r["max_fav"] for r in rows) / nn
        aa = sum(r["max_adv"] for r in rows) / nn
        v = sq_verdict(af, aa, nn)
        # V2 gross-edge per arah: pnl_pct desimal -> persen, bandingkan dgn biaya.
        ge = [abs(_f(r.get("pnl_pct"))) * 100.0 for r in rows if _f(r.get("pnl_pct"))]
        avg_ge = (sum(ge) / len(ge)) if ge else 0.0
        # Profitabilitas per arah (dari trade pnl, bukan signal_quality rows).
        dir_trades = [t for t in trades if str(t["side"]).upper().startswith("L") == (d == "LONG")]
        dir_pnl = sum(t["pnl_usd"] for t in dir_trades)
        ample = bool(avg_ge >= HIGH_EDGE_MIN_PCT)
        dir_quality[d] = {"n": nn, "avg_fav": round(af, 4), "avg_adv": round(aa, 4),
                          "verdict": v, "action": gate_action(v),
                          "avg_gross_edge_pct": round(avg_ge, 4),
                          "high_edge": bool(ample and dir_pnl > 0),
                          "net_after_cost_pct": round(avg_ge - COST_MODEL_PCT, 4),
                          "dir_pnl_usd": round(dir_pnl, 4)}

    # ── HIGH-GROSS-EDGE FILTER (V2, 2026-08-11) ──
    # pnl_pct disimpan DESIMAL (0.0059 = 0.59%) -> konversi ke persen utk banding biaya.
    # CATATAN jujur: avg_gross_edge = AMPLITUDO pergerakan rata-rata (|pnl_pct|), BUKAN
    # profitabilitas. Track beramplitudo besar tapi WR rendah & PnL negatif TIDAK layak.
    # Klasifikasi layak = amplitude >= ambang DAN profitabilitas nyata (PnL>0 & PF>=1).
    gross_edges = [abs(_f(t["pnl_pct"])) * 100.0 for t in trades if _f(t["pnl_pct"])]
    avg_gross_edge_pct = (sum(gross_edges) / len(gross_edges)) if gross_edges else 0.0
    net_after_cost_pct = round(avg_gross_edge_pct - COST_MODEL_PCT, 4)
    ample_amplitude = bool(avg_gross_edge_pct >= HIGH_EDGE_MIN_PCT)
    total_pnl = sum(t["pnl_usd"] for t in trades)
    profitable = bool(total_pnl > 0 and (pf is None or pf >= 1.0))
    high_edge = bool(ample_amplitude and profitable)

    return {
        "label": label, "n": n, "wins": len(wins), "losses": len(losses),
        "win_rate": (len(wins) / n) if n else 0.0,
        "gross_profit": round(gp, 4), "gross_loss": round(gl, 4),
        "profit_factor": round(pf, 3) if pf != float("inf") else None,
        "total_pnl_usd": round(sum(t["pnl_usd"] for t in trades), 4),
        "avg_pnl_usd": round(statistics.mean([t["pnl_usd"] for t in trades]), 4) if n else 0.0,
        "avg_hold_h": round(statistics.mean(holds), 2) if holds else 0.0,
        "exits": {k: {"n": v["n"], "pnl": round(v["pnl"], 4)} for k, v in exits.items()},
        "by_sym": {k: {"n": v["n"], "wins": v["wins"], "pnl": round(v["pnl"], 4)} for k, v in by_sym.items()},
        # trade-level pnl per pair (kronologis) untuk gate statistik BH-FDR (perbaikan #3)
        "by_pair_rows": _pair_rows(trades),
        "by_intel": {k: {"n": v["n"], "pnl": round(v["pnl"], 4)} for k, v in by_intel.items()},
        "days_run": round(days_run, 1), "verdict": verdict,
        "note": recommendation(verdict, n, days_run),
        "signal_quality": {"trades": len(sq), "by_direction": dir_quality},
        "gross_edge": {"avg_gross_edge_pct": round(avg_gross_edge_pct, 4),
                        "net_after_cost_pct": net_after_cost_pct,
                        "high_edge": high_edge,
                        "cost_model_pct": COST_MODEL_PCT,
                        "threshold_pct": HIGH_EDGE_MIN_PCT},
    }


def recommendation(verdict, n, days_run):
    if verdict == "SIGNIFICANT":
        return f"n={n} ≥ {MIN_SIGNIFICANT} — hasil pembelajaran SIGNIFIKAN, layak evaluasi Gate-2."
    if verdict == "EMERGING":
        return f"n={n} (5-19) — pembelajaran MUNCUL, lanjutkan hingga n≥{MIN_SIGNIFICANT}."
    if n == 0:
        return (f"n=0 selama {days_run:.0f} hari — BELUM ADA pembelajaran. "
                f"Strategi tidak fire di regime ini (LONG-only momentum/ADX-gated). "
                f"Tindakan: pastikan learning mode aktif; jika tetap 0 dalam 3-7 hari, "
                f"lebarkan strategi (SHORT + timeframe lain) per mandat dua-arah.")
    return f"n={n} (<{MIN_EMERGING}) — pembelajaran belum cukup; butuh lebih banyak trade."


def build_report(results, temporal=None, regime_info=None):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = []
    lines.append("# 📚 PAPER TEST — LAPORAN PEMBELAJARAN (WAJIB)\n")
    lines.append(f"> Di-generate: {now} · Mesin: `scripts/paper_test_learning.py` · "
                 f"Data-gate: n≥{MIN_SIGNIFICANT}=SIGNIFICANT | n≥{MIN_EMERGING}=EMERGING | n<{MIN_EMERGING}=INSUFFICIENT\n")
    lines.append("\n**Prinsip:** setiap paper test WAJIB menghasilkan pembelajaran signifikan. "
                 "Track dengan `INSUFFICIENT` = BELUM belajar → wajib ditindaklanjuti.\n")
    lines.append("\n## Ringkasan\n")
    lines.append("| Track | n | WR | PF | PnL USD | AvgHold(h) | Verdict |")
    lines.append("|-------|---|----|----|---------|-----------|---------|")
    for r in results:
        pf = f"{r['profit_factor']:.2f}" if r["profit_factor"] is not None else "∞"
        emoji = {"SIGNIFICANT": "🟢", "EMERGING": "🟡", "INSUFFICIENT": "🔴",
                 "NOT_RUNNING": "⚫"}.get(r["verdict"], "⚪")
        lines.append(f"| {r['label']} | {r['n']} | {r['win_rate']*100:.0f}% | {pf} | "
                     f"{r['total_pnl_usd']:+.2f} | {r['avg_hold_h']:.1f} | {emoji} {r['verdict']} |")
    lines.append("\n## Detail per Track\n")
    for r in results:
        lines.append(f"### {r['label']} — {r['verdict']}")
        lines.append(f"- Berjalan: {r['days_run']:.1f} hari · n={r['n']} · WR {r['win_rate']*100:.0f}% "
                     f"({r['wins']}W/{r['losses']}L) · PF {r['profit_factor'] if r['profit_factor'] is not None else '∞'} "
                     f"· PnL ${r['total_pnl_usd']:+.2f} · avg ${r['avg_pnl_usd']:+.3f}/trade · avg hold {r['avg_hold_h']}h")
        if r["exits"]:
            exits = ", ".join(f"{k}:{v['n']}t(${v['pnl']:+.2f})" for k, v in sorted(r["exits"].items()))
            lines.append(f"- Exit: {exits}")
        if r["by_sym"]:
            syms = ", ".join(f"{k}:{v['n']}t(${v['pnl']:+.2f})" for k, v in sorted(r["by_sym"].items()))
            lines.append(f"- Per-symbol: {syms}")
        if r["by_intel"]:
            intels = ", ".join(f"{k}:{v['n']}t(${v['pnl']:+.2f})" for k, v in sorted(r["by_intel"].items()))
            lines.append(f"- Per-intel: {intels}")
        sq = r.get("signal_quality", {})
        if sq and sq.get("by_direction"):
            parts = []
            for d, q in sorted(sq["by_direction"].items()):
                emoji = {"HAS_EDGE": "🟢", "MARGINAL": "🟡", "ANTI_PREDICTIVE": "🔴", "INSUFFICIENT": "⚪"}[q["verdict"]]
                ge = q.get("avg_gross_edge_pct", 0.0)
                net = q.get("net_after_cost_pct", 0.0)
                he = q.get("high_edge", False)
                ge_emoji = "🟢" if he else ("🟡" if net > 0 else "🔴")
                parts.append(f"{d}: {emoji}{q['verdict']} (FAV {q['avg_fav']*100:+.2f}% / ADV {q['avg_adv']*100:+.2f}% "
                             f"n={q['n']} · grossEdge {ge:+.2f}% → net {net:+.2f}% {ge_emoji}) → {q['action']}")
            lines.append(f"- **Kualitas sinyal (arah):** " + " · ".join(parts))
        ge = r.get("gross_edge", {})
        if ge:
            ge_emoji = "🟢" if ge.get("high_edge") else ("🟡" if (ge.get("net_after_cost_pct") or 0) > 0 else "🔴")
            lines.append(f"- **High-Gross-Edge (V2):** avg gross {ge.get('avg_gross_edge_pct',0):+.2f}% → "
                         f"net (cost {ge.get('cost_model_pct',0):.2f}%) {ge.get('net_after_cost_pct',0):+.2f}% "
                         f"· ambang {ge.get('threshold_pct',0):.1f}% → {'LAYAK KEJAR' if ge.get('high_edge') else 'TIDAK layak (biaya > edge)'} {ge_emoji}")
        lines.append(f"- 📌 **{r['note']}**\n")

    # ── REGIME / STANDBY ──
    if regime_info:
        emoji = {"STABLE": "🟢", "FLAPPING": "🔴", "INSUFFICIENT": "⚪"}[regime_info.get("regime", "INSUFFICIENT")]
        lines.append(f"\n## 🧭 Regime: {emoji} {regime_info.get('regime')}"
                     f" · STANDBY={'ON' if regime_info.get('standby') else 'OFF'}"
                     f" · recent-n LONG={regime_info.get('recent_n',{}).get('LONG',0)} "
                     f"SHORT={regime_info.get('recent_n',{}).get('SHORT',0)} ({regime_info.get('recent_h')}h)\n")
        if regime_info.get("standby"):
            lines.append("> 🔴 **STANDBY ON** (advisory utk PAPER) — regime berbalik cepat (FLAPPING): "
                         "tak ada arah yang bisa dipercaya untuk keputusan LIVE. Untuk paper test, "
                         "STANDBY TIDAK memblokir entry — hanya arah berstatus **PAUSE** (anti-predictive, "
                         "n≥8) yang diblokir, agar data pembelajaran tetap terkumpul di regime berbalik "
                         "(bukti sebelum keputusan).\n")

    # ── UJI STABILITAS TEMPORAL ──
    if temporal:
        lines.append("\n## 🕐 Uji Stabilitas Temporal (FAV/ADV per window — anti confound)\n")
        lines.append("> Pertanyaan: apakah 'arah A buruk' stabil atau artefak satu regime? "
                     "Perhatian: arah & waktu bisa saling membingungkan (SHORT di window awal, "
                     "LONG di window akhir). Verdict: CONSISTENT / REGIME_DEPENDENT / INSUFFICIENT.\n")
        for d, info in sorted(temporal.items()):
            lines.append(f"### {d} — {info['verdict']} (n={info['n']})")
            if info.get("windows"):
                lines.append("| W | rentang | n | WR | FAV | ADV | FAV>ADV? |")
                lines.append("|---|---------|----|----|-----|-----|---------|")
                for w in info["windows"]:
                    ok = "✅" if w["fav_gt_adv"] else "❌"
                    lines.append(f"| W{w['w']} | {w['range']} | {w['n']} | {w['wr']*100:.0f}% | "
                                 f"{w['avg_fav']*100:+.2f}% | {w['avg_adv']*100:+.2f}% | {ok} |")
                if info["verdict"] == "REGIME_DEPENDENT":
                    lines.append("→ ⚠️ Tanda berbalik antar window = **regime-dependent**, BUKAN edge stabil.")
                elif info["verdict"] == "CONSISTENT":
                    lines.append("→ Tanda konsisten lintas window (n≥6) — kandidat edge, tetap pantau.")
                else:
                    lines.append("→ Belum cukup data (butuh n≥6 & window berisi) untuk menyimpulkan.")
            lines.append("")

    lines.append("---\n*Laporan rolling — setiap regenerasi menimpa. Arsip: git history.*\n")
    return "\n".join(lines)


def run():
    results = []
    for label, fname, stype in TRACKS:
        path = DATA / fname
        st = {}
        if path.exists():
            try:
                st = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                # FIX RCA 2026-10-31: 1 file state korup/kosong (race baca-vs-tulis
                # sesaat, bukan writer non-atomic - swing_deep_learner & realwide
                # sudah tmp+replace) dulu MENJATUHKAN SELURUH laporan 11 track
                # (146 traceback historis -> laporan wajib tidak pernah terbit).
                # Degrade graceful per-track, konsisten pola _safe_json yang
                # sudah ada di swing_deep_learner.py; terlihat di stderr, bukan
                # ditelan diam-diam.
                print(f"WARN run(): {fname} gagal parse ({e}) - track '{label}' "
                      f"dilewati sbg data kosong, bukan crash laporan", file=sys.stderr)
        r = analyze(label, stype, st)
        if not path.exists():
            # Lane tanpa state file = tidak pernah/tidak lagi berjalan. Jangan
            # campur dengan "INSUFFICIENT" (berjalan tapi n kecil) — beda makna.
            r["verdict"] = "NOT_RUNNING"
            r["note"] = f"State file {fname} tidak ada — lane tidak berjalan, bukan bukti edge negatif."
        results.append(r)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="tulis data/paper_test_learning.json saja")
    ap.add_argument("--status", action="store_true", help="ringkas ke stdout")
    a = ap.parse_args()
    results = run()
    if a.status:
        for r in results:
            ge = r.get("gross_edge", {})
            ge_txt = ""
            if ge:
                he = "🟢KEJAR" if ge.get("high_edge") else ("🟡NET+" if (ge.get("net_after_cost_pct") or 0) > 0 else "🔴BIAYA>")
                ge_txt = f" gross={ge.get('avg_gross_edge_pct',0):+.1f}% net={ge.get('net_after_cost_pct',0):+.1f}% {he}"
            print(f"{r['label']:<14} n={r['n']:<3} WR={r['win_rate']*100:3.0f}% "
                  f"PF={r['profit_factor'] if r['profit_factor'] is not None else '∞':<5} "
                  f"PnL=${r['total_pnl_usd']:+8.2f} {r['verdict']}{ge_txt}")
        return
    temporal, aggregate, regime_info = edge_temporal_report()
    _cache_5m_save()  # persist 5m-path cache setelah semua track diproses
    REPORT_JSON.write_text(json.dumps({"generated": datetime.now(timezone.utc).isoformat(),
                                       "gate": {"significant": MIN_SIGNIFICANT, "emerging": MIN_EMERGING},
                                       "tracks": results, "temporal": temporal,
                                       "aggregate": aggregate, "regime": regime_info}, indent=2))
    # EDGE-GATE — keputusan per arah (per-track + AGREGAT lintas track).
    # Track dua-arah membaca _AGGREGATE juga: arah yg PAUSE di agregat → skip di semua track.
    # ── PER-PAIR PRUNE (2026-08-29, Deep-Loop toward EXCEEDING North Star ≥0.7%) ──
    # A wide universe (19-20 pairs) lifts throughput but a few structurally-losing
    # pairs drag the aggregate avg below target. Auto-PAUSE a pair only when the
    # evidence is unambiguous: n>=GATE_MIN_N (8) AND net-negative PnL AND WR<40%.
    # Conservative on purpose — never kills a pair on a couple of unlucky losses;
    # fires only on proven structural drags. Tracks skip PAUSED pairs on entry.
    def _pairs_pause(r):
        """Pause pair proven drag (uji statistik BH-FDR, rolling window).

        Rule (2026-09-25): bootstrap one-sided H0 mean(pnl_usd) >= 0, alpha=0.05
        dengan BH-FDR atas seluruh pair yang diuji; min_n=5 per pair; window =
        30 trade terakhir per pair (drag sembuh otomatis lepas). Guard: maksimum
        PAIR_GATE_MAX_PAUSE_FRACTION universe. Legacy/forced list tetap dihormati.
        """
        label = r.get("label")
        out = set(FORCED_PAIRS_PAUSE.get(label, set())) | set(LEGACY_PAIRS_PAUSE.get(label, set()))
        rows = r.get("by_pair_rows") or {}
        if not rows:
            # Tidak ada data trade-level (mis. run parsial) → jangan pause baru,
            # hanya list forced/legacy (fail-closed terhadap aksi tanpa bukti).
            return sorted(out)

        def _boot_p(vals):
            n = len(vals)
            if n < PAIR_GATE_MIN_N:
                return None
            if sum(vals) / n >= 0:
                return 1.0
            hits = 0
            for _ in range(PAIR_GATE_BOOTSTRAP_ITERS):
                s = 0.0
                for _ in range(n):
                    s += vals[random.randrange(n)]
                if s / n >= 0:
                    hits += 1
            return hits / PAIR_GATE_BOOTSTRAP_ITERS

        cand = []
        for sym, vals in rows.items():
            v = list(vals)[-PAIR_GATE_WINDOW:]
            p = _boot_p(v)
            if p is not None:
                cand.append((sym, p, len(v)))
        cand.sort(key=lambda x: x[1])
        m = max(1, len(cand))
        for i, (sym, p, _n) in enumerate(cand):
            if p <= PAIR_GATE_ALPHA * (i + 1) / m:
                out.add(sym)
        cap = max(1, int(len(rows) * PAIR_GATE_MAX_PAUSE_FRACTION))
        if len(out) > cap:
            out = set(sorted(out)[:cap])
        return sorted(out)
    gate = {"generated": datetime.now(timezone.utc).isoformat(),
            "rule": {"n_min": GATE_MIN_N, "anti_pred_fraction": ANTI_PRED_FRAC,
                     "has_edge_fraction": HAS_EDGE_FRAC,
                     "action": "PAUSE = skip arah anti-predictive (avg_fav<40%avg_adv, n>=8; agregat pool lintas track)",
                     "pair_pause": ("skip pair proven-drag (uji statistik 2026-09-25): "
                                    f"bootstrap one-sided mean(pnl_usd)<0 p<={PAIR_GATE_ALPHA} "
                                    f"BH-FDR, min_n={PAIR_GATE_MIN_N}, window={PAIR_GATE_WINDOW} "
                                    f"trade terakhir; cap {PAIR_GATE_MAX_PAUSE_FRACTION:.0%} universe")},
            "gate": {r["label"]: {d: q["action"]
                                  for d, q in r.get("signal_quality", {}).get("by_direction", {}).items()}
                     for r in results},
            "pairs_pause": {r["label"]: _pairs_pause(r) for r in results},
            "_AGGREGATE": {d: a["action"] for d, a in aggregate.items()},
            "_REGIME": regime_info["regime"],
            "_STANDBY": regime_info["standby"]}
    GATE_JSON.write_text(json.dumps(gate, indent=2))
    if not a.json:
        REPORT_MD.write_text(build_report(results, temporal, regime_info))
        print(f"✅ Laporan pembelajaran: {REPORT_MD}")
    print(f"✅ Data pembelajaran: {REPORT_JSON}")
    print(f"✅ Edge-gate: {GATE_JSON}")


if __name__ == "__main__":
    main()
