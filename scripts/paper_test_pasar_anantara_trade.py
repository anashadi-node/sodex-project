#!/usr/bin/env python3
"""PAPER TEST TRADING — SoDEX track dgn sinyal LAPORAN PASAR-ANANTARA.

Sinyal = produksi deterministik (momentum_composite + deterministic_direction)
dari presentiment_data/presentiment_forecast (READ-ONLY import — produksi
laporan pasar tak disentuh). Setiap pair universe SoDEX sama dgn realwide.

Entry  : momentum_score per horizon T+24h (threshold 0.40 produksi)
         momentum >= +0.40 → LONG · <= -0.40 → SHORT · mid → TUNGGU (no entry)
Geometri: mirror realwide (TP6%/SL1.5%/TIME30h/CD4/MAX8) supaya perbandingan
         apples-to-apples — hanya sinyal yang berbeda.

METRIK (honest, target 0.7%/trade wallet):
  WR, PF, avg wallet_roi, cum, >=0.7% count, vs base rate (up proba).

Catatan kejujuran: backtest 60/90d produksi menunjukkan deterministik
ANTI-predictive (WR < base). Paper test ini mengukur NYATA di live paper —
bagus atau jelek, apa adanya.

Usage:
  python3 scripts/paper_test_pasar_anantara_trade.py --loop --interval 300
  python3 scripts/paper_test_pasar_anantara_trade.py --status
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

from cost_model import round_trip_frac as _rt_cost  # SUMBER TUNGGAL biaya (audit 30-Sep-2026)
PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
sys.path.insert(0, str(PROJECT / "anantara"))
import paper_test_realwide as RW          # universe + geometry (single of truth)
import presentiment_data as pdata
import presentiment_forecast as pfc

# ── signal source: produksi deterministik (read-only) ──
HORIZON_TRADE_H = 24        # horizon yang produksi keep (h4/h12 suppressed)
ENTRY_THR = pfc.NEUTRAL_THRESHOLD[HORIZON_TRADE_H]  # 0.40

# ── geometri & env — mirror realwide (apples-to-apples) ──
PAIRS = RW.PAIRS
BN = RW.BN
TP_PCT = RW.TP_PCT
SL_PCT = RW.SL_PCT
MIN_HOLD_SL_H = RW.MIN_HOLD_SL_H
TIME_STOP_H = RW.TIME_STOP_H
LEVERAGE = RW.LEVERAGE
COOLDOWN_H = RW.COOLDOWN_H
MAX_TOTAL = RW.MAX_TOTAL
NOTIONAL = 100.0
MAKER_FEE = 0.00024
SPREAD = RW.SPREAD if hasattr(RW, "SPREAD") else {}
TOTAL_WALLET_CAPITAL = float(os.environ.get("SODEX_TOTAL_WALLET", "108.10"))
TARGET_MIN_PCT = 0.008

STATE = PROJECT / "data" / "paper_test_pasar_anantara_trade_state.json"
LOG = PROJECT / "data" / "paper_test_pasar_anantara_trade.jsonl"

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"

# ── PER-SYMBOL SKILL GATE (RCA 2026-09-10) ──────────────────────────────────
# Temuan: track ini entry di aset yang accuracy-nya ANTI-predictive (XRP hr=0/36,
# DOGE 5.9%, ETH 6.5%, BNB 9.5% < base rate) → rugi $-90 kec nama. Fix: blok entry
# untuk aset yang TERBUKTI anti-predictive (n>=20 DAN hit_rate <= base_rate),
# dan wajib confidence-gate deterministik (momentum yang cukup kuat untuk LINTAS
# dead-zone, mirip conf-gate 0.60 di produksi). Fail-open jika bridge tidak
# terjangkau (paper collection tetap jalan); BLOCK hanya untuk bukti statistik.
ACCURACY_URL = "http://localhost:8000/prediction/accuracy"
MIN_ACC_N = 20          # minimal sampel sebelum aset boleh di-claim anti-predictive
CONF_GATE = 0.55        # momentum score min utk committed entry (produksi 0.55-0.60)
_skill_cache = {"ts": 0.0, "data": {}}


def _fetch_per_symbol_accuracy() -> dict:
    """Get per-symbol accuracy from hermes_bridge (cache 10 min, fail-open {})."""
    now = time.time()
    if now - _skill_cache["ts"] < 600:
        return _skill_cache["data"]
    try:
        req = urllib.request.Request(ACCURACY_URL, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=8).read().decode())
        _skill_cache["data"] = (d or {}).get("per_symbol", {})
    except Exception:
        _skill_cache["data"] = {}
    _skill_cache["ts"] = now
    return _skill_cache["data"]


def skill_gate_blocks(sym: str) -> bool:
    """True = aset terbukti ANTI-predictive → jangan entry.

    Bukti yang mem-BLOCK (audit 2026-09-12, dua aturan, salah SATU cukup):
      1. RELATIF:  n>=20 DAN hit_rate <= base_rate (skill <= 0) — model kalah
         dari drift pasar.
      2. ABSOLUT:  n>=20 DAN hit_rate < 0.35 — model salah lebih sering dari
         benar, TERMASUK saat base rate rendah (APT: hr 22.6%, base 17.5%,
         skill +5% → lolos aturan 1 tapi p=0.001 di bawah undian).
    Window 7d dipakai kalau ada sampel (konsisten dgn gate report produksi);
    fallback all-time. Kecocokan (n<20 atau tidak ada data) → fail-OPEN.
    """
    acc = _fetch_per_symbol_accuracy().get(sym)
    if not acc:
        return False
    n = int(acc.get("total_7d", 0) or 0)
    hr = float(acc.get("hit_rate_7d", 0) or 0)
    base = float(acc.get("base_rate_7d", 0) or 0)
    if n < MIN_ACC_N:
        n = int(acc.get("total", 0) or 0)
        hr = float(acc.get("hit_rate", 0) or 0)
        base = float(acc.get("base_rate", 0) or 0)
    if n < MIN_ACC_N:
        return False
    if hr <= base:
        return True
    if hr < 0.35:
        return True
    return False


def fetch_ohlcv(sym: str, limit: int = 300) -> dict:
    """Use Realwide's spot→futures fallback for perp-only symbols."""
    d = RW.fetch_ohlcv(sym, limit=limit)
    return {k: (v.tolist() if hasattr(v, "tolist") else v)
            for k, v in d.items()}


