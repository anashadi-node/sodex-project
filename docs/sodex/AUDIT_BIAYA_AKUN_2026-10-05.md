# Audit Biaya Akun Nyata & Paper Test — 2026-10-05

> Dokumen ini adalah **hasil audit read-only**: tidak ada kredensial yang ditampilkan,
> tidak ada lane live yang disentuh, tidak ada gate/leverage/sizing/target yang diubah.
> Semua angka dapat diperiksa ulang dengan perintah di §9.

---

## 0. Ringkasan untuk yang sibuk

| # | Temuan | Angka |
|---|---|---|
| 1 | **Fee yang diasumsikan harness BENAR** | Hyperliquid dibaca langsung dari akun: cross **0,045%/sisi**, add **0,015%/sisi** = persis asumsi. Binance tidak bisa dibaca (kunci ditolak) → tier VIP0 sesuai volume ~0 |
| 2 | **Biaya tahan (holding) salah 16,6×** | Asumsi **0,4000%/24 jam** vs funding nyata **0,0240%/24 jam** (24.123 titik, 11 simbol, 2023-10→2025-09) |
| 3 | **Dua cacat model biaya** | (C-1) ambang anggaran dilebih-lebihkan **0,376 poin persen**; (C-2/F-2) deret net **tidak pernah** dibebani funding, dan kontrol **undercharge 0,10%** round-trip (bias **melawan** mesin) |
| 4 | **Paper test nyata: laba E1 = satu pair, satu bulan** | E1 +85,25 **seluruhnya** dari PEPE/USDC Juni (+88,42); tanpa itu **−3,17**. 98% fill E1 = **MAKER** (artefak simulator) |
| 5 | **Fee memakan 93% bruto paper test** | fee nyata **455,55** vs net **32,60** → bruto ≈ 488,15 |
| 6 | **Spread nyata SoDEX sangat kecil** | median **1,71 bp** (0,0171%) → biaya taker **0,0086%/sisi** (24 jam buku L1, 77 simbol) |
| 7 | **Setelah biaya dikoreksi, penghambat bergeser ke STATISTIK** | di tier `bar`/`hl4h`, H13b/H13c kini **lolos anggaran** + mengalahkan kontrol, tapi tetap gagal **BH-FDR** → putusan tetap 0/12 |
| 8 | **Lead baru (EKSPLORASI, belum boleh dipakai)** | tape nyata SoDEX: arah **momentum** +3,3…+4,7%/24 jam — n tidak independen (≤3 episode), **tidak lolos BH-FDR** |
| 9 | **Mesin terkuat yang pernah diukur: Alpaca B5 ETF momentum** | **456.499 trade · 56 tahun tanggal NYATA · t=+25,69 · tidak terkonsentrasi · positif di 45/56 tahun** — tapi edge hanya **+0,0237%/trade** |
| 10 | **BOTTLENECK SEBENARNYA = magnitudo edge per-trade** | target 0,8%/48 jam butuh edge **0,4–0,8%/trade**; mesin terbaik 0,024% → **17–33× kurang**. Menutupnya butuh **leverage 18× = DILARANG** |
| 11 | **BUG-8 ditemukan & diperbaiki** | lama tahan terimplementasi **hb−1 bar** → tier `hl1d` tahan **0 jam** (3 dari 41 evaluasi degenerat). Diperbaiki env-gated; **0/12 tetap**, `BH-lulus` tetap kosong |

---

## 1. Metode (read-only, dapat diaudit)

| Sumber | Cara | Batas |
|---|---|---|
| Tarif Hyperliquid | `POST api.hyperliquid.xyz/info {"type":"userFees"}` (publik) | — |
| Saldo/posisi HL | `{"type":"clearinghouseState"}` | — |
| Tarif Binance | `GET fapi/v1/commissionRate` (signed) | **ditolak 401** |
| Funding Binance | `GET fapi/v1/fundingRate` (publik, tanpa kunci) | 2023-10-01 → 2025-09-30 |
| Buku L1 SoDEX | `data/sodex_book_recorder.db` (mode=ro) | 2026-08-01 23:08 → 08-02 23:08 (24 jam) |
| Tape SoDEX | `data/sodex_public_trades.db` (mode=ro) | 2026-07-30 23:08 → 08-02 23:08 (3 hari) |
| Paper test | `twin_engine.db` (mode=ro) | 2026-06-12 → 2026-09-29 |

---

## 2. Tarif akun nyata

### 2.1 Hyperliquid — dibaca dari akun, bukan dari ingatan

```
userCrossRate = 0.00045   (0,0450% per sisi — menyeberang/market)
userAddRate   = 0.00015   (0,0150% per sisi — menambah likuiditas/limit pasif)
volume 14 hari user = 0    → TINGKAT DASAR (retail, bukan VIP, bukan market maker)
activeReferralDiscount = 0.0  · activeStakingDiscount = 0.0
```

