# HASIL PRAREG-SIG-01 — 8 Keluarga Sinyal Diuji

**Tanggal:** 23 Oktober 2026 · **Pra-registrasi:** `PRAREG_SIG_01_2026-10-23.md` (dibekukan sebelum run)
**Data:** SoDEX 5m, 15 simbol, 22 Sep – 22 Okt 2026 (30 hari) · **Biaya:** 6,49 bps RT
**Split:** 70% latih / 30% uji (OOS) · **Script:** `scripts/research/sig_search_prereg.py`

---

## 1. Hasil utama

| Keluarga | n latih | Latih (bps) | n OOS | **OOS (bps)** | t | WR | Simbol + | Verdict |
|---|---|---|---|---|---|---|---|---|
| F1 cross-sectional momentum | 770 | −1,70 | 351 | **−7,89** | −0,85 | 45,3% | 7/14 | tolak |
| F2 Donchian (TS momentum) | 1.174 | −9,08 | 499 | **−0,86** | −0,11 | 30,9% | 9/15 | tolak |
| F3 z-score reversion | 1.478 | −4,13 | 633 | **−2,04** | −0,42 | 59,7% | 6/15 | tolak |
| F4 volatility breakout | 4.332 | −5,40 | 1.816 | **−6,50** | −2,95 | 41,6% | 3/15 | tolak |
| F5 time-of-day (00→02 UTC) | 315 | −21,50 | 135 | **−20,67** | −2,50 | 43,7% | 0/15 | tolak |
| F6 fade extreme (3σ) | 2.211 | −9,58 | 927 | **−2,24** | −0,63 | 52,8% | 8/15 | tolak |
| F7 gap continuation | 0 | — | 0 | — | — | — | — | tidak teruji (gap ≈ 0 di perp 5m) |
| F8 BTC lead-lag | 126 | +16,76 | 70 | **−47,43** | −2,53 | 55,7% | 1/14 | tolak (tanda berbalik) |

**Kriteria lulus:** OOS ≥ +9,57 bps **dan** ≥10/15 simbol positif **dan** t>2,5 **dan** lolos BH-FDR.
**Tidak satu pun keluarga memenuhi.** BH-FDR menandai F4, F5, F8 sebagai "signifikan" — semuanya
**signifikan negatif**, bukan positif.

### Kontrol

| Kontrol | Hasil | Interpretasi |
|---|---|---|
| Entri acak (n=450) | **−8,61 bps** | Bukan −6,49: dalam periode ini pasar sendiri turun **−2,44 bps per 2 jam**. Null yang benar = −8,61 |
| F8 latih → uji | +16,76 → −47,43 | Contoh sempurna overfit: positif di latih, hancur di uji |

---

## 2. Kasus F5 — temuan yang tampak kuat, lalu gugur

Pada data SoDEX 30 hari, jam 00–02 UTC tampak sangat kuat: rata-rata **−17 bps** dan **0/15**
simbol positif. Profil per jam bahkan lebih ekstrem: jam 21 = **+19,4 bps, 15/15 simbol**;
jam 13 = **−31,0 bps, 0/15**.

**Dua kelemahan yang membunuhnya:**

1. **15 simbol bukan 15 uji independen.** Semua alt bergerak bersama; n independen sebenarnya
   hanya **30 hari**, bukan 5.400 observasi.
2. **Diuji pada 2,8 tahun data Binance (2024–2026, 1h, BTC/ETH/SOL):** profil jam **tidak stabil**.

| Korelasi profil 24 jam | Nilai |
|---|---|
| 2024 vs 2025 | 0,73 |
| 2025 vs 2026 | **−0,15** |
| 2024 vs 2026 | **−0,16** |

Jam 20 yang tampak +10…+20 bps di 2024 dan 2025 menjadi ~0 di 2026. Jam 21 (bintang di SoDEX)
di Binance hanya +3,3 / +1,3 / −3,9 bps. **Kesimpulan: efek jam = noise rezim, bukan edge.**

---

## 3. Daya uji (MDE) — seberapa besar klaim yang boleh dibuat

| Keluarga | n OOS | sd (bps) | MDE 80% | n dibutuhkan untuk mendeteksi 9,57 bps |
|---|---|---|---|---|
| F1 | 351 | 174,8 | 26,1 | 2.615 |
| F2 | 499 | 169,8 | 21,3 | 2.469 |
| F3 | 633 | 120,7 | 13,4 | 1.247 |
| F4 | 1.816 | 93,9 | **6,2** | 754 |
| F5 | 135 | 96,2 | 23,2 | 792 |
| F6 | 927 | 109,1 | 10,0 | 1.018 |
| F8 | 70 | 156,6 | 52,4 | 2.099 |

**Yang boleh disimpulkan:**
- F4 punya daya cukup: edge >6,2 bps **dapat dikesampingkan** untuk volatility breakout.
- F6 dapat mengesampingkan edge >10 bps.
- F1, F2, F5, F8 **tidak berdaya** untuk ambang 9,57 bps — hasilnya "tidak konklusif", bukan
  "terbukti tidak ada". Ini harus dinyatakan jujur.

---

## 4. Kesimpulan

1. Dari 8 keluarga yang diuji pra-registrasi, **nol** menghasilkan OOS ≥ +9,57 bps.
2. Satu-satunya pola yang tampak kuat (jam) **gugur** pada uji lintas-venue & lintas-tahun.
3. Bukti yang ada konsisten dengan: **tidak ada edge arah pada horizon 5m–4 jam di SoDEX**
   sebesar yang dibutuhkan target.

## 5. Yang belum diuji (jujur)

- **Microstructure L2** (order flow imbalance dll.): data baru 1 hari → belum bisa diklaim.
- **Funding/basis**: SoDEX funding belum dikoleksi; riset literatur berjalan terpisah.
- **Horizon lebih panjang** (1–7 hari): 30 hari data terlalu pendek untuk n cukup.
- **Leverage/sizing**: tidak diuji, dan tidak akan menambah edge — hanya memperbesar varians.

## 6. Rekomendasi

Jangan alokasikan modal ke keluarga mana pun di atas. Bila riset dilanjutkan, prioritasnya
**menambah panjang data** (bukan menambah jumlah keluarga): untuk mendeteksi 9,57 bps pada
sd ~100 bps dibutuhkan **±750–2.600 trade non-overlap**, artinya 3–10× lipat data yang ada.