def _candles(d: dict):
    """dict fetch_ohlcv → list[Candle] produksi (o/h/l/c/v/t)."""
    return [pdata.Candle(t=t, o=o, h=h, l=l, c=c, v=v)
            for t, o, h, l, c, v in zip(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"])]


def sinyal(d: dict) -> tuple[str, float]:
    """Momentum composite produksi → (aksi, momentum). aksi ∈ LONG/SHORT/TUNGGU."""
    score = pdata.momentum_composite(_candles(d))
    dirc = pfc.deterministic_direction(score, HORIZON_TRADE_H)
    aksi = {"UP": "LONG", "DOWN": "SHORT"}.get(dirc, "TUNGGU")
    return aksi, score


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"open": {}, "closed": [], "last_entry": {}, "created": now_iso(),
            "n_trades": 0, "n_wins": 0, "n_below": 0, "total_pnl_usd": 0.0}


def save_state(st: dict) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE)


def status(st: dict) -> None:
    c = st.get("closed", [])
    n = len(c)
    if n:
        wins = sum(1 for t in c if (t.get("pnl_usd") or 0) > 0)
        roi = sum(t.get("wallet_roi", 0) for t in c) / n * 100
        pos = sum(t.get("pnl_usd", 0) for t in c if t.get("pnl_usd", 0) > 0)
        neg = abs(sum(t.get("pnl_usd", 0) for t in c if t.get("pnl_usd", 0) < 0))
        pf = pos / neg if neg > 0 else (99.0 if pos > 0 else 0.0)
    else:
        wins = roi = pf = 0
    open_n = len(st.get("open", {}))
    wr_s = (f"{wins / n * 100:.1f}%" if n else "—")
    print(f"PASAR-ANANTARA TRADE — n={n}  WR={wr_s}  PF={pf:.2f}  "
          f"avgWalletROI={roi:+.3f}%/t  cum=${st.get('total_pnl_usd', 0):+.2f}  "
          f">=0.8%: {sum(1 for t in c if (t.get('wallet_roi', 0) or 0) >= 0.008)}/{n}  open={open_n}")