**Kesimpulan:** asumsi harness `TAKER["hl"]=0.00045`, `MAKER["hl"]=0.00015` **cocok persis**.

**Tangga biaya HL (dari akun, untuk pertanyaan "akses eksekusi"):**

| Notional 14 hari | cross | add |
|---|---|---|
| 0 (sekarang) | 0,0450% | 0,0150% |
| 5 juta | 0,0400% | 0,0120% |
| 25 juta | 0,0350% | 0,0080% |
| 100 juta | 0,0300% | 0,0040% |
| **500 juta** | 0,0280% | **0,0000%** |
| 2 miliar | 0,0260% | 0,0000% |
| 7 miliar | 0,0240% | 0,0000% |

Plus diskon staking HYPE hingga **40%** (0,1% supply → 20%; 1% → 30%; 5% → 40%).
Artinya: **"maker gratis" hanya tercapai di 500 juta notional 14 hari** — jauh di luar jangkauan modal saat ini.

### 2.2 Binance USDM — tidak dapat dibaca dari akun

| Percobaan | Hasil |
|---|---|
| `fapi/v2/account` mainnet (signed) | ❌ **HTTP 401 Unauthorized** |
| `fapi/v2/account` testnet futures (signed) | ❌ **HTTP 401 Unauthorized** |
| endpoint publik jadwal fee (2 varian) | ❌ 404 |

**Temuan operasional:** kunci `BINANCE_API_KEY` (64 char, ada) **ditolak venue**. Karena CEX berjalan
`dry_run=true`, ini tidak mengganggu lane paper — tetapi **harus diperbarui sebelum ada rencana
CEX live**. (Sisi baik: kunci mati tidak bisa membocorkan apa pun.)

**Fallback terverifikasi-sebagian:** volume akun ≈ 0 dan tanpa BNB → **VIP0** (jadwal USDM publik:
maker 0,0200% / taker 0,0500%) — sama dengan asumsi harness `TAKER["binance"]=0.0005`,
`MAKER["binance"]=0.0002`. Status: **konsisten, belum terverifikasi dari akun.**

---

## 3. Funding nyata vs asumsi — cacat terbesar yang ditemukan

Sumber: `fapi/v1/fundingRate`, **24.123 titik** (11 simbol × 2.193 settlement 8-jaman),
2023-10-01 → 2025-09-30, cache `data/funding_binance/`.

| Simbol | rata-rata/24 jam | \|rata-rata\|/24 jam | % positif | maks/24 jam |
|---|---|---|---|---|
| BTCUSDT | 0,0260% | 0,0275% | 90,6% | 0,264% |
| ETHUSDT | 0,0279% | 0,0292% | 91,6% | 0,305% |
| SOLUSDT | 0,0244% | 0,0330% | 78,1% | 0,358% |
| BNBUSDT | −0,0066% | 0,0315% | 25,4% | 0,389% |
| XRPUSDT | 0,0296% | 0,0344% | 86,2% | 0,330% |
| DOGEUSDT | 0,0295% | 0,0332% | 86,3% | 0,308% |
| ADAUSDT | 0,0281% | 0,0342% | 86,2% | 0,336% |
| AVAXUSDT | 0,0223% | 0,0364% | 76,2% | **0,431%** |
| LINKUSDT | 0,0291% | 0,0338% | 86,9% | 0,347% |
| DOTUSDT | 0,0231% | 0,0340% | 81,3% | 0,339% |
| LTCUSDT | 0,0312% | 0,0331% | 91,3% | 0,329% |
| **SEMUA** | **0,0240%** | **0,0328%** | **80,0%** | 0,431% |

**Perbandingan:** asumsi harness **0,4000%/24 jam** = **16,6×** rata-rata nyata.
Bahkan **kejadian terburuk** yang teramati (AVAX 0,431%/24 jam) hanya **1,08×** asumsi —
artinya asumsi 0,40% diperlakukan sebagai *kondisi ekstrem permanen*.

Catatan penting: 80% settlement **positif** → arah posisi menentukan siapa yang membayar.
Fade yang menjadi **SHORT** setelah kenaikan justru **menerima** funding; fade yang menjadi
**LONG** setelah penurunan **membayar**. Model datar 0,40% membuang informasi ini.

---

## 4. Dua cacat model biaya (berlawanan arah) dan perbaikannya

### C-1 — Uji anggaran memakai biaya tahan yang salah

`min_gross(slip) = fee_pair + slip + 0,004 × (24/24)` → angka 0,004 inilah yang selama ini
dibaca sebagai "biaya 0,40%" di laporan. Efeknya, ambang "perlu" **dilebih-lebihkan 0,376 poin persen**:

