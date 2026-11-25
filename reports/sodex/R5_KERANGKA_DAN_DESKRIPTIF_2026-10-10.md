# R5 — KERANGKA 5 CLASSIFIER REGIME + HASIL DESKRIPTIF AWAL

**Tanggal:** 10-Okt-2026 · **Sifat:** read-only, tanpa order
**Protokol beku:** `docs/sodex/R5_PROTOKOL_CLASSIFIER_REGIME.md` sha256 `3c8eb224d6bf385c…` (commit `eb18998`, dibekukan SEBELUM runner)
**Runner:** `scripts/research/r5_regime_classifiers.py` sha256 `d18965c58faec971…` · **Universe breadth:** 95 simbol (`data/sodex_klines/1h`)
**Keluaran:** `reports/sodex/R5_MONITOR.json` + `R5_MONITOR.md` (log harian) · timer `sodex-r5-monitor.timer` (08:20 WIB)

## Arm yang diuji (semua mekanis, parameter bulat, dilarang dituning)

| Arm | Definisi risk-on | Sumber |
|---|---|---|
| RF0 | BTC 1h ret24 > 0 **dan** c > SMA72 (baseline R4) | BTC 1h |
| RF1 | BTC 1h c > SMA72 **dan** ATR%24 ≤ p80 dari 720 bar | BTC 1h |
| RF2 | Efficiency Ratio (Kaufman) ER24 ≥ 0,35 | BTC 1h |
| RF3 | breadth: ≥50% universe di atas SMA72 sendiri | 95 simbol 1h |
| RF4 | BTC 1d: c > SMA20 **dan** SMA20 naik 5 hari | BTC 1d |

## Hasil deskriptif (BUKAN verdict — jendela sudah terlihat)

**TRAIN ≤ 30-Sep** (sinyal n=1612, WR 41,2%):

| arm | kept n | WR kept | WR dropped | ΔWR | p |
|---|---|---|---|---|---|
| RF0 | 847 | 39,79% | 42,75% | **−2,96 pp** | 0,756 |
| RF1 | 835 | 42,63% | 39,64% | +2,99 pp | 0,162 |
| RF2 | 375 | 42,40% | 40,82% | +1,58 pp | 0,294 |
| RF3 | 1147 | 41,59% | 40,22% | +1,37 pp | 0,328 |
| RF4 | 1146 | 37,61% | 50,00% | **−12,39 pp** | 0,989 |

**SEEN 1–10 Okt** (sinyal n=236, WR 25,4%; kontrol RANDOM 19,4%):

| arm | kept n | WR kept | WR dropped | ΔWR |
|---|---|---|---|---|
| RF0 | 162 | 23,46% | 29,73% | −6,27 pp |
| RF1 | 206 | 27,18% | 13,33% | **+13,85 pp** |
| RF2 | 65 | 20,00% | 27,49% | −7,49 pp |
| RF3 | 192 | 22,92% | 36,36% | −13,44 pp |
| RF4 | 232 | 25,86% | 0,00% | +25,86 pp (hanya 4 trade dibuang) |

**FWD ≥ 11-Okt:** 0 trade → verdict **BELUM DIAMBIL** (dikunci: kalender ≥ 31-Okt **dan** n_kept ≥ 40).

## Bacaan jujur

1. **Tidak ada satu pun arm yang menaikkan WR secara meyakinkan** di dua jendela deskriptif. Yang tertinggi di train hanya +2,99 pp (RF1, p=0,162) — jauh dari signifikan.
2. **RF0 (classifier R4) sudah merugikan bahkan di train** (−2,96 pp) — ini *membenarkan* kegagalan R4 yang ditemukan lewat label retrospektif, dari sisi lain.
3. **RF4 (arah harian) paling berbahaya**: kept 37,61% vs dropped 50,00% di train — aturan tren harian justru menandai "risk-on" tepat sebelum long kalah.
4. RF1 (SMA72 + filter volatilitas) satu-satunya yang arahnya konsisten positif di kedua jendela (+3,0 pp train, +13,9 pp seen) — tapi **p=0,16 di train** dan di jendela seen WR absolutnya 27,2% (jauh di bawah baseline) → **bukan bukti, hanya petunjuk lemah**.
5. Implikasi: hipotesis "WR bisa dinaikkan lewat gate regime sederhana" **tidak didukung** oleh data yang ada. Jendela forward tetap akan memutuskan sesuai protokol — tetapi ekspektasi jujurnya negatif.

## Catatan teknis

- Perbaikan bug: `binom_onesided` semula memakai `math.comb` → overflow pada n besar; diganti implementasi log-space (`lgamma`). **Nilai matematis identik**; juga dipatch di runner R4. Nilai R4 lama tidak berubah (G1 p=1,000).
- Metrik window TWOWAY pada subset kept sangat underpowered (nw 2–3 di jendela 10 hari) → dilaporkan, bukan syarat.
- `kept n` yang lebih kecil berarti lebih banyak trade dibuang (dianggap melawan regime).

*Laporan · Hermes Anantara v3 · 10-Okt-2026*

---

## KOREKSI PASCA-AUDIT (10-Okt, `reports/sodex/AUDIT_R3_R5_2026-10-10.md`)

1. **De-duplikasi + entry-time**: tabel di atas memakai 1 baris duplikat (spot_swing_v2) dan 40 baris tanpa entry-time. Angka kept yang benar: **RF0 161 · RF1 205 · RF2 65 · RF3 191 · RF4 232** (sebelumnya 162/206/65/192/232). Kesimpulan **tidak berubah** (RF1 tetap satu-satunya positif: +13,5 pp; RF0 tetap negatif: −6,75 pp).
2. **Metrik window diperbaiki**: grid kini **tetap** (jangkar 2026-08-03Z) dan window kosong **dilewati** (sebelumnya dihitung 0,0% → median bias ke 0). Karena itu kolom window berubah nyata, mis. train RF0 kept **nw=40 median +1,063%** (dulu 0,000). Ditambah metrik **gaya-tracker** (grid span, kosong=0%) agar sebanding dengan gate resmi.
3. **RF1 dirapikan**: data kurang → `None` (tidak digate, konsisten semua arm); p80 volatilitas kini dari **720 bar sebelum** bar berjalan (ex-ante murni).
4. Tidak ada ambang, kriteria, atau jendela verdict yang diubah.