def run_cycle(st: dict, dry: bool = True) -> list:
    hits = []
    now = time.time()
    for p in PAIRS:
        try:
            d = fetch_ohlcv(BN[p])
        except Exception as e:
            hits.append(f"{p}:fetch_err"); continue
        _c = d.get("c")
        if _c is None or len(_c) == 0:
            hits.append(f"{p}:empty"); continue
        px = float(_c[-1])
        cost = float(_rt_cost(venue="sodex_perps", order_type="taker", pair=p,
                                 include_funding=True))  # audit 30-Sep: biaya JUJUR (perps, +funding)

        # ── manage open ──
        if p in st["open"]:
            t = st["open"][p]
            hold_h = (now - t["entry_ts"]) / 3600.0
            g = (px - t["entry_p"]) / t["entry_p"]
            reason = None
            if g >= TP_PCT:
                reason = "TP"
            elif g <= -SL_PCT and hold_h >= MIN_HOLD_SL_H:
                reason = "SL"
            elif hold_h >= TIME_STOP_H:
                reason = f"TIME_{TIME_STOP_H}h"
            t["peak_g"] = max(t.get("peak_g", g), g)
            if not reason and t["peak_g"] >= 0.012 and g <= 0.004:
                reason = "SL_PROTECT"
            if reason:
                pnl = g - cost
                pnl_usd = pnl * NOTIONAL * LEVERAGE
                roi = pnl_usd / TOTAL_WALLET_CAPITAL
                rec = {**t, "exit_p": px, "exit_ts": now, "exit_iso": now_iso(),
                       "exit_r": reason, "pnl_pct": pnl, "pnl_usd": pnl_usd,
                       "wallet_roi": roi, "hold_h": round(hold_h, 1),
                       "below_target": roi < TARGET_MIN_PCT}
                if not dry:
                    st["closed"].append(rec)
                    st["n_trades"] += 1
                    if pnl_usd > 0:
                        st["n_wins"] += 1
                    st["n_below"] += 1 if roi < TARGET_MIN_PCT else 0
                    st["total_pnl_usd"] += pnl_usd
                    LOG.open("a").write(json.dumps(rec) + "\n")
                    del st["open"][p]
                    hits.append(f"{p}:CLOSE {reason} {pnl:+.2%} (${pnl_usd:+.2f})")
                else:
                    hits.append(f"{p}:DRY-CLOSE {reason} {pnl:+.2%}")

        # ── entry ──
        if p in st["open"] or len(st["open"]) >= MAX_TOTAL:
            continue
        if (now - st.get("last_entry", {}).get(p, 0)) / 3600.0 < COOLDOWN_H:
            continue
        try:
            aksi, score = sinyal(d)
        except Exception as e:
            hits.append(f"{p}:sig_err"); continue
        if aksi == "TUNGGU":
            continue
        # RCA 2026-09-10: jangan entry di aset terbukti anti-predictive
        if skill_gate_blocks(p):
            hits.append(f"{p}:SKILL_GATE_BLOCK (anti-predictive, hr<=base)")
            continue
        # Confidence gate: momentum harus cukup kuat (>=0.55 produksi),
        # bukan 0.40 minimal. Sinyal tipis tidak layak komit.
        if abs(score) < CONF_GATE:
            hits.append(f"{p}:CONF_GATE {score:+.2f} < {CONF_GATE}")
            continue
        hits.append(f"{p}:SIGNAL {aksi} score={score:+.2f}")
        if not dry:
            st["open"][p] = {
                "sym": p, "side": "L" if aksi == "LONG" else "S",
                "entry_p": px, "entry_ts": now, "entry_iso": now_iso(),
                "regime": f"PASAR_{HORIZON_TRADE_H}h_{aksi}",
                "conviction": round(abs(score), 2),
                "tp": TP_PCT, "sl": SL_PCT, "lev": LEVERAGE, "peak_g": 0.0,
            }
            st["last_entry"][p] = now
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    st = load_state()
    if a.status:
        status(st); return
    if a.loop:
        while True:
            try:
                hits = run_cycle(st, dry=a.dry)
                for h in hits:
                    print(f"[{now_iso()[:19]}] {h}", flush=True)
                if not dry_save(a):
                    save_state(st)
            except Exception as e:
                print(f"[{now_iso()[:19]}] ERR {type(e).__name__}: {e}", flush=True)
            time.sleep(a.interval)
    else:
        hits = run_cycle(st, dry=a.dry)
        for h in hits:
            print(f"[{now_iso()[:19]}] {h}", flush=True)
        if not a.dry:
            save_state(st)
        status(st)


def dry_save(a):
    return a.dry


if __name__ == "__main__":
    main()