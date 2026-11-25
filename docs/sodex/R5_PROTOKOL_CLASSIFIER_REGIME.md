# R5 — PROTOKOL BEKU: PERBANDINGAN 5 CLASSIFIER REGIME (gate arah)

**Dibekukan:** 10-Okt-2026, SEBELUM runner dijalankan
**Sifat:** read-only. TANPA order, TANPA perubahan track/threshold/flag live.
**Alasan ada:** R4 (2 kondisi: ret24 + SMA72) terlalu kasar — label retrospektif Okt: gate G1 membuang 74 LONG non-BULL yang justru WR 31,1% vs kept 23,5% (ΔWR −6,3 pp). R5 menggantinya dengan **beberapa classifier mekanis yang lebih kaya**, dibandingkan dalam satu kerangka dengan koreksi multiplicity.

## Sumber data (terverifikasi ada)

- `data/sodex_klines/1h/BTC-USD.json` — 8.585 bar (12-Okt-2025 → 09-Okt-2026), field `bars`.
- `data/sodex_klines/1d/BTC-USD.json` — 363 bar.
- `data/sodex_klines/1h/*.json` — **92 simbol segar** (≥ 9-Okt) → dipakai untuk breadth.
- Trade: 7 berkas `data/paper_test_*_state.json` (set yang sama dengan R3/R4).

Semua perhitungan memakai **bar yang sudah TUTUP sebelum waktu entry** (tanpa look-ahead).

## 5 arm (parameter bulat/standar — DILARANG dituning)

| Arm | Definisi "risk-on" (LONG boleh) | Parameter |
|---|---|---|
| **RF0** | BTC 1h: ret24 > 0 **dan** c > SMA72 (baseline R4) | 24/72 |
| **RF1** | BTC 1h: c > SMA72 **dan** ATR%24 ≤ p80 dari 720 bar terakhir | 72 / 24 / 720 |
| **RF2** | BTC 1h: **Efficiency Ratio** (Kaufman) ER24 ≥ 0,35 — ER = \|c_t−c_{t−24}\| / Σ\|Δc\| | 24 / 0,35 |
| **RF3** | **Breadth**: porsi universe (92 simbol) dengan c > SMA72 sendiri ≥ 50% | 72 / 50% |
| **RF4** | BTC 1d: c > SMA20 **dan** SMA20 naik (SMA20_d > SMA20_{d−5}) | 20 / 5 |

Semantik gate tiap arm: **buang LONG saat risk-off**, **buang SHORT saat risk-on**. Hanya PENGHAPUSAN — tidak ada trade baru dikarang (memperbanyak SHORT = mesin baru, bukan gate).

## Kriteria keputusan (beku)

Jendela verdict = **forward murni**: entry ≥ **2026-10-11T00:00Z**.

Per arm, semua harus terpenuhi:
1. `n_kept ≥ 40`
2. `WR_kept ≥ 45,0%`
3. `ΔWR(kept − dropped) ≥ +5,0 pp`
4. uji binomial satu-sisi vs baseline train 40,9% → `p < 0,05`
5. **koreksi Holm-Bonferroni** atas K = 5 arm: p terkecil harus < 0,0100; berikutnya < 0,0125; berikutnya < 0,0167; berikutnya < 0,025; terakhir < 0,05
6. WR_kept > WR arm **RANDOM** pada jendela yang sama (ΔWR > 0)

**Pemenang** = arm dengan p terkecil yang lolos SEMUA butir. **Tidak ada yang lolos → R5 GAGAL.**

Sekunder (dilaporkan, BUKAN syarat): metrik window resmi 30 jam pada subset kept (TWOWAY-only, wallet 242,79); dinyatakan *underpowered* bila < 8 window.

## Disiplin (anti optional-stopping & anti p-hunting)

- Verdict diambil **SEKALI**: saat kalender ≥ **31-Okt-2026** DAN `n_kept ≥ 40` pada arm terbaik. Bila per **30-Nov-2026** belum tercapai → **TIDAK KONKLUSIF** (bukan lolos).
- Setelah beku: **tidak ada** penambahan arm, penggantian ambang, atau penggantian sumber data. Perubahan apa pun = protokol baru (R6) dengan trial tercatat.
- Monitor harian bersifat operasional, **bukan** dasar keputusan dini.
- Periode 1–10 Okt sudah terlihat di R3C → dilaporkan sebagai **label deskriptif**, bukan verdict. Train (≤30-Sep) juga deskriptif.
- 5 arm berbagi data yang sama → korelasi antar-arm diakui; Holm menangani multiplicity, dan itu sebabnya ambang arm terbaik diperketat ke p < 0,01.

## Batas yang diakui

1. Gate hanya bisa membuang; upside maksimum = menghindari kerugian, bukan menambah profit.
2. ER/breadth/daily-SMA adalah proxy regime, bukan kebenaran; semuanya bisa salah label saat pasar transisi.
3. Forward window pendek (mulai 11-Okt) → bila n_kept tidak mencapai 40, hasil = tidak konklusif.
4. Tidak mengubah target 0,8%, tidak mengubah SL/TP/leverage, tidak menyalakan order.

*Protokol beku · Hermes Anantara v3 · 10-Okt-2026*
