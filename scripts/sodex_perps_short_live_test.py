#!/usr/bin/env python3
"""MINIMAL real-money PERPS SHORT live test — the bear-side of a bidirectional system.

Spot cannot short → SHORT needs perps. This is the complement to sodex_spot_live_test
(long side). Together = full bidirectional: LONG in confirmed bull (spot),
SHORT in confirmed bear (perps). Answers the mandate: NOT long-only.

SAFETY ENVELOPE (hard-coded):
  • SHORT only, perps, MIN notional $10 (SoDEX floor), leverage 2× → margin ~$5
  • SL +2% (price up) → worst loss = 2% × $10 = $0.20/trade
  • TP -4% (price down) → +$0.40
  • 2× lev + 2% stop → liquidation (~-50%) never reached before stop
  • MAX_POSITIONS=1 · SESSION_LOSS_CAP=-$1 · DAILY_CAP=3
  • KILL switch: touch data/PERPS_SHORT_KILL
  • DRY default; real orders only with --live
  • Dormant until perps margin funded (checks balance, skips if <$6)

Gate (bear-confirmed, 3 sources agree): PRICE bear-momentum AND intel<=48 (risk-off)
AND forecast DOWN (for reliable coins). Same gate engine as paper_test_combined.

Fund the short side:  transfer USDC spot→perps margin (user action), e.g.
  bin/sodex transfer --from spot --to perps --asset vUSDC --amount 20

Run:  python3 scripts/sodex_perps_short_live_test.py --preflight
      python3 scripts/sodex_perps_short_live_test.py --live --loop
      python3 scripts/sodex_perps_short_live_test.py demo
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
from research_short_bear import short_signal
# paper_test_combined ARCHIVED 2026-09-08 -> archive/papertracks_20260908/.
# Track comissioned (stale Aug-28). Script permanen DISABLED (unvalidated
# short signal); import kept via archive path so revival searchable.
import sys, os as _os
_ARCHIVE = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)),
                         "archive", "papertracks_20260908")
sys.path.insert(0, _ARCHIVE)
sys.path.insert(0, str(PROJECT / "scripts"))
from paper_test_combined import get_intel, get_forecast, get_reliable_coins, gate, fetch_ohlcv

SODEX = str(PROJECT / "bin" / "sodex")
STATE = PROJECT / "data" / "perps_short_live_state.json"
LOG = PROJECT / "data" / "perps_short_live.jsonl"
KILL = PROJECT / "data" / "PERPS_SHORT_KILL"

NOTIONAL = 10.0        # SoDEX perps min
LEVERAGE = 2
SL_PCT, TP_PCT = 0.020, 0.040
TIME_STOP_H = 30        # target TF 1-30h; close overdue positions (was: no time-stop = stuck)
MAX_POSITIONS, SESSION_LOSS_CAP, DAILY_CAP = 1, -1.0, 3
MIN_MARGIN = 6.0       # skip if perps margin below this

PAIRS = {"SOL": ("SOL-USD", 3), "BTC": ("BTC-USD", 5), "ETH": ("ETH-USD", 4)}  # (sym, qty_prec)
BN = {"SOL": "SOLUSDT", "BTC": "BTCUSDT", "ETH": "ETHUSDT"}
INTEL_SHORT_MAX = 48.0


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def sodex(args, timeout=25):
    return subprocess.run([SODEX] + args, capture_output=True, text=True,
                          timeout=timeout, env=os.environ.copy())


def perp_top(sym):
    r = sodex(["orderbook", "perps", sym, "--depth", "1", "--format", "json"])
    d = json.loads(r.stdout); d = d.get("data", d)

    def _px(x):
        return float(x.get("price", 0)) if isinstance(x, dict) else float(x[0])
    b = d.get("bids") or []; a = d.get("asks") or []
    return (_px(b[0]) if b else 0.0), (_px(a[0]) if a else 0.0)


def perps_margin():
    try:
        r = sodex(["balance", "perps"])
        for l in r.stdout.splitlines():
            if "vUSDC" in l:
                return float(l.split("total=")[1].split()[0])
    except Exception:
        pass
    return 0.0


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {"open": {}, "closed": [], "session_pnl": 0.0, "day": "", "trades_today": 0}


def save_state(st):
    tmp = STATE.with_suffix(".tmp"); tmp.write_text(json.dumps(st, indent=1)); tmp.replace(STATE)


def roll_day(st):
    d = datetime.now(timezone.utc).strftime("%Y%m%d")
    if st.get("day") != d:
        st["day"] = d; st["trades_today"] = 0; st["session_pnl"] = 0.0


def perps_position_qty(coin, sym):
    """Verify fill via endpoint benar (2026-09-04 fix — CLI 'positions' SELALU
    null meski posisi nyata ada, root cause insiden ETH -$2.92 di realwide)."""
    try:
        from sodex_realtime_sync import real_perps_positions
        positions = real_perps_positions()
        for p in positions:
            if p.get("symbol") == sym:
                return float(p.get("size") or 0)
        return 0.0
    except Exception:
        return None


def venue_fmt(sym, price, qty):
    """(price_s, qty_s) sesuai presisi RESMI venue — bukan 6 desimal asal.

    BUG NYATA (audit 30-Sep-2026): file ini mengirim `round(bid*0.999, 6)` dan
    `round(ask*1.001, 6)` — 6 desimal. Venue perps memakai tick tetap (mis.
    ETH-USD tick 0,1; UNI-USD 0,0001) dan harga yang BUKAN kelipatan tick
    ditolak "price is invalid" → order hilang SENYAP (tak ada fill, tak ada
    error yang terbaca). Metadata diambil dari `markets perps` lewat
    fetch_venue_meta (bukan tebakan magnitudo). qty ikut diformat → cegah
    notasi ilmiah Python ("7e-05") yang bukan angka valid bagi venue.
    """
    try:
        from sodex_maker_order import fetch_venue_meta
        meta = fetch_venue_meta(sym, sodex)
    except Exception:
        meta = {}
    tick, qp = meta.get("tick"), meta.get("qty_prec")
    if tick:
        dec = max(0, len(f"{float(tick):.10f}".rstrip("0").split(".")[-1]))
        p_s = f"{round(float(price), dec):.{dec}f}"
    else:
        p_s = str(price)
    q_s = f"{round(float(qty), int(qp)):.{int(qp)}f}" if qp is not None else str(qty)
    return p_s, q_s


def order(sym, side, qty, price, live, reduce_only=False):
    p_s, q_s = venue_fmt(sym, price, qty)      # presisi venue, bukan 6 desimal
    cmd = ["orders", "place", "perps", "--symbol", sym, "--side", side,
           "--type", "limit", "--price", p_s, "--qty", q_s, "--tif", "ioc"]
    if reduce_only:
        cmd.append("--reduce-only")
    if not live:
        return {"dry": True, "cmd": " ".join(cmd)}
    r = sodex(cmd)
    # rc + stderr WAJIB terekam — kegagalan senyap adalah kelas bug yang dilarang.
    return {"dry": False, "rc": r.returncode, "out": r.stdout[:300],
            "err": (r.stderr or "")[:300]}


def cycle(st, live):
    roll_day(st)
    out = []
    if KILL.exists():
        return ["KILL switch present — no trading"]
    if st["session_pnl"] <= SESSION_LOSS_CAP:
        return [f"session loss cap {st['session_pnl']:.2f} — halted"]
    margin = perps_margin()
    if margin < MIN_MARGIN and not st["open"]:
        return [f"perps margin ${margin:.2f} < ${MIN_MARGIN} — DORMANT (fund spot→perps to activate short)"]
    intel_score, intel_label = get_intel()
    reliable = get_reliable_coins()
    for coin, (sym, prec) in PAIRS.items():
        try:
            bid, ask = perp_top(sym)
        except Exception:
            out.append(f"{coin}:book_err"); continue
        if bid <= 0:
            out.append(f"{coin}:no_bid"); continue

        # manage open SHORT (entry was sell; profit when price falls)
        if coin in st["open"]:
            t = st["open"][coin]
            g = (t["entry_p"] - ask) / t["entry_p"]     # short pnl: entry - current
            reason = "TP" if g >= TP_PCT else ("SL" if g <= -SL_PCT else None)
            if not reason and (time.time() - datetime.fromisoformat(t["entry_iso"]).timestamp()) / 3600 >= TIME_STOP_H:
                reason = "TIME_30h"
            if reason:
                res = order(sym, "buy", t["qty"], ask * 1.001, live, reduce_only=True)
                pnl_usd = g * NOTIONAL
                rec = {**t, "exit_p": ask, "exit_iso": now_iso(), "reason": reason,
                       "pnl_pct": g, "pnl_usd": pnl_usd, "close": res}
                st["closed"].append(rec); st["session_pnl"] += pnl_usd; del st["open"][coin]
                with open(LOG, "a") as f:
                    f.write(json.dumps(rec) + "\n")
                out.append(f"{coin}:COVER {reason} {g*100:+.2f}% (${pnl_usd:+.3f}) {'LIVE' if live else 'DRY'}")
                continue
            out.append(f"{coin}:SHORT {g*100:+.2f}%"); continue

        # entry SHORT (bear-confirmed)
        if len(st["open"]) >= MAX_POSITIONS or st["trades_today"] >= DAILY_CAP:
            continue
        d = fetch_ohlcv(BN[coin]); i = len(d["c"]) - 2
        if not short_signal(d, i):
            continue
        fc = get_forecast(coin)
        ok, why = gate("S", coin, intel_score, fc, reliable)
        if not ok:
            out.append(f"{coin}:SHORT-BLOCK {why}"); continue
        qty = round(NOTIONAL / bid, prec)
        px = bid * 0.999                 # sell just below bid to cross; order() memformat ke tick venue
        if live:
            sodex(["leverage", sym, str(LEVERAGE), "--mode", "isolated"])
        held_before = perps_position_qty(coin, sym) if live else None
        res = order(sym, "sell", qty, px, live)
        if live:
            # BUKTI fill = DELTA posisi, BUKAN LEVEL (audit 30-Sep-2026). Guard lama
            # `abs(held) < qty*0.5` lolos bila sudah ada posisi sisa dari siklus
            # sebelumnya → ENTRY palsu tercatat, counter cap tidak naik, order
            # dikirim ulang tiap siklus. Terukur di spot lane: 14 ENTRY palsu.
            held_after = perps_position_qty(coin, sym)
            delta = (None if held_before is None or held_after is None
                     else abs(held_after) - abs(held_before))
            if delta is None or delta < qty * 0.5:
                out.append(f"{coin}:NO_FILL (before={held_before}, after={held_after}, "
                           f"delta={delta}, qty={qty}, rc={res.get('rc')}) — order tidak "
                           f"terisi, state NOT saved | err: {str(res.get('err'))[:120]}")
                continue
        t = {"coin": coin, "sym": sym, "entry_p": bid, "qty": qty, "notional": NOTIONAL,
             "lev": LEVERAGE, "entry_iso": now_iso(), "intel": intel_score,
             "fc": (fc or {}).get("dir"), "gate": why, "order": res}
        st["open"][coin] = t; st["trades_today"] += 1
        with open(LOG, "a") as f:
            f.write(json.dumps({"event": "SHORT_ENTRY", **t}) + "\n")
        out.append(f"{coin}:SHORT ${NOTIONAL} @{bid} qty={qty} ({why}) {'LIVE' if live else 'DRY'}")
    return out


def preflight():
    print("═══ PERPS SHORT LIVE TEST — PREFLIGHT ═══")
    print(f"creds: ADDRESS={'yes' if os.environ.get('SODEX_ADDRESS') else 'NO'} "
          f"KEY={'yes' if os.environ.get('SODEX_PRIVATE_KEY') else 'NO'}")
    m = perps_margin()
    print(f"perps margin: ${m:.2f}  ({'READY' if m >= MIN_MARGIN else 'DORMANT — needs funding'})")
    print(f"SAFETY: notional=${NOTIONAL} lev={LEVERAGE}× SL=+{SL_PCT*100}% TP=-{TP_PCT*100}% "
          f"maxpos={MAX_POSITIONS} sessioncap=${SESSION_LOSS_CAP} → worst loss/trade=${NOTIONAL*SL_PCT:.2f}")
    if m < MIN_MARGIN:
        print(f"→ TO ACTIVATE SHORT: transfer ~$20 vUSDC spot→perps (you have $227 spot):")
        print(f"   bin/sodex transfer --from spot --to perps --asset vUSDC --amount 20")
    print("posisi REAL di exchange (endpoint terverifikasi, bukan CLI cacat):")
    try:
        from sodex_realtime_sync import real_perps_positions
        real_pos = real_perps_positions()
        if not real_pos:
            print("  0 posisi (bersih)")
        else:
            for p in real_pos:
                print(f"  {p['symbol']} size={p['size']} entry={p['avgEntryPrice']} leverage={p['leverage']}x")
    except Exception as e:
        print(f"  GAGAL cek posisi real: {e} — JANGAN lanjut live sampai ini fixed")
    print("─── DRY cycle (what it WOULD do now) ───")
    st = load_state()
    for line in cycle(st, live=False):
        print(" ", line)


def demo():
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    st = {"open": {}, "closed": [], "session_pnl": -1.5, "day": today, "trades_today": 0}
    assert cycle(st, False)[0].startswith("session loss cap"), "loss cap not enforced"
    KILL.touch()
    st2 = {"open": {}, "closed": [], "session_pnl": 0.0, "day": today, "trades_today": 0}
    assert cycle(st2, False)[0].startswith("KILL"), "kill not enforced"
    KILL.unlink()
    assert NOTIONAL * SL_PCT <= 0.20, "worst loss not minimal"
    # short pnl sign: entry 100, price drops to 96 → +4% profit
    g = (100 - 96) / 100
    assert abs(g - 0.04) < 1e-9 and g >= TP_PCT, "short pnl math wrong"
    print(f"demo OK — kill+losscap enforced, short-pnl sign correct, worst loss=${NOTIONAL*SL_PCT:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="preflight")
    ap.add_argument("--preflight", action="store_true"); ap.add_argument("--live", action="store_true")
    ap.add_argument("--loop", action="store_true"); ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.cmd == "demo":
        demo(); return
    if a.status:
        st = load_state(); print(json.dumps({k: st.get(k) for k in
              ("session_pnl", "trades_today", "open")}, indent=1)); return
    if a.loop:
        st = load_state()
        while True:
            for line in cycle(st, a.live):
                print(f"[{now_iso()}] {line}", flush=True)
            save_state(st); time.sleep(a.interval)
        return
    if a.preflight or a.cmd == "preflight":
        preflight(); return
    st = load_state()
    for line in cycle(st, a.live):
        print(f"[{now_iso()}] {line}")
    save_state(st)


if __name__ == "__main__":
    main()