| Tier | Ambang beku | Ambang dengan funding nyata |
|---|---|---|
| Tier-1 (slip 0,248%) | 0,748% | **0,372%** |
| Tier-1 (slip 0,446%) | 0,946% | **0,570%** |
| Tier-1 (slip 0,482%) | 0,982% | **0,606%** |
| Tier-2 (slip 0,02%) | 0,530% | **0,144%** |
| HL 4j/1d (slip 0,02%) | 0,530% | **0,154%** |

### C-2 (F-2) — Net tanpa funding + kontrol undercharge

Dua sub-cacat pada **deret net** (bukan pada uji anggaran):

1. **Funding tidak pernah dibebankan.** `net[f] -= P_` dan `net[g] -= P_` dengan `P_` = fee taker
   per sisi. Tidak ada suku funding sama sekali → seluruh `mean48`/`SR` yang terbit **optimistis**
   sebesar biaya funding nyata (≈0,024%/hari tahan, berarah).
2. **Kontrol dibebani lebih murah dari mesin.** Kontrol membayar `SLIP_BAR` (0,02%) per sisi,
   sedangkan mesin membayar **slippage + fee taker 0,05%** per sisi → kontrol **undercharge
   0,10% round-trip**. Arah bias: **melawan mesin** (kontrol jadi tampak lebih kuat dari sebenarnya),
   sehingga `control_p = 1,00` yang terbit sebagian adalah artefak.

### Perbaikan — env-gated, **default tidak berubah**

```python
R4D_FAIR=1        # (a) kontrol bayar fee yang SAMA dengan mesin
                  # (b) funding NYATA berarah dibebankan di mesin DAN kontrol
R4D_HOLD_COST=…   # biaya tahan per 24 jam untuk uji anggaran (0,000240 = terukur)
```

Bukti default tetap = spesifikasi beku `d63e7ee`:

```
DEFAULT : FAIR=False USE_FUNDING=False HOLD_COST=0.004   min_gross(0,248%) = 0,007480  ← beku
FAIR=1  : FAIR=True  USE_FUNDING=True  HOLD_COST=0.00024 min_gross(0,248%) = 0,003720
```

Hasil FAIR ditulis ke berkas **terpisah** (`reports/sodex/R4D_*_fair_results.json`) supaya
rekam jejak hasil beku tidak tertimpa.

---

## 5. Dampak pada putusan (jalankan ulang dengan biaya yang benar)

Empat tier dijalankan ulang dengan `R4D_FAIR=1` (F-2 + funding nyata). Hasil di berkas
`reports/sodex/R4D_*_fair_results.json`; hasil beku **tidak ditimpa**.

| Tier | Mesin | mean48 | SR | seg+ | trade | bruto | perlu (FAIR) | anggaran | ctrl_p | BH | Putusan |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **t1** | H13a | −0,0633% | −0,58 | 0/3 | 1.203 | −0,722% | 0,372% | TIDAK | 1,0000 | — | FAIL |
| **t1** | H13b | −0,0467% | −0,55 | 1/3 | 320 | −1,250% | 0,570% | TIDAK | 1,0000 | — | FAIL |
| **t1** | H13c | −0,0096% | −0,20 | 1/3 | 77 | −0,166% | 0,606% | TIDAK | 0,0050 | — | FAIL |
| bar | H13a | +0,0547% | +0,59 | 2/3 | 1.675 | −0,086% | 0,164% | TIDAK | 0,0050 | — | FAIL |
| bar | H13b | +0,0490% | +0,58 | 2/3 | 502 | **+0,567%** | 0,164% | **OK** | 0,0050 | — | FAIL |
| bar | H13c | +0,0099% | +0,22 | 2/3 | 114 | **+0,313%** | 0,164% | **OK** | 0,0050 | — | FAIL |
| hl4h | H13a | +0,0274% | +0,45 | 2/3 | 657 | −0,156% | 0,154% | TIDAK | 1,0000 | — | FAIL |
| hl4h | H13b | −0,0178% | −0,34 | 1/3 | 272 | −1,147% | 0,154% | TIDAK | 1,0000 | — | FAIL |
| hl4h | H13c | +0,0619% | +0,92 | 2/3 | 98 | **+2,756%** | 0,154% | **OK** | 0,0050 | — | FAIL |
| hl1d | H13a | −0,0093% | −0,36 | 1/3 | 446 | +0,036% | 0,154% | TIDAK | 1,0000 | — | FAIL |
| hl1d | H13b | −0,0383% | −1,17 | 1/3 | 363 | −0,461% | 0,154% | TIDAK | 1,0000 | — | FAIL |
| hl1d | H13c | −0,0322% | −0,80 | 0/3 | 225 | −0,683% | 0,154% | TIDAK | 1,0000 | — | FAIL |

PBO: t1 0,5952 · bar 0,5635 · hl4h 0,0992 · hl1d 0,2579. **BH-lulus = ∅ di semua tier.**

**Tiga kesimpulan dari tabel ini:**

