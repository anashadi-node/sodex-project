#!/usr/bin/env python3
"""EVALUATOR PRAREG-32 — maker-donchian Binance USDM, forward 2026-10-27 → 2026-11-26.

Protokol BEKU: reports/sodex/PRAREG32_MAKER_PROTOCOL.json
  sha256 3d44c04df2ffd17ee26bd50237add1465703bddc44e3b79508d5539eec99dc24
Amandemen: docs/sodex/VENUE_BHL_AUDIT_2_KOREKSI.md (A dinilai EQUAL-WEIGHT,
leave-one-out wajib, AS gate 13,4 bps, t>=2,5, kill-switch DD 5% wallet).
AMANDEMEN_2 (25-Okt-2026, sebelum forward pertama, ambang TIDAK diubah): protokol
  menulis AS = fill_price - signal_price_at_touch, tetapi harga mid saat sentuh tidak
  terukur dari OHLC 1h. Implementasi: laporkan DUA definisi AS (vs close bar sinyal =
  literal; vs close bar yang menyentuh = adverse nyata) dan gerbang D lulus hanya bila
  KEDUANYA <= 13,4 bps (lebih ketat, tidak melonggarkan). AS juga dilaporkan per simbol.

Aturan yang diimplementasikan (verbatim protokol):
  Sinyal  : Donchian-20 breakout + volok (v > SMA24) + BULL (ADX>22, c>SMA50>SMA200)
            — parameter PRODUKSI, tanpa tuning. LONG-only (sesuai definisi produksi).
  Geometri: TP 4% / SL 2% / time-stop 30 jam. SL dicek lebih dulu dalam bar yang sama.
  Eksekusi: MAKER pasif. Aturan fill BEKU WIBAWA PRAREG-5 §3:
            limit = close_sinyal * (1 - 1/2spread) ; terisi bila low bar berikutnya <= limit.
            Tidak tersentuh -> trade DILEWATI (tidak dianggap terisi di close).
  Ukuran  : size 0,75 wallet/posisi, maks 5 posisi konkuren.
  Agregasi: 1 window = grid 30 jam, jangkar 2026-08-03Z, bucket exit_ts.
            pct_EW(window) = rata-rata TAK BERBOBOT atas 20 simbol pool
            (simbol tanpa trade = 0,0%). Cap-weighted DILARANG (AUDIT-2).
  Biaya   : Binance USDM — maker 0,25 bps/leg, taker 6,125 bps/leg
            (konteks_angka protokol: maker RT 0,5 bps, taker RT 12,25 bps);
            funding 0,13 bps/8 jam tahan. Entry selalu maker; exit TP/TIME maker,
            exit SL taker (SL = stop market, wajib agresif).
  Konvensi window (AMANDEMEN_TARGET_AB_2026-10-10): window KOSONG dilewati (n_empty).
  Fail-closed: window usable < 24 ATAU trade < 60 -> verdict GAGAL_DATA (bukan lolos).

Tidak menyentuh dry_run, order, atau kode produksi mana pun. READ-ONLY.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import statistics as st
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KD = os.path.join(ROOT, "data/binance_klines/1h")
STATUS_PATH = os.path.join(ROOT, "reports/sodex/PRAREG32_STATUS.json")
POOL_PATH = os.path.join(ROOT, "reports/sodex/PRAREG32_POOL.json")
PROTOCOL_PATH = os.path.join(ROOT, "reports/sodex/PRAREG32_MAKER_PROTOCOL.json")

ANCHOR = datetime(2026, 8, 3, tzinfo=timezone.utc).timestamp()
WINDOW_H = 30
FREEZE = datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp()
FWD_START = datetime(2026, 10, 27, tzinfo=timezone.utc).timestamp()
FWD_END = datetime(2026, 11, 26, tzinfo=timezone.utc).timestamp()

MIN_WINDOWS = 24
MIN_TRADES = 60
T_MIN = 2.5
TARGET_PCT = 0.8
FAIL_MEAN_PCT = 0.4
FAIL_HIT_PCT = 40.0
FILL_OK = 0.60
FILL_FAIL = 0.40
AS_GATE_BPS = 13.4
DD_KILL_FRAC = 0.05

TP_PCT, SL_PCT, TIME_H = 0.04, 0.02, 30
SIZE_FRAC = 0.75
MAX_CONCURRENT = 5
MIN_WARM = 210

FEE_MAKER_LEG_BPS = 0.25
FEE_TAKER_LEG_BPS = 6.125
FUNDING_8H_BPS = 0.13
VERDICT_DATE = "2026-11-27"
GIVEUP_DATE = "2026-12-02"

POOL_MIN_BARS_30D = 600            # data segar: >=600 bar 1h dalam 30d sebelum freeze


def _vr():
    spec = importlib.util.spec_from_file_location(
        "vr", os.path.join(ROOT, "scripts/research/venue_replay_bhl.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


VR = _vr()


def spread_bps(sym_base: str) -> float:
    """Spread proxy Binance (dipakai juga oleh ARITHMETIC/AUDIT-2)."""
    return float(VR.SPREAD_OVR.get(sym_base, VR.VENUE["binance"]["spread_default"]))


def gate_D(fill_rate: float, as_touch_med: float | None, as_signal_med: float | None) -> bool:
    """D = fill-rate >= 60% DAN AS median <= 13,4 bps. Dua definisi AS diwajibkan lulus
    keduanya (stricter, tidak melonggarkan ambang): protokol menulis AS = fill_price -
    signal_price_at_touch; dengan OHLC 1h harga mid saat sentuh tidak terukur, sehingga
    dipakai (a) selisih thd close bar sinyal (literal) dan (b) selisih thd close bar yang
    menyentuh (=adverse nyata bila positif). Keduanya dilaporkan; ambang tidak diubah."""
    if fill_rate < FILL_OK:
        return False
    for v in (as_touch_med, as_signal_med):
        if v is None or float(v) > AS_GATE_BPS:
            return False
    return True


def dry_run_flag():
    """Protokol §design: paper_mode WAJIB (dry_run=true). Dicatat di status, read-only."""
    for rel in ("config.json", "freqtrade_user_data/config.json", "user_data/config.json"):
        fp = os.path.join(ROOT, rel)
        if os.path.exists(fp):
            try:
                return {"file": rel, "dry_run": bool(json.load(open(fp)).get("dry_run"))}
            except Exception as e:
                return {"file": rel, "error": str(e)[:80]}
    return None


def sha256_file(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def wallet_usd() -> float:
    p = os.path.join(ROOT, "reports/sodex/PRAREG26_MESIN_SELEKSI_STATUS.json")
    if os.path.exists(p):
        try:
            return float(json.load(open(p)).get("wallet_usd") or 243.02)
        except Exception:
            pass
    return 243.02


class PoolError(RuntimeError):
    pass


def load_or_freeze_pool(now_ts: float | None = None) -> list[str]:
    """Pool tetap: simbol Binance USDM spread<=2 bps, volume kuotasi 30d teratas,
    hanya yang datanya segar (>=600 bar 1h dalam 30d sebelum freeze). Dibekukan sekali,
    lalu IMMUTABLE: sha256 dicatat; perubahan isi = error (fail-closed)."""
    if os.path.exists(POOL_PATH):
        rec = json.load(open(POOL_PATH))
        syms = list(rec.get("symbols") or [])
        if not syms:
            raise PoolError("pool file tanpa symbols")
        body = json.dumps(syms)
        if rec.get("sha256_symbols") and hashlib.sha256(body.encode()).hexdigest() != rec["sha256_symbols"]:
            raise PoolError("pool file diubah setelah freeze -> evaluasi dihentikan")
        return syms

    lo, hi = FREEZE - 30 * 86400, FREEZE
    ranked = []
    for f in sorted(os.listdir(KD)):
        if not f.endswith("USDT.json"):
            continue
        base = f[:-len("USDT.json")]
        spr = spread_bps(base)
        if spr > 2.0:
            continue
        rows = VR.load_klines(os.path.join(KD, f))
        if not rows:
            continue
        nb, qv = 0, 0.0
        for r in rows:
            t = r[0]
            if lo <= t <= hi:
                nb += 1
                qv += float(r[4]) * float(r[5])
        if nb >= POOL_MIN_BARS_30D:
            ranked.append((base, qv, nb))
    ranked.sort(key=lambda x: (-x[1], x[0]))
    syms = [b for b, _, _ in ranked[:20]]
    rec = {"prereg": "PRAREG-32", "frozen_utc": (now_ts or FREEZE),
           "aturan": ("spread proxy <= 2 bps; volume kuotasi 30d (bar <= freeze) teratas; "
                      ">=600 bar 1h dalam 30d (segar)"),
           "freeze_ts_utc": datetime.fromtimestamp(FREEZE, tz=timezone.utc).isoformat(),
           "symbols": syms,
           "sha256_symbols": hashlib.sha256(json.dumps(syms).encode()).hexdigest(),
           "peringkat_qv30_usd": {b: round(q, 1) for b, q, _ in ranked[:20]}}
    json.dump(rec, open(POOL_PATH, "w"), indent=1)
    return syms


def signals_donchian(d: dict) -> list[int]:
    """Indeks bar sinyal Donchian-20 + volok + BULL (definisi produksi, verbatim)."""
    c, h, l, o, v, t = d["c"], d["h"], d["l"], d["o"], d["v"], d["t"]
    n = len(c)
    s50, s200 = VR.sma(c, 50), VR.sma(c, 200)
    a = VR.adx(h, l, c)
    va = VR.sma(v, 24)
    out = []
    for i in range(MIN_WARM, n - 1):
        if c[i] > h[i - 20:i].max() and v[i] > (va[i] if not math.isnan(va[i]) else v[i]) \
                and a[i] > 22 and c[i] > s50[i] and s50[i] > s200[i]:
            out.append(i)
    return out


def walk_exit(d: dict, i0: int, entry_px: float, entry_ts: float,
              long: bool = True) -> tuple[float | None, float | None, str]:
    """Geometri produksi: SL dicek lebih dulu dalam bar; TIME 30 jam."""
    c, h, l, t = d["c"], d["h"], d["l"], d["t"]
    n = len(c)
    sgn = 1.0 if long else -1.0
    tp_p = entry_px * (1 + sgn * TP_PCT)
    sl_p = entry_px * (1 - sgn * SL_PCT)
    j_end = min(i0 + int(math.ceil(TIME_H)), n)
    for j in range(i0, j_end):
        if sgn > 0:
            if l[j] <= sl_p:
                return sl_p, t[j], "SL"
            if h[j] >= tp_p:
                return tp_p, t[j], "TP"
        else:
            if h[j] >= sl_p:
                return sl_p, t[j], "SL"
            if l[j] <= tp_p:
                return tp_p, t[j], "TP"
    k = min(j_end - 1, n - 1)
    return c[k], t[k], "TIME"


def build_signals(syms: list[str]) -> tuple[dict, list[dict], dict]:
    """Kumpulkan sinyal SEMUA simbol lalu urutkan kronologis (mutlak perlu untuk
    batas 5 posisi konkuren). Tiap sinyal membawa data yang dibutuhkan."""
    data, sigs, meta = {}, [], {}
    for s in syms:
        p = os.path.join(KD, f"{s}USDT.json")
        rows = VR.load_klines(p)
        if len(rows) < MIN_WARM + 2:
            meta[s] = {"error": "data_less_than_warmup", "n_bar": len(rows)}
            continue
        d = VR.arrays(rows)
        data[s] = d
        meta[s] = {"n_bar": len(rows),
                   "last_bar_utc": datetime.fromtimestamp(d["t"][-1], tz=timezone.utc).isoformat()}
        for i in signals_donchian(d):
            sigs.append({"sym": s, "i": i, "ts": d["t"][i]})
    sigs.sort(key=lambda x: (x["ts"], x["sym"]))
    return data, sigs, meta


def evaluate(verbose: bool = True) -> dict:
    syms = load_or_freeze_pool()
    wallet = wallet_usd()
    data, sigs, meta = build_signals(syms)

    trades, unfilled, incomplete = [], [], 0
    busy_until: dict[str, float] = {}
    open_pos: list[tuple[float, str]] = []          # (exit_ts, sym) untuk batas konkuren

    for sg in sigs:
        s, i = sg["sym"], sg["i"]
        d = data[s]
        ts_sig = d["t"][i]
        if ts_sig < FREEZE:                          # AUDIT-2: filter bar > freeze_ts
            continue
        if ts_sig < busy_until.get(s, 0.0):
            continue
        open_pos = [p for p in open_pos if p[0] > ts_sig]
        if len(open_pos) >= MAX_CONCURRENT:
            continue
        n = len(d["c"])
        hs = spread_bps(s) / 2.0 / 1e4
        p_sig = float(d["c"][i])
        lim = p_sig * (1.0 - hs)
        last_touch = i + int(math.ceil(TIME_H))
        if last_touch > n - 1:
            incomplete += 1
            continue
        fill_j = None
        for j in range(i + 1, last_touch + 1):
            if d["l"][j] <= lim:
                fill_j = j
                break
        # counterfactual taker (untuk diagnostik adverse selection, PRAREG-5 §6.2)
        cf_entry = float(d["o"][i + 1])
        cf_px, cf_ts, cf_why = walk_exit(d, i + 1, cf_entry, d["t"][i + 1])
        cf_gross = None
        if cf_px is not None:
            cf_gross = (cf_px / cf_entry - 1) * 1e4

        if fill_j is None:
            unfilled.append({"sym": s, "ts_sig_utc": datetime.fromtimestamp(ts_sig, tz=timezone.utc).isoformat(),
                             "cf_gross_bps": None if cf_gross is None else round(cf_gross, 2)})
            busy_until[s] = ts_sig + TIME_H * 3600     # tetap "sibuk": order pasif menggantung
            continue

        entry_ts = d["t"][fill_j]
        exit_px, exit_ts, why = walk_exit(d, fill_j, lim, entry_ts)
        hold_h = max(0.0, (exit_ts - entry_ts) / 3600.0)
        exit_fee = FEE_TAKER_LEG_BPS if why == "SL" else FEE_MAKER_LEG_BPS
        funding = FUNDING_8H_BPS * hold_h / 8.0
        gross = (exit_px / lim - 1) * 1e4
        net = gross - FEE_MAKER_LEG_BPS - exit_fee - funding
        usd = SIZE_FRAC * wallet * net / 1e4
        c_fill = float(d["c"][fill_j])
        # protokol §design: adverse selection = (fill_price - signal_price_at_touch)
        as_protocol = (lim - p_sig) / p_sig * 1e4           # vs harga sinyal (close bar sinyal)
        # adverse sebenarnya: bar yang menyentuh limit TUTUP di bawah fill (=0 bila tidak terus turun)
        as_touch = (lim - c_fill) / c_fill * 1e4            # >0 = adverse, <=0 = tidak adverse
        trades.append({"sym": s, "i": i, "ts_sig_utc": datetime.fromtimestamp(ts_sig, tz=timezone.utc).isoformat(),
                       "entry_utc": datetime.fromtimestamp(entry_ts, tz=timezone.utc).isoformat(),
                       "exit_utc": datetime.fromtimestamp(exit_ts, tz=timezone.utc).isoformat(),
                       "entry_ts": entry_ts, "exit_ts": exit_ts, "why": why, "hold_h": round(hold_h, 2),
                       "p_sig": p_sig, "limit": lim, "close_bar_fill": c_fill,
                       "as_protocol_bps": round(as_protocol, 4),
                       "as_touch_close_bps": round(as_touch, 4),
                       "gross_bps": round(gross, 2), "net_bps": round(net, 2), "usd": round(usd, 4),
                       "cf_gross_bps": None if cf_gross is None else round(cf_gross, 2)})
        busy_until[s] = exit_ts
        open_pos.append((exit_ts, s))

    trades.sort(key=lambda r: r["exit_ts"])
    n_req = len(trades) + len(unfilled)
    fill_rate = (len(trades) / n_req) if n_req else 0.0

    # ── window grid 30 jam, jangkar 03-Agu-2026Z, bucket exit_ts ──
    rows = []
    if trades:
        k0 = int((min(r["exit_ts"] for r in trades) - ANCHOR) // (WINDOW_H * 3600))
        k1 = int((min(FWD_END, max(r["exit_ts"] for r in trades)) - ANCHOR) // (WINDOW_H * 3600))
        for k in range(k0, k1 + 1):
            t0, t1 = ANCHOR + k * WINDOW_H * 3600, ANCHOR + (k + 1) * WINDOW_H * 3600
            if not (t0 >= FWD_START and t1 <= FWD_END):
                continue
            sel = [r for r in trades if t0 <= r["exit_ts"] < t1]
            per_sym = {}
            for s in syms:
                usd_s = sum(r["usd"] for r in sel if r["sym"] == s)
                per_sym[s] = round(usd_s / wallet * 100, 4)      # simbol tanpa trade = 0,0%
            ew = st.mean(per_sym.values()) if per_sym else 0.0
            rows.append({"k": k, "start_utc": datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(),
                         "end_utc": datetime.fromtimestamp(t1, tz=timezone.utc).isoformat(),
                         "n_trade": len(sel), "pct_EW": round(ew, 4),
                         "pct_capweighted_terlarang": round(sum(r["usd"] for r in sel) / wallet * 100, 4),
                         "per_simbol": per_sym})

    n_empty = sum(1 for r in rows if r["n_trade"] == 0)
    usable = [r for r in rows if r["n_trade"] > 0]
    ew = [r["pct_EW"] for r in usable]
    nets = [r["net_bps"] for r in trades]
    t_stat = None
    if len(nets) >= 3 and st.pstdev(nets) > 0:
        t_stat = st.mean(nets) / (st.pstdev(nets) / math.sqrt(len(nets)))
    as_med = st.median([r["as_protocol_bps"] for r in trades]) if trades else None
    as_touch_med = st.median([r["as_touch_close_bps"] for r in trades]) if trades else None

    # AS dilaporkan PER SIMBOL (protokol §design)
    as_per_simbol = {}
    for s in syms:
        v = [r["as_protocol_bps"] for r in trades if r["sym"] == s]
        w = [r["as_touch_close_bps"] for r in trades if r["sym"] == s]
        as_per_simbol[s] = {"n": len(v),
                            "median_fill_minus_signal_bps": round(float(st.median(v)), 4) if v else None,
                            "median_touch_bps": round(float(st.median(w)), 4) if w else None}

    # leave-one-out simbol terbesar (AUDIT-2 wajib)
    loo = None
    if usable:
        contrib = {}
        for s in syms:
            contrib[s] = sum(r["pct_EW"] * 0 + r["per_simbol"][s] for r in usable) / len(usable)
        biggest = max(contrib, key=lambda s: abs(contrib[s]))
        red = []
        for r in usable:
            others = [v for s, v in r["per_simbol"].items() if s != biggest]
            red.append(st.mean(others) if others else 0.0)
        loo = {"symbol": biggest, "mean_pct_tanpa": round(float(st.mean(red)), 4) if red else None}

    # kill-switch DD kumulatif > 5% wallet
    run, worst = 0.0, 0.0
    for r in trades:
        run += r["usd"]
        worst = min(worst, run)
    dd_frac = -worst / wallet

    # adverse selection diagnostik (PRAREG-5 §6.2 / diag_maker_vs_taker.py): terisi vs tidak
    f_g = [r["gross_bps"] for r in trades]
    u_g = [r["cf_gross_bps"] for r in unfilled if r["cf_gross_bps"] is not None]
    as_diag = float(st.mean(f_g) - st.mean(u_g)) if (f_g and u_g) else None

    # ── verdict (fail-closed) ──
    alasan: list[str] = []
    hit_pct = (sum(1 for x in ew if x > 0) / len(ew) * 100) if ew else 0.0
    if len(usable) < MIN_WINDOWS or len(trades) < MIN_TRADES:
        status = "GAGAL_DATA"
        alasan.append(f"data kurang: window usable {len(usable)}/{MIN_WINDOWS}, trade {len(trades)}/{MIN_TRADES}")
    elif dd_frac > DD_KILL_FRAC:
        status = "GAGAL (kill-switch DD)"
        alasan.append(f"DD kumulatif {dd_frac*100:.2f}% wallet > {DD_KILL_FRAC*100:.0f}% (kill-switch)")
    else:
        A = st.mean(ew) >= TARGET_PCT
        B = st.median(ew) > 0 and hit_pct >= 50
        C = (t_stat or -9) >= T_MIN
        D = gate_D(fill_rate, as_touch_med, as_med)
        if st.mean(ew) < FAIL_MEAN_PCT:
            alasan.append(f"mean EW {st.mean(ew):.3f}% < {FAIL_MEAN_PCT}%")
        if hit_pct < FAIL_HIT_PCT:
            alasan.append(f"hit {hit_pct:.1f}% < {FAIL_HIT_PCT:.0f}%")
        if fill_rate < FILL_FAIL:
            alasan.append(f"fill-rate {fill_rate*100:.1f}% < {FILL_FAIL*100:.0f}%")
        if not A:
            alasan.append(f"A: mean EW {st.mean(ew):.3f}% < {TARGET_PCT}%")
        if not B:
            alasan.append(f"B: median {st.median(ew):.3f}% / hit {hit_pct:.1f}%")
        if not C:
            alasan.append(f"C: t={t_stat if t_stat is None else round(t_stat, 3)} < {T_MIN}")
        if not D:
            alasan.append(f"D: fill {fill_rate*100:.1f}% / AS_touch {as_touch_med} / AS_fill-signal {as_med} bps > {AS_GATE_BPS}")
        gagal = (st.mean(ew) < FAIL_MEAN_PCT) or (hit_pct < FAIL_HIT_PCT) or (fill_rate < FILL_FAIL)
        status = "LOLOS" if (A and B and C and D) else ("GAGAL (kriteria gagal)" if gagal else "TIDAK LOLOS")

    # FIX (2026-11-06): window_berikutnya dulu = start window PERTAMA (konstan dari
    # FWD_START), jadi selalu tampak "macet 27 Okt" walau evaluasi sudah maju ke Nov.
    # Sekarang = start window setelah k maksimum yang sudah dievaluasi.
    if rows:
        knext = max(r["k"] for r in rows) + 1
    else:
        knext = int(math.ceil((FWD_START - ANCHOR) / (WINDOW_H * 3600)))
    wb = None if (trades and max(r["exit_ts"] for r in trades) >= FWD_END - WINDOW_H * 3600) else \
        datetime.fromtimestamp(ANCHOR + knext * WINDOW_H * 3600, tz=timezone.utc).isoformat()
    last_bars = [m["last_bar_utc"] for m in meta.values() if isinstance(m, dict) and m.get("last_bar_utc")]

    out = {"generated_utc": datetime.now(timezone.utc).isoformat(), "prereg": "PRAREG-32",
           "wallet_usd": wallet, "status": status, "alasan_verdict": alasan,
           "status_padanan_prereg31": "DATA KURANG" if status == "GAGAL_DATA" else status,
           "protokol_sha256": sha256_file(PROTOCOL_PATH),
           "dry_run_produksi": dry_run_flag(),
           "jendela": {"forward_start": "2026-10-27T00:00:00Z", "forward_end": "2026-11-26T00:00:00Z",
                       "min_windows": MIN_WINDOWS, "ambang_t": T_MIN, "n_min_trade": MIN_TRADES,
                       "verdict_date": VERDICT_DATE, "giveup_date": GIVEUP_DATE,
                       "as_gate_bps": AS_GATE_BPS},
           "pool": {"n": len(syms), "symbols": syms, "sumber": os.path.basename(POOL_PATH)},
           "fill": {"n_req": n_req, "n_fill": len(trades), "n_unfilled": len(unfilled),
                    "fill_rate": round(fill_rate, 4), "n_incomplete_dilewati": incomplete},
           "adverse_selection_bps": {
               "median_fill_minus_signal": None if as_med is None else round(float(as_med), 4),
               "median_touch_close": None if as_touch_med is None else round(float(as_touch_med), 4),
               "diag_terisi_minus_tidak_terisi": None if as_diag is None else round(as_diag, 2),
               "catatan": ("limit maker selalu di bawah harga sinyal (LONG), sehingga "
                           "fill_price - signal_price selalu negatif (= konsesi 1/2 spread, "
                           "bukan adverse). AS adverse sesungguhnya = bar yang memenuhi limit "
                           "TUTUP di bawah fill (median_touch_close > 0). Keduanya dibandingkan "
                           "ke ambang 13,4 bps; D lulus hanya bila keduanya <= ambang."),
               "per_simbol": as_per_simbol},
           "A_mean_pct_EW": round(st.mean(ew), 4) if ew else None,
           "B_median_pct": round(st.median(ew), 4) if ew else None,
           "B_hit_pct": round(hit_pct, 1) if ew else None,
           "C_t_net": None if t_stat is None else round(t_stat, 3),
           "C_net_mean_bps": round(st.mean(nets), 2) if nets else None,
           "D_fill_rate": round(fill_rate, 4),
           "D_as_median_bps": None if as_touch_med is None else round(float(as_touch_med), 4),
           "leave_one_out": loo, "dd_kumulatif_frac": round(dd_frac, 4),
           "n_window_total": len(rows), "n_usable": len(usable), "n_empty": n_empty,
           "n_empty_dilewati": n_empty, "window_berikutnya": wb, "last_bar_utc": max(last_bars) if last_bars else None,
           "n_signal_total": len(sigs), "sisa_posisi_terbuka": len(open_pos),
           "per_simbol_meta": meta, "windows": rows, "trades": trades, "unfilled": unfilled}
    return out


def main() -> int:
    out = evaluate()
    json.dump(out, open(STATUS_PATH, "w"), indent=1)
    print(f"PRAREG-32  status={out['status']}  pool={out['pool']['n']}  window_usable={out['n_usable']}"
          f"  trade={out['fill']['n_fill']}  fill={out['fill']['fill_rate']:.1%}")
    print(f"wallet=${out['wallet_usd']:.2f}  A={out['A_mean_pct_EW']}  B_med={out['B_median_pct']}"
          f"  B_hit={out['B_hit_pct']}  C_t={out['C_t_net']}  AS_touch={out['D_as_median_bps']}"
          f"  AS_fill-signal={out['adverse_selection_bps']['median_fill_minus_signal']}")
    print(f"signal={out['n_signal_total']}  unfilled={out['fill']['n_unfilled']}"
          f"  incomplete={out['fill']['n_incomplete_dilewati']}  dry_run={out['dry_run_produksi']}"
          f"  next_window={out['window_berikutnya']}")
    print(f"alasan={out['alasan_verdict']}  -> {STATUS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
