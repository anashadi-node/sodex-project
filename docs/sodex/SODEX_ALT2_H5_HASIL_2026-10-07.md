# HASIL H5 — UJI MEAN-REVERSION PASCA-BREAKOUT DI SODEX (SODEX-ALT2) — 2026-10-07

**Pra-registrasi:** `docs/sodex/SODEX_ALT2_H5_PRAREG_2026-10-07.md` — dikunci commit `130206d`
**sebelum** hasil dijalankan. Ambang & arah tidak diubah setelahnya.
**Data:** `scratch/sodex_minutes` → bar 4H, **3 simbol (BTC/ETH/SOL), 131 hari, 2.307 bar**.
**Harness:** `scripts/sodex_h5_meanrev_study.py` · kontrol entry acak 1000 permutasi (sign-aware).

---

## 1. VERDICT: **BELUM CUKUP BUKTI** (n < 100 — sesuai §4 pra-registrasi)

| Sisi (48 jam, horizon primer) | n | net (bp) | tahan 1,5× | WR | p | gagal |
|---|---|---|---|---|---|---|
| FADE_BREAKDOWN (beli setelah breakdown) | **36** | **−233,6** | −237,6 | 38,9% | 0,001 | c1, c2, c3 |
| FADE_BREAKOUT (jual setelah breakout) | **61** | **−125,7** | −129,7 | 57,4% | 0,001 | c1, c2, c3 |

- **c1 gagal** pada kedua sisi (36 dan 61, syarat 100) → label formal = **"BELUM CUKUP BUKTI"**.
- **Tetapi arahnya jelas berlawanan dengan hipotesis.** Kedua sisi fade **rugi besar**, bukan
  sekadar tidak terbukti. p = 0,001 (kontrol sign-aware) berarti kedua sisi fade
  **secara signifikan lebih buruk daripada entry acak**.

## 2. Verifikasi independen (sebelum mempercayai angka)

Dihitung ulang manual dari tape bar-menit, terpisah dari harness:

| Sisi | n | rata-rata 48 jam | net (bp) |
|---|---|---|---|
| Setelah **breakdown** | 36 | **−2,256 %** | long −233,6 / short **+217,6** |
| Setelah **breakout** | 61 | **+1,177 %** | long **+109,7** / short −125,7 |

- Angka **cocok persis** dengan keluaran harness → tidak ada kesalahan tanda/indeks.
- **Look-ahead diperiksa**: `hi30/lo30/vmed` semuanya `NaN` pada 10 baris pertama tiap simbol
  (memakai `shift(1)`) → tidak ada kebocoran masa depan.
- Pembanding: rata-rata 48 jam **semua** bar = +0,42 %.

**Bacaan data:** di SoDEX, breakout **BERLANJUT**, bukan balik arah.
Setelah breakdown ekstrem, harga turun **lagi** 2,26% dalam 48 jam; setelah breakout, naik lagi 1,18%.

## 3. Temuan terpenting: **kedua venue SALING BERTENTANGAN**

| | Binance (11 simbol × 3 thn) | SoDEX (3 simbol × 131 hari) |
|---|---|---|
| Setelah breakout Naik | underperform vs acak → **balik arah** | **+1,177%** → **berlanjut** |
| Setelah breakdown | fwd di atas acak → **balik arah** | **−2,256%** → **berlanjut** |
| Kesimpulan | indikasi mean-reversion | indikasi momentum |

**Efek ini TIDAK REPLIKASI lintas venue.** Arahnya berbalik 180° antara Binance dan SoDEX.

Ini berarti: **tidak ada satu pun arah (ikut tren ATAU fade) yang bisa dipercaya.**
Strategi #1 (ikut tren) gagal di Binance; kebalikannya (fade) gagal di SoDEX.
Yang "menang" hanya bisa dipilih *setelah* melihat data — itulah definisi overfitting.

## 4. Batasan yang melemahkan bahkan angka ini

- **n kecil + jendela 48 jam yang tumpang-tindih**: 36 episode tersebar di hanya **12 hari**,
  61 episode di **22 hari**. Jumlah **hari-kejadian independen ≈ 12–22**, jauh di bawah n.
  Efektifnya, p = 0,001 itu **terlalu optimistis** — kontrol saya mengacak dalam (simbol × hari)
  dan **tidak** memperhitungkan ketergantungan antar-hari.
- **Funding diabaikan** (histori funding SoDEX hanya ~5 hari). Untuk 48 jam, funding bisa
  ~10–15 bp.
- **Hanya 3 simbol**; kontribusi satu simbol besar di beberapa sel (SOL 65%, ETH 30%).
- **Data Binance ≠ SoDEX**, dan sebaliknya.

## 5. Disiplin: BERHENTI membuat hipotesis dari data ini

Dalam satu hari saya sudah membuat **3 putaran** hipotesis dari data yang sama
(Top-4 → mean-reversion → arah berlawanan). Melanjutkan putaran ke-4 = **p-hacking**:
dengan cukup banyak percobaan, sesuatu yang "signifikan" pasti muncul dari kebetulan.
**Saya hentikan di sini, dan saya nyatakan itu secara terbuka.**

## 6. Kesimpulan jujur

1. **H5 (mean-reversion) TIDAK didukung**; petunjuknya bahkan berlawanan arah.
2. **Tidak ada arah breakout yang andal** — efeknya bergantung venue, tidak replikasi.
3. **Kendala yang mengikat bukan ide strategi, tapi BUKTI.** Data SoDEX dengan riwayat panjang
   hanya 3 simbol; itu terlalu kecil untuk memutuskan apa pun soal edge.

**Yang TIDAK berubah:** target 0,8%/48 jam tetap belum tercapai dan belum terbukti mustahil.
**Yang berubah:** tiga keluarga strategi (breakout-tren, order-flow, momentum) sudah diuji dan
tidak lulus; jalur yang tersisa menuntut **data yang lebih panjang**, bukan ide yang lebih banyak.

## 7. Rekomendasi falsifiable berikutnya (pilih satu, jangan semua)

1. **Tunggu ~2 minggu** sampai data SoDEX 92 simbol matang (≈14 hari) → uji cross-sectional
   (#3 ProSP / #4 momentum) dengan **tenaga statistik nyata** (92 simbol × 14 hari).
   Keputusan **14-Okt** (cron `5772ddb0c61b`) sudah mencakup pengukuran laju F1/F3.
2. **Perluas riwayat** dengan menarik arsip trade SoDEX lebih jauh ke belakang bila venue
   menyediakannya (butuh keputusan Anda — di luar READ-ONLY).
3. **Batasi jumlah uji** dengan satu pra-registrasi final terakhir, lalu **terima hasilnya**
   apa pun — bukan menggeser ambang sampai lulus.