1. **Putusan tidak berubah: 0/12 lulus.** Bahkan dengan ambang anggaran yang lebih rendah
   (t1 0,748% → **0,372%**; Tier-2/HL 0,530% → **0,154%**), tidak ada mesin yang lulus.
2. **Efek funding kecil, efek kontrol besar.** Membebankan funding menggeser `mean48` hanya
   ≤0,001 poin persen (funding nyata 0,024%/24 jam), tetapi F-2 menggeser `perlu` **0,376 poin
   persen** — jadi cacat yang signifikan adalah **C-1/F-2**, bukan arah funding.
3. **Penghambat bergeser dari BIAYA ke STATISTIK (temuan baru yang penting).** Di tier `bar`
   dan `hl4h`, H13b dan H13c sekarang **lolos uji anggaran** (bruto +0,567%/+0,313%/+2,756% vs
   perlu 0,164%/0,154%) **dan mengalahkan kontrol** (ctrl_p 0,0050), **tetapi tetap gagal**
   karena bukti statistiknya lemah: SR 0,22–0,92, segmen tidak stabil, dan **tidak lolos BH-FDR**.

> Artinya: kekeliruan biaya selama ini **menyembunyikan** fakta bahwa beberapa sel sudah
> "cukup murah" tetapi **belum cukup kuat**. Menghapus cacat biaya tidak membuka pintu;
> ia hanya memindahkan alasan penolakan dari "terlalu mahal" menjadi "tidak signifikan".

---

## 6. Paper test nyata (`twin_engine.db`, 2026-06-12 → 2026-09-29)

### 6.1 Angka dasar

| Mesin | n round-trip | menang | rata-rata net | t-stat | total net | fill | % maker |
|---|---|---|---|---|---|---|---|
| **E1** | 13.092 | **93,1%** | +0,00651 | **+49,60** | **+85,25** | 63.638 | **98,3%** |
| E2 | 605 | 3,5% | −0,05934 | −32,46 | −35,90 | 3.368 | 100% |
| PVE | 1.594 | 53,8% | −0,01051 | −1,30 | −16,76 | 3.188 | 9,6% |
| **SEMUA** | **15.291** | 85,5% | +0,00213 | +2,47 | **+32,60** | 70.194 | — |

### 6.2 Biaya nyata yang sudah dibayar

| | nilai |
|---|---|
| total fee | **455,55** |
| total notional | 2.500.097 |
| biaya efektif | **0,0182%** dari notional |
| net_pnl | **+32,60** |
| bruto sebelum fee | **≈ +488,15** |
| **fee / bruto** | **93,3%** |

### 6.3 E1: t=+49,6 yang ternyata rapuh

| Potongan | n | rata-rata | total |
|---|---|---|---|
| E1 seluruhnya | 13.092 | +0,00651 | +85,25 |
| E1 **PEPE/USDC saja** | 12.652 | +0,00699 | **+88,42** |
| E1 **tanpa PEPE/USDC** | 440 | **−0,00719** | **−3,17** |
| E1 bulan 2026-06 | 12.767 | +0,00682 | +87,09 |
| E1 bulan 2026-09 | 325 | **−0,00564** | **−1,83** |

Tiga tanda sekaligus menunjukkan **artefak simulator**, bukan edge:

1. **97% trade = satu pair** (PEPE/USDC) dalam **satu bulan** (Juni).
2. **98,3% fill E1 adalah MAKER** — simulator mengisi limit pasif tanpa posisi antrian dan
   tanpa *adverse selection*; ini persis pelajaran yang sudah dibayar mahal di R4-C (H11–H12).
3. **Berbalik negatif** di bulan berikutnya (−1,83) ketika pair berganti.

### 6.4 PVE: churn tanpa waktu tahan

PVE 90% taker dengan durasi round-trip **≈0 detik** (masuk dan keluar hampir bersamaan) —
yaitu memutar spread + fee, dan hasilnya **−16,76**. E2 (100% maker) bahkan lebih buruk: menang
hanya **3,5%** dari waktu.

### 6.5 Putusan paper test

> Paper test **tidak menghasilkan edge yang dapat dipercaya**. Satu-satunya mesin yang positif
> (E1) bergantung pada (a) satu pair, (b) satu bulan, dan (c) asumsi fill maker tanpa
> adverse selection. Yang tersisa setelah biaya nyata adalah **+32,60** dari bruto **+488,15**
> — fee memakan **93%**. Ini konsisten dengan temuan riset: **constraint = eksekusi, bukan sinyal.**

---

## 7. Spread nyata SoDEX (buku L1, 24 jam, 77 simbol)

| Statistik | Nilai |
|---|---|
| median spread semua simbol | **1,71 bp** (0,0171%) |
| p90 spread | 11,44 bp |
| **biaya taker = setengah spread (median)** | **0,0086% per sisi** |
| paling sempit | SNDK 0,08 bp → 0,0004%/sisi |
| paling lebar | EWY 34,30 bp → 0,1715%/sisi |

