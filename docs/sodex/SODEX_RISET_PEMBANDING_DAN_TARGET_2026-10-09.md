# SoDEX — RISET PEMBANDING EKSTERNAL + UJI "APAKAH TARGET SALAH?" (2026-10-09)

**Sifat:** read-only. Tidak ada perubahan target, ambang, flag, parameter. Tidak ada order.
**Pemicu:** instruksi Mas Anas 09-Okt: jangan berhenti di 20-Nov; cari semua cara; cek apakah ada
pihak lain yang berhasil; cek apakah Target Utama sendiri yang salah.
**Scope:** wallet SoDEX saja (keputusan 08-Okt).

## 1. Hipotesis yang dibantah

| # | Hipotesis | Hasil |
|---|---|---|
| H-A1 | Carry spot-perp DALAM SoDEX bisa menutup celah | **TERBANTAH oleh aritmetika** (§2) |
| H-A2 | Maker rebate SoDEX memberi edge struktural | **TERBANTAH** (§3) |
| H-A3 | Reversal 1h + fee maker = 81% target | **sudah TERBANTAH** PRAREG-5 (adverse selection 3,9 bp/periode) |
| H-C | Pihak lain mencapai ≥ level target ini | **TIDAK ditemukan** satu pun (§4) |
| H-B | Target 0,8%/48j salah-kalibrasi vs. benchmark | **DIDUKUNG**, tapi keputusan milik Mas Anas (§5) |
| H-A4 | SoPoints/airdrop = sumber return non-arah | **BELUM teruji**, butuh data akun + keputusan definisi target (§6) |

## 2. Carry spot-perp dalam SoDEX (data live 09-Okt, 92 perps / 40 spot / 23 pasangan)

Sumber: `mainnet-gw.sodex.dev/api/v1/{perps,spot}/markets/tickers` (cache scratch `sodex_tickers_20261009.json`).

- Funding diselesaikan **per jam**. Median seluruh perps **0,125 bp/jam**; **37 dari 92 simbol tepat di lantai 0,125** (komponen suku bunga baku), rata-rata 0,13.
  82 positif / 10 negatif.
- Lantai 0,125 bp/jam = **11%/tahun**. Per 48 jam = **0,060%**. Target = 0,8% → carry maksimum tanpa biaya menutup **7,5% target**.
- Funding tertinggi: SKHX 0,985 bp/jam (vol 24j $47 rb), LITE 0,90 ($9 rb), MRNA 0,69 ($60 rb) — perps saham/RWA tipis. Bahkan 0,985 bp/jam = 0,047%/48j. Tidak ada simbol mendekati cap 4%/jam.
- Hanya 23 simbol punya spot. Kedalaman top-of-book spot **$148–$2.640**; volume spot 24j: BTC $31 rb, ETH $18,5 rb, lainnya < $5 rb. Spread spot altcoin 4–10 bp (lebih besar dari carry 48j).
- Basis (mark/spot) acak −12…+6 bp: noise lebih besar dari carry per hari.

**Kesimpulan:** carry in-venue tertutup oleh aritmetika (tanpa perlu backtest): plafon 0,06%/48j vs butuh 0,8%.
Ini konsisten dengan R4-B H8 (PBO 0,29, FAIL) di audit.

## 3. Maker rebate

Rebate −0,001…−0,003% (−0,1…−0,3 bp) mensyaratkan **share volume maker 14 hari > 0,5…3%** (dokumen resmi
sodex.com/documentation/trading-mechanics/trading-fees). BTC+ETH saja ≈ $170 jt/hari → 0,5% dari volume
maker 14 hari = orde jutaan dolar. Wallet ini plafon strategi ≈ $8–22 rb (STRUKTUR_BIAYA §7). **Tidak terjangkau**
(estimasi aritmetik, bukan pengukuran akun). Dan besarnya −0,1 bp: kecil dibanding adverse selection 3,9 bp.

## 4. Triangulasi: siapa yang "berhasil", dan seberapa besar

| Pembanding | Return tahunan | Setara per 48 jam | Target 0,8% = berapa × | Sumber / mutu |
|---|---:|---:|---:|---|
| Medallion (Renaissance) bersih 1988–2018 | 39% | 0,181% | **4,4×** | Cornell 2020 via media; sekunder; hanya karyawan, cap ~$10 M |
| Medallion kotor | 66% | 0,278% | 2,9× | idem; Sharpe > 2,0, beta ≈ −1 |
| Dana kuantitatif kripto, median sejak berdiri | 24,1% | 0,118% | 6,8× | cryptofundresearch.com (agregator, self-reported → bias survivorship) |
| Dana kripto rata-rata 2025 | −7,2% | — | — | idem; 63% dana rugi; quant +0,4% |
| Market-neutral kripto | 13–18,5% | ~0,07–0,09% | ~10× | Galaxy VisionTrack via media |
| Indeks CFR median tahunan (semua dana) | 46,5% | 0,21% | 3,8× | murni beta kripto, bukan alpha |
| **Target Anantara** | **329% majemuk** (146% aritmetik) | **0,8%** | 1× | |

Temuan: **tidak ada satu pun pembanding terdokumentasi yang mendekati 329%/tahun secara konsisten**.
Rekor terbaik dunia (Medallion) berada di 3–4× di bawah target dan itu pun pada modal terbatas, infrastruktur
HFT, dan tim ilmuwan. Kinerja >100%/tahun yang ada di dataset adalah tahun beta (2017 +1.111%, 2020–21) —
bukan alpha berulang. Median Sharpe dana kripto 1,17–1,53; target proyek mensyaratkan ≥ 2,3.

