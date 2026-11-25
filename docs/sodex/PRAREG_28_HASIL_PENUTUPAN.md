# PRAREG-28 — HASIL PENUTUPAN: Momentum Cross-Sectional Market-Neutral

**Tanggal:** 22-Okt-2026 · **Hash protokol:** `PRAREG_28_MOMENTUM_CROSS_SECTIONAL.md.sha256` (dibekukan 01:56Z, SEBELUM skrip ditulis)
**Status:** **H1 DITOLAK. H1b (lebih lemah) SEBAGIAN didukung, tetap GAGAL gerbang.**

## 1. Hasil (apa adanya, kedua K, kedua biaya)

| K (hari) | Biaya | Sharpe | %/48 jam | maxDD | Turnover/thn | DSR | Lolos? |
|---|---|---|---|---|---|---|---|
| 14 | 25bps | +0,05 | **−0,0167%** | −69,0% | 137× | 0,007 | **GAGAL** |
| 14 | 10bps | +0,73 | **+0,0962%** | −42,6% | 137× | 0,295 | **GAGAL** (DSR & floor & maxDD) |
| 7 | 25bps | −0,25 | −0,0654% | −85,3% | 190× | 0,0004 | **GAGAL** |
| 7 | 10bps | +0,71 | +0,0912% | −55,5% | 190× | 0,275 | **GAGAL** |

**Tidak ada kombinasi yang lolos.** Bahkan skenario terbaik (K=14, 10bps — biaya optimis yang tidak realistis untuk rebalance harian penuh) gagal di 4 dari 7 kriteria: maxDD absolut (−42,6% vs syarat ≤20%), blok 20-hari, floor %/48j (0,096% vs syarat 0,10% — hampir, tapi tidak lolos), dan DSR (0,295 vs syarat >0,95).

## 2. Diagnosis — MENGAPA gagal (bukan cuma "gagal", tapi akar masalahnya)

**Turnover 137–190× per tahun adalah pembunuh utama.** Rebalance harian penuh tanpa band (sesuai protokol beku) berarti buku diputar ulang hampir seluruhnya setiap hari. Pada biaya realistis 25bps/sisi, ini menghabiskan **3,4–4,75% dari modal per tahun hanya untuk biaya transaksi** — jauh lebih besar dari sinyal mentah yang terdeteksi.

**Yang menarik secara ilmiah (bukan alasan untuk melonggarkan gerbang):** pada biaya 10bps (skenario optimis), sinyal K=14 menunjukkan **Sharpe +0,73 dan return positif di ≥2 dari 3 sub-periode** — ada JEJAK edge ekonomi riil di balik sinyal mentah. Masalahnya murni **struktural (frekuensi rebalance), bukan sinyal yang kosong total** seperti keluarga trend-following (PRAREG-25) yang gagal di hampir semua sub-periode sekaligus.

## 3. Bug ditemukan saat eksekusi — dilaporkan jujur (tidak memengaruhi verdict)

Kriteria **e (p-value < Bonferroni)** dihitung dengan memanggil `boot_p()` dari modul PRAREG-25 membandingkan return strategi vs **vektor nol**. Fungsi itu didesain untuk membandingkan DUA seri return (strategi vs BTC), dan punya guard `if pstdev(a1) and pstdev(a2)`. Karena vektor nol punya `pstdev=0` (falsy di Python), guard ini **selalu gagal**, sehingga pembilang tidak pernah bertambah dan `p` selalu `0.0` — bukan p-value yang valid secara statistik, melainkan artefak dari pemakaian fungsi di luar desainnya. **Ini tidak mengubah verdict** karena 4 kriteria lain (b, d, f, g) sudah gagal jauh dari ambang pada setiap kombinasi — hasil GAGAL tetap sama dengan atau tanpa kriteria e. Dicatat untuk kejujuran metodologis, dan sebagai pelajaran untuk PRAREG-29 bila dilanjutkan: pakai one-sample t-test atau bootstrap mean>0 langsung, bukan `boot_p` dua-seri.

## 4. Sensitivitas (K=14, 25bps, terverifikasi)

| Skenario | Sharpe | %/48j | maxDD |
|---|---|---|---|
| Tanpa top-3 kontributor | −0,43 | −0,091% | −84,3% |
| Tanpa simbol delisting | +0,42 | +0,044% | −55,7% |

Menghapus top-3 kontributor membuat hasil **lebih buruk** (bukan lebih baik) — berarti return positif yang ada TIDAK didominasi oleh 1-2 outlier (bagus secara metodologis), tapi juga menegaskan strategi secara keseluruhan tipis dan rapuh.

## 5. Verdict PRAREG-28

**H1 (Sharpe positif signifikan, maxDD rendah, ≥lantai 0,10%) — DITOLAK.**
**H1b (Sharpe positif tapi di bawah lantai) — SEBAGIAN benar hanya pada skenario biaya optimis (10bps); pada biaya realistis (25bps) bahkan Sharpe nyaris nol/negatif.**

**Kesimpulan:** Cross-sectional momentum BISA memiliki sinyal ekonomi riil (Sharpe 0,7 di 10bps), tapi **implementasi rebalance harian penuh tanpa band menghancurkannya lewat biaya transaksi** sebelum sempat diuji sebagai kandidat 0,8%. Ini bukan "mekanisme mati" seperti trend-following (PRAREG-25) — ini **"mekanisme yang keburu mati karena cara eksekusinya"**. Perbaikan struktural (rebalance band, holding period lebih panjang dari 1 hari, turnover cap) adalah jalan yang BELUM dicoba — layak jadi PRAREG-29 terpisah (pra-registrasi baru, bukan tweak setelah lihat hasil ini).

## 6. Yang TIDAK dilakukan (sesuai batas protokol beku §7)

Tidak menguji rebalance band, tidak menguji holding period >1 hari, tidak menguji K lain. Semua itu adalah PERBAIKAN yang harus dipra-registrasi terpisah (PRAREG-29) — bukan diubah di sini setelah melihat hasil GAGAL ini.

## 6. ADENDUM (22-Okt, setelah PRAREG-29) — koreksi framing

Klaim di §2 bahwa pada 10bps "ada JEJAK edge ekonomi riil" **perlu dinuansakan**. Uji ex-top3 pada PRAREG-28 (25bps) menunjukkan −74,2% / Sharpe −0,43, sehingga pada saat itu edge tampak sebagai artefak 1–3 nama (LUNA/XRP/ADA).

PRAREG-29 (`PRAREG_29_HASIL_PENUTUPAN.md`) memberi dekomposisi yang lebih bersih pada ladder turnover: pada **0bps**, R=7 menghasilkan **+0,106%/48j tanpa 3 kontributor teratas** (Sharpe +0,81) — jadi edge lintas-sectional itu **nyata dan lebih lebar dari dugaan awal**, hanya sangat tipis (≈0,13%/48j kotor, ≈1/6 target). Penyebab kesan "artefak" di PRAREG-28 adalah **beban biaya 25bps yang menutupi seluruh edge**, bukan ketiadaan edge.

Verdict PRAREG-28 (**GAGAL**) tidak berubah sedikit pun. Yang dikoreksi hanya penjelasannya: bukan "sinyal palsu", melainkan "sinyal nyata yang terlalu tipis untuk biaya dan risiko pada konfigurasi itu".

---

*PRAREG-28 selesai 22-Okt-2026 · dicatat di `research/trials.csv` dan `reports/sodex/sodex_trial_registry.json` · tidak ada kode produksi/eksekusi yang disentuh.*