**Catatan kejujuran (penting):** angka ini **bukan** pembanding langsung untuk "slippage terukur
0,248–0,482%" di R4-D. Keduanya mengukur hal berbeda:

- **setengah spread** = biaya langsung menyeberang (1,7 bp median),
- **slippage 1-menit terukur** = perpindahan harga yang *merugikan* selama eksekusi pada bar kejadian ekstrem (0,248–0,482%).

Keduanya bisa benar bersamaan: spread tipis, tetapi saat kejadian ekstrem harga bergerak melawan
posisi Anda dalam hitungan detik. Yang **tidak** boleh lagi diklaim: bahwa "biaya taker di SoDEX
mahal karena spread". Datanya menunjukkan sebaliknya.

---

## 7b. Simulasi pada TAPE NYATA SoDEX (3 hari, 20 simbol) — biaya dari buku nyata

Skrip: `scripts/sodex_tape_fade_sim.py` (read-only). Kejadian: |return 1 jam| ≥ θ. Masuk pada
trade pertama setelah bar kejadian, **menyeberang setengah spread nyata** (median 0,34–0,67 bp
dari buku L1); tahan 24 jam; keluar menyeberang lagi; fee 2 sisi.

| Arah | θ | n | net | bruto | menang | ctrl (acak) | p |
|---|---|---|---|---|---|---|---|
| **fade** (melawan) | 1,5% | 44 | **−3,35%** | −3,33% | 20,5% | −0,27% | 0,925 |
| **fade** | 2,0% | 21 | **−4,05%** | −4,02% | 4,8% | −0,46% | 0,928 |
| **fade** | 3,0% | 9 | **−4,15%** | −4,13% | 11,1% | −0,37% | 0,933 |
| **momentum** (searah) | 1,5% | 44 | **+3,28%** | +3,30% | 79,5% | +0,38% | 0,094 |
| **momentum** | 2,0% | 21 | **+3,98%** | +4,00% | 95,2% | +0,20% | 0,059 |
| **momentum** | 3,0% | 9 | **+4,09%** | +4,11% | 88,9% | +0,20% | 0,068 |
| **momentum** | 5,0% | 1 | +4,68% | +4,70% | 100% | +0,35% | 0,058 |

**Yang boleh dikatakan:**

- Biaya **bukan** penghambat di sini: setengah spread nyata hanya 0,34–0,67 bp, jadi bruto ≈ net.
- Arah **fade** di venue ini, pada jendela ini, **kalah jauh bahkan sebelum biaya** (−3,3% s.d. −4,1%).
- Arah **momentum** justru positif besar dan mengalahkan kontrol acak.

**Yang TIDAK boleh dikatakan (batas keras):**

- **Ini EKSPLORASI — bukan uji hipotesis.** Angka ini **tidak boleh** menjadi dasar putusan
  atau perubahan sistem tanpa pra-registrasi.
- **n kecil dan tidak independen.** Hold 24 jam pada tape 3 hari → jendela saling bertumpuk;
  jumlah episode independen paling banyak **3**, bukan 44/21/9.
- **Multiplisitas.** 16 varian diuji; p terkecil 0,0475 **tidak lolos** BH-FDR
  (ambang BH untuk uji terkecil dari 16 pada q=0,10 = 0,00625).
- **Satu rezim, satu venue, 20 simbol** (termasuk saham ter-tokenisasi) — tidak dapat digeneralisasi.
- Arah momentum berlawanan dengan temuan eksplorasi Binance (fade ≈ +0,6%/24 jam sebelum biaya),
  sehingga **venue dan simbol jelas memengaruhi arah**.

**Tindak lanjut yang benar:** pra-registrasi uji momentum pada tape SoDEX **forward**
(minimum 30 hari, n≥30 episode independen), sebelum satu baris kode produksi disentuh.

---

## 7c. Paper/replay Alpaca — 456.499 trade, 56 tahun (temuan terkuat sejauh ini)

Sumber: `data/alpaca/paper_trades.jsonl` (215,7 MB), skrip `scripts/alpaca_paper_replay_audit.py`.
Mesin: `B5_REGIME_MOMENTUM`, sumber `alpaca_etf_momentum_next_bar_paper`, 95 simbol ETF/saham AS.

**Tanggalnya NYATA, bukan sintetis** — dibuktikan dengan hari-hari krisis historis:

| Tanggal | Peristiwa | Return portofolio hari itu |
|---|---|---|
| 1987-10-19 | Black Monday | **−4,42%** |
| 2020-03-12 | COVID crash | −1,32% |
| 2022-06-13 | bear 2022 | −1,20% |
| 2020-03-16 | COVID crash | −0,72% |
| 2008-10-10 | krisis 2008 | −0,29% |

### Statistik per-trade (n besar, dan **lolos uji konsentrasi yang mematikan E1**)

