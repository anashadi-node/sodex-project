---
name: prereg-30-oi-crowding-reversal
description: PRAREG-30 — pra-registrasi dibekukan: crowding-reversal berbasis open interest. Diuji offline, tanpa leverage.
metadata:
  type: project
---

# PRAREG-30 — CROWDING REVERSAL BERBASIS OPEN INTEREST

**Status: DIBEKUKAN SEBELUM DATA DIEVALUASI.**
Di-hash sebelum satu sinyal pun dihitung. Tidak ada parameter di bawah yang boleh diubah
setelah hasil terlihat. Bila gagal → dicatat gagal, tanpa penyelamatan post-hoc.

- Tanggal beku: **22-Okt-2026** · Inisiatif: user ("tulis PRAREG-30 sekarang"), lanjutan Opsi 1.
- Jenis: **riset offline**. BUKAN arm live, BUKAN paper arm. Tidak menyentuh arm A/B (PRAREG-26/27).
- Modal berisiko: **$0**. Tidak ada order, tidak ada kredensial.

## 0. Mengapa hipotesis ini ada (jejak bukti, bukan selera)

PRAREG riset paralel 22-Okt menemukan dua fakta terukur:
1. Buku hidup arm A punya edge tipis (+2,0 pp di atas breakeven WR 38,5%) tapi **bimodal** —
   20 trade teratas = 91,3% PnL, dan **tidak ada** aturan seleksi yang mencapai hit rate 50%.
   Artinya: masalahnya **variance**, bukan ketiadaan sinyal.
2. Data **open interest + rasio posisi top-trader + taker ratio** tersedia gratis, 5 menit,
   historis (diverifikasi HTTP 200 pada Binance Vision).

Hipotesis ini menyerang variance dengan **informasi orthogonal terhadap arah harga**:
mengukur *seberapa ramai* satu sisi, bukan *ke mana* harga pergi.

## 1. Hipotesis falsifiable (satu kalimat)

> Bila open interest naik tajam **tanpa** disertai kemajuan harga, maka posisi yang menumpuk
> berada di sisi yang salah, dan harga cenderung **berbalik melawan sisi ramai** dalam 8 jam.

**Falsifikasi:** bila arah sinyal tidak mengalahkan arah acak (arm kontrol) setelah biaya,
hipotesis **salah** — bukan "perlu filter tambahan".

## 2. Data (semua publik, gratis, tanpa kredensial)

| Komponen | Sumber | Granularitas | Cakupan |
|---|---|---|---|
| OI + top-trader ratio + taker ratio | Binance Vision `futures/um/daily/metrics` | 5 menit | listing → 2026-10-21 |
| Harga OHLC | `data/binance_klines/1h` (lokal) | 1 jam | 2024-01-01 → 2026-10-08 |
| Ekstensi replikasi | Binance Vision `futures/um/monthly/klines` | 1 jam | 2021-01-01 → 2023-12-31 |

**Universe (tetap, 20 simbol):**
`BTC ETH SOL DOGE XRP HYPE BCH ONDO AAVE ADA BNB LINK AVAX LTC DOT TRX SUI ENA ARB OP`
— dipilih **sebelum** hasil, dari daftar PAIRS mesin yang berjalan + likuiditas. Simbol tanpa
kline 1h setelah unduhan ekstensi → dibuang **mekanis**, dicatat di `data/prereg30/MANIFEST.json`.
Simbol yang listing di tengah periode masuk saat riwayatnya ≥ 30 hari (mekanis, tanpa pilih tangan).

## 3. Konstruksi fitur (tepat, beku)

Resolusi dasar **1 jam, UTC**. Snapshot metrics 5 menit → ambil **nilai terakhir** dalam jam tersebut.

```
OI_t        = sum_open_interest_value  (USDT, bukan kontrak -> lintas simbol)
oi_ret_4h   = OI_t / OI_{t-4} - 1
sigma_30d   = std(oi_ret_4h) atas 720 jam terakhir, DI-SHIFT 1 (tanpa look-ahead)
z_oi        = oi_ret_4h / sigma_30d          # butuh >= 720 jam riwayat, jika tidak: tidak ada sinyal

r_4h        = close_t / close_{t-4} - 1
atr_pct_1h  = ATR(14) pada 1h / close_t      # Wilder TR rata-rata 14 bar
flat        = |r_4h| < 1.0 * atr_pct_1h      # gerak 4 jam lebih kecil dari 1 ATR jam

ratio_t     = sum_toptrader_long_short_ratio
pct_30d     = persentil ratio_t dalam 720 jam terakhir (di-shift 1)
crowd_long  = pct_30d >= 0.90
crowd_short = pct_30d <= 0.10
```

**Aturan sinyal (beku):**

| Arah | Kondisi (semua harus benar) |
|---|---|
| **SHORT** | `z_oi >= 1.5` **dan** `flat` **dan** `crowd_long` |
| **LONG** | `z_oi >= 1.5` **dan** `flat` **dan** `crowd_short` |

Tidak ada kondisi lain. Tidak ada filter tambahan. Tidak ada pemilihan jam/simbol/hari.

