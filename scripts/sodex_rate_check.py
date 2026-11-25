#!/usr/bin/env python3
"""Verifikasi laju onset F3 vs falsifier (READ-ONLY, dapat dijalankan ulang).

Konteks: docs/sodex/SODEX_LAJU_EPISODE_RISET_2026-10-07.md §6. Tuas perluasan cakupan
OBI 20 -> 92 (commit a9ec461) dipasang 07-Okt-2026. Script ini mengukur funnel F3 dan
MEMBANDINGKANNYA dgn ambang yang sudah ditetapkan lebih dulu:

    [3] >= 2,3 onset/hari  -> CUKUP   (proyeksi >=100 episode dalam 44 hari)
    1,0 .. 2,3 /hari       -> BELUM CUKUP
    [3] <  1,0 onset/hari  -> GAGAL   (falsifier terpenuhi: tuas tidak bekerja)

Aturan metode: hitung laju HANYA pada rentang saat cakupan OBI sudah penuh (dideteksi dari
data, bukan diasumsikan) -- jendela campuran menggelembungkan/menyesatkan laju. Event funding
di-dedup per funding_time (satu settlement = satu event), karena collector menulis beberapa
baris per settlement.

READ-ONLY: hanya membaca file data. Tidak menyentuh gate/ambang/posisi.

Pakai: python3 scripts/sodex_rate_check.py [--since YYYYMMDD]
"""
from __future__ import annotations
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sodex_prereg_f3 as f3  # noqa: E402

COVER_FRAC = 0.8          # cakupan dianggap "penuh" bila >=80% simbol punya baris dalam 1 jam
TARGET_RATE, FAIL_RATE = 2.3, 1.0
DAYS_LEFT_REF = 44        # 07-Okt -> 20-Nov (HARD_STOP)


def coverage_start(obi, frac=COVER_FRAC):
    """ts pertama (detik) saat >=frac*total simbol punya minimal 1 baris OBI di jam itu."""
    need = frac * len(obi)
    per_hour = defaultdict(set)
    for s, rows in obi.items():
        for ts, *_ in rows:
            per_hour[int(ts // 3600)].add(s)
    for h in sorted(per_hour):
        if len(per_hour[h]) >= need:
            return h * 3600
    return None


def stages(frows, obi_rows, t_lo):
    """Funnel per simbol: [1] funding lolos, [2] + OBI tersedia, [3] + OBI selaras (onset)."""
    oti = [x[0] for x in obi_rows]
    s1 = s2 = s3 = 0
    seen_ft, lastfire = set(), -10**9
    for ts, fr, fts in frows:
        if ts < t_lo or abs(fr) < f3.FUNDING_THR or fts in seen_ft:
            continue
        seen_ft.add(fts)
        s1 += 1
        i = bisect_right(oti, ts) - 1
        if i < 0:
            continue
        s2 += 1
        _, o20, mid0 = obi_rows[i]
        side = "sell" if fr > 0 else "buy"
        aligned = (side == "sell" and o20 < -f3.OBI_THR) or (side == "buy" and o20 > f3.OBI_THR)
        if aligned and mid0 > 0 and ts - lastfire >= f3.GAP_S:
            s3 += 1
            lastfire = ts
    return s1, s2, s3


def main(argv):
    if "--since" in argv:
        t_lo = datetime.strptime(argv[argv.index("--since") + 1], "%Y%m%d").replace(
            tzinfo=timezone.utc).timestamp()
        how = "manual (--since)"
    else:
        t_lo, how = None, "otomatis (deteksi cakupan penuh)"
    fund = f3.load_funding()
    obi, _ = f3.load_obi_tape(20261002)
    if not fund or not obi:
        print("GAGAL: data funding/OBI tidak terbaca.")
        return 1
    if t_lo is None:
        t_lo = coverage_start(obi)
        if t_lo is None:
            print(f"GAGAL: cakupan OBI belum pernah mencapai {COVER_FRAC:.0%} simbol.")
            return 1
    t_hi = max(r[-1][0] for r in obi.values() if r)
    span_d = (t_hi - t_lo) / 86400.0
    tot = [0, 0, 0]
    per_sym = {}
    for sym, frows in fund.items():
        if sym not in obi or not obi[sym]:
            continue
        a, b, c = stages(frows, obi[sym], t_lo)
        per_sym[sym] = (a, b, c)
        tot[0] += a
        tot[1] += b
        tot[2] += c
    print(f"[F3 LAJU] jendela = {datetime.fromtimestamp(t_lo, timezone.utc):%Y-%m-%d %H:%M} "
          f".. {datetime.fromtimestamp(t_hi, timezone.utc):%Y-%m-%d %H:%M} UTC  ({span_d:.2f} hari)")
    print(f"          mulai   = {how} | simbol dinilai = {len(per_sym)}")
    if span_d < 0.5:
        print("          PERINGATAN: jendela < 0,5 hari -> laju belum stabil (n terlalu kecil).")
    print(f"  [1] funding lolos        = {tot[0]:5d}  ({tot[0] / span_d:5.2f}/hari)")
    print(f"  [2] + OBI tersedia       = {tot[1]:5d}  ({tot[1] / span_d:5.2f}/hari)")
    print(f"  [3] + OBI selaras (onset)= {tot[2]:5d}  ({tot[2] / span_d:5.2f}/hari)")
    rate = tot[2] / span_d if span_d > 0 else 0.0
    proj = rate * DAYS_LEFT_REF
    print(f"  proyeksi {DAYS_LEFT_REF} hari ke HARD_STOP {f3.HARD_STOP} = ~{proj:.0f} "
          f"episode (butuh {f3.N_EP_MIN})")
    if rate >= TARGET_RATE:
        v = "CUKUP"
    elif rate >= FAIL_RATE:
        v = "BELUM CUKUP"
    else:
        v = "GAGAL (falsifier terpenuhi)"
    print(f"  ==> VERDICT LAJU: {v}  (ambang: >= {TARGET_RATE}/hari cukup; "
          f"< {FAIL_RATE}/hari gagal)")
    if per_sym:
        top = sorted(per_sym.items(), key=lambda kv: -kv[1][2])[:5]
        print("  kontributor onset teratas: " + ", ".join(f"{s}={c[2]}" for s, c in top if c[2]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
