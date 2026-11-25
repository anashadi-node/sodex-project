# Riset: Geometri Exit & Sumber Expectancy — SoDEX Paper, 2026-11-25

**Status:** riset selesai, kesimpulan **negatif untuk klaim alpha**; satu hipotesis
lanjut ke uji forward (lane AB10). Live tetap **NO-GO**.

**Pertanyaan yang diuji:** mengapa 13 lane paper dengan n≥20 tidak ada yang
menghasilkan edge positif, dan apakah penyebabnya geometri exit atau kualitas sinyal?

---

## 1. Metode (dan kalibrasinya)

**Replay kontrafaktual:** entry diambil **apa adanya** dari trade nyata lane paper
(waktu, harga, arah, ATR saat entry). Hanya **exit** yang disimulasikan ulang dengan
kombinasi TP = k_tp × ATR, SL = k_sl × ATR, dan time stop H jam, memakai klines 1h
venue-native `data/sodex_klines/1h` (23 simbol, s.d. 2026-11-25T11:00Z).

Aturan pesimistis: bila TP dan SL tersentuh di bar yang sama → **SL dianggap kena
dulu**. Ini mencegah bias optimis pada bar 1 jam.

**Biaya:** dikalibrasi empiris, bukan diasumsikan. Selisih `gross` dari harga vs
`pnl_pct` tercatat konsisten **≈15,7 bps round-trip** (7 lane: 15,10–15,83 bps).

**Kalibrasi metode (wajib sebelum klaim apa pun):** replay dengan geometri **milik
lane itu sendiri** harus mereproduksi hasil tercatat.

| Lane | n | Tercatat | Replay | Selisih |
|---|---|---|---|---|
| twoway_ab9a | 212 | −0,149 % | −0,227 % | −0,078 pp |
| twoway_ab9e | 280 | −0,243 % | −0,169 % | +0,075 pp |
| twoway_ab9c | 87 | +0,005 % | +0,043 % | +0,038 pp |

Selisih < 0,08 pp dengan tanda bervariasi → replay **tidak** sistematis optimis.
Tanpa langkah ini, seluruh temuan di bawah tidak sah.

**Dedup:** 855 trade mentah dari 5 lane → **696 trade unik** setelah dedup
(pair, arah, jam entry). Tanpa dedup, n menggelembung dan CI terlalu sempit.

---

## 2. Temuan 1 — Defect aritmetika: RR 0,25

Lane A/B 9a–9e memakai **TP 1,500 % / SL 6,000 %**, yaitu **RR = 0,25**.

- Win rate tercatat: **68,9 %**
- Win rate impas (breakeven) yang dibutuhkan: **80,0 %**

Kekurangan 11,1 pp terhadap titik impas **sebelum** bicara arah atau sinyal. Dengan
biaya 15,7 bps = **10 % dari jarak TP**, geometri ini secara struktural tidak bisa
menghasilkan edge kecuali WR > 80 %.

Artinya: 13 lane yang "gagal" bukan bukti sinyal buruk — itu **konsekuensi aritmetika
geometri**. Uji lanjut memisahkan keduanya.

---

## 3. Temuan 2 — Sweep geometri: TP lebar lebih baik, tapi tidak lolos koreksi

126 kombinasi (7 TP × 6 SL × 3 time stop) pada 696 trade unik. **BH-FDR q=0,05 →
0 kombinasi lolos.** Ini penting: kombinasi terbaik tidak boleh diklaim sebagai temuan.

| TP/ATR | SL/ATR | hold | n | mean net | CI95 | WR | p (mentah) |
|---|---|---|---|---|---|---|---|
| 6,0 | 4,0 | 48 h | 682 | **+0,653 %** | [+0,23; +1,10] | 52,9 % | 0,0016 |
| 6,0 | 6,0 | 48 h | 682 | +0,558 % | [+0,12; +1,03] | 54,1 % | 0,0082 |
| 6,0 | 4,0 | 30 h | 682 | **+0,456 %** | [+0,08; +0,84] | 53,8 % | 0,0093 |
| 6,0 | 3,0 | 48 h | 682 | +0,431 % | [0,00; +0,86] | 48,5 % | 0,0233 |

p terkecil 0,0016 vs ambang BH 0,000397 → **gagal**. Yang menopang hipotesis bukan
p-value tunggal, melainkan **monotonisitas**: seluruh kolom TP besar konsisten positif
(TP 6×ATR), pola yang punya mekanisme (butuh ruang untuk tren), bukan cherry-pick.

---

## 4. Temuan 3 — Seluruh gain berasal dari SHORT; LONG negatif

