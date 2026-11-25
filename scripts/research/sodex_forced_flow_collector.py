#!/usr/bin/env python3
"""Collector aliran paksa (forced flow) — R07/R09.

Merekam, 24/7, tiga hal yang tidak bisa dibeli ulang di kemudian hari:

  1. OI Binance per 15 detik (USD = jumlah koin x harga)  -> deteksi de-leveraging
  2. Event OI collapse (>=2% dalam 15 menit) + arah gerak 15 menit
  3. Harga mid SoDEX pada saat event dan pada +30s, +1m, +5m, +15m, +1j, +4j

Kenapa 15 detik: proxy OI 5 menit (arsip) terlalu kasar untuk mengukur apakah
efek hidup <1 jam. Kenapa harga SoDEX diukur langsung: histori 1m SoDEX tidak
bisa di-backfill (endpoint trades tanpa paginasi, klines 1m tidak tersedia).

READ-ONLY. Tidak ada order, tidak ada kredensial.

Pakai:
    python3 scripts/research/sodex_forced_flow_collector.py            # jalan terus
    python3 scripts/research/sodex_forced_flow_collector.py --once     # satu siklus
    python3 scripts/research/sodex_forced_flow_collector.py --seconds 120
"""
from __future__ import annotations

import argparse
import heapq
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data/sodex_forced_flow")
SYMS = ["AAVE", "BCH", "BNB", "BTC", "DOGE", "ENA", "ETH", "LINK", "ONDO", "SOL", "SUI", "XRP"]
OI_WINDOW_S = 900          # 15 menit
OI_DROP = -0.020           # ambang event
COOLDOWN_S = 4 * 3600      # per simbol
FOLLOWUPS = [30, 60, 300, 900, 3600, 14400]
UA = "anantara-research/1.0 (read-only forced-flow collector)"
BIN = "https://fapi.binance.com"
SODEX = "https://mainnet-gw.sodex.dev/api/v1/perps"

_running = True


def _stop(signum, frame):
    global _running
    _running = False


