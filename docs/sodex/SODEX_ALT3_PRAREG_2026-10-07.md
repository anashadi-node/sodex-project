# SODEX-ALT3 — PRA-REGISTRASI: Uji Cross-Sectional pada Venue Asli (92 simbol × ~12 bulan)

**Status: BEKU sejak commit ini.** Ambang, arah, dan spesifikasi ditetapkan **sebelum**
backfill klines selesai dan **sebelum** satu pun hasil dihitung.
Tanggal: 2026-10-07 · Lingkup: proyek SODEX · Mode: READ-ONLY.

---

## §1 Alasan dataset baru (temuan 2026-10-07)

Probing endpoint publik SoDEX menemukan bahwa **histori klines di venue aslinya jauh lebih dalam
daripada yang pernah dikumpulkan**:

| Interval | Kedalaman tersedia (hasil probing) |
|---|---|
| 1 menit | hanya beberapa hari terakhir |
| 5 / 15 / 30 menit | beberapa minggu–bulan |
| **1 jam** | **~2025-10-12 → sekarang (~12 bulan)** |
| **1 hari** | **~2025-10-12 → sekarang (~12 bulan)** |

Jumlah pasar: **92 simbol perps** (`/markets/tickers`).

Artinya: **Top-4 bisa diuji di venue yang benar dengan tenaga statistik nyata** — 92 simbol ×
~12 bulan — alih-alih 3 simbol × 131 hari (tape lama) atau proksi Binance.

## §2 Dataset & kualitas (BEKU)

- **Sumber:** endpoint publik `klines` (GET, tanpa auth) → `scratch/sodex_klines/{SYM}_1h.parquet`.
- **Universe:** 92 simbol dari `/markets/tickers`.
- **Bar:** 1 jam; bar 4H/24H diturunkan dari 1H (bukan sumber terpisah).
- **Rentang:** 2025-10-12 → saat backfill.
- **Pemeriksaan kualitas wajib sebelum uji (fail-closed):**
  1. `ts` monoton naik & unik per simbol.
  2. Harga `o,h,l,c` numerik & > 0 (API mengembalikan **string** — wajib dikonversi;
     bug ini sudah tertangkap dan diperbaiki di `scripts/sodex_backfill_klines.py`).
  3. `h ≥ max(o,c)` dan `l ≤ min(o,c)` pada ≥ 99% bar.
  4. Tidak ada bar dengan volume negatif.
  Bila simbol gagal → **dikeluarkan**, dan jumlah yang dikeluarkan dilaporkan.

## §3 Pembagian IS/OOS dan pemeriksaan independensi (BEKU)

- **IS** = 2025-10-12 .. 2026-05-31 (7,7 bulan; **periode yang belum pernah dilihat** sistem).
- **OOS** = 2026-06-01 .. terakhir (≈4,3 bulan).

**Masalah independensi yang diakui terbuka:**
Bagian OOS **tumpang-tindih** dengan periode yang sudah saya lihat pada tape 3 simbol
(BTC/ETH/SOL, mulai 22 Mei 2026). Karena itu, **dimensi cross-sectional (92 simbol) adalah
sepenuhnya baru**, tetapi seri waktu BTC/ETH/SOL **bukan** data yang benar-benar perawan.

**Mitigasi wajib (mengikat):** selain hasil penuh, laporkan **subset tanpa BTC/ETH/SOL**
(89 simbol) — subset itu **seluruhnya belum pernah dilihat**. Bila hasil penuh dan subset
berbeda arah → **verdict otomatis GAGAL** (bukti tidak stabil).

## §4 Hipotesis & spesifikasi (BEKU — diuji SEMUA, dilaporkan SEMUA)

Semua sinyal memakai data ≤ t (tidak ada look-ahead). Peringkat dihitung **lintas simbol
pada bar yang sama**. Entry = `open` bar t+1; exit = `close` bar t+H.

