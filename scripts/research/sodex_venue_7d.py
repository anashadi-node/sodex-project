#!/usr/bin/env /usr/bin/python3
"""KAMPANYE 7 HARI — Venue Market SoDEX (READ-ONLY, tanpa kredensial).

Tujuan: merekam microstructure SoDEX selama 7 hari penuh untuk mengukur
spread capture, adverse selection, fill probability, dan kedalaman book —
sesuatu yang mustahil diukur dari data 15 detik/20 menit.

Aliran yang direkam
  book    : top-20 bid/ask tiap CYCLE detik  (~104 MB/hari)
  trades  : incremental, dedupe via trade id
  klines  : 1m, tiap 60 detik (aliran silang untuk verifikasi)
  deep    : tiap 1 jam, orderbook limit=50 (menguji kedalaman sebenarnya)

Integritas
  - bid < ask wajib; pelanggaran dihitung, TIDAK dibuang (bukti mentah)
  - trade id monoton; duplikat dihitung
  - heartbeat tiap siklus: lag, req/s, error rate
  - quality JSON harian: baris, pelanggaran, gap
  - manifest run.json dibekukan saat start (hash konfigurasi)
  - berhenti otomatis setelah DURATION_DAYS
  - berhenti bila disk < MIN_FREE_GB

Keamanan
  - hanya GET publik ke gateway; tidak membaca .env; tidak ada order
"""
from __future__ import annotations

import glob
import hashlib
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
UA = {"User-Agent": "anantara-research/1.0 (sodex venue campaign)"}
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
OUT = os.path.join(ROOT, "data", "sodex_venue_7d")
LOG = os.path.join(ROOT, "logs", "sodex_venue_7d.log")

CYCLE = float(os.environ.get("CYCLE", "10"))
DEPTH = 20
DEEP_DEPTH = 50
TRADE_LIMIT = 200
DURATION_DAYS = float(os.environ.get("DURATION_DAYS", "7"))
MIN_FREE_GB = 5.0

CONFIG = dict(version="1.1", cycle_s=CYCLE, depth=DEPTH, deep_depth=DEEP_DEPTH,
              trade_limit=TRADE_LIMIT, duration_days=DURATION_DAYS,
              endpoint=B, streams=["book", "trades", "klines", "deep"])

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
    except Exception:
        pass


def fetch(path: str, tries: int = 3):
    url = f"{B}/{path}"
    for i in range(tries):
        if _stop:
            return None
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.loads(r.read().decode())
            if isinstance(d, dict):
                return d.get("data") if d.get("code") == 0 else None
            return None
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2.0 * (i + 1))
                continue
            time.sleep(0.8 * (i + 1))
        except Exception:
            time.sleep(0.8 * (i + 1))
    return None


def top_symbols(n: int = 10) -> list[str]:
    # Daftar simbol WAJIB dipatok lewat env agar tidak berubah saat service restart.
    pinned = os.environ.get("SYMBOLS", "").strip()
    if pinned:
        return [x.strip() for x in pinned.split(",") if x.strip()]
    vol = []
    for f in glob.glob(os.path.join(ROOT, "data", "sodex_klines", "1h", "*.json")):
        if "MANIFEST" in f:
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        bars = d.get("bars") or []
        if len(bars) < 24:
            continue
        q = 0.0
        for b in bars[-24:]:
            try:
                q += float(b.get("q") or 0) if isinstance(b, dict) else float(b[6])
            except Exception:
                pass
        if q > 0:
            vol.append((q, d.get("symbol") or os.path.basename(f)[:-5]))
    vol.sort(reverse=True)
    return [s for _, s in vol[:n]] or ["BTC-USD", "ETH-USD", "SOL-USD"]


