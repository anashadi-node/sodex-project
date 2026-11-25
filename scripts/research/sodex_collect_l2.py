#!/usr/bin/env /usr/bin/python3
"""Kolektor L2 SoDEX (READ-ONLY, publik, tanpa kredensial).

Merekam dua aliran per simbol:
  book   : snapshot orderbook top-20 (bids/asks/updateID/blockTime)
  trades : transaksi incremental (dedupe via id `t`, hanya yang baru)

Output append-only JSONL per simbol per hari:
  data/sodex_l2/book/<SYM>/YYYY-MM-DD.jsonl
  data/sodex_l2/trades/<SYM>/YYYY-MM-DD.jsonl
  data/sodex_l2/_heartbeat.json          (kesegaran, dibaca monitor)

Kenapa: tanpa data book/trades, studi market-making & fill maker TIDAK bisa
divalidasi (hanya ada 1h/1d). Data yang tidak direkam hari ini hilang permanen.

Safety:
  - hanya GET publik; tidak menyentuh kredensial/order
  - loop tidak pernah mati karena satu request gagal
  - berhenti sendiri bila ruang disk < MIN_FREE_GB
  - tulis flush per baris; rotasi harian; tidak ada file yang ditimpa
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

B = "https://mainnet-gw.sodex.dev/api/v1/perps"
UA = {"User-Agent": "anantara-research/1.0 (read-only l2 collector)"}
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
OUT = os.path.join(ROOT, "data", "sodex_l2")
LOG = os.path.join(ROOT, "logs", "sodex_l2_collector.log")

CYCLE = 15.0          # detik antar siklus
DEPTH = 20            # level per sisi
TRADE_LIMIT = 200     # maksimum yang diterima API (1000 -> error)
MIN_FREE_GB = 5.0
TOP_N = 10

_stop = False


def _sig(*_a):
    global _stop
    _stop = True


signal.signal(signal.SIGTERM, _sig)
signal.signal(signal.SIGINT, _sig)


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def fetch(path: str, tries: int = 3):
    url = f"{B}/{path}"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode())
            if isinstance(d, dict) and d.get("code") == 0:
                return d.get("data")
            return None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2.0 * (i + 1))
                continue
            time.sleep(1.0 * (i + 1))
        except Exception:  # noqa: BLE001
            time.sleep(1.0 * (i + 1))
    return None


def top_symbols() -> list[str]:
    """Pilih simbol paling likuid dari klines 1h yang ADA (tanpa unduh baru)."""
    vol = []
    for f in glob.glob(os.path.join(ROOT, "data", "sodex_klines", "1h", "*.json")):
        if "MANIFEST" in f:
            continue
        try:
            d = json.load(open(f))
        except Exception:  # noqa: BLE001
            continue
        bars = d.get("bars") or []
        if len(bars) < 24:
            continue
        q = 0.0
        for b in bars[-24:]:
            try:
                if isinstance(b, dict):
                    q += float(b.get("q") or 0)
                elif isinstance(b, (list, tuple)) and len(b) > 6:
                    q += float(b[6])
                else:
                    q += 0.0
            except Exception:  # noqa: BLE001
                pass
        if q > 0:
            vol.append((q, d.get("symbol") or os.path.basename(f)[:-5]))
    vol.sort(reverse=True)
    out = [s for _, s in vol[:TOP_N]]
    return out or ["BTC-USD", "ETH-USD", "SOL-USD"]


def open_append(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return open(path, "a", buffering=1)


def day_path(kind: str, sym: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return os.path.join(OUT, kind, sym, f"{day}.jsonl")


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    syms = top_symbols()
    log(f"start symbols={len(syms)} {syms}")

    last_trade: dict[str, int] = {}
    # Seed dari file hari ini: restart TIDAK boleh menulis ulang trade lama.
    for sym in syms:
        p = day_path("trades", sym)
        if not os.path.exists(p):
            continue
        m = 0
        with open(p) as f:
            for line in f:
                try:
                    t = json.loads(line)["t"]
                    if isinstance(t, int) and t > m:
                        m = t
                except Exception:  # noqa: BLE001
                    pass
        if m:
            last_trade[sym] = m
    log(f"seed last_trade={len(last_trade)} simbol")
    handles: dict[tuple[str, str], Any] = {}
    errors = 0
    n_book = n_trade = 0

    while not _stop:
        t0 = time.time()
        free_gb = shutil.disk_usage(ROOT).free / 1e9
        if free_gb < MIN_FREE_GB:
            log(f"STOP disk {free_gb:.1f}GB < {MIN_FREE_GB}GB")
            break

        for sym in syms:
            if _stop:
                break
            now = datetime.now(timezone.utc)
            stamp = now.isoformat(timespec="milliseconds")

            ob = fetch(f"markets/{sym}/orderbook?limit={DEPTH}")
            if isinstance(ob, dict) and ob.get("bids"):
                rec = {"ts": stamp, "sym": sym, "bt": ob.get("blockTime"),
                       "uid": ob.get("updateID"),
                       "bids": ob["bids"][:DEPTH], "asks": (ob.get("asks") or [])[:DEPTH]}
                key = ("book", sym)
                if key not in handles:
                    handles[key] = open_append(day_path("book", sym))
                handles[key].write(json.dumps(rec, separators=(",", ":")) + "\n")
                n_book += 1
            else:
                errors += 1

            tr = fetch(f"markets/{sym}/trades?limit={TRADE_LIMIT}")
            if isinstance(tr, list) and tr:
                last = last_trade.get(sym)
                fresh = [x for x in tr if isinstance(x, dict) and isinstance(x.get("t"), int)
                         and (last is None or x["t"] > last)]
                if fresh:
                    fresh.sort(key=lambda x: x["t"])
                    key = ("trades", sym)
                    if key not in handles:
                        handles[key] = open_append(day_path("trades", sym))
                    for x in fresh:
                        handles[key].write(json.dumps(
                            {"ts": stamp, "sym": sym, "t": x["t"], "T": x.get("T"),
                             "side": x.get("S"), "p": x.get("p"), "q": x.get("q")},
                            separators=(",", ":")) + "\n")
                    n_trade += len(fresh)
                    last_trade[sym] = fresh[-1]["t"]
            else:
                errors += 1

        hb = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "symbols": syms, "book_rows": n_book, "trade_rows": n_trade,
              "last_trade_id": last_trade, "errors": errors}
        tmp = os.path.join(OUT, "_heartbeat.json.tmp")
        with open(tmp, "w") as f:
            json.dump(hb, f)
        os.replace(tmp, os.path.join(OUT, "_heartbeat.json"))

        dt = time.time() - t0
        if dt < CYCLE:
            time.sleep(CYCLE - dt)

    for h in handles.values():
        try:
            h.close()
        except Exception:  # noqa: BLE001
            pass
    log(f"stop book_rows={n_book} trade_rows={n_trade} errors={errors}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
