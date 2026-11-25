# PRAREG-28 — MOMENTUM CROSS-SECTIONAL MARKET-NEUTRAL (LONG TOP / SHORT BOTTOM)

**Dibekukan:** 22-Okt-2026, SEBELUM skrip evaluasi ditulis/dijalankan · **Sifat:** READ-ONLY, backtest historis, tanpa order, tanpa posisi, tanpa flag live.
**Alasan dijalankan:** `PRAREG_25_HASIL_PENUTUPAN.md` §9 menyatakan keluarga trend-following long-only HABIS dan merekomendasikan keluarga **struktural berbeda** — kandidat #3: *"cross-sectional momentum relatif (long top-N / short bottom-N, market-neutral — bukan long-only)"*. Ini eksekusi kandidat itu.
**Keputusan user:** 22-Okt-2026, "Approve dan jalankan Opsi 2 + 3 secara bersamaan" (Opsi 3 = mulai riset mekanisme baru).
**Hash dokumen ini:** dicatat di `PRAREG_28_MOMENTUM_CROSS_SECTIONAL.md.sha256` segera setelah teks ini beku, SEBELUM skrip ditulis.

---

## 1. Hipotesis (ditulis sebelum data diproses untuk sinyal ini)

**H1:** Strategi relative cross-sectional momentum — ranking return K-hari antar simbol, long kuartil teratas, short kuartil terbawah, dollar-neutral — pada universe yang sama dengan PRAREG-24/25 (top-20 likuid, rebalance bulanan) menghasilkan Sharpe tahunan **positif signifikan** (lolos gerbang e & g di bawah) dengan **maxDD absolut jauh lebih kecil** dari keluarga trend-following long-only (karena net eksposur pasar ≈0), dan %/48 jam mendekati atau melewati **lantai tangga 0,10%** (bukan 0,8% penuh — tangga diadopsi 22-Okt, lihat `AMANDEMEN_TANGGA_TARGET_RESMI_2026-10-22.md`).

**H1b (lebih lemah, jujur diprediksi lebih mungkin benar):** Sharpe positif tapi %/48j masih di bawah lantai 0,10% — konsisten dengan pola "koreksi struktural menurunkan risiko lebih cepat daripada menaikkan return" yang sudah terlihat di PRAREG-24 (V2: maxDD turun ke −22,6% tapi %/48j juga hanya 0,138%).

## 2. Data (sudah ada, dibuat 09-Okt-2026 untuk PRAREG-25 — dipakai ulang, bukan dikumpulkan setelah lihat hasil sinyal ini)

- Sumber: `data/prereg25/*_1d.json` — 66 simbol Binance spot USDT, 1d, 2017-08-17 → terbaru tersedia (≈2026-10-09+).
- **Jendela terverifikasi:** `≤ 2025-10-09` (sama batas dengan PRAREG-24/25, agar dapat dibandingkan apple-to-apple).
- **Jendela ekstensi** (`> 2025-10-09`, tidak terverifikasi independen): dilaporkan terpisah, tidak dipakai untuk vonis gerbang.
- **Universe bulanan:** identik logika PRAREG-25 `build_universe()` — top-20 berdasar median dollar-volume 30 hari, rebalance tiap ganti bulan. **Tidak dibangun ulang dari nol** — mengimpor fungsi yang sama untuk menjamin universe identik (bukan sumber perbedaan hasil).

## 3. Sinyal (BEKU — dilarang diubah setelah melihat hasil)

Pada setiap hari **t** dengan universe bulan itu `U_t` (20 simbol):

1. Untuk setiap simbol `s ∈ U_t` yang eligible (index ≥ `K + WARMUP`, WARMUP=360 hari sama seperti PRAREG-25), hitung **return K-hari**: `ret_K(s,t) = close[t]/close[t-K] − 1`.
2. **Dua nilai K diuji, DUA-DUANYA dilaporkan (tidak boleh pilih setelah lihat hasil):**
   - **K_primer = 14 hari**
   - **K_sekunder = 7 hari**
3. Urutkan simbol eligible menurun berdasar `ret_K`. **LONG** = 25% teratas (pembulatan ke bawah, minimum 2 simbol); **SHORT** = 25% terbawah (sama aturan). Bila eligible < 8 simbol pada hari itu → tidak ada posisi hari itu (dilaporkan sebagai `n_empty_days`, bukan dihapus).
4. **Bobot:** equal-weight di dalam tiap leg; total LONG = **+0,50**, total SHORT = **−0,50** (gross 1,00, net 0,00 — dollar-neutral pada level sinyal; tidak ada vol-targeting dan tidak ada pembagi-N tambahan — ini sengaja dibuat sederhana sebagai baseline keluarga baru).
5. **Rebalance:** harian (data 1d adalah granularitas terkecil tersedia). **Tidak ada band/threshold** — rebalance penuh tiap hari; turnover dilaporkan jujur sebagai diagnostik, bukan dioptimalkan.
6. **Biaya:** `|Δbobot per simbol|` dikali **25 bps/sisi (primer)** dan **10 bps/sisi (sekunder)** — identik formula `run()` PRAREG-25.

