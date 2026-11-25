# PRAREG-2 — Amandemen: Hipotesis Range-Position MOMENTUM (post-hoc)

**Status: DIBEKUKAN SEBELUM DIUJI.** Ditulis 07-Okt-2026, setelah menjalankan
PRAREG-1 dan **sebelum** menjalankan uji validasi apa pun atas hipotesis ini.
Registry trial ekosistem: 40.

---

## 1. Mengapa amandemen ini ada (dan mengapa ia TERPISAH dari PRAREG-1)

PRAREG-1 mendeklarasikan `RANGEPOS` sebagai sinyal **reversal** (tanda −):
long yang dekat dasar rentang 20 hari, short yang dekat puncak.

Hasil PRAREG-1 di panel panjang Binance (248 simbol, ~6 tahun, 24 trial):

| trial | neto | sd | S_ann | t_NW | p | seg+ |
|---|---|---|---|---|---|---|
| RANGEPOS_H2 | −23,62 bps | 150 bps | **−2,13** | **−5,10** | <0,0001 | **0/3** |
| RANGEPOS_H5 | −45,10 bps | 235 bps | −1,64 | −3,98 | 0,0001 | 1/3 |

Tanda reversal **ditolak secara sangat kuat**, dan ketiga segmen waktu semuanya
negatif. Ini bukan artefak biaya: bruto RANGEPOS_H2 = −20,2 bps, sedangkan
biayanya hanya 3,4 bps — jadi arah sebaliknya punya bruto +20,2 bps.

**Tetapi** tanda kebalikan itu **DIPILIH SETELAH MELIHAT DATA**. Mengklaimnya
sebagai temuan prarreg akan melanggar aturan #8 PERINTAH_1_SoDEX (dilarang
menyembunyikan trial yang gagal) dan menggelembungkan false discovery.
Karena itu ia dideklarasikan sebagai **hipotesis baru** di sini, lalu diuji
dengan pemisahan waktu yang tidak boleh disetel ulang.

---

## 2. Spesifikasi DIBEKUKAN

```
sinyal   : S = (close − lo(N)) / (hi(N) − lo(N))            N = 20 (utama)
           long yang dekat puncak (S→1), short yang dekat dasar (S→0)
bobot    : peringkat lintas-seksi, dollar-neutral, SUM|w| = 1
hold     : H = 2 hari (Binance, SoDEX 1d) ; H = 24 jam (SoDEX 1h)
biaya    : 1x = 8,00 bps round-trip (taker SoDEX 4 bps/sisi)
           realistis = 9,71 bps round-trip (+ slippage 0,86 bps/sisi)
           2x = 16,00 bps round-trip
kontrol  : sinyal diacak dalam baris, konstruksi identik; dinilai pada BRUTO
           (neto kontrol tercemar biaya turnover acak ~1,33 vs sinyal ~0,68)
```

**Pemisahan waktu (uji sah satu-satunya):**
- **IS** = 60% periode terawal panel Binance → ukur tanda & besaran, tanpa setel ulang.
- **OOS** = 40% periode terakhir → diuji apa adanya.
- Sensitivitas N ∈ {10, 20, 40, 60} dilaporkan **sebagai stabilitas, bukan pemilihan**;
  N utama tetap 20 apa pun hasilnya.

**Ambang lulus OOS:** S_ann ≥ 2,30 (biaya 1x) **DAN** ≥ 1,80 (biaya 2x)
**DAN** t_NW ≥ 2,0 **DAN** tanda IS = tanda OOS **DAN** 3/3 segmen positif
**DAN** kontrol negatif tidak lulus.

**Ambang replikasi venue (SoDEX):** tanda harus SAMA dengan Bukti-1; besaran
|IC_SoDEX| ≥ ½ |IC_Binance|. Gagal → label `TIDAK-REPLIKASI`, tidak boleh
dipakai mesin SoDEX (pelajaran H5: breakout di SoDEX berbalik arah di Binance).

---

## 3. Yang TIDAK dilakukan setelah ini

- Tidak menyetel ulang N, hold, atau ambang setelah melihat OOS.
- Tidak menghapus RANGEPOS (tanda −) yang gagal dari registry.
- Tidak menaikkan leverage; tidak mengubah target 0,8%/48 jam.
- Tidak mengklaim alpha dari jendela < 6 bulan (aturan #4 PERINTAH_1).

## 4. Urutan eksekusi

1. `scripts/research/range_pos_validation.py` → IS/OOS + sensitivitas N + SoDEX 1d/1h.
2. Hasil apa pun dilaporkan APA ADANYA, lulus atau gagal.
3. Kalau lulus: kandidat mesin, lanjut uji korelasi terhadap mesin divisi lain
   (syarat rho ≤ 0,10) sebelum diusulkan ke portofolio.

Dibekukan: 07-Okt-2026 · Divisi Riset Anantara Sakti