| Metrik | Nilai |
|---|---|
| n | **456.499** (95 simbol) |
| menang | 50,65% |
| **net per trade** | **+0,02373%** |
| bruto per trade | +0,02511% |
| biaya per trade | 0,00138% (sangat kecil — ETF komisi-nol + spread tipis) |
| **t-stat** | **+25,69** (CI95 +0,0219% … +0,0255%) |
| tanpa 5 simbol teratas | +0,02268% (n=422.994) → **TIDAK terkonsentrasi** |
| periode positif | **45 dari 56** tahun |
| periode negatif | 1973-74, 1977, 1988, 1994, 2000-02, 2008, 2015, 2022 → **rezim bear** (masuk akal) |

**Kalibrasi probabilitas: GAGAL.**

| Metrik | Nilai | Ambang |
|---|---|---|
| rata-rata `predicted_probability` | 0,6031 | — |
| akurasi aktual | 0,5065 | — |
| **overconfident** | **+0,0966** | — |
| ECE | 0,0966 | target <0,10 → **mepet, hampir gagal** |
| Brier sejati | **0,2594** | >0,25 = **lebih buruk dari tebakan konstan 0,5** |

Artinya: *seleksi trade*-nya punya edge, tetapi *angka probabilitasnya* tidak layak dipakai
untuk sizing posisi. Dua hal ini harus dipisahkan.

---

## 7d. Bottleneck sebenarnya: **magnitudo edge per-trade** (temuan inti sesi ini)

Seluruh investigasi sebelumnya berfokus pada **biaya**. Setelah biaya dikoreksi (§5), dan setelah
mesin terbaik diukur pada n=456k (§7c), hambatan sesungguhnya terlihat jelas:

> Pada portofolio **equal-weight yang selalu penuh**, return harian ≈ **edge per-trade**.
> Jadi target **0,8% per 48 jam** membutuhkan **edge per-trade ≈ 0,4–0,8%** — bukan 0,02%.

| Lama tahan | Trade penuh per 48 jam | Edge per-trade yang **dibutuhkan** | Mesin terbaik sekarang (0,024%) |
|---|---|---|---|
| 1 hari | 2,0 | **0,40%** | **17× kurang** |
| 2 hari | 1,0 | **0,80%** | **33× kurang** |
| 5 hari | 0,4 | **2,00%** | **83× kurang** |

Portofolio equal-weight Alpaca B5 yang terukur = **+0,0436% / 48 jam** → untuk mencapai 0,8%
diperlukan **18,35×** (leverage 18×, **DILARANG** oleh batas keamanan).

**Perbandingan semua mesin yang pernah diuji:**

| Mesin | Edge per-trade (bruto/net) | Status |
|---|---|---|
| **Alpaca B5 ETF momentum** | **+0,0237% net** (t=+25,7, n=456k) | nyata tapi **17–33× kurang** |
| R4-D H13a/b/c fade Binance | −0,72% / −1,25% / −0,17% bruto | **negatif** |
| R4-C maker H11/H12 | −0,19% / +0,39% / +1,06% bruto | 9/9 FAIL (adverse selection) |
| R4-B H8 carry funding | +0,40% bruto, SR 2,65, 136 trade | n<20, PBO 0,29 → FAIL |
| twin_engine E1 (paper SoDEX) | +0,0065%/round-trip | artefak fill MAKER |

**Kesimpulan bottleneck:** constraint bukan sinyal, bukan fee, bukan spread, bukan eksekusi —
melainkan **magnitudo edge per-trade relatif terhadap target**. Semua mesin yang ditemukan
memiliki edge 0,02% (terbaik) sampai negatif, sedangkan target menuntut 0,4–0,8%.

Implikasi (tanpa mengubah target, karena target = harga mati):

1. Cari mesin dengan **pergerakan per-trade 10–30× lebih besar** (swing 3–8%, bukan 0,3–1%),
   dengan bukti OOS yang lolos BH — bukan menambah jumlah trade kecil.
2. Atau naikkan jumlah **trade penuh non-tumpang-tindih** per 48 jam (butuh edge frekuensi tinggi
   yang lolos fee — jalur ini sudah 9/9 gagal di R4-C).
3. **Leverage bukan jawaban** (dilarang) dan **mengubah target bukan wewenang agen**.

---

## 7e. BUG-8 — lama tahan terimplementasi **kurang satu bar** (ditemukan dari log tier `hl1d`)

Ditemukan saat memeriksa ulang log run FAIR. Kode keluar-waktu memakai
`g_exit = min(f + hb - 1, n-1)` sedangkan `hb = HOLD_H // BAR_H` — jadi posisi ditahan
**hb−1 bar**, bukan hb bar:

