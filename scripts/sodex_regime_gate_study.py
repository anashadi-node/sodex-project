"""Studi prediktor REZIM ex-ante untuk track `twoway` SoDEX (Opsi 2).

LATAR (kenapa ini, bukan lagi filter entry)
-------------------------------------------
D07 membuktikan: edge LONG `twoway` bukan alpha, melainkan eksposur faktor
"alt mengalahkan BTC". Edge HIDUP di satu jendela (04-19 Sep, +62,96 bps) dan
MATI di periode terkini (19-Sep..03-Okt, -28,40 bps SEBELUM biaya).

Uji 12 filter ENTRY gagal semua. Karena itu pertanyaannya berubah:

    Bukan "entry seperti apa yang bagus?"     (filter)
    Tapi "rezim pasar seperti apa yang bagus?" (gate)

Bedanya penting:
  - FILTER menyaring trade di dalam rezim apa pun.
  - GATE mematikan seluruh mesin saat rezim tidak mendukung, lalu menyalakannya
    kembali saat mendukung. Gate memakai informasi PASAR, bukan informasi TRADE.

PREDIKTOR EX-ANTE = pengukur yang nilainya SUDAH DIKETAHUI SEBELUM trade dibuka,
tanpa memakai satu pun informasi dari masa depan. Aturan besi: setiap angka yang
masuk ke prediktor hanya boleh berasal dari data dengan cap waktu LEBIH AWAL
dari `entry_time`. Kalau tidak, kita bukan meramal -- kita mengintip jawaban.

KANDIDAT (DIDEKLARASIKAN DI MUKA -- jangan tambah setelah melihat hasil)
-----------------------------------------------------------------------
  K1  rs24      : (rata-rata return 21 alt, 24 jam terakhir) - (return BTC, 24 jam)
  K2  rs7d      : idem, jendela 7 hari
  K3  breadth24 : fraksi simbol dengan return 24 jam > 0
  K4  btcvol24  : volatilitas terealisasi BTC 15m selama 24 jam terakhir
  K5  btctrend  : BTC close / SMA200(jam) - 1

GERBANG YANG DIUJI (dideklarasikan di muka)
--------------------------------------------
  G1  rs24 > 0            -- alt sedang mengungguli BTC
  G2  rs7d > 0            -- idem, lebih lambat
  G3  breadth24 > 0,50    -- mayoritas pasar naik
  G4  btcvol24 < median   -- rezim tenang
  G5  btctrend > 0        -- BTC di atas SMA200

VALIDASI (pelajaran 2026-10-05, WAJIB >=3 segmen)
-------------------------------------------------
Gerbang LAYAK hanya bila subset yang diloloskannya mencapai cost 2x (16 bps)
POSITIF di KETIGA segmen waktu. Dua segmen tidak sah: dua potongan berdekatan
tidak menguji ketahanan rezim -- lihat skill `signal-gate-falsification`.

Penalti multiple-testing memakai `n_trials` (registry harness + 5 kandidat ini).

Read-only kecuali `--log` yang mencatat 5 trial ke registry.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import datetime as dt
import glob
import json
import math
import os
import re
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "docs/handover/RISET_TO_DIVISI_2026-10-01/harness"))

import sodex_harness_reeval as H  # noqa: E402

KLINE_DIR = os.path.join(ROOT, "data/trail_lab_klines")
HARI_MS = 86_400_000
BAR_MS = 900_000          # 15 menit
GATE_EDGE_BPS = 2 * H.SODEX_FEE_BPS   # 16 bps
MIN_N = 30


# --------------------------------------------------------------------------
# Pemuatan data
# --------------------------------------------------------------------------

def muat_kline() -> dict[str, tuple[list[int], list[float]]]:
    """{SIMBOL: (daftar_ts_ms, daftar_close)} dari kline 15m di trail_lab."""
    panel: dict[str, dict[int, float]] = collections.defaultdict(dict)
    for f in glob.glob(os.path.join(KLINE_DIR, "*.json")):
        m = re.match(r"([A-Z0-9]+USDT)_15m_", os.path.basename(f))
        if not m:
            continue
        sym = m.group(1)
        try:
            d = json.load(open(f))
        except Exception:
            continue
        for t, c in zip(d.get("t") or [], d.get("c") or []):
            panel[sym][int(t)] = float(c)
    out: dict[str, tuple[list[int], list[float]]] = {}
    for sym, d in panel.items():
        ts = sorted(d)
        out[sym] = (ts, [d[k] for k in ts])
    return out


def ret_n(ts: list[int], cl: list[float], t_ms: int, jendela_ms: int) -> float | None:
    """Return dari bar TERAKHIR YANG SUDAH SELESAI sebelum t_ms, ke belakang jendela_ms.

    HANYA memakai bar dengan cap waktu < t_ms -> tidak ada look-ahead.
    """
    i = bisect.bisect_left(ts, t_ms) - 1        # bar terakhir sebelum t_ms
    if i < 1:
        return None
    j = bisect.bisect_left(ts, ts[i] - jendela_ms)
    if j >= i:
        return None
    # Jendela harus BENAR-BENAR terpenuhi. Tanpa ini, saat warm-up sebuah return
    # 15 menit akan dilabeli "24 jam" (atau "7 hari") -- angka yang tampak sah
    # tetapi artinya salah, dan ia bocor ke prediktor sebagai sinyal palsu.
    if (ts[i] - ts[j]) < 0.8 * jendela_ms:
        return None
    p0, p1 = cl[j], cl[i]
    if p0 <= 0:
        return None
    return p1 / p0 - 1.0


def vol_n(ts: list[int], cl: list[float], t_ms: int, jendela_ms: int) -> float | None:
    """Simpangan baku return bar di dalam jendela, memakai bar sebelum t_ms saja."""
    i = bisect.bisect_left(ts, t_ms) - 1
    if i < 3:
        return None
    j = bisect.bisect_left(ts, ts[i] - jendela_ms)
    if j >= i or (ts[i] - ts[j]) < 0.8 * jendela_ms:
        return None                              # jendela belum terpenuhi (warm-up)
    win = cl[j:i + 1]
    if len(win) < 3:
        return None
    r = [win[k] / win[k - 1] - 1.0 for k in range(1, len(win)) if win[k - 1] > 0]
    return statistics.pstdev(r) if len(r) >= 2 else None


def fitur_ex_ante(t_ms: int, panel: dict[str, tuple[list[int], list[float]]]) -> dict[str, float | None]:
    """Hitung 5 kandidat, SEMUA dari bar dengan cap waktu < t_ms."""
    btc = panel.get("BTCUSDT")
    btc24 = ret_n(*btc, t_ms, HARI_MS) if btc else None
    btc7d = ret_n(*btc, t_ms, 7 * HARI_MS) if btc else None

    alt = [s for s in panel if s not in ("BTCUSDT", "XAUTUSDT")]   # XAUT = emas, bukan alt crypto
    r24 = [x for s in alt if (x := ret_n(*panel[s], t_ms, HARI_MS)) is not None]
    r7d = [x for s in alt if (x := ret_n(*panel[s], t_ms, 7 * HARI_MS)) is not None]

    rs24 = (statistics.fmean(r24) - btc24) if (r24 and btc24 is not None) else None
    rs7d = (statistics.fmean(r7d) - btc7d) if (r7d and btc7d is not None) else None
    breadth = (sum(1 for x in r24 if x > 0) / len(r24)) if r24 else None
    bvol = vol_n(*btc, t_ms, HARI_MS) if btc else None

    trend = None
    if btc:
        ts, cl = btc
        i = bisect.bisect_left(ts, t_ms) - 1
        if i >= 200:
            sma = statistics.fmean(cl[i - 199:i + 1])
            if sma > 0:
                trend = cl[i] / sma - 1.0

    return {"rs24": rs24, "rs7d": rs7d, "breadth24": breadth, "btcvol24": bvol, "btctrend": trend}


# --------------------------------------------------------------------------
# Evaluasi
# --------------------------------------------------------------------------

def edge(sub: list[dict], candles, n_trials: int) -> dict | None:
    """Evaluasi subset lewat harness beku."""
    if len(sub) < MIN_N:
        return None
    try:
        g, res = H.evaluate(
            returns=[H.trade_return(r) for r in sub],
            market=H.btc_market_returns(sub, candles),
            sides=[H.side_sign(r) for r in sub],
            fee_bps=H.SODEX_FEE_BPS,
            n_trials=n_trials,
            groups=[H.trade_symbol(r) for r in sub],
            periods_per_year=365,
            min_n=MIN_N,
        )
    except Exception:
        return None
    cs = res.get("cost_stress", {})
    return {
        "n": len(sub),
        "wr": res.get("wr", 0.0),
        "edge": res.get("excess_mean", 0.0) * 1e4,
        "cost2x": cs.get("2.0", {}).get("mean", 0.0) * 1e4,
        "passed": bool(g.get("passed")) if g else False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", action="store_true", help="catat 5 trial ke registry harness")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dev = "-dev" if args.dry_run else ""
    os.chdir(ROOT)
    print(f"sumber kline: {KLINE_DIR}{dev}")

    panel = muat_kline()
    print(f"  simbol termuat: {len(panel)}  (contoh: {sorted(panel)[:6]})")

    lo = [r for r in H.closed_rows(H.TRACKS["twoway"])
          if H.arm_of(r) == H.ARM_SIGNAL and H.side_sign(r) == 1]
    lo = [r for r in lo if H.trade_symbol(r) in {s.replace("USDT", "") for s in panel}]
    print(f"  trade LONG dgn kline: {len(lo)}")

    # --- fitur ex-ante per trade ---
    for r in lo:
        t = H.parse_dt(r.get("entry_time"))
        r["_f"] = fitur_ex_ante(int(t.timestamp() * 1000), panel)

    ada = [r for r in lo if r["_f"]["rs24"] is not None]
    print(f"  trade dgn fitur lengkap: {len(ada)}")

    semua = [x for r in lo for x in r["_f"].values() if x is not None]
    print(f"  sinyal fitur tersedia : {len(semua)} nilai")

    candles = H.fetch_btc_1h(dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
                             dt.datetime.now(dt.timezone.utc))
    n_trials = 11 + 5

    # --- gerbang (dideklarasikan di muka) ---
    med_vol = statistics.median([r["_f"]["btcvol24"] for r in ada if r["_f"]["btcvol24"] is not None])
    gerbang = [
        ("G1 rs24>0", lambda f: (f["rs24"] or 0) > 0),
        ("G2 rs7d>0", lambda f: (f["rs7d"] or 0) > 0),
        ("G3 breadth24>0,50", lambda f: (f["breadth24"] if f["breadth24"] is not None else 0) > 0.50),
        ("G4 btcvol24<median", lambda f: (f["btcvol24"] if f["btcvol24"] is not None else 9e9) < med_vol),
        ("G5 btctrend>0", lambda f: (f["btctrend"] or 0) > 0),
    ]

    # --- tiga segmen waktu ---
    srt = sorted(ada, key=lambda r: str(r.get("entry_time") or ""))
    n3 = len(srt) // 3
    blok = [("S1", srt[:n3]), ("S2", srt[n3:2 * n3]), ("S3", srt[2 * n3:])]

    base = edge(ada, candles, n_trials)
    print()
    print("BASELINE (semua LONG, tanpa gerbang):")
    if base:
        print(f"  n={base['n']} WR={base['wr']*100:.1f}% edge={base['edge']:+.2f} "
              f"cost2x={base['cost2x']:+.2f}")
    print()
    print(f"{'gerbang':<22}{'n':>5}{'WR':>7}{'edge':>9}{'cost2x':>9}  S1/S2/S3 cost2x")
    print("-" * 78)

    layak = []
    for nama, fn in gerbang:
        sub = [r for r in ada if fn(r["_f"])]
        m = edge(sub, candles, n_trials)
        if m is None:
            print(f"{nama:<22}{len(sub):>5}   (n<{MIN_N}, dilewati)")
            continue
        seg = [edge([r for r in b if fn(r["_f"])], candles, n_trials) for _, b in blok]
        tanda = "/".join("-" if x is None else ("OK" if x["cost2x"] > 0 else "no") for x in seg)
        ok = m["cost2x"] > 0 and all(x is not None and x["cost2x"] > 0 for x in seg)
        if ok:
            layak.append(nama)
        print(f"{nama:<22}{m['n']:>5}{m['wr']*100:>6.1f}%{m['edge']:>9.2f}"
              f"{m['cost2x']:>9.2f}  {tanda} {'LAYAK' if ok else ''}")

    # --- komplemen G4 (rezim bergejolak) sbg kontrol arah ---
    print()
    print("KOMPLEMEN (kondisi KEBALIKAN) -- diuji dgn aturan 3 segmen yg sama:")
    print(f"{'komplemen':<24}{'n':>5}{'WR':>7}{'edge':>9}{'cost2x':>9}  S1/S2/S3 cost2x")
    print("-" * 78)
    lawan_layak = []
    for nama, fn in gerbang:
        sub = [r for r in ada if not fn(r["_f"])]
        m = edge(sub, candles, n_trials)
        if m is None:
            print(f"  bukan-{nama:<19}{len(sub):>5}   (n<{MIN_N}, dilewati)")
            continue
        seg = [edge([r for r in b if not fn(r["_f"])], candles, n_trials) for _, b in blok]
        tanda = "/".join("-" if x is None else ("OK" if x["cost2x"] > 0 else "no") for x in seg)
        ok = m["cost2x"] > 0 and all(x is not None and x["cost2x"] > 0 for x in seg)
        if ok:
            lawan_layak.append("bukan-" + nama)
        print(f"  bukan-{nama:<19}{m['n']:>5}{m['wr']*100:>6.1f}%{m['edge']:>9.2f}"
              f"{m['cost2x']:>9.2f}  {tanda} {'LAYAK' if ok else ''}")

    print()
    if layak:
        print(f"LAYAK (cost2x>0 di KETIGA segmen): {layak}")
    else:
        print("LAYAK: TIDAK ADA. Tidak ada gerbang rezim ex-ante yang bertahan di KETIGA segmen.")
        print("-> Track ini tetap tidak layak dipromosikan. Jangan pasang gate palsu.")
    if lawan_layak:
        print()
        print("PERHATIAN: komplemen lolos 3 segmen -> " + ", ".join(lawan_layak))
        print("   Arah gerbang TERBALIK dari hipotesis. Sebelum dipakai: wajib tambah")
        print("   kandidat ini ke n_trials (hipotesis baru = trial baru) dan uji ulang.")
    else:
        print("-> Komplemen juga tidak ada yang lolos 3 segmen.")

    if args.log and not args.dry_run:
        reg = H.TrialRegistry(str(H.TRIAL_REGISTRY_PATH))
        for nama, fn in gerbang:
            sub = [r for r in ada if fn(r["_f"])]
            m = edge(sub, candles, n_trials)
            H.log_trial(reg, strategy=f"twoway_gate_{nama.split()[0]}",
                        passed=bool(m and m["cost2x"] > 0), note="SoDEX regime gate study",
                        n=len(sub), reasons=[f"cost2x_positive({name_hint(nama)})"])
        print(f"-> 5 trial dicatat ke {H.TRIAL_REGISTRY_PATH.name}")
    return 0


def name_hint(nama: str) -> str:
    return nama.split()[0]


if __name__ == "__main__":
    raise SystemExit(main())