Keterbatasan (jujur): sumber web adalah agregator/blog, bukan filing primer; ada bias survivorship (dana gagal
berhenti melapor); saya tidak punya akses ke pelaku kecil yang mungkin profit tinggi tapi tidak
terdokumentasi. Absennya bukti ≠ bukti ketiadaan, tapi **beban pembuktian ada pada klaim 329%/tahun**.

Satu argumen optimis yang SAH: Medallion membatasi diri ke $10 M karena kapasitas. Wallet ini ≈ $8–22 rb —
jauh di bawah kapasitas, sehingga edge berkapasitas-kecil (perps saham/RWA tipis) *mungkin* tersedia bagi
modal kecil dan tidak bagi dana besar. Itu satu-satunya alasan struktural untuk optimisme, dan itu
**sudah diuji** lewat 11+ keluarga sinyal (0 lolos).

## 5. Apakah Target Utama yang salah? (analisis, bukan keputusan)

Arah aritmetika target:

| Target /48 jam | Majemuk /tahun | vs Medallion bersih |
|---:|---:|---:|
| 0,80% | +329% | 4,4× |
| 0,30% | +73% | 1,7× |
| 0,20% | +44% | 1,1× |
| 0,15% | +31% | 0,8× |
| 0,10% | +20% | 0,55× |

Pembacaan:
1. 0,8%/48j **bukan mustahil secara matematis**, tapi menuntut kinerja ≈ 4× rekor bersih dunia, diulang tiap
   48 jam, pada wallet kecil. Tidak ada preseden terverifikasi.
2. Bottleneck terukur (audit §6) = magnitudo edge per-trade: terbaik 0,02% vs 0,4–0,8% → 25–40×. Itu fakta
   data kita, bukan opini; berlaku di 0,8/0,6/0,5%.
3. **Definisi target sendiri punya 3 bagian yang bisa dikritik tanpa menurunkan angka**: (a) "per 48 jam
   AKUMULASI" menuntut ~182 jendela positif/tahun; (b) metrik berbasis PnL bersih menyingkirkan return non-trading
   (poin/airdrop); (c) gerbang sertifikasi (Sharpe ≥ 2,3, n ≥ 20, 3/3 segmen) tidak bergantung pada angka target.
4. Aturan proyek (audit): **mengubah target bukan wewenang agen**. Saya TIDAK mengubahnya. Saya hanya
   menyajikan opsi di bawah.

**Opsi untuk keputusan Mas Anas (tidak ada yang saya jalankan):**
- **O-1 Pertahankan 0,8%/48j sebagai aspirasi.** Tambahkan *lantai kelayakan* terpisah yang terdefinisi
  PRA-registrasi (mis. setara 40% bersih/tahun, ≈0,18%/48j) sebagai bukti hidup sistem; 0,8% tetap kompas.
- **O-2 Tambah metrik terpisah** "return non-trading (SoPoints/SOSO)" — dilaporkan sendiri, tidak dicampur PnL.
- **O-3 Biarkan seperti sekarang** (0,8% saja, gerbang beku) → konsekuensi sudah jelas: "belum ada edge terbukti".

## 6. Yang BELUM teruji dan masih layak dikejar (tanpa melanggar protokol)

1. **SoPoints (Layer 1 Season, 1 Sep 2026, 20 minggu → ± 19 Jan 2027)**: poin untuk volume, open interest, vault.
   $SOSO sudah listing → nilai terukur. Alokasi per poin **tidak terkonfirmasi** (sumber: orbitperpscreener,
   perpdexguide; "upside, bukan rencana"). Uji falsifiable: `nilai_USD(poin/minggu) − biaya_fee(volume)` > 0 pada
   akun nyata? Butuh: angka SoPoints akun Mas Anas per minggu + harga SOSO. **Perlu keputusan Mas Anas** karena
   menyentuh definisi target (O-2).
2. **Forward yang masih hidup**: PRAREG-16 (MACD_FADE|BULL|sodex n=49 hist; forward n≈5–8), F1, S1.
   Terus berjalan; tidak ada perubahan.
3. **Replikasi pembanding yang paling relevan**: market-neutral Sharpe ~2,5 pada skala kecil (CFR 2,45, 13%/th) =
   gaya mv_funding — sudah dikeluarkan dari scope oleh Mas Anas (08-Okt). Bila scope dilonggarkan,
   itu satu-satunya jalur dengan bukti eksternal dan internal (SR 4,78, n=17/20).

## 7. Falsifier & verifikasi

- Bila ada simbol SoDEX dengan funding ≥ 3 bp/jam stabil ≥ 3 hari **dan** spot likuid ≥ $5 rb top-of-book →
  hipotesis H-A1 dibuka ulang (cek ulang tiap `ticker` harian; skrip sudah ada di scratch).
- Bila SoPoints akun menghasilkan nilai bersih > 0 per $ volume setelah fee → buka H-A4 untuk pra-registrasi.
- Kebenaran angka §2 bisa diverifikasi ulang: tarik ulang kedua endpoint ticker; semua hitungan memakai kolom
  `fundingRate`, `askPx`, `bidPx`, `markPx`, `quoteVolume`.

— Hermes Anantara v3 — 2026-10-09