## 4. Metrik pelaporan

Identik PRAREG-25 `metrics()`: Sharpe tahunan (√365), return total, maxDD, **%/48 jam** = `(equity^(2/n) − 1) × 100`, CAGR, blok 20-hari (persentase positif + median), eksposur rata-rata (harus ≈1,0 gross, ≈0,0 net — dicek sebagai uji validitas internal, BUKAN kriteria lolos/gagal).

## 5. Gerbang (BEKU — semua wajib untuk "LULUS"; dikoreksi dari pelajaran PRAREG-25 §8)

| # | Kriteria | Catatan |
|---|---|---|
| a | Sharpe tahunan > 0 | tidak dibandingkan ke BTC — strategi ini dirancang market-neutral, BTC bukan benchmark relevan |
| b | **maxDD absolut ≤ 20%** | mutlak, bukan relatif ke BTC (beda dari gerbang PRAREG-23/24/25) — market-neutral harus punya risk profile rendah |
| c | Positif di ≥2 dari 3 sub-periode (2019-21, 2022-23, 2024-26) | sama definisi lama |
| d | ≥60% blok 20-hari positif **dan** median blok > 0 | sama definisi lama |
| e | p-value satu-sisi (return>0 vs nol, block-bootstrap 2.000 iter blok 20 hari) **< α Bonferroni**, dihitung saat eksekusi dari `n_trials_registry_saat_itu + 1` (trial ini) **× 2** (dua nilai K) | α presisi dihitung di laporan, bukan dipatok sekarang — n registry per 22-Okt = 130 |
| f | **%/48 jam ≥ 0,10%** (lantai tangga, bukan 0,8% penuh) | tangga diadopsi 22-Okt; ini syarat MINIMUM untuk disebut "kandidat hidup", bukan syarat sertifikasi penuh |
| g | **DSR > 0,95** (n_trials = registry aktual saat run) | diperkuat dari "DSR > 0" (lemah, diakui cacat di `PRAREG_25_HASIL_PENUTUPAN.md` §8.1) |
| h | Turnover tahunan — **diagnostik, dilaporkan, bukan gerbang lolos/gagal** | rebalance harian tanpa band diperkirakan tinggi; biaya nyata sudah termasuk di metrik return |

**Kedua nilai K (14 dan 7) dilaporkan lengkap dengan gerbangnya sendiri-sendiri — tidak ada "pilih yang terbaik".**

## 6. Sensitivitas wajib (K_primer, 25 bps, jendela terverifikasi)

- Tanpa 3 kontributor P&L terbesar (long+short gabungan).
- Tanpa simbol yang delisting sebelum `VERIFIED_END` (daftar sama dengan PRAREG-25).

## 7. Yang TIDAK dilakukan di PRAREG-28 (cakupan dibatasi, sengaja)

- **Tidak** menguji K lain selain 14 & 7 (setiap K tambahan = trial baru, harus pra-registrasi terpisah).
- **Tidak** menguji vol-targeting atau sizing berbeda (itu adalah PRAREG-24 untuk keluarga lama; akan jadi PRAREG-29 bila PRAREG-28 H1/H1b menunjukkan hasil yang layak diperbaiki).
- **Tidak** menyentuh data SoDEX forward — ini backtest Binance historis dulu. Sertifikasi forward di SoDEX (bila lolos di sini) adalah pra-registrasi terpisah berikutnya.

## 8. Reproduksi

```bash
cd ~/anantara-sakti
/usr/bin/python3 scripts/research/prereg28_cross_sectional_momentum.py
# Keluaran: reports/sodex/PRAREG28_HASIL.json
```

## 9. Disiplin

Protokol ini di-hash SEBELUM skrip evaluasi ditulis. Tidak ada ambang yang akan dilonggarkan setelah melihat hasil. Trial ini akan dicatat di `research/trials.csv` dan registry SEBELUM laporan penutupan ditulis.

*PRAREG-28 · Hermes Anantara v3 · dibekukan 22-Okt-2026 · read-only, tanpa order*
