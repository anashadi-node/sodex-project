# RCA OPSI-1 (MAKER ENTRY) — Mengapa Gagal dan Apakah Bisa Diperbaiki

**Tanggal:** 23 Oktober 2026 · **Snapshot:** `sodex_20261023_0515` (beku)
**Data:** 861 trade berharga; 5m 30 hari (15 simbol), 1m 7 hari (15 simbol); L2 10 simbol
**Status:** SELESAI — verdict **DITOLAK**, termasuk varian perbaikannya.

---

## 1. Pernyataan deviasi (tanpa menyebut penyebab)

> **Objek:** eksekusi entry pasif (maker) pada keluarga mesin SoDEX.
> **Defect:** hasil bersih per trade **tetap negatif ekstrem** (−66,6 bps) dan **tanda manfaatnya
> berbalik** antara periode latih (−32,1 bps) dan periode uji (+25,5 bps).

Bukan "maker itu buruk" — melainkan: pada kondisi apa maker menolong dan pada kondisi apa merusak.

---

## 2. Matriks IS / IS NOT (Kepner-Tregoe)

| Dimensi | IS (gagal) | IS NOT (tidak gagal) | Distinction | Change |
|---|---|---|---|---|
| **WHAT** | Limit dipasang **di harga entry** (X=0) → net −45,4 bps; yang terisi justru trade rugi | Limit dipasang **20 bps lebih baik** → −20,7 bps | jarak limit dari harga acuan | kedalaman limit |
| **WHERE** | Sisi **entry** (membuka posisi) | Sisi **exit TP** sudah pasif dan tidak pernah merusak | sisi eksekusi | — |
| **WHEN** | Oktober (chop): menolong +25 bps. Latih (tren): merusak −32 bps | 5m 30 hari: membaik monoton pada seluruh rentang | rezim tren vs chop | rezim pasar |
| **EXTENT** | 74,5% terisi; terisi gross −86 vs tidak terisi −85 (1m) | Pada X=0, 20 trade **tidak terisi** punya baseline **+60,1 bps** | siapa yang terisi | seleksi diri |

**DISTINCTION kunci:** yang membedakan bukan "pasif vs agresif", melainkan **apakah limit berada
di harga tempat pasar sedang bergerak menjauh** atau **di harga yang harus diraih pasar**.

**CHANGE kunci:** tidak ada perubahan kode/venue. Yang berubah adalah **rezim** — dan itu yang
membalik tanda manfaat.

---

## 3. Hipotesis penyebab dan pengujiannya

| # | Hipotesis | Uji | Hasil | Verdict |
|---|---|---|---|---|
| H1 | Limit di harga acuan = adverse selection by construction | Bagi populasi X=0 menjadi terisi vs tidak terisi | terisi **−51,03**, tidak terisi **+60,10** bps → selisih **111 bps** | **LOLOS SEMUA DIMENSI** |
| H2 | Fee maker lebih murah → cukup menutup | Hitung Δ fee | hanya **+1,66 bps** vs selisih seleksi 111 bps | DITOLAK |
| H3 | Masalah resolusi data (5m terlalu kasar) | Ulang di 1m | arah sama, magnitudo **lebih kecil** (+25 vs +45) | DITOLAK (bukan artefak) |
| H4 | Field high/low tertukar | Cek struktur bar + validasi bid<ask | `h`> `l` benar; 0 pelanggaran | DITOLAK |
| H5 | Coverage data (bar tidak menutupi window) | Fungsi `covers()` + hitung ulang | 98 trade tanpa data dikeluarkan; hasil tidak berubah arah | DITOLAK |

**Root cause terverifikasi: H1 — adverse selection struktural.**
Bukti pembalikan (verifikasi prediktif): *jika* H1 benar, *maka* memperdalam limit harus
memperkecil selisih terisi-vs-tidak-terisi secara monoton. Terukur:

| Kedalaman X | Terisi (baseline) | Tidak terisi | Selisih seleksi |
|---|---|---|---|
| 0 bps | −51,03 | **+60,10** | **111,1 bps** |
| 10 bps | −48,65 | −18,42 | 30,2 bps |
| 20 bps | −53,32 | −20,89 | 32,4 bps |

Prediksi terpenuhi (111 → ~31 bps), **tetapi** populasi "tidak terisi" sendiri sudah negatif
(−20,9 bps). Artinya: memperdalam limit memindahkan Anda ke populasi yang lebih buruk,
bukan ke populasi yang menguntungkan.

---

## 4. Bottleneck (TOC) — kesalahan saya sendiri