## 4. Eksekusi (beku, konservatif)

- **Entry:** harga **open bar 1h berikutnya** setelah bar sinyal ditutup (tidak ada look-ahead).
- **TP / SL:** masing-masing **1,0 × atr_pct_1h** dari harga entry.
- **Time stop:** **8 jam** (exit di close bar ke-8).
- **Tabrakan dalam satu bar:** bila TP dan SL tersentuh di bar yang sama → **anggap SL lebih dulu**
  (pesimistis). Tidak ada intrabar yang menguntungkan kita.
- **Satu posisi per simbol**, cooldown **8 jam** setelah exit.
- **Ukuran:** 1 unit notional tetap per trade. **TANPA leverage, tanpa compounding.**
  Return diukur sebagai % dari notional — jadi hasil tidak bisa "dibantu" leverage.
- **Exit darurat:** tidak ada. Aturan di atas lengkap.

## 5. Biaya

| Skenario | Biaya | Peran |
|---|---|---|
| **Primer** | **12 bps round-trip** (taker 4 bps/sisi + slippage 2 bps/sisi) | keputusan |
| Sensitivitas | 4 bps RT (maker) | dilaporkan, bukan keputusan |
| Stress | 20 bps RT | dilaporkan, bukan keputusan |

## 6. Pembagian data (beku)

| Set | Periode | Peran |
|---|---|---|
| **IS** | 2024-01-01 → 2025-12-31 | estimasi/diagnostik |
| **OOS** | 2026-01-01 → 2026-10-08 | **keputusan utama** |
| **Replikasi** | 2021-01-01 → 2023-12-31 | uji kestabilan (dilaporkan terpisah) |

OOS **tidak boleh** dilihat sebelum aturan di dokumen ini selesai di-hash dan di-commit.

## 7. Arm (2, keduanya dilaporkan)

| Arm | Deskripsi |
|---|---|
| **P (primer)** | arah dari aturan §3 |
| **C (kontrol)** | entry **identik**, arah **acak 50/50** dengan seed tetap `42`, exit identik |

Kontrol menjawab pertanyaan yang tepat: *apakah arah sinyal membawa informasi, atau kita hanya
menemukan bahwa TP=SL pada pasar yang berombak menghasilkan sesuatu?*

## 8. Gerbang keputusan (SEMUA wajib, pada 12 bps, OOS)

| # | Kriteria |
|---|---|
| a | n ≥ **300** trade di OOS (daya statistik) |
| b | **net expectancy > 0** per trade di OOS |
| c | **ΔWR(P − C) ≥ +3,0 pp**, block-bootstrap per minggu, **p < 0,025** (Bonferroni 2 arm) |
| d | IS **dan** OOS keduanya bertanda positif (konsistensi tanda) |
| e | Replikasi 2021–2023 bertanda sama; bila berlawanan → status **UNSTABLE**, bukan lolos |
| f | **t-stat ≥ 3,6** pada return per trade (konsisten ambang registry 135 trial) |
| g | Hasil **tidak** hilang saat 3 simbol penyumbang terbaik dibuang |

**Gagal salah satu → PRAREG-30 GAGAL.** Tidak ada "hampir lolos", tidak ada filter tambahan
setelah melihat hasil.

## 9. Sensitivitas wajib dilaporkan (bukan untuk memilih)

1. Gross (tanpa biaya) vs 12 bps vs 20 bps — memperlihatkan berapa yang dimakan biaya.
2. TP/SL = 1,5 ATR (hanya pelaporan; **tidak** boleh menggantikan 1,0 ATR).
3. LONG vs SHORT dipisah.
4. Per tahun (2024, 2025, 2026) dan per simbol.
5. Tanpa 3 simbol terbaik.
6. Distribusi trade per bulan (deteksi periode lengket/regime).

## 10. Akuntansi trial (jujur, tanpa disembunyikan)

- PRAREG-30 menambah **3 uji** ke registry: arm P, arm C, replikasi.
- Registry saat beku: **135** trial → n_trials jujur untuk DSR = **140** (margin).
- Hasil **negatif tetap dicatat** di `reports/sodex/sodex_trial_registry.json`.

## 11. Yang TIDAK dilakukan (batas keras)

- Tidak mengubah arm A/B, TP/SL buku hidup, atau leverage apa pun.
- Tidak mempromosikan hasil riset menjadi paper/live arm tanpa **PRAREG baru + hash + persetujuan Anas**.
- Tidak memilih simbol/jam/hari setelah melihat hasil.
- Tidak membuang sampel tanpa alasan terukur & tercatat.
- Tidak memakai data setelah 2026-10-08 untuk keputusan (holdout dijaga).

## 12. Definisi "berhasil" (agar tidak bisa digeser)

> Berhasil = **arm P mengalahkan arm C** pada arah, setelah biaya, dengan t ≥ 3,6,
> konsisten di IS dan OOS, dan tidak bergantung pada 3 simbol terbaik.
> Bukan "PnL positif" — PnL positif bisa datang dari keberuntungan arah di pasar trending.

---

*Beku 22-Okt-2026 · Hermes Anantara v3 · riset offline, modal $0, tanpa leverage*
