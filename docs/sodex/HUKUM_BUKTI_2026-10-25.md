# HUKUM BUKTI — MENGAPA GANTI TIMEFRAME TIDAK MENYELESAIKAN MASALAH

**Tanggal:** 25 Okt 2026 · **Ambang:** |t| ≥ 4,11 (N=1.271, Bonferroni α=0,05)

---

## 1. Hukumnya

Untuk strategi dengan edge per jam `r` dan volatilitas per jam `s`:

```
t = (r / s) × √(jam kalender)
```

**Turunannya** (W = panjang window, T = jam kalender):

```
μ_window = r·W          σ_window = s·√W          n = T / W
t = (μ/σ)·√n = (r·W / (s·√W))·√(T/W) = (r/s)·√T
```

`W` **hilang dari persamaan**. Artinya:

> **Panjang window tidak mengubah kecepatan bukti.** 30 jam, 48 jam, 72 jam —
> t hanya bergantung pada (edge/vol per jam) dan lamanya kalender.

## 2. Konsekuensi angka

| SR tahunan | Tahun sampai t = 4,11 |
|---|---|
| 1,0 | 16,9 |
| 1,5 | 7,5 |
| 2,0 | 4,2 |
| 2,5 | 2,7 |
| 3,0 | 1,9 |
| 4,0 | 1,1 |
| **14,1** | **0,085 (31 hari)** |

Untuk membuktikan apa pun dalam 31 hari, strategi harus punya **Sharpe tahunan 14,1**.
Tidak ada strategi kripto directional yang mendekati itu. Sharpe 2–3 sudah kelas dunia.

## 3. Proposal "0,6% per 48 jam" — hasil hitungan

| Formulasi | SR tahunan | Tahun sampai t = 4,11 |
|---|---|---|
| 0,8% / 30 jam (sd 8,72%) | 1,57 | **6,9** |
| 0,6% / 30 jam | 1,18 | 12,2 |
| **0,6% / 48 jam** (sd 11,03%) | **0,73** | **31,3** |

**0,6% per 48 jam justru 4,5× LEBIH SULIT dibuktikan** daripada 0,8% per 30 jam,
karena volatilitas tumbuh √waktu sedangkan target tumbuh linear.

## 4. Leverage tidak menolong

Dengan leverage L: μ_wallet = L·μ_notional, σ_wallet = L·σ_notional.
Rasio μ/σ **tidak berubah** → t tidak berubah. Leverage mengubah besaran rupiah,
bukan kekuatan bukti. Menaikkan leverage untuk "mengejar 0,8%" hanya menaikkan
risiko kebangkrutan, bukan mempercepat pembuktian.

## 5. Uji baru yang sudah dijalankan (bukan teori)

**PRAREG-SIG-07 — momentum cross-sectional market-neutral 48 jam**
(dibekukan sebelum dijalankan; universe 10 simbol likuid ≥ $5k/jam; long 3 / short 3;
biaya 12,98 bps per rebalance; era-real saja).

| Metrik | Hasil |
|---|---|
| Window | 66 |
| Mean net | **−72,05 bps / 48 jam** |
| sd | 457,5 bps |
| t | **−1,28** |
| Sharpe window | −0,157 (tahunan −2,13) |
| Split 70/30 | latih −98,24 bps (t −1,34) · uji −11,81 bps (t −0,15) |
| Permutasi | p = 0,208 |
| Verdict | **NO-GO** |

Hipotesis ekonomi yang berbeda (market-neutral, bukan directional) juga gagal.
Ini menambah 1 uji → N = 1.271.

## 6. Apa yang sebenarnya tersisa

Tiga jalur, dan hanya tiga:

| Jalur | Isi | Waktu sampai jawaban jujur |
|---|---|---|
| **A. Cari SR lebih tinggi** | terus uji keluarga sinyal baru pada data baru (funding, OI, likuidasi) | 4–17 tahun pada SR 1–2 |
| **B. Turunkan standar bukti secara eksplisit** | keputusan pakai kriteria keputusan (bukan signifikansi), ukuran kecil, kill-rule pra-komit | **bulan**, tapi jawabannya berupa P&L, bukan "terbukti" |
| **C. Terima target sebagai sasaran operasional** | 0,8% tetap target; dinilai dari hasil forward nyata, bukan uji hipotesis | berjalan terus |

**Tidak ada jalur D.** Tidak ada kombinasi timeframe, leverage, atau % target yang
membuat strategi biasa "pasti terbukti" dalam 31 hari. Itu aritmetika, bukan opini.

## 7. Yang saya lanjutkan (otomatis + berkala)

1. Kampanye venue 7 hari → verdict mekanisme 1 Nov (H1/H2/H4/H6).
2. Kolektor Deribit 180 hari → uji skew (butuh 120 hari).
3. Antrean riset data baru, masing-masing dengan syarat daya uji dihitung **sebelum** jalan:
   - funding carry cross-venue (SR realistis 2–4 → 1–4 tahun)
   - likuidasi/OI crowding (SR 0,5–1,5 → 7–17 tahun)
   - basis spot–perp (SR 1–3 → 2–17 tahun)

## 8. Pernyataan jujur

Saya tidak akan mengatakan "sudah pasti akurat terbukti" untuk metode apa pun yang
belum melewati t ≥ 4,11 pada data out-of-sample. Mengatakannya akan melanggar aturan
falsifikasi yang justru menjadi alasan sistem ini dipercaya.

Yang bisa saya janjikan: setiap metode yang saya uji akan dilaporkan **apa adanya**,
termasuk yang gagal, dan saya akan terus menguji sampai ada yang lolos — atau sampai
bukti menunjukkan tidak ada yang lolos.
