# TEMUAN EMPIRIS H1 & H3 — dijalankan 14 Sep 2026
**Sampel: 732 trade SoDEX (3 track) dengan lintasan harga direplay dari candle Binance 1h.**
**Data: 960 trade dimuat, 732 dianalisis (228 dilewati: simbol tanpa candle / tanggal kosong).**

---

## H1 — EXIT GEOMETRY: **CONFIRMED** (kuat)

```text
n = 732 trade

MEDIAN R tercapai (realized)      : −0,125R      ← negatif
MEAN R tercapai                   : +0,227R
MEDIAN favorable excursion (MFE)  : +1,087R      ← posisi media menyentuh +1,09R!
MEDIAN adverse excursion (MAE)    : −0,890R

52,18% dari SELURUH posisi menyentuh +1R favorable
70,36% dari SELURUH posisi menyentuh +0,5R favorable

11,34% dari posisi RUGI sempat menyentuh +1R      ← bracket bisa menyelamatkan
24,73% dari posisi RUGI sempat menyentuh +0,5R
10,11% dari posisi MENANG sempat menyentuh −0,75R

29,78% posisi mencapai ≥ +300 bps favorable excursion
  dari yang mencapai itu, 6,88% tetap ditutup negatif
```

### Interpretasi
**Gap raksasa antara MFE dan hasil realisasi.** Posisi media kita menyentuh **+1,09R**
keuntungan, tetapi R realisasi median **−0,125R**. Artinya: **keuntungan yang dicapai
tidak ditangkap oleh mekanisme exit.** Ini bukan masalah sinyal — sinyal cukup untuk
membawa harga ke zona profit. Ini masalah geometri exit.

**Replikasi mandiri dari temuan P04** (agen Hyperliquid: 43,2% capai ≥+300bps dalam 24j,
49,3% ditutup negatif; bracket mekanis memulihkan +39,0 bps/posisi) — kini terbukti
di data kita sendiri, bukan dipinjam dari literatur.

### Angka kunci untuk desain
```text
Jika exit di-capture pada +1R: 52,2% posisi akan menang (vs WR aktual ~44%)
Jika exit di-capture pada +0,5R: 70,4% posisi akan menang
→ Trade-off: menangkap lebih awal menaikkan WR tapi memotong ekor kanan.
  Ini adalah kurva trade-off yang HARUS dioptimasi, bukan ditebak.
```

**Label: CONFIRMED — n=732, lintasan harga direplay, konsisten dengan bukti eksternal P04.**

---

## H3 — LOW-VOLATILITY GATING: **FALSIFIED** (pola terbalik di data kita)

```text
Sextil volatilitas realisasi 24 jam PRA-ENTRY → hasil trade
sextil 0 (vol terendah, 0,37–1,54%)  : n=122  mean +0,130%  median −0,101%  WR 42,6%
sextil 1 (1,54–2,53%)                : n=123  mean +0,226%  median −0,422%  WR 43,1%
sextil 2 (2,54–3,27%)                : n=121  mean +0,469%  median −0,044%  WR 49,6%
sextil 3 (3,28–4,36%)                : n=122  mean +0,150%  median −1,051%  WR 43,4%
sextil 4 (4,36–5,69%)                : n=122  mean +0,391%  median +0,084%  WR 50,8%
sextil 5 (vol tertinggi, 5,70–19,27%): n=122  mean +0,686%  median −0,163%  WR 50,0%
```

### Interpretasi — INI PENTING
P08 (data ekuitas CSI 300) menemukan prediktabilitas return **terkonsentrasi di regime
volatilitas RENDAH** dan menyarankan *low-vol gating*. **Di data kita, polanya TERBALIK:**
sextil volatilitas TERTINGGI punya mean return tertinggi (+0,686%) dan WR tinggi (50,0%),
sementara sextil terendah paling lemah (+0,130%, WR 42,6%).

**→ Hipotesis H3 (low-vol gating untuk CEX) DITOLAK untuk konteks kripto-perp kita.**

### Mengapa bisa berbeda (hipotesis kerja, belum diuji)
```text
1. CSI 300 = ekuitas indeks, regime low-vol = tren tenang & likuiditas dalam
2. Kripto perp = vol tinggi sering berarti TREN/ekspansi, bukan noise
3. Trades kita sudah melalui filter regime (MOMENTUM/BEAR_MOMENTUM) →
   seleksi entry berkorelasi dengan volatilitas, sehingga sextil tinggi terisi
   justru oleh setup terbaik
```
**Caveat wajib:** ini bukan uji bebas — 732 trade adalah sampel yang SUDAH TERSARING
oleh aturan entry yang ada. Klaim "vol tinggi → return tinggi" belum bisa digeneralisasi
sebelum diuji pada sinyal mentah (bukan subset yang lolos filter).

**Label: FALSIFIED (untuk konteks kita) — namun dengan caveat sampel terseleksi.**

---

## IMPLIKASI LANGSUNG UNTUK MANDAT 0,8% / 30 JAM

```text
Prioritas #1 bergeser lebih tegas ke EXIT GEOMETRY:
  Gap median MFE (+1,087R) vs median realized (−0,125R) = ~1,2R yang hilang per posisi.
  Kami TIDAK perlu sinyal baru untuk menangkap ini — hanya kebijakan exit yang berbeda.

Matematika kasar (konservatif):
  Jika capture ditingkatkan dari ~0% ke 40% dari jarak menuju +1R pada 52% posisi:
    ΔR ≈ 0,52 × 1,0R × 0,40 ≈ +0,21R per posisi
  Dengan 732 posisi (≈7,3 bulan) dan risk ≈1,5% wallet per posisi:
    Δ ≈ 0,21 × 1,5% × 732 ≈ +2,3% kumulatif  → arah benar, magnitudo perlu uji lanjut
  (Angka ini ILUSTRASI aritmetika, BUKAN janji — harus divalidasi backtest penuh + biaya.)
```

## CHECKPOINT
```text
Berikutnya:
 [ ] H6  — uji mean-reversion 1h/4h/1d vs biaya nyata (data candle 30 simbol)
 [ ] H1b — SIMULASI kebijakan exit alternatif (fixed +1R, ladder 50%@+1R, trailing)
           pada 732 trade yang sama → pilih yang memaksimalkan E[R] setelah biaya
 [ ] H2  — fitur clock-phase / quarter-hour
 [ ] H5  — L2 state di atas OBI (data OBI 1-menit)
```
