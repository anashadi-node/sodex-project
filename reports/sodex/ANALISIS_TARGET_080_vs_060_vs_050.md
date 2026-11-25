# Analisis Kuantitatif: Target 0,8% vs 0,6% vs 0,5% per 48 Jam

Tanggal: 2026-10-08 · Lingkup: SoDEX (proyek SODEX saja) · Status: ANALISIS, bukan perubahan target
Sumber angka: `reports/sodex/TA11_EXIT_STUDY.json` (commit `5212819`), `reports/sodex/TA10_FADE_STUDY.json`
Metode: model lognormal per window 48 jam; P(kumulatif majemuk 1 tahun >= target); kontrafaktual gerbang memakai flag gerbang asli dari JSON.

## 1. Pertanyaan

Jika Target Utama diturunkan dari 0,8% menjadi 0,6% atau 0,5% per 48 jam (dari TOTAL modal wallet),
apakah probabilitas target terlampaui menjadi lebih besar?

## 2. Jawaban singkat

1. **YA secara mekanis** — bar yang lebih rendah selalu lebih sering tertembus, pada tingkat edge apa pun.
   Besarnya kenaikan bergantung pada apakah mesin+risiko dibiarkan tetap (lihat Tabel 4/5).
2. **TAPI hari ini tidak mengubah apa pun secara praktis** — edge terbaik yang terukur adalah
   mu = 19,15 bps/48j (13,67 bps setelah fee 2x). Itu 2,6x-3,7x di bawah target 0,5%, dan 4,2x-5,9x
   di bawah 0,8%. Pada tingkat edge itu P(kumulatif tahunan >= target) = 0,00000% untuk KETIGA target.
3. **Pembunuh sebenarnya bukan tinggi target, melainkan spesifisitas sinyal.** Jika gerbang Sharpe
   diturunkan ke 1,75 (konsekuensi wajar dari target 0,5%), hasilnya tetap **0/10 (TA11), 0/16 (TA10 sodex),
   0/16 (TA10 binance)**. Seluruh arm ber-S tinggi mati di gerbang kontrol `|t_ctrl| >= 2,0` (nilai 2,92-4,49).
   Menurunkan target tidak menyelamatkan satu kandidat pun.

## 3. Asumsi & definisi

- Window = 48 jam; 182,5 window per tahun.
- `mu` = ekspektasi return bersih per window (bps dari modal yang dialokasikan mesin).
- `sigma` = volatilitas return per window (bps). Angka mesin dari JSON (sd_bps).
- Modal wallet dipecah rata ke M mesin (slug); mu wallet = rata-rata mu mesin, BUKAN jumlah (tanpa leverage).
- Anchor risiko dari kerangka internal: target 0,8%/48j dicapai pada Sharpe tahunan 2,3
  => sigma window = 469,9 bps (4,70%) dan sigma tahunan 63,5%.
- Model normal/lognormal iid; return nyata berekor gemuk => peluang di ekor sedikit lebih kecil dari hitungan.

## 4. Tabel 1 — Target per 48 jam dan padanan majemuknya

| Target | per tahun (majemuk) | per tahun (aritmetika) |
|---|---|---|
| 0,8% / 48j | +328,1% | +146,0% |
| 0,6% / 48j | +197,9% | +109,5% |
| 0,5% / 48j | +148,5% | +91,2% |

## 5. Tabel 2 — Anchor risiko (kerangka sendiri)

| Besaran | Nilai |
|---|---|
| sigma per window (48j) | 469,9 bps = 4,70% |
| sigma tahunan | 63,5% |
| Sharpe tahunan yang dipersyaratkan | 2,30 |

## 6. Tabel 3 — mu per window -> ekspektasi tahunan & Sharpe (pada sigma anchor)

| mu (bps/48j) | ekspektasi tahunan (arit) | S_ann (pada sigma anchor) | S_ann (pada sigma alami mesin, 66,18 bps/win) |
|---|---|---|---|
| 13,67 (TRAIL_ATR25_H48, fee 2x) | 24,9% | 0,39 | 2,79 |
| 19,15 (TRAIL_ATR25_H48, net) | 34,9% | 0,55 | 3,91 |
| 25,62 (MACD_FADE_H48, net; deskriptif, gagal gerbang) | 46,8% | 0,74 | 5,23 |
| 50,00 (= target 0,5%) | 91,2% | 1,44 | 10,2 |
| 60,00 (= target 0,6%) | 109,5% | 1,72 | 12,2 |
| 80,00 (= target 0,8%) | 146,0% | 2,30 | 16,3 |