| Langkah TOC | Isi |
|---|---|
| **Identify** | Constraint = **gross edge sinyal**, bukan biaya. Pada populasi tercakup: **−42,07 bps/trade**. |
| **Exploit** | Perbaikan eksekusi maksimal terukur: **+21,36 bps** (X=20). Sisa defisit **−20,71 bps**. |
| **Subordinate** | Tidak ada konfigurasi eksekusi yang bisa menutup sisa itu. |
| **Elevate** | Hanya sinyal baru (bukan eksekusi) yang bisa. |
| **Repeat** | Setelah eksekusi diperbaiki, constraint tetap sinyal. |

**Kesalahan metodologis yang harus dicatat:** opsi-1 menyerang **biaya** (6,49 bps) sementara
**constraint** adalah **edge sinyal** (−42 s/d −91 bps). Itu optimasi pada non-constraint —
kesalahan TOC klasik. Perbaikan 21 bps terlihat besar, tetapi 21 < 42.

---

## 5. Kelayakan market-making (uji tambahan wajib)

Karena arah berikutnya adalah MM, aritmetikanya diuji lebih dulu.

**Ambang:** MM di top-of-book hanya hidup bila spread **> 2 × fee maker = 2,28 bps**.

| Simbol | Spread median | Layak |
|---|---|---|
| SUI | 1,03 bps | tidak |
| CL | 1,01 | tidak |
| SOL | 0,97 | tidak |
| ETH | 0,42 | tidak |
| LIT | 0,30 | tidak |
| XAUT / ZEC | 0,25 | tidak |
| HYPE | 0,13 | tidak |
| BTC | **0,12** | tidak |
| SNDK | 0,08 | tidak |

**0 dari 10 simbol lolos.** MM di touch mustahil secara aritmetika: Anda membayar 2,28 bps
untuk menangkap ≤ 1,03 bps.

**MM di kedalaman** (quote X bps dari mid, isi bila tersentuh ≤15 menit, keluar 30/60 menit):

| X | Simbol positif | Rata-rata | Median/simbol |
|---|---|---|---|
| 2 bps | **0/15** | −6,10 | −5,53 |
| 5 | **0/15** | −6,02 | −6,03 |
| 10 | **0/15** | −6,18 | −6,08 |
| 20 | **0/15** | −6,41 | −6,52 |

(hold 60m: 0/15, −6,8 s/d −7,4). **Tidak ada edge mean-reversion setelah wick** pada periode ini —
harga cenderung melanjutkan, bukan kembali.

**Kesimpulan MM:** tidak layak di SoDEX pada tier fee sekarang, baik di touch maupun di kedalaman.

---

## 6. Problem solving (A3)

**Background.** Target 0,8%/window 30j butuh 3,08 bps net/trade. Biaya nyata 6,49 bps RT →
gross wajib 9,57 bps.

**Current.** Gross pada populasi tercakup **−42,07 bps**; 7 hari terakhir **−90,80 bps**.
Eksekusi terbaik yang mungkin menutup 21,36 bps.

**Goal.** Gross ≥ +9,57 bps secara konsisten, atau hentikan alokasi.

**Root cause.** Sinyal tidak punya edge arah; eksekusi pasif menambah seleksi merugikan.

**Countermeasures.**
1. **Dilarang** memakai maker entry di harga acuan (X=0) — terbukti seleksi 111 bps.
2. Jika kelak entry pasif dipakai: wajib kedalaman ≥10 bps, window ≤30 menit, dan terdaftar
   sebagai trial baru (n_trials bertambah).
3. **Jangan** menjadikan MM sebagai jalur penyelamat — aritmetika fee vs spread menolaknya.
4. Satu-satunya jalur tersisa: sinyal arah baru dengan edge gross ≥10 bps, diuji pra-registrasi
   terpisah, dengan modal risiko nol sampai lolos.

**Follow-up.** Verdict tetap 25 Nov. Data L2 tetap direkam (biaya nol, opsi terbuka bila tier fee
berubah — mis. rebate maker atau volume tier).

---

## 7. Keterbatasan yang dinyatakan terbuka

1. Uji fill memakai OHLC, bukan antrean orderbook → fill nyata lebih rendah; arah kesimpulan
   (ditolak) tidak berubah karena variant sudah diberi keuntungan maksimum.
2. Exit dianggap sama dengan ledger → konservatif untuk varian (stop ikut menjauh, tidak dihitung).
3. Uji MM memakai sampel Sep 22 – Okt 22 (satu rezim). Kesimpulan "tidak layak" berlaku untuk
   rezim ini; pada rezim lain tanda bisa berubah — yang berarti MM menjadi taruhan rezim,
   bukan edge netral pasar.
4. Uji MM mengabaikan biaya inventory/hedge dan asumsi fill di level (tanpa antrean).

---

## 8. Keputusan

**Opsi 1: DITOLAK, termasuk varian kedalaman.** Tidak ada konfigurasi eksekusi yang menutup
selisih 42–91 bps. Rekomendasi: hentikan keluarga mesin ini, jangan alokasikan modal,
dan jangan menggantinya dengan market-making di venue ini.
