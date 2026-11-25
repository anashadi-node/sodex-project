#!/usr/bin/env python3
"""SHORT-BEAR PAPER v1 — strategi SHORT saat market bearish (2026-09-05).

Konteks: user approve lanjutkan riset short (market crypto sedang sideways
cenderung bearish). Perps-short LIVE dimatikan permanen 2026-09-04 krn signal
tak tervalidasi — PAPER INI utk kumpulkan bukti n>=30.

Signal: mirror research_short_bear.py short_signal() TAPI data Binance API
langsung (bukan feather yg hilang). Bear regime: ADX>25, c<SMA50<SMA200,
RSI 40-60, vol>1.1, 24h down, bump kecil utk sell.

Geometri baseline saat ini: TP +2.5% / SL -1.5%, leverage 2x, hold max 16h, cooldown 12h.
Signal baseline: ADX>25, c<SMA50<SMA200, lalu minimal 4 dari 5 gate
(price<SMA24, RSI 40-60, volume>1.1x, return 24h<-1.2%, return 1h<0).
Catatan: signal mirror sudah dipakai di riset_short_bear (backtest exploratory),
tapi LIVE perps-short lama TIDAK tervalidasi (semua phantom) — paper ini utk
mengumpulkan n>=30 bukti FORWARD dgn verify ketat sebelum layak live.

PAPER ONLY. Tidak pernah kirim order nyata.
Run: python3 scripts/paper_test_shortbear.py --loop --interval 300
"""

from __future__ import annotations
import argparse, json, os, time, sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
from cost_model import round_trip_frac as _rt_cost  # SUMBER TUNGGAL biaya (audit 30-Sep-2026)
import backtest_swing_gate1_v3 as v3

STATE_FILE = PROJECT / "data" / "paper_test_shortbear_state.json"
LOG_FILE = PROJECT / "data" / "paper_test_shortbear.jsonl"
TELEMETRY_FILE = PROJECT / "data" / "paper_test_shortbear_telemetry.jsonl"

PAIRS = ["BTC", "ETH", "SOL", "DOGE", "XRP", "UNI"]
BN = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
      "DOGE": "DOGEUSDT", "XRP": "XRPUSDT", "UNI": "UNIUSDT"}

TP_PCT = 0.025   # REV 2026-09-05: backtest 500h menunjukkan TP4% TIDAK tercapai
                 # di market sideways (0 TP semua pair, avg negatif). TP2.5% lebih
                 # realistis utk range. FALSIFIKASI dicatat di laporan riset.
SL_PCT = 0.015
LEVERAGE = 2      # L2 (bukan 3) — riset portfolio: L3 bahaya semua skenario.
TIME_STOP_H = 16      # REV 2026-09-05 (analisa TWOWAY): 55% short mentok TIME_30h
                      # tanpa profit (harga nyaris tak turun) — modal terikat lama.
                      # Short 16h = ambil profit kecil lebih cepat, buang modal.
                      # Riset forensik: hold 8-30h sweet spot tapi short TIDAK;
                      # short yg benar harus konklusif dalam 1 hari.
COOLDOWN_H = 12
MAX_TOTAL = 3
NOTIONAL = 50.0
ENV_WALLET = os.environ.get("SODEX_TOTAL_WALLET", "108.10")
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
FETCH_STAGGER_S = float(os.environ.get("SHORTBEAR_FETCH_STAGGER_S", "0.15"))


def _resolve_wallet_denominator(env_value=ENV_WALLET, reader=None, priced_reader=None):
    """Return (denominator, source, error) for target-ROI reporting.

    Order of preference:
      1. FINAL denominator (all holdings priced)                  -> "verified_snapshot"
      2. priced lower bound (some holding unpriced, reported)      -> "priced_lower_bound"
      3. env fallback                                              -> "env_unverified"
      4. nothing                                                   -> "unavailable"

    The target stays measurable at step 2, but it is ALWAYS labelled so no one
    reads a lower bound as if it were the final wallet value.
    """
    try:
        if reader is None:
            from sodex_wallet_denominator import read_real_wallet
            reader = read_real_wallet
        result = reader()
        # sodex_wallet_denominator.read_real_wallet() currently returns
        # (perps, spot, total, dust). Older tests/helpers returned 3 values.
        # Total is always index 2; do not fixed-unpack and accidentally
        # demote a verified denominator to priced_lower_bound.
        total = result[2]
        return float(total), "verified_snapshot", None
    except FileNotFoundError as exc:
        return float(env_value), "env_unverified", type(exc).__name__
    except ValueError as exc:
        try:
            if priced_reader is None:
                from sodex_wallet_denominator import read_priced_wallet
                priced_reader = read_priced_wallet
            _p, _s, priced, unpriced = priced_reader()
            return float(priced), "priced_lower_bound", (
                f"{type(exc).__name__}: {len(unpriced)} holding belum tervaluasi")
        except Exception as inner:
            return None, "unavailable", type(inner).__name__
    except Exception as exc:
        return None, "unavailable", type(exc).__name__