Catatan: Sharpe bergantung pada sigma yang dipilih. Pada vol alami mesin (sd 66,18 bps/window),
target 0,8%/48j menuntut Sharpe 16,3 — mustahil. Kerangka 2,3 hanya masuk akal bila vol wallet
di-skala ke 4,70%/window (63,5%/tahun), yaitu alokasi/eksposur jauh lebih agresif, bukan leverage tetap.

## 7. Tabel 4 — P(kumulatif majemuk 1 tahun >= target), sigma anchor 4,70%/window

| mu (bps/48j) | P(>=0,8%) | P(>=0,6%) | P(>=0,5%) |
|---|---|---|---|
| 0,00 | 0,455% | 2,081% | 3,995% |
| 13,67 | 1,337% | 5,007% | 8,719% |
| 19,15 | 1,981% | 6,855% | 11,493% |
| 25,62 | 3,063% | 9,669% | 15,512% |
| 50,00 | 12,085% | 27,434% | 37,683% |
| 60,00 | 18,855% | 37,743% | 48,951% |
| 80,00 | 37,895% | 60,363% | 70,839% |

**Baris kunci**: mesin yang tepat berada di anchor (mu = 80 bps) punya peluang 37,9% menembus 0,8%,
60,4% menembus 0,6%, dan 70,8% menembus 0,5% dalam setahun. Menurunkan target dari 0,8% ke 0,5%
menaikkan peluang dari 38% ke 71% (+33 poin persen) TANPA mengubah ekspektasi uangnya.

## 8. Tabel 5 — Kondisi hari ini (sigma alami mesin, 66,18 bps/window)

| mu | P(>=0,8%) | P(>=0,6%) | P(>=0,5%) |
|---|---|---|---|
| 19,15 (terbaik, net) | 0,00000% | 0,00000% | 0,00000% |
| 13,67 (terbaik, fee 2x) | 0,00000% | 0,00000% | 0,00000% |
| 25,62 (deskriptif, gagal gerbang) | 0,00000% | 0,00000% | 0,00003% |

Pada kondisi nyata sekarang, beda antara 0,5% dan 0,8% tidak dapat diukur — keduanya nol praktis.

## 9. Tabel 6 — Per window vs kumulatif (jangan tertukar)

mu = 19,15 bps, sd = 66,18 bps/window, korelasi antar mesin rho = 0,10.

| M mesin | sigma window | Sharpe tahunan | P(window >= 0,8%) | P(>= 0,6%) | P(>= 0,5%) |
|---|---|---|---|---|---|
| 1 | 66,18 | 3,91 | 17,9% | 26,9% | 32,1% |
| 4 | 37,73 | 6,86 | 5,3% | 13,9% | 20,7% |
| 8 | 30,51 | 8,48 | 2,3% | 9,0% | 15,6% |
| 12 | 27,69 | 9,34 | 1,4% | 7,0% | 13,3% |

Dua pelajaran penting:

- **Per window, target kadang terlampaui karena varians** (17,9-32,1% untuk satu mesin) — itu kebetulan,
  bukan edge. Yang majemuk adalah RATA-RATA (mu), dan rata-rata itu hanya 34,9%/tahun pada edge terbaik.
- **Diversifikasi menaikkan Sharpe tetapi MENURUNKAN peluang menembus ambang tinggi** (32,1% -> 15,6%
  untuk target 0,5%). Peluang menembus bar tinggi dimaksimalkan oleh konsentrasi/volatilitas, bukan
  oleh 6-8 mesin berkorelasi rendah. Diversifikasi membuat hasil lebih andal-positif, bukan lebih sering besar.
- Ekspektasi tahunan TIDAK berubah oleh jumlah mesin: 34,9% (arit) untuk M = 1..12, karena mu wallet =
  rata-rata mu mesin. Tanpa menaikkan edge atau eksposur, jumlah mesin tidak menambah return.

## 10. Tabel 7 — Paradoks sertifikasi: target lebih rendah, bukti justru lebih lama

| Target | mu untuk 50% odds | S_ann setara | Window sertifikasi (t >= 1,96) | Hari |
|---|---|---|---|---|
| 0,8% | 90,72 bps | 2,61 | 103,1 | ~206 |
| 0,6% | 70,86 bps | 2,04 | 168,9 | ~338 |
| 0,5% | 60,92 bps | 1,75 | 228,6 | ~457 |

