#!/usr/bin/env python3
"""PRAREG-23 H2 — satelit funding carry SoDEX: evaluasi + vonis.

Data: data/sodex_funding/funding_rates_history.jsonl (derivasi poll snapshot SoDEX).
Aturan gerbang H2 dibekukan di docs/sodex/PRAREG_23_TREN_HARIAN.md:
  lolos bila funding neto > 0 di >=70% jendela, tahunan neto >=5%, basis merugikan <1%,
  dengan >=20 jendela independen 5 hari. Kurang dari itu -> TIDAK KONKLUSIF.
"""
import json, os, statistics as st, datetime as dt
from collections import defaultdict

P = "data/sodex_funding/funding_rates_history.jsonl"
ROUND_TRIP_BPS = 9.4          # 4 kaki, semua maker (rekomendasi §5)
SATELLITE_SHARE = 0.20        # batas satelit
CORE = ["BTC", "ETH", "SOL", "XAUT", "BNB", "LINK", "XRP"]

rows = [json.loads(l) for l in open(P) if l.strip()]
by = defaultdict(list)
for r in rows:
    if r.get("funding_rate_bps") is not None:
        by[r["symbol"]].append(r)

out = {}
for s, v in by.items():
    bps = sorted(float(x["funding_rate_bps"]) for x in v)
    ts = sorted(int(x["funding_time_ms"]) for x in v if x.get("funding_time_ms"))
    med = st.median(bps)
    p10, p90 = bps[int(0.10 * len(bps))], bps[int(0.90 * len(bps))]
    # dua bacaan interval, keduanya dilaporkan (interval funding SoDEX tidak terverifikasi)
    ann_hourly = med / 100.0 * 8760 / 100.0 * 100      # % per tahun bila baris = per jam
    ann_8h = med / 100.0 * 3 * 365                      # % per tahun bila baris = rate 8 jam
    be_h = (ROUND_TRIP_BPS / med) if med > 0 else None  # jam untuk balik modal biaya
    out[s] = {"n": len(v), "median_bps": med, "p10_bps": p10, "p90_bps": p90,
              "min_bps": bps[0], "max_bps": bps[-1],
              "pct_positif": 100.0 * sum(1 for x in bps if x > 0) / len(bps),
              "annual_pct_jam": ann_hourly, "annual_pct_8j": ann_8h,
              "breakeven_jam": be_h,
              "pertama_utc": dt.datetime.fromtimestamp(ts[0] / 1000, dt.timezone.utc).isoformat() if ts else None,
              "terakhir_utc": dt.datetime.fromtimestamp(ts[-1] / 1000, dt.timezone.utc).isoformat() if ts else None}

ks = sorted({int(r["funding_time_ms"]) for r in rows if r.get("funding_time_ms")})
span_h = (ks[-1] - ks[0]) / 3600000.0
windows_5d = span_h / 120.0
n_sym = len(by)

# ceiling satelit: sumbu terbaik = simbol dgn median positif tertinggi
top = sorted([s for s in out if out[s]["median_bps"] > 0], key=lambda s: -out[s]["median_bps"])[:10]


def sat_contrib(sym, ann_key):
    """Kontribusi ke TOTAL wallet (%/48j): tahunan x (2/365) x porsi satelit."""
    return out[sym][ann_key] * 2 / 365.0 * SATELLITE_SHARE


hasil = {
    "protokol": "PRAREG-23-H2-v1",
    "sumber": P,
    "jumlah_baris": len(rows), "jumlah_simbol": n_sym,
    "rentang_utc": [dt.datetime.fromtimestamp(ks[0] / 1000, dt.timezone.utc).isoformat(),
                    dt.datetime.fromtimestamp(ks[-1] / 1000, dt.timezone.utc).isoformat()],
    "span_hari": round(span_h / 24, 2),
    "jendela_5hari_independen": round(windows_5d, 2),
    "ambang_jendela": 20,
    "vonis": "TIDAK KONKLUSIF" if windows_5d < 20 else "DAPAT DINILAI",
    "biaya_putaran_bps": ROUND_TRIP_BPS, "bagian_satelit": SATELLITE_SHARE,
    "per_simbol": out,
    "top10_median": top,
    "batas_atas_kontribusi_satelit_pct_48j": {
        "bacaan_jam_terbaik": round(sat_contrib(top[0], "annual_pct_jam"), 4),
        "bacaan_8j_terbaik": round(sat_contrib(top[0], "annual_pct_8j"), 4),
        "bacaan_jam_inti_BTC": round(sat_contrib("BTC", "annual_pct_jam"), 4),
        "bacaan_8j_inti_BTC": round(sat_contrib("BTC", "annual_pct_8j"), 4),
    },
    "lantai_tangga_pct_48j": 0.10,
}
os.makedirs("reports/sodex", exist_ok=True)
json.dump(hasil, open("reports/sodex/PRAREG23_H2_HASIL.json", "w"), indent=1)

print(f"baris {len(rows)} | simbol {n_sym} | span {span_h/24:.2f} hari | jendela 5-hari {windows_5d:.2f}")
print(f"VONIS: {hasil['vonis']} (butuh >=20 jendela)")
print(f"\n{'simbol':10s} {'n':>5s} {'median bps/j':>13s} {'%pos':>6s} {'thn(jam)':>9s} {'thn(8j)':>8s} {'balik modal':>11s}")
for s in sorted(out, key=lambda x: -out[x]["median_bps"])[:14]:
    d = out[s]
    be = f"{d['breakeven_jam']:.0f} jam" if d["breakeven_jam"] else "-"
    print(f"{s:10s} {d['n']:5d} {d['median_bps']:+13.4f} {d['pct_positif']:5.1f}% {d['annual_pct_jam']:8.2f}% {d['annual_pct_8j']:7.2f}% {be:>11s}")
print("\ninti (yang direncanakan):")
for s in CORE:
    if s in out:
        d = out[s]
        print(f"{s:10s} median {d['median_bps']:+.4f} bps -> thn {d['annual_pct_jam']:.2f}% (jam) / {d['annual_pct_8j']:.2f}% (8j) | %positif {d['pct_positif']:.1f}%")
print("\nBATAS ATAS kontribusi satelit (20% modal) ke wallet:")
c = hasil["batas_atas_kontribusi_satelit_pct_48j"]
for k, v in c.items():
    print(f"  {k:28s} {v:+.4f}%/48j  (lantai = 0,10%/48j -> {0.10/abs(v) if v else float('inf'):.1f}x terlalu kecil)")
print(f"\nbiaya 1 putaran (4 kaki maker) = {ROUND_TRIP_BPS} bps notional = {ROUND_TRIP_BPS*SATELLITE_SHARE/100:.4f}% wallet per siklus")