def http_json(url: str, timeout: float = 10.0, tries: int = 3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(0.6 * (i + 1))
    return {"__error__": str(last)}


def append(path: str, obj: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(obj, separators=(",", ":")) + "\n")


def day_path(kind: str, ts: float) -> str:
    d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    return os.path.join(OUT, kind, d + ".jsonl")


def sodex_mid(sym: str):
    d = http_json(f"{SODEX}/markets/{sym}-USD/orderbook?limit=1", timeout=8)
    try:
        b = float(d["data"]["bids"][0][0])
        a = float(d["data"]["asks"][0][0])
        if b > 0 and a > 0:
            return dict(mid=(a + b) / 2, bid=b, ask=a, ts=time.time(),
                        spread_bps=(a - b) / ((a + b) / 2) * 1e4)
    except Exception:                               # noqa: BLE001
        return None
    return None


def taker_ratio(sym: str):
    d = http_json(f"{BIN}/futures/data/takerlongshortRatio?symbol={sym}USDT&period=5m&limit=1", timeout=8)
    try:
        return float(d[-1]["buySellRatio"]), int(d[-1]["timestamp"])
    except Exception:                               # noqa: BLE001
        return None, None


def on_event(sym, now, chg, move, px, ratio, rts, pending):
    """Tulis event + jadwalkan follow-up harga (venue + kontrol L8).

    Dipisah dari loop supaya bisa diuji tanpa menunggu likuidasi nyata.
    """
    # KONTINUASI: harga turun -> SHORT (-1); harga naik -> LONG (+1)
    side = -1 if move < 0 else 1
    eid = f"{sym}-{int(now)}"
    mid = sodex_mid(sym)
    append(os.path.join(OUT, "events.jsonl"), dict(
        id=eid, t=int(now * 1000), sym=sym, oi_chg=round(chg, 5),
        move_15m=round(move, 5), taker_ratio=ratio, taker_ts=rts,
        binance_px=px, sodex=mid, side=side))
    print(f"EVENT {eid} oi={chg:+.2%} move={move:+.2%} side={side}", flush=True)
    if not mid:
        return eid, 0
    for h in FOLLOWUPS:
        heapq.heappush(pending, (now + h, eid, sym, h, side, mid["mid"]))
    others = [x for x in SYMS if x != sym]
    cs = others[int(now) % len(others)]
    cm = sodex_mid(cs)
    if cm:
        for h in FOLLOWUPS:
            heapq.heappush(pending, (now + h, "CTRL-" + eid, cs, h, side, cm["mid"]))
    return eid, len(pending)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--seconds", type=float, default=0)
    ap.add_argument("--self-test", action="store_true",
                    help="uji jalur follow-up di direktori sementara (tidak menyentuh data asli)")
    a = ap.parse_args()

    global OUT
    if a.self_test:
        import tempfile
        OUT = tempfile.mkdtemp(prefix="forced_flow_selftest_")
        a.once = True
        print(f"self-test di {OUT}")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    hist = {s: deque() for s in SYMS}      # (ts, oi_usd, price)
    last_event = {s: 0.0 for s in SYMS}
    ratios = {}
    pending = []            # heap (due_ts, event_id, sym, horizon, side, entry_mid)
    # pulihkan follow-up yang belum terekam (service restart / reboot)
    efile = os.path.join(OUT, "events.jsonl")
    ffile = os.path.join(OUT, "followups.jsonl")
    if os.path.exists(efile):
        have = set()
        if os.path.exists(ffile):
            for line in open(ffile):
                try:
                    j = json.loads(line)
                    have.add((j["id"], j["horizon_s"]))
                except Exception:                   # noqa: BLE001
                    pass
        now0 = time.time()
        rec = 0
        for line in open(efile).readlines()[-2000:]:
            try:
                j = json.loads(line)
            except Exception:                       # noqa: BLE001
                continue
            t_ev = j["t"] / 1000
            for h in FOLLOWUPS:
                if (j["id"], h) in have:
                    continue
                due = t_ev + h
                if due > now0:
                    heapq.heappush(pending, (due, j["id"], j["sym"], h, j["side"], None))
                    rec += 1
                elif now0 - due < 900:
                    heapq.heappush(pending, (now0, j["id"], j["sym"], h, j["side"], None))
                    rec += 1
        print(f"pulihkan {rec} follow-up tertunda", flush=True)
    started = time.time()
    cycles = events_n = 0
    if a.self_test:
        heapq.heappush(pending, (time.time() - 1, "TEST-BTC", "BTC", 60, 1))

    while _running:
        t0 = time.time()
        prices = http_json(f"{BIN}/fapi/v1/ticker/price")
        pmap = {}
        if isinstance(prices, list):
            for p in prices:
                pmap[p["symbol"]] = float(p["price"])

        for s in SYMS:
            px = pmap.get(s + "USDT")
            oi = http_json(f"{BIN}/fapi/v1/openInterest?symbol={s}USDT")
            if not px or "__error__" in oi:
                continue
            try:
                qty = float(oi["openInterest"])
            except Exception:                   # noqa: BLE001
                continue
            now = time.time()
            oi_usd = qty * px
            hist[s].append((now, oi_usd, px))
            while hist[s] and now - hist[s][0][0] > OI_WINDOW_S + 60:
                hist[s].popleft()

            append(day_path("oi", now), dict(t=int(now * 1000), s=s, oi_usd=round(oi_usd),
                                             px=px, oi_qty=qty))

            # --- deteksi event: OI 15 menit lalu vs sekarang ---
            ref = None
            best = 1e9
            for ts, oi_ref, p_ref in hist[s]:
                age = now - ts
                if age >= OI_WINDOW_S - 20 and abs(age - OI_WINDOW_S) < best:
                    best = abs(age - OI_WINDOW_S)
                    ref = (ts, oi_ref, p_ref)
            if ref and ref[1] > 0 and now - last_event[s] > COOLDOWN_S:
                chg = oi_usd / ref[1] - 1
                if chg <= OI_DROP:
                    r, rts = ratios.get(s, (None, None))
                    move = (px / ref[2] - 1) if ref[2] else 0.0
                    try:
                        on_event(s, now, chg, move, px, r, rts, pending)
                        events_n += 1
                        last_event[s] = now
                    except Exception as exc:            # noqa: BLE001
                        import traceback
                        print(f"EVENT GAGAL {s}: {exc}", flush=True)
                        traceback.print_exc()

        # --- follow-up harga SoDEX ---
        while pending and pending[0][0] <= time.time():
            due, eid, s, h, side, entry_mid = heapq.heappop(pending)
            mid = sodex_mid(s)
            if mid:
                append(os.path.join(OUT, "followups.jsonl"), dict(
                    id=eid, sym=s, horizon_s=h, side=side, due=int(due * 1000),
                    t=int(time.time() * 1000), mid=mid["mid"], bid=mid["bid"],
                    ask=mid["ask"], spread_bps=round(mid["spread_bps"], 3)))

        cycles += 1
        if cycles % 20 == 0:                    # rasio taker tiap ~5 menit
            for s in SYMS:
                r, ts = taker_ratio(s)
                if r is not None:
                    ratios[s] = (r, ts)

        if a.once:
            break
        if a.seconds and time.time() - started >= a.seconds:
            break
        sleep = 15 - (time.time() - t0)
        if sleep > 0:
            end = time.time() + sleep
            while _running and time.time() < end:
                time.sleep(min(0.5, end - time.time()))

    if a.self_test:
        f = os.path.join(OUT, "followups.jsonl")
        ok = os.path.exists(f) and os.path.getsize(f) > 0
        print(f"SELF-TEST follow-up: {'LULUS' if ok else 'GAGAL'} -> {f}")
        if ok:
            print(open(f).read().strip()[:200])

    print(f"berhenti: {cycles} siklus, {events_n} event, {len(pending)} follow-up tertunda", flush=True)


if __name__ == "__main__":
    sys.exit(main())