Geometri TP 6×ATR / SL 4×ATR / 30 h pada 696 trade unik:

| Arah | n | mean net | CI95 | p |
|---|---|---|---|---|
| SHORT | 454 | **+1,046 %** | [+0,57; +1,54] | <0,0001 |
| LONG | 228 | **−0,721 %** | [−1,29; −0,15] | 0,993 |

LONG negatif di **setiap** periode dan setiap rezim. Jadi "pooled +0,456 %" adalah
campuran short yang menutupi long yang merugi — bukan edge dua arah.

---

## 5. Temuan 4 (paling penting) — Itu beta, bukan alpha

Kontrol RANDOM sudah ada di dalam lane (entry acak, biaya sama). Perbandingan pada
geometri fixed TP 9 % / SL 6 % / 30 h:

| Kelompok | n | mean net |
|---|---|---|
| SIGNAL SHORT | 267 | **+1,348 %** |
| RANDOM SHORT | 187 | **+1,070 %** |
| SIGNAL LONG | 147 | −0,893 % |
| RANDOM LONG | 81 | −1,044 % |

Uji beda dua sampel (Welch):

- **SIGNAL short − RANDOM short = +0,278 pp, t=0,61, p=0,543** → **tidak ada alpha sinyal**.
- SHORT − LONG = +2,241 pp, t=4,71, p<0,0001 → seluruh efek adalah **arah/rezim**.
- Pada RANDOM pun SHORT − LONG = +2,114 pp, p=0,0007 → sama.

Kesimpulan: sistem tidak menemukan sinyal. Ia menemukan bahwa **short di pasar yang
turun 47 % menguntungkan**. Entry acak mendapat 79 % dari hasil entry sinyal.

Konsekuensi jujur: keunggulan ini **hilang saat BTC berbalik naik**. Ia bukan aset
produksi; ia taruhan arah yang dibungkus sebagai sistem.

---

## 6. Temuan 5 — Bukti tambahan bahwa efek tidak stabil

- **Peluruhan temporal (30 h):** 60 % awal +0,612 % → 40 % terakhir +0,217 % (p=0,226).
- **48 h:** 60 % awal +1,123 % → 40 % terakhir **−0,063 %** (p=0,574).
- **Ekuitas berurutan (pooled, TP6/SL4/30h):** total +310,8 % namun **drawdown −53,5 %**.
  Angka total itu artefak urutan trade dan sangat sensitif; jangan dikutip sebagai hasil.
- Short-only lebih stabil: per minggu +0,947 % / +0,947 % / +1,698 % (30 h), dan tetap
  +1,062 % setelah 10 trade terbaik dibuang → **bukan** bergantung pada beberapa
  outlier besar.

---

## 7. Yang tetap belum terbukti (batas kejujuran)

1. Sampel **13 hari**, satu rezim (BEAR), satu venue, 23 simbol.
2. Replay memakai bar 1 jam → urutan intra-bar tidak diketahui; mitigasi = SL dulu.
3. Biaya 15,7 bps adalah **rata-rata**; saat volatil, slippage bisa jauh lebih besar.
4. Funding tidak dimodelkan per trade.
5. Korelasi antar-posisi tidak dimodelkan; 4 short serentak = satu taruhan.
6. Semua angka adalah return **per notional posisi**, bukan % dari total wallet.

---

## 8. Keputusan & langkah berikut

**Tidak ada perubahan pada lane produksi atau parameter live.** Live tetap NO-GO.

Satu hipotesis dilanjutkan sebagai **uji forward murni** (bukan izin live):
lane `anantara-paper-ab10` — sinyal SHORT-only (`TW_BLOCK_LONG_SIGNAL=1`),
TP 9 % / SL 6 % / time stop 30 h, regime gate ON, state terpisah.

Kriteria lulus yang harus dipenuhi **sebelum** hipotesis ini boleh menyentuh uang:

1. n ≥ 40 trade forward dengan geometri sama.
2. **SIGNAL short − RANDOM short** dengan CI95 bawah > 0 → bukti alpha, bukan beta.
3. Bertahan pada minimal satu perubahan rezim (BULL atau CHOP berkepanjangan).
4. Drawdown ekuitas lane < 15 % wallet pada sizing uji.

Selama (2) belum terpenuhi, lane ini hanya menghasilkan **beta**, dan beta tidak boleh
di lever untuk mengejar 0,8 %/window: satu short squeeze menghapus puluhan window.

---

*Dibuat 2026-11-25. Skrip: `scratch/replay_geometry.py`, `scratch/sweep_geometry.py`,
`scratch/falsify_geometry.py`. Semua angka dihitung program, bukan perkiraan.*