| Kode | Sinyal | Arah | Formasi | Tahan (H) |
|---|---|---|---|---|
| **H6a** | momentum | long desil atas `ret_24h` / short desil bawah | 24 jam | 24 jam |
| **H6b** | momentum | idem | 72 jam | 72 jam |
| **H6c** | momentum | idem | 168 jam | 168 jam |
| **H7a** | reversal jangka pendek | arah TERBALIK dari H6 (fade) | 4 jam | 4 jam |
| **H7b** | reversal jangka pendek | arah terbalik | 8 jam | 8 jam |
| **H8a** | risk-managed trend | peringkat `ret_72h / vol_72h` | 72 jam | 72 jam |
| **H8b** | risk-managed trend | peringkat `ret_168h / vol_168h`, eksposur diskalakan `min(1, 40% / vol_ann)` | 168 jam | 168 jam |
| **H8c** | risk-managed trend | H8b + gate rezim: hanya bila `ret_168h` searah pada BTC | 168 jam | 168 jam |

Catatan jujur: **H8 adalah aproksimasi** dari "#4 Risk-Managed Regime Momentum", dan **#3 ProSP
tidak diuji** karena spesifikasi aslinya (skor probabilitas + Open Interest) tidak tersedia.
**Jangan** menyebut H8 sebagai "#4" dan **jangan** mengklaim #3 diuji.

Desil = 10% teratas / 10% terbawah. Zat posisi: sama-rata (equal weight) di dalam desil.

## §5 Biaya (BEKU)

- Taker SoDEX resmi **4 bp/leg → 8 bp round trip**.
- Uji ketahanan **1,5× (12 bp)**.
- Funding **diabaikan**; diakui sebagai batasan (hold 168 jam bisa kena funding ~15–40 bp).
- Slippage **tidak** dimodelkan → hasil lebih optimistis daripada kenyataan.

## §6 Syarat LULUS (BEKU — 5 syarat, pada segmen OOS)

| # | Syarat |
|---|---|
| c1 | n ≥ **100** bar-kejadian (dihitung per (simbol × waktu)) |
| c2 | net rata-rata > **0** setelah biaya 8 bp |
| c3 | tetap > 0 pada biaya **1,5× (12 bp)** |
| c4 | p_kontrol < **0,05** (kontrol peringkat acak, 1000 permutasi, sign-aware) |
| c5 | kontribusi satu simbol ≤ **30%** dari total net |

Berlaku juga **c6 (mitigasi §3):** hasil penuh dan subset-tanpa-BTC/ETH/SOL **tidak boleh
berlawanan arah**. Jika berlawanan → **GAGAL**.

**Multiple testing:** 8 varian diuji → **BH-FDR q = 0,10** dilaporkan. Varian yang lulus c1–c6
tetapi **tidak** lulus BH **tidak boleh** diklaim sebagai temuan.

## §7 Kontrol negatif (WAJIB)

- **Peringkat acak** pada bar yang sama, jumlah sampel identik (menguji apakah **urutan
  cross-sectional** membawa informasi).
- **Entry acak** pada (simbol × bar) yang sama (menguji apakah **waktu** membawa informasi).
- Kontrol wajib **sign-aware** (bug ini pernah muncul; ada tes regresinya).
- Harness wajib lulus `tests/test_binance_alt_harness.py` sebelum hasil dipercaya.

## §8 Tiga hasil yang mungkin (DITETAPKAN SEBELUM DATA)

1. **LULUS** — ada varian yang lulus c1–c6 **dan** BH-FDR.
2. **GAGAL** — semua varian gagal minimal satu syarat.
3. **BELUM CUKUP BUKTI** — n < 100 atau simbol gagal kualitas sehingga universe terlalu kecil.

Label **#3 bukan kekalahan dan bukan kemenangan.**

## §9 Batasan yang diakui

- **Funding diabaikan**, slippage tidak dimodelkan → hasil bias optimistis.
- **Overlap waktu jendela** pada H ≥ 24 jam → jumlah kejadian independen < n; p-value optimistis.
- Banyak simbol adalah **pasar tipis**; likuiditas nyata bisa jauh di bawah asumsi.
- Tokenized stocks/ETF (AAPL, NVDA, TSLA, dst.) punya **gap di luar jam bursa** →
  return semalam bisa melompat; ini **bukan** perilaku kripto 24/7.
- Bila LULUS, klaim maksimum = **"layak diuji dengan modal"**, BUKAN "target 0,8%/48 jam tercapai".

## §10 Cara verifikasi ulang

```bash
.venv-research/bin/python3 scripts/sodex_backfill_klines.py --interval 1h   # data
.venv-research/bin/python3 scripts/sodex_alt3_xsec_study.py                 # uji
```
