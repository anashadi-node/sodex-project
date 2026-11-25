#!/usr/bin/env python3
"""SPOT LIVE v2 - uang nyata kecil, sinyal 100% sama dgn paper_test_spot_swing_v2.

REV 2026-09-04: v1 pakai sinyal dari research_short_bear.long_signal() + gate
intel/forecast terpisah - BUKAN replika paper resmi SPOT_SWING_v4 (WR100% n=10
tervalidasi). v2 IMPORT LANGSUNG paper_test_spot_swing_v2.py sbg single source
of truth: check_signal_combined(), btc_regime_ok(), get_liquid_pairs(),
mode adaptif - zero divergence risk.

SAFETY ENVELOPE (hardcoded):
  SIZE_USD=$3/trade, MAX_POSITIONS=1, SESSION_LOSS_CAP=-$1, DAILY_TRADE_CAP=3,
  KILL switch file, DRY by default.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))
import paper_test_spot_swing_v2 as PT  # single source of truth utk paper
from sodex_realtime_sync import real_spot_balance

SODEX = str(PROJECT / "bin" / "sodex")
STATE = PROJECT / "data" / "spot_live_test_state.json"
LOG = PROJECT / "data" / "spot_live_test.jsonl"
KILL = PROJECT / "data" / "SPOT_LIVE_KILL"

# ── HARD SAFETY (do not raise without explicit user instruction) ──
# SIZE_USD=$6 (bukan $3): SoDEX spot minNotional=$5 utk semua pair (verified
# 2026-09-04). $6 target beri buffer thd floor-rounding qty precision (BTC/LINK
# terbukti jatuh ke $4.65-4.78 dgn target $5 tepat - qty*ask harus tetap >=$5
# SETELAH round-down presisi, bukan sebelum).
SIZE_USD = 6.0
MAX_POSITIONS = 1
SESSION_LOSS_CAP = -1.0
DAILY_TRADE_CAP = 3
TP_PCT, SL_PCT = PT.TP_PCT, PT.SL_PCT          # identik paper (2.5%/1.5%)
TIME_STOP_H = PT.TIME_STOP_H                    # identik paper (30h)

# Qty precision per spot pair yg TERSEDIA di SoDEX (verified 2026-09-04 via
# `bin/sodex markets --format json`). Hanya pair yg live-tradeable dimasukkan;
# get_liquid_pairs() dari paper bisa return pair lain (misal thin) - live skip
# pair yg tidak ada di mapping ini demi keamanan (fail-closed, bukan fail-open).
SPOT_QTY_PREC = {"vBTC_vUSDC": 5, "vSOL_vUSDC": 3, "vETH_vUSDC": 4,
                 "vTON_vUSDC": 2, "vHYPE_vUSDC": 2, "vXRP_vUSDC": 1,
                 "vLINK_vUSDC": 1, "vUNI_vUSDC": 2, "vBNB_vUSDC": 3}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def sodex(args, timeout=25):
    return subprocess.run([SODEX] + args, capture_output=True, text=True,
                          timeout=timeout, env=os.environ.copy())


def spot_top(vsym):
    """(bid, ask) from SoDEX spot book via CLI json."""
    r = sodex(["orderbook", "spot", vsym, "--depth", "1", "--format", "json"])
    d = json.loads(r.stdout)
    d = d.get("data", d)
    bids = d.get("bids") or []
    asks = d.get("asks") or []

    def _px(level):
        if isinstance(level, dict):
            return float(level.get("price", 0))
        return float(level[0])
    bid = _px(bids[0]) if bids else 0.0
    ask = _px(asks[0]) if asks else 0.0
    return bid, ask


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


def coin_from_vsym(vsym: str) -> str:
    """Nama coin logis dari simbol venue: 'vLINK_vUSDC' -> 'LINK'."""
    return vsym.split("_")[0].lstrip("v")


def vcoin_of(vsym: str) -> str:
    """Nama coin di SALDO venue: 'vLINK_vUSDC' -> 'vLINK'.

    BUG NYATA (audit 29-Sep-2026): loop memakai `coin = vsym.split("_")[0].lstrip("v")`
    = 'LINK', lalu mengeceknya di /balance yang isinya 'vLINK' → selalu absen → 0.0
    → dianggap NO_FILL padahal order BENAR-BENAR terisi. Efeknya: (a) 7.407 log
    NO_FILL palsu, (b) tidak satu pun posisi tercatat → tidak ada TP/SL/time-stop
    yang mengelola inventori nyata. Prefix 'v' adalah bagian dari nama token di venue.
    """
    return vsym.split("_")[0]


def spot_holdings(coin):
    """Return quantity of spot coin held (source of truth: exchange balance).
    FIX 2026-09-04: None HARUS berarti API call gagal (rc!=0 atau JSON error),
    BUKAN "coin tidak ada di balance". Sebelumnya coin yg belum pernah dipegang
    (absen dari list balance, BUKAN 0) salah dianggap None -> semua entry BTC/
    LINK/dst yg belum pernah dipegang SELALU NO_FILL meski order benar2 fill.
    Return 0.0 jika API sukses tapi coin absen (artinya benar2 belum punya)."""
    r = sodex(["balance", "spot", "--format", "json"])
    if r.returncode != 0:
        return None  # API call gagal - benar2 tidak bisa verifikasi
    try:
        data = json.loads(r.stdout or "[]")
        rows = data if isinstance(data, list) else data.get("data", [])
        for row in rows:
            if row.get("coin") == coin:
                return float(row.get("total") or 0)
        return 0.0  # API sukses, coin absen dari list = benar2 0 (bukan gagal)
    except Exception:
        return None  # parse gagal - benar2 tidak bisa verifikasi


_VENUE_META_CACHE = {}


def venue_meta(vsym):
    """Metadata pasar venue untuk 1 simbol (pricePrecision/tickSize/minNotional).

    BUG NYATA (audit 30-Sep-2026, uang nyata): order DITOLAK venue dengan
    "sodex API error (code -1): price is invalid" karena skrip mengirim harga
    ber-6 desimal (`round(ask*1.001, 6)`) padahal venue memakai tick tetap
    (mis. pricePrecision=2 / tickSize=0.01). Qty sangat kecil juga terkirim
    dalam notasi ilmiah Python ("7e-05") yang bukan angka valid bagi venue.
    Presisi diambil dari `markets spot`, TIDAK ditebak.
    """
    if vsym in _VENUE_META_CACHE:
        return _VENUE_META_CACHE[vsym]
    meta = {}
    try:
        r = sodex(["markets", "spot", "--format", "json"], timeout=20)
        rows = json.loads(r.stdout or "[]")
        rows = rows if isinstance(rows, list) else rows.get("data", [])
        for row in rows:
            if str(row.get("name")) == str(vsym):
                meta = row
                break
    except Exception:
        meta = {}
    _VENUE_META_CACHE[vsym] = meta
    return meta


def venue_fmt(vsym, price, qty):
    """(price_s, qty_s) sesuai presisi venue — cegah 'price is invalid'."""
    meta = venue_meta(vsym)
    pp = int(meta.get("pricePrecision") or 6)
    qp = int(meta.get("quantityPrecision") or 6)
    return (f"{round(float(price), pp):.{pp}f}",
            f"{round(float(qty), qp):.{qp}f}")


def place_buy(vsym, qty, price, live):
    if live:
        price, qty = venue_fmt(vsym, price, qty)  # str sesuai presisi venue
    cmd = ["orders", "place", "spot", "--symbol", vsym, "--side", "buy",
           "--type", "limit", "--price", f"{price}", "--qty", f"{qty}", "--tif", "ioc"]
    if not live:
        return {"dry": True, "cmd": " ".join(cmd)}
    r = sodex(cmd)
    # AUDIT 30-Sep-2026: rc + stderr WAJIB ikut terekam. Terukur: order gagal
    # dengan rc=1 dan stdout KOSONG — pesan sebabnya hanya ada di stderr, yang
    # sebelumnya dibuang → 7.482 log NO_FILL tanpa sebab yang bisa dibaca.
    return {"dry": False, "rc": r.returncode, "out": r.stdout[:300],
            "err": (r.stderr or "")[:300], "sent_price": price, "sent_qty": qty}


def place_sell(vsym, qty, price, live):
    if live:
        price, qty = venue_fmt(vsym, price, qty)
    cmd = ["orders", "place", "spot", "--symbol", vsym, "--side", "sell",
           "--type", "limit", "--price", f"{price}", "--qty", f"{qty}", "--tif", "ioc"]
    if not live:
        return {"dry": True, "cmd": " ".join(cmd)}
    r = sodex(cmd)
    # AUDIT 30-Sep-2026: rc + stderr WAJIB ikut terekam (lihat place_buy).
    return {"dry": False, "rc": r.returncode, "out": r.stdout[:300],
            "err": (r.stderr or "")[:300], "sent_price": price, "sent_qty": qty}



def live_entry_reconciled(st):
    """Allow no new spot entry while exchange/local holdings diverge."""
    try:
        balances = {
            str(b.get("coin")): float(b.get("total") or 0)
            for b in real_spot_balance()
        }
        expected = set()
        for coin in st.get("open", {}):
            expected.add(coin if str(coin).startswith("v") else "v" + str(coin).upper())
        allow = set()
        for coin in os.environ.get("SODEX_MANUAL_SPOT_ALLOWLIST", "").split(","):
            coin = coin.strip()
            if not coin:
                continue
            allow.add(coin)
            # Convenience: "BTC" means "vBTC", but exact SoDEX symbols like
            # "WSOSO"/"aUNITREE" must also remain valid.
            if not coin.startswith(("v", "a")):
                allow.add("v" + coin.upper())
        untracked = [
            coin for coin, qty in balances.items()
            if coin != "vUSDC" and qty > 0 and coin not in expected and coin not in allow
        ]
        if untracked:
            return False, f"untracked={sorted(untracked)}"
        for coin in expected:
            if balances.get(coin, 0.0) <= 0:
                return False, f"missing={coin}"
        return True, "match"
    except Exception as e:
        return False, f"reconcile_error={e}"


def cycle(st, live):
    roll_day(st)
    out = []
    if KILL.exists():
        return ["KILL switch present — no trading"]
    if st["session_pnl"] <= SESSION_LOSS_CAP:
        return [f"session loss cap {st['session_pnl']:.2f} — halted"]

    # exits — pakai TP/SL/TIME_STOP identik paper (2.5%/1.5%/30h)
    for coin in list(st["open"].keys()):
        t = st["open"][coin]
        vsym = t["vsym"]
        try:
            bid, ask = spot_top(vsym)
        except Exception:
            out.append(f"{coin}:book_err"); continue
        if bid <= 0:
            out.append(f"{coin}:no_bid"); continue
        g = (bid - t["entry_p"]) / t["entry_p"]
        reason = "TP" if g >= TP_PCT else ("SL" if g <= -SL_PCT else None)
        if not reason and (time.time() - datetime.fromisoformat(t["entry_iso"]).timestamp()) / 3600 >= TIME_STOP_H:
            reason = "TIME_30h"
        if reason:
            vcoin = vcoin_of(vsym)
            held_before = spot_holdings(vcoin) if live else None
            res = place_sell(vsym, t["qty"], round(bid * 0.999, 6), live)
            if live:
                time.sleep(2)
                # AUDIT 30-Sep-2026: exit WAJIB terbukti juga (delta saldo TURUN).
                # Tanpa ini posisi dihapus dari state + PnL dibukukan padahal aset
                # masih dipegang di venue -> inventori nyata tak terkelola (tidak
                # ada TP/SL/time-stop lagi yang menjaganya).
                held_after = spot_holdings(vcoin)
                delta = (None if held_before is None or held_after is None
                         else held_before - held_after)
                if delta is None or delta < t["qty"] * 0.5:
                    out.append(f"{coin}:SELL_NO_FILL (vcoin={vcoin}, before={held_before}, "
                               f"after={held_after}, delta={delta}, qty={t['qty']}, "
                               f"rc={res.get('rc')}) — posisi DIPERTAHANKAN, PnL tidak "
                               f"dibukukan | venue: {str(res.get('out'))[:90]} "
                               f"| err: {str(res.get('err'))[:140]}")
                    continue
            pnl_usd = g * SIZE_USD
            rec = {**t, "exit_p": bid, "exit_iso": now_iso(), "reason": reason,
                   "pnl_pct": g, "pnl_usd": pnl_usd, "sell": res}
            st["closed"].append(rec); st["session_pnl"] += pnl_usd
            del st["open"][coin]
            with open(LOG, "a") as f:
                f.write(json.dumps(rec, default=str) + "\n")
            out.append(f"{coin}:SELL {reason} {g*100:+.2f}% (${pnl_usd:+.3f}) {'LIVE' if live else 'DRY'}")
            continue
        out.append(f"{coin}:HOLD {g*100:+.2f}%")

    if live:
        reconciled, detail = live_entry_reconciled(st)
        if not reconciled:
            out.append(f"RECONCILIATION HALT: {detail}")
            return out

    # entries — PERSIS sinyal dari paper: check_signal_combined + btc_regime_ok
    if len(st["open"]) >= MAX_POSITIONS or st["trades_today"] >= DAILY_TRADE_CAP:
        return out
    try:
        liquid_pairs = PT.get_liquid_pairs()
    except Exception as e:
        out.append(f"liquid_pairs_err:{e}"); return out
    regime_on = PT.btc_regime_ok()
    for vsym in sorted(liquid_pairs, key=lambda s: -liquid_pairs[s]):
        if vsym not in SPOT_QTY_PREC:
            continue  # fail-closed: hanya pair yg qty-precision-nya diverifikasi manual
        coin = coin_from_vsym(vsym)
        if coin in st["open"]:
            continue
        bn = PT.SPOT_TO_BN.get(vsym)
        if not bn:
            continue
        try:
            h, l, c = PT.fetch_klines(bn)
        except Exception:
            continue
        if not PT.check_signal_combined(h, l, c):
            continue
        try:
            bid, ask = spot_top(vsym)
        except Exception:
            continue
        if ask <= 0:
            continue
        qty = round(SIZE_USD / ask, SPOT_QTY_PREC.get(vsym, 4))
        if qty * ask < 5.0:  # SoDEX spot minNotional=$5, semua pair (verified)
            out.append(f"{coin}:skip qty*ask=${qty*ask:.2f} < minNotional $5")
            continue
        px = round(ask * 1.001, 6)
        vcoin = vcoin_of(vsym)
        held_before = spot_holdings(vcoin) if live else None
        delta = None
        res = place_buy(vsym, qty, px, live)
        if live:
            time.sleep(2)
            # AUDIT 30-Sep-2026: bukti fill = DELTA saldo, BUKAN LEVEL saldo.
            # Level salah: bila coin sudah dipegang (sisa fill lama / inventori
            # manual), order yang GAGAL tetap lolos penjaga -> ENTRY palsu
            # tercatat, counter cap tidak naik, loop mengulang tiap siklus.
            # Terukur: 14 ENTRY palsu dgn saldo venue tidak berubah sama sekali.
            held_after = spot_holdings(vcoin)
            delta = (None if held_before is None or held_after is None
                     else held_after - held_before)
            oid_zero = "orderID=0" in str(res.get("out") or "")
            if delta is None or delta < qty * 0.5:
                out.append(f"{coin}:NO_FILL (vcoin={vcoin}, before={held_before}, "
                           f"after={held_after}, delta={delta}, qty={qty}, "
                           f"rc={res.get('rc')}, oid0={oid_zero}) — saldo venue tidak "
                           f"naik, state NOT saved | venue: {str(res.get('out'))[:90]} "
                           f"| err: {str(res.get('err'))[:140]}")
                continue
        t = {"coin": coin, "vsym": vsym, "entry_p": ask, "qty": qty, "size_usd": SIZE_USD,
             "entry_iso": now_iso(), "regime_on": regime_on, "fill_delta": delta, "buy": res}
        st["open"][coin] = t; st["trades_today"] += 1
        with open(LOG, "a") as f:
            f.write(json.dumps({"event": "ENTRY", **t}, default=str) + "\n")
        out.append(f"{coin}:BUY ${SIZE_USD} @{ask} qty={qty} regime={'ON' if regime_on else 'OFF'} "
                   f"{'LIVE' if live else 'DRY'}")
        break  # 1 entry per cycle, identik paper
    return out


def preflight():
    print("=== SPOT LIVE TEST v2 — PREFLIGHT (sinyal identik paper_test_spot_swing_v2) ===")
    print(f"creds: ADDRESS={'yes' if os.environ.get('SODEX_ADDRESS') else 'NO'} "
          f"KEY={'yes' if os.environ.get('SODEX_PRIVATE_KEY') else 'NO'}")
    try:
        r = sodex(["balance", "spot"])
        usdc = [l for l in r.stdout.splitlines() if "vUSDC" in l]
        print("vUSDC balance:", usdc[0].strip() if usdc else "?")
    except Exception as e:
        print("balance err:", e)
    print(f"SAFETY: size=${SIZE_USD} maxpos={MAX_POSITIONS} sessioncap=${SESSION_LOSS_CAP} "
          f"dailycap={DAILY_TRADE_CAP} TP=+{TP_PCT*100}% SL=-{SL_PCT*100}% "
          f"-> worst loss/trade=${SIZE_USD*SL_PCT:.3f}")
    try:
        lp = PT.get_liquid_pairs()
        tradeable = [s for s in lp if s in SPOT_QTY_PREC]
        print(f"liquid pairs (paper): {len(lp)} total, {len(tradeable)} live-tradeable "
              f"(qty-prec verified): {tradeable}")
    except Exception as e:
        print(f"liquid_pairs err: {e}")
    print("--- DRY cycle (what it WOULD do right now) ---")
    st = load_state()
    for line in cycle(st, live=False):
        print(" ", line)
    print("--- to go live: python3 scripts/sodex_spot_live_test.py --live --loop ---")


def demo():
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    st = {"open": {}, "closed": [], "session_pnl": -1.5, "day": today, "trades_today": 0}
    assert cycle(st, live=False)[0].startswith("session loss cap"), "loss cap not enforced"
    KILL.touch()
    st2 = {"open": {}, "closed": [], "session_pnl": 0.0, "day": today, "trades_today": 0}
    assert cycle(st2, live=False)[0].startswith("KILL"), "kill switch not enforced"
    KILL.unlink()
    assert SIZE_USD * SL_PCT < 0.10, "worst-case loss not minimal"
    assert TP_PCT == PT.TP_PCT and SL_PCT == PT.SL_PCT, "geometry harus identik paper"
    print(f"demo OK — kill+losscap enforced, worst loss/trade=${SIZE_USD*SL_PCT:.3f}, "
          f"geometry identik paper v4")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="preflight")
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.cmd == "demo":
        demo(); return
    if a.status:
        st = load_state()
        print(json.dumps({k: st[k] for k in ("session_pnl", "trades_today", "open")
                          if k in st}, indent=1)); return
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