def day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def path_for(kind: str, sym: str, d: str | None = None) -> str:
    p = os.path.join(OUT, kind, sym, f"{d or day()}.jsonl")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def h_for(handles: dict, kind: str, sym: str, d: str) -> Any:
    """Handle append per (kind, sym, hari UTC).

    Kunci WAJIB memuat hari: tanpa itu handle yang dibuka kemarin terus dipakai
    setelah tengah malam UTC sehingga data hari baru masuk ke file hari lama.
    Handle hari lama ditutup agar FD tidak bocor (4 kind x N sym x hari).
    """
    for k in [k for k in list(handles) if k[:2] == (kind, sym) and k[2] != d]:
        try:
            handles.pop(k).close()
        except Exception:
            handles.pop(k, None)
    k = (kind, sym, d)
    if k not in handles:
        handles[k] = open(path_for(kind, sym, d), "a", buffering=1)
    return handles[k]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    syms = top_symbols()
    started = datetime.now(timezone.utc)
    deadline = started.timestamp() + DURATION_DAYS * 86400
    cfg_hash = hashlib.sha256(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()[:16]

    manifest = dict(CONFIG, started_utc=started.isoformat(), symbols=syms,
                    config_sha256=cfg_hash, host=os.uname().nodename)
    tmp = os.path.join(OUT, "run.json.tmp")
    json.dump(manifest, open(tmp, "w"), indent=1)
    os.replace(tmp, os.path.join(OUT, "run.json"))
    log(f"START symbols={len(syms)} {syms} cycle={CYCLE}s duration={DURATION_DAYS}d cfg={cfg_hash}")

    last_trade: dict[str, int] = {}
    for sym in syms:
        p = path_for("trades", sym)
        if os.path.exists(p):
            m = 0
            with open(p) as f:
                for line in f:
                    try:
                        t = json.loads(line)["t"]
                        m = max(m, t) if isinstance(t, int) else m
                    except Exception:
                        pass
            if m:
                last_trade[sym] = m

    handles: dict[tuple[str, str], Any] = {}
    q = dict(book=0, trades=0, klines=0, deep=0, spread_viol=0, bad_price=0,
             dup_trade=0, req=0, err=0, trunc=0, last_deep=0.0, kline_last=0.0)
    err_log: list = []
    daily: dict[str, dict] = {}
    t_start = time.time()
    hb: dict = {}

    while not _stop:
        now = time.time()
        if now >= deadline:
            log("DURATION tercapai — berhenti terjadwal")
            break
        free_gb = shutil.disk_usage(ROOT).free / 1e9
        if free_gb < MIN_FREE_GB:
            log(f"STOP disk {free_gb:.1f}GB < {MIN_FREE_GB}GB")
            break

        dayk = day()
        dd = daily.setdefault(dayk, dict(book=0, trades=0, klines=0, deep=0,
                                         spread_viol=0, bad_price=0, dup_trade=0,
                                         errors=0, first=None, last=None))
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        # klines dirotasi 3 fase: hindari burst 10 permintaan pada detik yang sama
        kline_phase = int(now // max(1.0, CYCLE)) % 3
        do_kline = True
        do_deep = (time.time() - q["last_deep"]) >= 3600

        for idx, sym in enumerate(syms):
            if _stop:
                break
            q["req"] += 1
            ob = fetch(f"markets/{sym}/orderbook?limit={DEPTH}")
            if isinstance(ob, dict) and ob.get("bids") and ob.get("asks"):
                bids, asks = ob["bids"][:DEPTH], ob["asks"][:DEPTH]
                try:
                    bb, ba = float(bids[0][0]), float(asks[0][0])
                    if bb <= 0 or ba <= 0:
                        q["bad_price"] += 1; dd["bad_price"] += 1
                    if bb >= ba:
                        q["spread_viol"] += 1; dd["spread_viol"] += 1
                except Exception:
                    q["bad_price"] += 1; dd["bad_price"] += 1
                rec = {"ts": stamp, "sym": sym, "bt": ob.get("blockTime"),
                       "uid": ob.get("updateID"), "bids": bids, "asks": asks}
                h = h_for(handles, "book", sym, dayk)
                h.write(json.dumps(rec, separators=(",", ":")) + "\n")
                q["book"] += 1; dd["book"] += 1
                dd["first"] = dd["first"] or stamp; dd["last"] = stamp
            else:
                q["err"] += 1; dd["errors"] += 1
                err_log.append(f"{stamp} {sym} book_fail")

            q["req"] += 1
            tr = fetch(f"markets/{sym}/trades?limit={TRADE_LIMIT}")
            if isinstance(tr, list):
                last = last_trade.get(sym)
                fresh = []
                for x in tr:
                    if not isinstance(x, dict) or not isinstance(x.get("t"), int):
                        continue
                    if last is not None and x["t"] <= last:
                        q["dup_trade"] += 1; dd["dup_trade"] += 1
                        continue
                    fresh.append(x)
                if fresh:
                    fresh.sort(key=lambda x: x["t"])
                    h = h_for(handles, "trades", sym, dayk)
                    for x in fresh:
                        h.write(json.dumps(
                            {"ts": stamp, "sym": sym, "t": x["t"], "T": x.get("T"),
                             "side": x.get("S"), "p": x.get("p"), "q": x.get("q")},
                            separators=(",", ":")) + "\n")
                    q["trades"] += len(fresh); dd["trades"] += len(fresh)
                    last_trade[sym] = fresh[-1]["t"]
                    if last is not None and len(fresh) >= TRADE_LIMIT:
                        q["trunc"] += 1
                        err_log.append(f"{stamp} {sym} TRUNC")
            else:
                q["err"] += 1; dd["errors"] += 1
                err_log.append(f"{stamp} {sym} trades_fail")

            # klines 1m tiap 60 detik (aliran silang)
            if do_kline and idx % 3 == kline_phase:
                q["req"] += 1
                q["kline_last"] = time.time()
                kl = fetch(f"markets/{sym}/klines?interval=1m&limit=3")
                if isinstance(kl, list) and kl:
                    h = h_for(handles, "klines", sym, dayk)
                    for b in kl:
                        h.write(json.dumps(dict(b, recv=stamp),
                                           separators=(",", ":")) + "\n")
                    q["klines"] += len(kl); dd["klines"] += len(kl)
                else:
                    q["err"] += 1; dd["errors"] += 1

            # deep snapshot tiap 1 jam
            if do_deep:
                q["req"] += 1
                dp = fetch(f"markets/{sym}/orderbook?limit={DEEP_DEPTH}")
                if isinstance(dp, dict) and dp.get("bids"):
                    h = h_for(handles, "deep", sym, dayk)
                    h.write(json.dumps(
                        {"ts": stamp, "sym": sym, "requested": DEEP_DEPTH,
                         "returned_bids": len(dp["bids"]), "returned_asks": len(dp.get("asks") or []),
                         "bt": dp.get("blockTime"), "uid": dp.get("updateID"),
                         "bids": dp["bids"], "asks": dp.get("asks") or []},
                        separators=(",", ":")) + "\n")
                    q["deep"] += 1; dd["deep"] += 1
        if do_kline:
            q["kline_last"] = time.time()
        if do_deep:
            q["last_deep"] = time.time()

        elapsed = max(1e-6, time.time() - t_start)
        hb = dict(ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  uptime_s=round(elapsed), remaining_h=round((deadline - time.time()) / 3600, 2),
                  symbols=syms, rows=dict(book=q["book"], trades=q["trades"],
                                          klines=q["klines"], deep=q["deep"]),
                  quality=dict(spread_violations=q["spread_viol"], bad_price=q["bad_price"],
                               dup_trades=q["dup_trade"], errors=q["err"],
                               truncations=q["trunc"], recent_errors=err_log[-5:]),
                  req_per_s=round(q["req"] / elapsed, 2),
                  last_trade_id=last_trade, cycle_s=CYCLE, free_gb=round(free_gb, 1))
        tmp = os.path.join(OUT, "_heartbeat.json.tmp")
        with open(tmp, "w") as f:
            json.dump(hb, f)
        os.replace(tmp, os.path.join(OUT, "_heartbeat.json"))
        with open(os.path.join(OUT, f"_quality_{dayk}.json"), "w") as f:
            json.dump(dict(date=dayk, **dd), f, indent=1)

        dt = time.time() - now
        if dt < CYCLE:
            time.sleep(CYCLE - dt)

    for h in handles.values():
        try:
            h.close()
        except Exception:
            pass
    final = dict(finished_utc=datetime.now(timezone.utc).isoformat(),
                 config_hash=cfg_hash,
                 rows=hb.get("rows", {}), quality=hb.get("quality", {}),
                 uptime_s=hb.get("uptime_s", round(time.time() - t_start)),
                 complete=(time.time() >= deadline))
    json.dump(final, open(os.path.join(OUT, "_FINAL_SUMMARY.json"), "w"), indent=1)
    log(f"STOP book={q['book']} trades={q['trades']} klines={q['klines']} deep={q['deep']} "
        f"viol={q['spread_viol']} err={q['err']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