| Tier | `BAR_H` | `hb` | lama tahan nyata (beku) | seharusnya |
|---|---|---|---|---|
| `t1` / `bar` | 1 | 24 | 23 jam | 24 jam |
| `hl4h` | 4 | 6 | **20 jam** | 24 jam |
| **`hl1d`** | 24 | 1 | **0 jam** | 24 jam |

Untuk grid harian (`hl1d`), `hb = 1` → `g = f` → **posisi masuk dan keluar di bar yang sama**.
Itu menjelaskan mengapa hasil `hl1d` beku hampir nol (mean48 −0,0093/−0,0383/−0,0322%;
laju stop 8,9/13,7/21,2%) — yang terukur hanyalah biaya masuk-keluar, bukan tahan 24 jam.
**Jadi 3 dari 41 evaluasi yang dilaporkan sebelumnya (seluruh tier `hl1d`) adalah pengukuran
degenerat** dan tidak boleh dihitung sebagai uji "tahan 24 jam".

Perbaikan bersifat **env-gated** (`R4D_HOLD_EXACT=1` → tahan tepat `hb` bar = 24 jam di semua
tier); **default tetap perilaku beku** agar rekam jejak lama tetap dapat direproduksi.
Hasil terkoreksi ditulis terpisah: `reports/sodex/R4D_*_fair_hold_results.json`.

Perbandingan putusan (**`R4D_FAIR=1 R4D_HOLD_EXACT=1`** — biaya terkoreksi + tahan 24 jam sejati;
keluaran `reports/sodex/R4D_*_fair_hold_results.json`):

| Tier | H13a | H13b | H13c | BH-lulus | PBO | Putusan |
|---|---|---|---|---|---|---|
| `t1` | −0,0751% TIDAK (bruto −0,988%) | −0,0505% TIDAK (bruto −1,841%) | −0,0153% TIDAK (bruto −2,742%) | kosong | 0,5754 | 0/3 |
| `bar` | +0,0459% TIDAK (bruto −0,272%) | +0,0461% **anggaran OK** (bruto +0,594%) | +0,0061% TIDAK (bruto −0,334%) | kosong | 0,4762 | 0/3 |
| `hl4h` | +0,0255% TIDAK (bruto −0,287%) | −0,0106% TIDAK (bruto −0,988%) | +0,0418% **anggaran OK** (bruto +2,001%) | kosong | 0,1984 | 0/3 |
| `hl1d` | −0,0183% TIDAK (bruto −0,345%) | −0,0572% TIDAK (bruto −0,806%) | −0,0528% TIDAK (bruto −1,211%) | kosong | 0,3056 | 0/3 |

**Putusan: 0/12 di keempat tier, `BH-lulus` kosong di semua** — hasil sebelumnya **robust**
terhadap BUG-8, jadi angka kumulatif **41 evaluasi · 0 lulus** tetap sah.

Perhatikan: dengan tahan 24 jam sejati, tier `t1` justru **memburuk** dibanding versi tahan
23 jam (H13a −0,0633% → **−0,0751%**; bruto −0,722% → **−0,988%**; H13c bruto −0,166% →
**−2,742%**). Eksekusi 1-menit pada kejadian ekstrem memang yang paling mahal.

Bukti bahwa tier `hl1d` lama memang degenerat: dengan tahan 24 jam sejati, laju stop naik
dari 8,9/13,7/21,2% (tahan 0 jam) menjadi **17,5/24,2/33,1%**, dan bruto per trade berbalik
negatif (+0,036/−0,461/−0,683% → **−0,345/−0,806/−1,211%**). Versi degenerat **mempercantik**
hasil, bukan menutupinya.

Catatan: perbaikan lama-tahan **tidak menyelamatkan** apa pun — bruto per trade justru memburuk
di `bar` (H13a −0,086% → −0,272%; H13c +0,313% → −0,334%). Konsisten dengan temuan §7d:
hambatannya **magnitudo edge**, bukan lama tahan, bukan biaya.

---

## 8. Kesimpulan

1. **Fee: asumsi harness benar.** HL terverifikasi dari akun (0,045%/0,015%); Binance VIP0 sesuai volume 0.
2. **Biaya tahan: asumsi 0,40%/24 jam salah 16,6×.** Angka terukur 0,0240%/24 jam; ambang "perlu"
   yang terbit dilebih-lebihkan 0,376 poin persen.
3. **Kontrol lebih murah dari mesin (F-2)** → sebagian `control_p = 1,00` adalah artefak.
4. **Paper test tidak punya edge yang bertahan**; labanya satu pair satu bulan dengan fill maker,
   dan fee memakan 93% bruto.
5. **Spread SoDEX tipis (1,7 bp median)** → hambatan bukan spread, melainkan *adverse selection*
   saat kejadian (konsisten dengan R4-C/R4-D).
6. **Yang benar-benar menghalangi target 0,8%/48 jam bukan sinyal dan bukan fee, melainkan
   akses eksekusi**: pada akun sekarang, biaya taker HL 0,045%/sisi dan Binance 0,05%/sisi adalah
   tingkat retail; "maker gratis" butuh 500 juta notional 14 hari.