TOTAL_WALLET, WALLET_DENOMINATOR_SOURCE, WALLET_DENOMINATOR_ERROR = \
    _resolve_wallet_denominator()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _finite(value):
    """JSON-safe numeric telemetry; unavailable values become null."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _candle_ts(d, index):
    values = d.get("t", d.get("dates"))
    if values is None or index < 0 or index >= len(values):
        return None
    return _finite(values[index])


def _append_telemetry(row):
    TELEMETRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TELEMETRY_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n")


def fetch_funding_status(sym_bn):
    """Read Binance Futures funding once; never expose credentials."""
    try:
        import urllib.request as _ur
        import json as _json
        url = "https://fapi.binance.com/fapi/v1/premiumIndex"
        req = _ur.Request(url, headers={"User-Agent": "anantara/1.0"})
        with _ur.urlopen(req, timeout=8) as response:
            funding = {
                item["symbol"]: float(item.get("lastFundingRate") or 0)
                for item in _json.loads(response.read().decode())
            }
        value = funding.get(sym_bn)
        return {
            "value": _finite(value),
            "source": "binance_futures_premium_index",
            "error": None if value is not None else "symbol_missing",
        }
    except Exception as exc:
        # Preserve existing paper fail-open behavior, but make it observable.
        return {
            "value": None,
            "source": "binance_futures_premium_index",
            "error": type(exc).__name__,
        }


def evaluate_short_signal(f, sym_bn=None, funding_fetcher=None):
    """Return one auditable decision with all signal/block reasons."""
    reasons = []
    if not f.get("sufficient", False):
        reasons.append("insufficient_data")
    if not f.get("bear_stack", False):
        reasons.append("bear_stack_failed")
    if int(f.get("chk", 0)) < 4:
        reasons.append("chk_below_4")
    if not f.get("r1_negative", False):
        reasons.append("return_1h_not_negative")
    if f.get("weekend", False):
        reasons.append("weekend")

    funding = {"value": None, "source": None, "error": None}
    if f.get("candidate", False) and sym_bn:
        funding = (funding_fetcher or fetch_funding_status)(sym_bn)
        if isinstance(funding, (int, float)):
            funding = {"value": _finite(funding), "source": "custom", "error": None}
        if funding.get("value") is not None and funding["value"] < 0:
            reasons.append("funding_negative")

    return {
        "accepted": bool(f.get("candidate", False) and "funding_negative" not in reasons),
        "block_reasons": reasons,
        "funding": funding,
        "funding_value": funding.get("value"),
        "funding_source": funding.get("source"),
        "funding_error": funding.get("error"),
    }


def short_funnel(d, now_dt=None):
    """Telemetry funnel SHORT-BEAR — observability tanpa mengubah entry logic."""
    out = {
        "sufficient": False, "bear_stack": False, "chk": 0,
        "r1_negative": False, "weekend": False, "candidate": False,
        "adx": None, "r1": None, "rsi": None, "volume_ratio": None,
        "r24": None, "close": None, "sma24": None, "sma50": None,
        "sma200": None, "signal_index": None, "signal_candle_ts": None,
        "gate_price_below_sma24": False, "gate_rsi_40_60": False,
        "gate_volume_gt_1_1": False, "gate_return_24h_below": False,
        "gate_return_1h_negative": False,
    }
    i = len(d["c"]) - 2
    if i < 200:
        return out
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    a = v3.adx(h, l, c)
    s50 = v3.sma(c, 50)
    s200 = v3.sma(c, 200)
    rv = v3.rsi(c)
    s24 = v3.sma(c, 24)
    va = v3.sma(v, 24)
    r24 = v3.rr(c, 24)
    r1 = v3.rr(c, 1)
    vr = v[i] / va[i] if va[i] > 0 else 1.0
    out.update({
        "sufficient": True, "signal_index": i,
        "signal_candle_ts": _candle_ts(d, i), "adx": _finite(a[i]),
        "r1": _finite(r1[i]), "rsi": _finite(rv[i]),
        "volume_ratio": _finite(vr), "r24": _finite(r24[i]),
        "close": _finite(c[i]), "sma24": _finite(s24[i]),
        "sma50": _finite(s50[i]), "sma200": _finite(s200[i]),
    })
    out["bear_stack"] = bool(a[i] > 25 and c[i] < s50[i] and s50[i] < s200[i])
    out["gate_price_below_sma24"] = bool(c[i] < s24[i])
    out["gate_rsi_40_60"] = bool(40 < rv[i] < 60)
    out["gate_volume_gt_1_1"] = bool(vr > 1.1)
    out["gate_return_24h_below"] = bool(i >= 24 and not np.isnan(r24[i]) and r24[i] < -0.012)
    out["gate_return_1h_negative"] = bool(i >= 1 and not np.isnan(r1[i]) and r1[i] < 0)
    out["r1_negative"] = out["gate_return_1h_negative"]
    out["chk"] = sum((
        out["gate_price_below_sma24"], out["gate_rsi_40_60"],
        out["gate_volume_gt_1_1"], out["gate_return_24h_below"],
        out["gate_return_1h_negative"],
    ))
    if now_dt is None:
        now_dt = datetime.now(timezone.utc)
    out["weekend"] = now_dt.weekday() >= 5
    out["candidate"] = bool(out["bear_stack"] and out["chk"] >= 4
                            and out["r1_negative"] and not out["weekend"])
    return out


def short_signal(d, now_dt=None, sym_bn=None):
    """Mirror research_short_bear.short_signal with auditable funding check."""
    f = short_funnel(d, now_dt=now_dt)
    return evaluate_short_signal(f, sym_bn=sym_bn)["accepted"]


def fetch_ohlcv(sym, limit=300):
    """Fetch OHLCV dari Binance. RETRY+BACKOFF (fix fetch_err burst rate-limit).

    RC 2026-09-10: fetch_err semua pair (22:36 log) = transient Binance
    rate-limit 429 saat burst 6-pair/cycle. Bukan bug logika — bottleneck API
    (TOC). Fix: exponential backoff 2 attempt + 0.5s/1s sleep. LIMIT WAJIB
    >= 300 (JANGAN turunkan ke 200): short_signal() butuh i=len-2 >= 200
    utk indikator SMA200/ADX — limit 200 memutus syarat insufficient SEMUA
    pair selama 26 jam (bug 5d51e67, RCA 2026-09-10 user priority alert).
    """

    params = {"symbol": sym, "interval": "1h", "limit": limit}
    for attempt in [1, 2]:
        try:
            r = requests.get(BINANCE_KLINES, params=params, timeout=15)
            r.raise_for_status()
            d = r.json()
            return {
                "o": np.array([float(x[1]) for x in d]),
                "h": np.array([float(x[2]) for x in d]),
                "l": np.array([float(x[3]) for x in d]),
                "c": np.array([float(x[4]) for x in d]),
                "v": np.array([float(x[5]) for x in d]),
                "t": np.array([float(x[0]) for x in d]) / 1000,
            }
        except Exception:
            if attempt == 2:
                raise
            time.sleep(0.5 * attempt)  # backoff: 0.5s, then 1.0s
    raise RuntimeError(f"fetch failed {sym}")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"open": {}, "closed": [], "last_entry": {}, "created": now_iso()}


def save_state(st):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(STATE_FILE)


def _rsi2(d):
    """RSI(2) utk exit MR — sensitif utk deteksi oversold/overbought cepat."""
    import backtest_swing_gate1_v3 as _v3
    return _v3.rsi(d["c"])[-1]


def run_cycle(st, dry=False):
    hits = []
    fetch_ok = 0
    fetch_err = 0
    funnel = {"sufficient": 0, "bear_stack": 0, "chk4": 0, "r1neg": 0,
              "candidate": 0, "max_chk": 0}
    now = datetime.now(timezone.utc)
    cycle_iso = now.isoformat()

    def emit(row):
        if not dry:
            try:
                _append_telemetry(row)
            except Exception as exc:
                hits.append(f"{row.get('pair', '?')}:telemetry_err:{type(exc).__name__}")

    for idx, p in enumerate(PAIRS):
        if idx and FETCH_STAGGER_S > 0:
            time.sleep(FETCH_STAGGER_S)
        row = {
            "schema_version": 1, "cycle_iso": cycle_iso, "pair": p,
            "symbol": BN[p], "venue": "SoDEX-paper",
            "signal_source": "binance-spot-ohlcv", "decision": None,
            "block_reasons": [], "funding_value": None,
            "funding_source": None, "funding_error": None,
            "wallet_denominator": _finite(TOTAL_WALLET),
            "wallet_denominator_source": WALLET_DENOMINATOR_SOURCE,
            "wallet_denominator_error": WALLET_DENOMINATOR_ERROR,
        }
        try:
            d = fetch_ohlcv(BN[p])
            fetch_ok += 1
        except Exception as exc:
            fetch_err += 1
            row["decision"] = "fetch_error"
            row["block_reasons"] = [f"fetch_error:{type(exc).__name__}"]
            emit(row)
            hits.append(f"{p}:fetch_err:{type(exc).__name__}")
            continue

        f = short_funnel(d, now_dt=now)
        evaluation = evaluate_short_signal(f, sym_bn=BN[p])
        row.update({
            "decision": "candidate" if f["candidate"] else "no_candidate",
            "block_reasons": list(evaluation["block_reasons"]),
            "funding_value": evaluation["funding_value"],
            "funding_source": evaluation["funding_source"],
            "funding_error": evaluation["funding_error"],
            "funnel": f,
            "signal_candle_ts": f["signal_candle_ts"],
            "entry_candle_ts": _candle_ts(d, len(d["c"]) - 1),
            "entry_price": _finite(d["c"][-1]) if len(d["c"]) else None,
            "entry_price_source": "binance-spot-last-ohlcv-close",
        })
        if f["sufficient"]: funnel["sufficient"] += 1
        if f["bear_stack"]: funnel["bear_stack"] += 1
        if f["chk"] >= 4: funnel["chk4"] += 1
        if f["r1_negative"]: funnel["r1neg"] += 1
        if f["candidate"]: funnel["candidate"] += 1
        funnel["max_chk"] = max(funnel["max_chk"], int(f["chk"]))
        if not f["sufficient"]:
            emit(row)
            hits.append(f"{p}:insufficient")
            continue

        px = float(d["c"][-1])
        # BIAYA BENAR (audit 30-Sep-2026): taker 2 sisi + spread 2 sisi + funding.
        cost = float(_rt_cost(venue="perps", order_type="taker", pair=p,
                              include_funding=True))

        # manage open SHORT
        if p in st["open"]:
            t = st["open"][p]
            hold_h = (now - datetime.fromisoformat(t["entry_iso"])).total_seconds() / 3600
            g = (t["entry_p"] - px) / t["entry_p"]  # profit saat harga turun
            t["mfe_pct"] = max(float(t.get("mfe_pct", 0.0)), g)
            t["mae_pct"] = min(float(t.get("mae_pct", 0.0)), g)
            reason = None
            if g >= TP_PCT:
                reason = "TP"
            elif g <= -SL_PCT:
                reason = "SL"
            elif hold_h >= TIME_STOP_H:
                reason = f"TIME_{TIME_STOP_H}h"
            if not reason and g >= 0.005:
                try:
                    r2 = _rsi2(d)
                    if r2 < 30:
                        reason = "MR_EXIT"
                except Exception:
                    pass
            row.update({
                "position_state": "open", "current_return_pct": _finite(g),
                "mfe_pct": _finite(t["mfe_pct"]), "mae_pct": _finite(t["mae_pct"]),
                "hold_h": round(hold_h, 1), "entry_price": _finite(t["entry_p"]),
                "entry_price_source": t.get("entry_price_source", row["entry_price_source"]),
            })
            if reason:
                pnl = g - cost
                pnl_usd = pnl * NOTIONAL * LEVERAGE
                rec = {**t, "exit_p": px, "exit_iso": now_iso(), "exit_r": reason,
                       "pnl_pct": round(pnl, 4), "pnl_usd": round(pnl_usd, 2),
                       "hold_h": round(hold_h, 1),
                       "wallet_roi": round(pnl_usd / TOTAL_WALLET, 4) if TOTAL_WALLET else None}
                row.update({"decision": "close", "exit_reason": reason,
                            "exit_price": _finite(px), "pnl_pct": _finite(pnl),
                            "pnl_usd": _finite(pnl_usd), "mfe_pct": _finite(t["mfe_pct"]),
                            "mae_pct": _finite(t["mae_pct"]), "hold_h": round(hold_h, 1)})
                if not dry:
                    st["closed"].append(rec)
                    del st["open"][p]
                    st["last_entry"][p] = now.timestamp()
                    with open(LOG_FILE, "a", encoding="utf-8") as log_fh:
                        log_fh.write(json.dumps(rec) + "\n")
                emit(row)
                hits.append(f"{p}:CLOSE {reason} {pnl*100:+.2f}%")
                continue
            emit(row)
            hits.append(f"{p}:HOLD {g*100:+.2f}% {hold_h:.1f}h")
            continue

        # entry SHORT
        if not evaluation["accepted"]:
            row["decision"] = "blocked_signal"
            emit(row)
            continue
        if len(st["open"]) >= MAX_TOTAL:
            row["decision"] = "blocked_risk"
            row["block_reasons"] = ["max_positions"]
            emit(row)
            continue
        la = st["last_entry"].get(p, 0)
        if (now.timestamp() - la) / 3600 < COOLDOWN_H:
            row["decision"] = "blocked_risk"
            row["block_reasons"] = ["cooldown"]
            emit(row)
            continue
        entry = {"pair": p, "side": "SHORT", "entry_p": px,
                 "entry_iso": now_iso(), "regime": "BEAR_MOMENTUM",
                 "signal_candle_ts": f["signal_candle_ts"],
                 "entry_candle_ts": row["entry_candle_ts"],
                 "entry_price_source": row["entry_price_source"],
                 "signal_metrics": f, "funding_value": evaluation["funding_value"],
                 "funding_source": evaluation["funding_source"],
                 "mfe_pct": 0.0, "mae_pct": 0.0}
        if not dry:
            st["open"][p] = entry
            st["last_entry"][p] = now.timestamp()
        row["decision"] = "short_entry"
        row["block_reasons"] = []
        row["entry_price"] = _finite(px)
        emit(row)
        hits.append(f"{p}:SHORT_ENTRY @{px:.4f}")
    signals = sum(1 for h in hits if "SHORT_ENTRY" in h)
    hits.append(f"SCAN ok={fetch_ok} err={fetch_err} signal={signals} open={len(st['open'])}")
    hits.append("FUNNEL sufficient={sufficient} bear_stack={bear_stack} chk4={chk4} "
                "r1neg={r1neg} candidate={candidate} max_chk={max_chk}".format(**funnel))
    if not dry:
        save_state(st)
    return hits


def status(st):
    c = st["closed"]
    if not c:
        print(f"SHORT-BEAR paper — open={len(st['open'])} closed=0")
        return
    wins = sum(1 for t in c if t["pnl_pct"] > 0)
    gp = sum(t["pnl_pct"] for t in c if t["pnl_pct"] > 0)
    gl = -sum(t["pnl_pct"] for t in c if t["pnl_pct"] <= 0)
    pf = gp / gl if gl > 0 else float("inf")
    tot = sum(t["pnl_usd"] for t in c)
    wr = 100 * wins / len(c)
    print(f"SHORT-BEAR paper (TP{TP_PCT*100:.1f}/SL{SL_PCT*100:.1f}, {LEVERAGE}x, no min-hold)")
    print(f"  n={len(c)}  WR={wr:.1f}%  PF={pf:.2f}  net=${tot:+.2f}  open={len(st['open'])}")
    target_hits = sum(1 for t in c if TOTAL_WALLET and t.get("wallet_roi", 0) >= 0.008)
    denom = f"${TOTAL_WALLET:.2f} ({WALLET_DENOMINATOR_SOURCE})" if TOTAL_WALLET else "UNAVAILABLE (fail-closed)"
    print(f"  wallet denominator: {denom}")
    print(f"  >=0.8% wallet: {target_hits}/{len(c)}")


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
            except Exception as e:
                print(f"[{now_iso()[:19]}] ERR {e}", flush=True)
            time.sleep(a.interval)
    else:
        hits = run_cycle(st, dry=a.dry)
        for h in hits:
            print(f"[{now_iso()[:19]}] {h}")


if __name__ == "__main__":
    main()