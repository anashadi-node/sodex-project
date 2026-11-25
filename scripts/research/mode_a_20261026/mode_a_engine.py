#!/usr/bin/env python3
"""Mode A signal engine v2 (hardened): daily Donchian-ensemble trend following, SPOT, long-only, NO leverage.

Numerik IDENTIK dengan mode_a_engine_orig.py (v1) pada data valid (dibuktikan test_engine_v2.py).
Perbaikan v1 -> v2 (semua fail-closed: data buruk => DataError, BUKAN bobot salah diam-diam):
  F1  bar terakhir salah satu aset telat/NaN  -> v1 diam-diam membuang aset itu dan MENAIKKAN bobot aset lain (+50%)
  F2  hari hilang di tengah seri               -> v1 menggeser lookback diam-diam
  F3  bar parsial hari berjalan ikut dipakai   -> v1 memakai harga intraday sebagai "penutupan" (kebocoran/inkonsistensi)
  F4  harga <=0 / non-finite / lonjakan >60%/hari -> v1 membuat bobot 0 diam-diam
  F5  fetch: Timestamp.utcnow() usang, satu host saja, tanpa cek konsistensi -> update_history() inkremental, host cadangan,
      cek return overlap, tulis atomik
  F6  tidak ada perencana order -> plan_orders(): minNotional, stepSize, jual-dulu, tak pernah jual > saldo / beli > kas
Mode:
  A  (default, DIBEKUKAN dokumen 26-Okt) bobot per sinyal; sisa = kas
  B1 sisa kas -> XAUT (paper, butuh persetujuan)
  B2 sisa kas x sinyal XAUT -> XAUT (paper, butuh persetujuan)
Engine TIDAK mengirim order apa pun (dry-run only). Eksekusi live = keputusan GO-LIVE manual.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import os
import sys
import tempfile

import numpy as np
import pandas as pd

LOOKBACKS = [5, 10, 20, 30, 60, 90, 150, 250, 360]
VT = 0.50
BAND = 0.20
MIN_HIST = 360
VOL_WIN = 90
MAX_JUMP = 0.60          # |ret harian| > 60% = data rusak (maks nyata sampel: ETH -43,2% 12-Mar-2020)
MODES = ("A", "B1", "B2")

# Spesifikasi pasar SoDEX spot, diverifikasi live 26-Okt-2026 (GET /api/v1/spot/markets/symbols). Ambil ulang sebelum live.
DEFAULT_META = {
    "btc":  {"symbol": "vBTC_vUSDC",  "step": 0.00001, "min_notional": 5.0, "taker": 0.00065, "maker": 0.00035},
    "eth":  {"symbol": "vETH_vUSDC",  "step": 0.0001,  "min_notional": 5.0, "taker": 0.00065, "maker": 0.00035},
    "xaut": {"symbol": "vXAUt_vUSDC", "step": 0.0001,  "min_notional": 5.0, "taker": 0.00065, "maker": 0.00035},
}


class DataError(ValueError):
    """Data harga tidak layak dipakai. Jangan trading; perbaiki sumber data."""


def today_utc() -> pd.Timestamp:
    return pd.Timestamp(dt.datetime.now(dt.timezone.utc).date())


# ----------------------------------------------------------------------------------------------- validasi
def validate_closes(closes: dict, today: pd.Timestamp | None = None, max_jump: float = MAX_JUMP) -> None:
    """Fail-closed. Syarat: indeks harian UTC naive, terurut, unik, TANPA hari hilang, harga finite >0, tanpa bar
    parsial (tanggal < hari ini UTC), tanpa lonjakan tak masuk akal, dan SEMUA aset berakhir di tanggal yang sama."""
    if not closes:
        raise DataError("closes kosong")
    today = (today if today is not None else today_utc()).normalize()
    lasts = {}
    for k, s in closes.items():
        if not isinstance(s, pd.Series) or not isinstance(s.index, pd.DatetimeIndex):
            raise DataError(f"{k}: harus pd.Series ber-DatetimeIndex")
        if s.index.tz is not None:
            raise DataError(f"{k}: indeks harus tz-naive (UTC)")
        if len(s) == 0:
            raise DataError(f"{k}: seri kosong")
        if not (s.index == s.index.normalize()).all():
            raise DataError(f"{k}: indeks harus tanggal harian (00:00 UTC)")
        if not s.index.is_monotonic_increasing or not s.index.is_unique:
            raise DataError(f"{k}: indeks tidak terurut/duplikat")
        v = s.to_numpy(dtype=float)
        if not np.isfinite(v).all():
            raise DataError(f"{k}: ada NaN/inf")
        if (v <= 0).any():
            raise DataError(f"{k}: ada harga <= 0")
        if len(pd.date_range(s.index[0], s.index[-1], freq="D")) != len(s):
            raise DataError(f"{k}: ada hari hilang di tengah seri")
        if s.index[-1] >= today:
            raise DataError(f"{k}: bar {s.index[-1].date()} belum ditutup (hari ini UTC {today.date()}); buang bar parsial")
        if len(v) > 1 and np.abs(v[1:] / v[:-1] - 1).max() > max_jump:
            raise DataError(f"{k}: lonjakan harian > {max_jump:.0%} (data rusak?)")
        lasts[k] = s.index[-1]
    if len(set(lasts.values())) != 1:
        raise DataError("bar terakhir tidak sama antar aset (data telat): " + ", ".join(f"{k}={d.date()}" for k, d in lasts.items()))


# ----------------------------------------------------------------------------------------------- sinyal
def donchian_signal(close: pd.Series) -> pd.Series:
    p = close.values.astype(float)
    n = len(p)
    out = np.zeros(n)
    for L in LOOKBACKS:
        inpos = False
        stop = -np.inf
        for t in range(L, n):
            hi_prev = p[t - L:t].max()
            w2 = p[t - L + 1:t + 1]
            mid = (w2.max() + w2.min()) / 2
            if not inpos:
                if p[t] > hi_prev:
                    inpos = True
                    stop = mid
            else:
                if p[t] < stop:
                    inpos = False
                    stop = -np.inf
                else:
                    stop = max(stop, mid)
            out[t] += 1.0 if inpos else 0.0
    return pd.Series(out / len(LOOKBACKS), index=close.index)


def target_history(closes: dict, vt: float = VT, mode: str = "A", validate: bool = True,
                   today: pd.Timestamp | None = None) -> pd.DataFrame:
    """Bobot target yang diputuskan pada tiap penutupan harian (indeks = tanggal penutupan itu)."""
    if mode not in MODES:
        raise ValueError(f"mode harus salah satu {MODES}")
    if validate:
        validate_closes(closes, today=today)
    if mode != "A" and not {"btc", "eth", "xaut"} <= set(closes):
        raise ValueError("mode B1/B2 butuh aset btc, eth, xaut")
    px = pd.DataFrame({k: v for k, v in closes.items()}).sort_index()
    sig = pd.DataFrame({k: donchian_signal(closes[k].dropna()) for k in closes}).reindex(px.index).fillna(0.0)
    ret = px.pct_change(fill_method=None)
    vol = ret.rolling(VOL_WIN).std() * math.sqrt(365)
    elig = (px.notna().cumsum() >= MIN_HIST) & px.notna()
    n_el = elig.sum(axis=1).replace(0, np.nan)
    tgt = (sig * np.minimum(1.0, vt / vol)).where(elig, 0.0).div(n_el, axis=0).fillna(0.0)
    tot = tgt.sum(axis=1)
    tgt = tgt.div(np.maximum(tot, 1.0), axis=0)
    if mode != "A":
        rem = (1.0 - tgt["btc"] - tgt["eth"]).clip(lower=0.0)
        tgt["xaut"] = (rem if mode == "B1" else rem * sig["xaut"]).where(elig["xaut"], 0.0)
    return tgt


def latest_targets(closes: dict, vt: float = VT, mode: str = "A", validate: bool = True,
                   today: pd.Timestamp | None = None) -> dict:
    t = target_history(closes, vt, mode, validate, today)
    last = t.iloc[-1]
    return {"mode": mode, "asof_close": str(t.index[-1].date()), "weights": {k: float(last[k]) for k in t.columns}}


# ----------------------------------------------------------------------------------------------- order
def rebalance_orders(current: dict, target: dict, band: float = BAND) -> dict:
    """Bobot = fraksi total ekuitas. Mengembalikan fraksi trade bertanda (+beli / -jual)."""
    orders = {}
    for k, t in target.items():
        w = current.get(k, 0.0)
        diff = t - w
        if (t == 0 and w > 0) or abs(diff) > band * max(t, 0.05):
            orders[k] = diff
    return orders


def _floor_step(qty: float, step: float) -> float:
    """Pembulatan ke bawah EKSAK (Decimal). Versi lama memakai +1e-9 sehingga bisa membulatkan KE ATAS 1 step
    (qty jual > saldo -> ditolak venue / saldo negatif). Hasil dijamin <= qty."""
    from decimal import Decimal, ROUND_FLOOR
    n = (Decimal(str(qty)) / Decimal(str(step))).to_integral_value(ROUND_FLOOR)
    return float(n * Decimal(str(step)))


def plan_orders(targets: dict, holdings: dict, prices: dict, cash_usd: float,
                meta: dict | None = None, band: float = BAND, cash_buffer: float = 0.005) -> dict:
    """Rencana order SPOT dry-run. Tidak pernah: short, jual > saldo, beli > kas (sisa buffer), order < minNotional.
    Jual dieksekusi lebih dulu. holdings = jumlah koin; prices = USD per koin (tengah buku)."""
    meta = meta or DEFAULT_META
    for k in targets:
        if k not in prices or not (prices[k] > 0) or not math.isfinite(prices[k]):
            raise DataError(f"harga {k} tidak valid untuk perencanaan order")
        if holdings.get(k, 0.0) < 0:
            raise DataError(f"saldo {k} negatif")
    if cash_usd < 0 or not math.isfinite(cash_usd):
        raise DataError("kas tidak valid")
    equity = cash_usd + sum(holdings.get(k, 0.0) * prices[k] for k in targets)
    if equity <= 0:
        return {"equity": equity, "orders": [], "skipped": [], "dry_run": True}
    cur_w = {k: holdings.get(k, 0.0) * prices[k] / equity for k in targets}
    want = rebalance_orders(cur_w, targets, band)
    orders, skipped = [], []
    cash = cash_usd
    for k, d in sorted(want.items(), key=lambda kv: kv[1]):          # negatif (jual) dulu
        m, px = meta[k], prices[k]
        if d < 0:
            full_exit = targets[k] == 0
            qty = holdings.get(k, 0.0) if full_exit else min(holdings.get(k, 0.0), -d * equity / px)
            qty = _floor_step(qty, m["step"])
            if qty <= 0 or qty * px < m["min_notional"]:
                skipped.append({"asset": k, "side": "SELL", "reason": "di bawah minNotional/step", "notional": qty * px})
                continue
            cash += qty * px * (1 - m["taker"])
            orders.append({"asset": k, "symbol": m["symbol"], "side": "SELL", "qty": qty, "notional": qty * px, "ref_px": px})
        else:
            budget = max(0.0, cash * (1 - cash_buffer))
            notional = min(d * equity, budget / (1 + m["taker"]))
            qty = _floor_step(notional / px, m["step"])
            if qty <= 0 or qty * px < m["min_notional"]:
                skipped.append({"asset": k, "side": "BUY", "reason": "di bawah minNotional/step atau kas kurang", "notional": qty * px})
                continue
            cash -= qty * px * (1 + m["taker"])
            orders.append({"asset": k, "symbol": m["symbol"], "side": "BUY", "qty": qty, "notional": qty * px, "ref_px": px})
    return {"equity": equity, "cash_after": cash, "orders": orders, "skipped": skipped, "dry_run": True}


# ----------------------------------------------------------------------------------------------- data
HOSTS = ("https://api.binance.com", "https://data-api.binance.vision")


def fetch_binance_daily(symbol: str, start_ms: int = 1502928000000, today: pd.Timestamp | None = None) -> pd.Series:
    """Penutupan harian UTC Binance; buang hari berjalan. Coba host cadangan bila gagal."""
    import urllib.request
    last_err = None
    for host in HOSTS:
        try:
            rows, cur = [], start_ms
            while True:
                url = f"{host}/api/v3/klines?symbol={symbol}&interval=1d&startTime={cur}&limit=1000"
                with urllib.request.urlopen(url, timeout=30) as r:
                    batch = json.loads(r.read())
                if not batch:
                    break
                rows += batch
                cur = batch[-1][6] + 1
                if len(batch) < 1000:
                    break
            s = pd.Series({pd.Timestamp(x[0], unit="ms").normalize(): float(x[4]) for x in rows}).sort_index()
            td = (today if today is not None else today_utc()).normalize()
            return s[s.index < td]
        except Exception as e:  # noqa: BLE001 - coba host berikutnya
            last_err = e
    raise DataError(f"fetch {symbol} gagal di semua host: {last_err}")


def load_csv(path: str) -> pd.Series:
    d = pd.read_csv(path, parse_dates=[0])
    d = d.set_index(d.columns[0]).iloc[:, 0].astype(float).sort_index()
    return d[~d.index.duplicated(keep="last")]


def update_history(path: str, symbol: str, today: pd.Timestamp | None = None, ret_tol: float = 0.02) -> pd.Series:
    """Tambah bar baru ke CSV riwayat. Rantai berdasarkan RETURN (level sumber lama boleh beda skala, mis. Coin Metrics ->
    Binance). Menolak bila return overlap berbeda > ret_tol (sumber berubah/rusak). Tulis atomik."""
    old = load_csv(path)
    start = int((old.index[-1] - pd.Timedelta(days=4)).timestamp() * 1000)
    new = fetch_binance_daily(symbol, start, today)
    ov = old.index.intersection(new.index)
    if len(ov) < 2:
        raise DataError(f"{symbol}: overlap < 2 hari, tidak bisa verifikasi")
    r_old, r_new = old.loc[ov].pct_change().dropna(), new.loc[ov].pct_change().dropna()
    if (r_old - r_new).abs().max() > ret_tol:
        raise DataError(f"{symbol}: return overlap berbeda > {ret_tol:.0%}; sumber tidak konsisten")
    anchor = ov[-1]
    add = new.loc[new.index > old.index[-1]]
    if len(add):
        add = add / new.loc[anchor] * old.loc[anchor]
        old = pd.concat([old, add])
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    os.close(fd)
    old.rename("close").to_csv(tmp, index_label="date")
    os.replace(tmp, path)
    return old


if __name__ == "__main__":
    # usage: mode_a_engine.py update|plan <data_dir> [--mode A|B1|B2] [--state state.json]   (dry-run, tidak mengirim order)
    cmd, ddir = sys.argv[1], sys.argv[2]
    mode = sys.argv[sys.argv.index("--mode") + 1] if "--mode" in sys.argv else "A"
    syms = {"btc": "BTCUSDT", "eth": "ETHUSDT", "xaut": "XAUTUSDT"}
    if cmd == "update":
        for k, s in syms.items():
            r = update_history(os.path.join(ddir, f"{k}.csv"), s)
            print(k, r.index[-1].date(), len(r))
    elif cmd == "plan":
        res = latest_targets({k: load_csv(os.path.join(ddir, f"{k}.csv")) for k in syms}, mode=mode)
        if "--state" in sys.argv:
            st = json.load(open(sys.argv[sys.argv.index("--state") + 1]))
            res["plan"] = plan_orders(res["weights"], st["holdings"], st["prices"], st["cash_usd"])
        print(json.dumps(res, indent=2))
    else:
        raise SystemExit("perintah: update | plan")