Menurunkan target menurunkan persyaratan Sharpe, tetapi untuk MEMBUKTIKAN edge yang lebih tipis
secara statistik dibutuhkan sampel forward lebih banyak (206 -> 338 -> 457 hari). HARD_STOP 20 Nov 2026
(~43 hari lagi) berarti tidak ada satu pun dari ketiganya yang tersertifikasi pada siklus ini.

## 11. Tabel 8 — Kontrafaktual gerbang: apa yang terbuka bila target/Sharpe diturunkan?

Gerbang Sharpe dilonggarkan ke S_ann >= 1,75 dan S_fee2x >= 1,35 (setara semangat target ~0,5%),
gerbang kualitas TETAP (t >= 1,96; |t_ctrl| < 2,0; seg 3/3; BH; turnover <= 1,5):

| Keluarga | Lolos dengan gerbang normal | Lolos dengan gerbang Sharpe diturunkan |
|---|---|---|
| TA11 SoDEX (10 arm) | 0/10 | **0/10** |
| TA10 SoDEX (16 arm) | 0/16 | **0/16** |
| TA10 Binance (16 arm) | 0/16 | **0/16** |

Delapan arm ber-S >= 1,75 (MACD_FADE_H24/H48, STOP_ATR15_H24/H48, TP2R_SL1R_H48, TRAIL_ATR15_H48,
TRAIL_ATR25_H24/H48) semuanya mati di `|t_ctrl|` 2,92-4,49 (MACD_FADE_H48 juga gagal BH).
Artinya: pelonggaran target/Sharpe tidak membuka satu kandidat pun. Penyumbat = spesifisitas kontrol
dan multiple-testing, bukan tinggi target.

## 12. Kesimpulan

1. Secara matematis: menurunkan target MENAIKKAN probabilitas terlampaui. Pada mesin ber-mu = target
   (0,8% -> 0,6% -> 0,5% per 48j), peluang tahunan naik 37,9% -> 60,4% -> 70,8%.
2. Secara ekonomi: ekspektasi uang TIDAK berubah; yang berubah hanya ambang yang disebut "sukses".
   Nilai tahunan yang dijanjikan turun dari +328% ke +198% ke +148%.
3. Secara empiris hari ini: tidak ada perubahan praktis. Edge terbaik 19,15 bps/48j (13,67 fee2x) membuat
   P ~ 0 untuk ketiganya; dan kontrafaktual gerbang menunjukkan 0/10, 0/16, 0/16 tetap nol.
4. Identitas penting: menurunkan target SAMBIL menurunkan risiko secara proporsional menjaga Sharpe tetap
   membuat P konstan (~37,9%). Target hanya lebih mudah ditembus bila mesin dan risikonya dibiarkan tetap.

## 13. Rekomendasi (keputusan tetap milik Mas Anas)

- **Pertahankan 0,8% sebagai North Star.** Lever yang benar-benar menaikkan peluang pencapaian adalah
  edge per window (mu), pengurangan fee/slippage, dan validasi forward — bukan angka target. Bukti:
  tidak satu pun arm yang gagal karena "S kurang untuk 0,8%"; semuanya gagal karena kualitas sinyal.
- Bila ingin milestone yang lebih mudah dipantau, tambahkan **tangga milestone non-pengganti**
  (mis. 0,2% -> 0,3% -> 0,4% per 48j pada rekap rolling) tanpa mengubah definisi target.
- Bila Mas Anas tetap memutuskan menurunkan target: itu keputusan arbiter, wajib dideklarasikan,
  dan gerbang S_ann/S_fee2x pada PRAREG baru ikut turun (pelonggaran aturan) — dengan konsekuensi
  waktu sertifikasi memanjang (206 -> 338/457 hari) dan nol kandidat terbuka hari ini.
- Jalur hidup satu-satunya tetap: PRAREG-12 forward (verdict n >= 40) dan pencarian sinyal ber-edge
  lebih besar per window.

## 14. Governance

- Dokumen ini ANALISIS, bukan perubahan target. Target 0,8% tetap berlaku sampai keputusan eksplisit user.
- Tidak ada parameter, gerbang, atau protokol beku yang diubah oleh dokumen ini.
- Tidak ada kredensial yang ditulis atau di-commit.