7. **Setelah biaya dikoreksi, penghambat bergeser ke STATISTIK.** Di tier `bar` dan `hl4h`,
   H13b/H13c kini lolos anggaran **dan** mengalahkan kontrol, tetapi tetap gagal BH-FDR/segmen.
   Jadi menghapus cacat biaya **tidak** membuka pintu — ia hanya mengubah alasan penolakan.
8. **Lead baru (EKSPLORASI, belum boleh dipakai):** pada tape nyata SoDEX, arah **momentum**
   (bukan fade) setelah kejadian ≥1,5% memberi +3,3% s.d. +4,7% per 24 jam dengan biaya nyata
   yang sangat kecil. Batas keras: n tidak independen (≤3 episode), tidak lolos BH-FDR,
   satu rezim. **Wajib pra-registrasi uji forward ≥30 hari sebelum dipakai.**
9. **Mesin terkuat yang pernah diukur** = Alpaca B5 ETF momentum: 456.499 trade, 56 tahun
   tanggal nyata, t=+25,69, tidak terkonsentrasi, positif di 45/56 tahun (negatif hanya di rezim
   bear) — **tetapi probabilitasnya tidak terkalibrasi** (Brier 0,2594 > 0,25; overconfident 9,7 pp).
10. **BOTTLENECK SEBENARNYA (temuan inti): magnitudo edge per-trade.** Target 0,8%/48 jam
    menuntut edge per-trade **0,4–0,8%**; mesin terbaik yang ada hanya **0,024%** → **17–33×
    kurang**. Menutup celah itu tanpa edge lebih besar berarti **leverage ~18× — DILARANG**.
    Jadi constraint bukan lagi sinyal/fee/spread/eksekusi, melainkan **skala pergerakan per trade**.

11. **BUG-8 (integritas pengukuran):** lama tahan terimplementasi **hb−1 bar**, sehingga tier
    `hl1d` (grid harian) menahan posisi **0 jam** — masuk-keluar di bar yang sama. Ketiga
    evaluasi tier itu (dari 41) **degenerat** dan versi degeneratnya justru *mempercantik* hasil.
    Diperbaiki env-gated (`R4D_HOLD_EXACT=1`), default beku tetap reproducible (terbukti
    byte-identik), dan dengan tahan 24 jam sejati putusan tetap **0/12** dengan `BH-lulus` kosong.


### Rekomendasi (tanpa mengubah target — target adalah harga mati)

| Prioritas | Aksi | Alasan kuantitatif |
|---|---|---|
| 1 | Cari mesin dengan **pergerakan per-trade 10–30× lebih besar** (swing 3–8%), bukan menambah trade kecil | target butuh 0,4–0,8%/trade |
| 2 | Pra-registrasi uji **momentum SoDEX forward** (≥30 hari, n≥30 episode independen) — **blokir: recorder tape SoDEX berhenti 2026-08-03** | satu-satunya lead arah baru yang positif |
| 3 | Perbaiki **kalibrasi** probabilitas mesin (ECE 0,0966 / Brier 0,2594) sebelum dipakai untuk sizing | sizing berbasis p yang overconfident 9,7 pp |
| 4 | Perbarui kunci Binance sebelum ada rencana CEX live | kunci sekarang ditolak 401 |
| — | **JANGAN** menaikkan leverage untuk menutup celah 18× | dilarang batas keamanan |

---

## 9. Cara memeriksa ulang

```bash
cd ~/anantara-sakti
.venv-research/bin/python3 scripts/download_funding_binance.py     # funding (publik)
R4D_TIER=t1 R4D_FAIR=1 .venv-research/bin/python3 scripts/r4d_harness.py   # putusan terkoreksi
.venv-research/bin/python3 -c "import sqlite3;c=sqlite3.connect('file:twin_engine.db?mode=ro',uri=True);print(c.execute('SELECT engine,COUNT(*),ROUND(AVG(CAST(net_pnl AS REAL)),5) FROM rts GROUP BY engine').fetchall())"
.venv-research/bin/python3 -c "import sqlite3;c=sqlite3.connect('file:data/sodex_book_recorder.db?mode=ro',uri=True);print(c.execute('SELECT COUNT(*),AVG((ask-bid)/((ask+bid)/2)*10000) FROM l1 WHERE bid>0 AND ask>bid').fetchone())"
```

**Berkas terkait:** `scripts/download_funding_binance.py` · `scripts/r4d_harness.py` (env `R4D_FAIR`, `R4D_HOLD_COST`) ·
`data/funding_binance/` (24.123 titik + MANIFEST) · `reports/sodex/R4D_*_fair_results.json` ·
`docs/sodex/R4D_PROTOKOL_H13_2026-10-05.md` (spesifikasi beku, tidak diubah).
