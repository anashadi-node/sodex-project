# STRUKTUR BIAYA EKSEKUSI SoDEX — PENGUKURAN (read-only, tanpa order)

**Tanggal:** 2026-10-07 · **Metode:** endpoint publik + dokumentasi venue + verifikasi silang kode produksi repo
**Sifat:** pengukuran biaya. **Tidak ada order dikirim. Tidak ada parameter/target yang diubah.**

---

## 1. Mengapa ini dilakukan

Bind constraint yang terbukti (R4B, 5 Okt) = **edge bersih per mesin**, dan biaya adalah
komponen yang bisa dikurangi tanpa menemukan alpha baru. Seluruh riset mekanisme sebelumnya
memakai **taker 4 bps/sisi** dan **tidak pernah memodelkan maker**, spread, atau kedalaman.
Itu celah terbesar yang belum tergarap.

## 2. Spread & kedalaman live (sensus 92 simbol perps, endpoint tickers publik)

| Statistik spread efektif (ask−bid)/mid | bps |
|---|---:|
| median | **1,32** |
| mean | 2,21 |
| Q1 / Q3 | 0,54 / 2,67 |
| ≤2 bps / ≤5 bps | 63 / 83 simbol (dari 92) |

| Simbol teraktif | spread | kedalaman top-of-book | quoteVolume |
|---|---:|---:|---:|
| BTC-USD | **0,12 bps** | $37.536 | 85,6 jt |
| ETH-USD | **0,39 bps** | $50.712 | 84,9 jt |
| SOL-USD | 0,86 bps | $31.794 | 2,1 jt |
| US500-USD | 0,13 bps | $163 | 2,5 jt |
| XAUT-USD | 0,24 bps | $13.673 | 1,7 jt |

**Kesimpulan spread: eksekusi BUKAN penyumbatnya.** Spread majors SoDEX (0,12–0,39 bps)
setara venue besar. Median 1,32 bps juga tipis.

## 3. Struktur fee resmi (dokumentasi venue, `sodex.com/documentation/trading-mechanics/trading-fees`)

Tier ditentukan **volume 14 hari bergulir**, diselesaikan harian (UTC), satu tier untuk semua pasar.
Volume perps + 2× volume spot digabung.

| Tier | Volume 14D | Perps **Taker** | Perps **Maker** | Spot Taker | Spot Maker |
|---|---|---:|---:|---:|---:|
| 0 | ≤ $5 jt | 0,040% (4,00 bps) | 0,012% (1,20 bps) | 0,065% | 0,035% |
| 1 | > $5 jt | 0,036% | 0,010% | 0,055% | 0,025% |
| 2 | > $25 jt | 0,032% | 0,006% | 0,045% | 0,015% |
| 3 | > $100 jt | 0,028% | 0,002% | 0,035% | 0,005% |
| 4 | > $500 jt | 0,026% | **0,000%** | 0,030% | 0,000% |

**Diskon staking SOSO:** 5% (≥30 SOSO) · 10% (≥300) · 15% (≥3.000) · 20% (≥30.000) · 30% (≥300.000) · 40% (≥1.500.000).

**Maker Rebate** (jika share volume maker 14D melewati ambang — menggantikan fee maker):

| Tier | Share maker 14D | Fee Maker |
|---|---|---:|
| 1 | > 0,50% | **−0,001% (−0,10 bps)** |
| 2 | > 1,50% | −0,002% |
| 3 | > 3,00% | −0,003% |

Dibayar kontinu langsung ke wallet trading. **Catatan jujur: rebate hanya −0,1…−0,3 bps — bukan jackpot.**

## 4. Fee NYATA akun ini (bukan asumsi)

`anantara/sodex_farming.py` baris 8 menyatakan akun ini punya **maker fee 0,0114% = 1,14 bps**, dan
baris 3199 memakai model komposit **`maker 1,14 bps / taker 3,80 bps`**. Jadi kode produksi repo
sudah memakai maker; hanya **riset** yang belum.

**Asumsi riset saya sebelumnya (taker 4,00 bps) = benar untuk tier 0 taker.** Yang salah bukan
angkanya, melainkan **tidak pernah menguji mode maker sama sekali**.

Terverifikasi di harness (`xsec_mech_study` baris 229–232):
`to = Σ|w_t − w_{t−1}|` dan `net = gross − to × fee_oneway`. Jadi `fee_oneway` = fee per sisi
dan `turnover × fee` = biaya per periode. **Konvensi sah.**

## 5. EKONOMI: efek fee pada mekanisme terbaik (reversal, PRAREG-4, **DESKRIPTIF**)

Net per 48 jam (bps) dan % target 80 bps. Taker dikenai setengah spread median (0,66 bps);
maker tidak membayar dan tidak mengambil spread (**konservatif**).

| hold | bruto/48j | turnover | taker 4,00 | taker 3,80 | **MAKER 1,14** | rebate −0,10 |
|---:|---:|---:|---:|---:|---:|---:|
| **1 jam** | 92,66 | 0,51 | −22,1 (−28%) | −17,1 (−21%) | **+64,6 (81%)** | +95,1 (119%) |
| 2 jam | 53,77 | 0,67 | −21,5 (−27%) | −18,2 (−23%) | +35,4 (44%) | +55,4 (69%) |
| 4 jam | 32,97 | 0,85 | −14,7 (−18%) | −12,7 (−16%) | +21,3 (27%) | +34,0 (42%) |
| 8 jam | 15,43 | 1,04 | −13,7 (−17%) | −12,5 (−16%) | +8,3 (10%) | +16,1 (20%) |
| 12 jam | 8,85 | 1,20 | −13,5 (−17%) | −12,6 (−16%) | +3,4 (4%) | +9,3 (12%) |
| 24 jam | 23,36 | 1,32 | +11,1 (14%) | +11,6 (15%) | +20,4 (25%) | +23,6 (30%) |
| 48 jam | 16,93 | 1,31 | +10,8 (14%) | +11,1 (14%) | +15,4 (19%) | +17,1 (21%) |

### Tiga hal yang dibaca dari tabel ini

1. **Eksekusi, bukan sinyal, adalah pembeda antara "gagal" dan "81% target".** Di hold 1 jam,
   arah reversal **RUGI −28%** dengan taker tapi **UNTUNG +81%** dengan maker. Sinyalnya identik.
2. **Hold 1 jam mendominasi** karena 48 periode per 48 jam: edge per periode dipungut 48×
   sedangkan biaya per periode turun ke 0,58 bps (0,51 × 1,14). Di hold 48 jam edge hanya
   dipungut 1×.
3. Semua hold lain ≤44%; hold 24/48 jam hanya 19–25%.

## 6. Uji "apakah ini cuma bid-ask bounce?"

Ini pertanyaan yang bisa membatalkan seluruh temuan, jadi diuji:

| | nilai |
|---|---|
| bruto reversal hold-1 | **1,93 bps/jam** |
| spread median venue | 1,32 bps → bruto **1,5×** spread median |
| spread majors (BTC/ETH/SOL) | 0,12 / 0,39 / 0,86 bps → bruto **5–16×** spread majors |

**Kesimpulan:** pada majors, bruto 1,93 bps/jam adalah 5–16× spread, jadi **tidak bisa dijelaskan
seluruhnya oleh bid-ask bounce**. Ini melemahkan kekhawatiran yang saya tulis di laporan PRAREG-4.
Tetapi **bukan berarti bisa ditangkap** — lihat §8.

## 7. Kapasitas

| | USD |
|---|---:|
| Total kedalaman top-of-book 92 simbol | **227.394** |
| Kedalaman p10 / p25 / median | 105 / 146 / 297 |
| **Plafon wallet** (equal-weight, Σ\|w\|=1, 75 simbol) | **≈ 7.900 / 10.900 / 22.300** |

Wallet SoDEX saat ini (endpoint publik, read-only) **jauh di bawah plafon** → per-simbol
alokasi yang dibutuhkan ≈ puluhan dolar, sedangkan kedalaman p10 $105. **Kapasitas BUKAN
penyumbat pada skala sekarang.**

**Tetapi:** plafonnya tidak ikut tumbuh dengan wallet. Di atas ~$8–22 rb, strategi ini tidak bisa
dipakai penuh dan % target per TOTAL wallet otomatis gagal. **Ini batas absolut pada PnL, bukan
pada persentase** — dan harus dicatat sebagai batas, bukan disembunyikan.

## 8. WHAT COULD KILL THIS — satu pertanyaan terbuka, dan itu pertanyaan terbesar

Semua angka di §5 memakai **harga close bar 1 jam**. Seorang **maker tidak bertransaksi di harga
close.** Maker hanya terisi ketika pasar datang kepadanya — yaitu **adverse selection**: order
istirahat Anda terisi justru saat harga bergerak melawan Anda.

> **Ini adalah jebakan klasik:** strategi mean-reversion pasif tampak luar biasa pada data
> close-to-close dan gagal live, karena Anda hanya terisi di sisi yang salah.

Karena itu §5 harus dibaca sebagai: *"JIKA kita bisa bertransaksi pada harga close bar dengan fee
maker, maka 81% target"*. **Bukan** "kita sudah punya 81% target".

## 9. Uji falsifikasi berikutnya (siap dijalankan, data sudah ada)

**PRAREG-5 — realisme fill maker.** Menjawab §8 dengan data yang sudah dimiliki (klines 1 jam 100
simbol, ada high/low):

1. Sinyal reversal hold-1 → niat beli di simbol X pada harga `close_t − ½spread`.
2. **Terisi HANYA jika `low_{t+1} ≤ limit`.** Kalau tidak tersentuh → **tidak ada posisi**
   (bukan diasumsikan terisi di close).
3. Ukur return terealisasi hanya pada periode yang benar-benar terisi.
4. **Kontrol wajib: taker-shadow** — jalankan strategi identik dengan asumsi terisi di close
   (taker) untuk mengukur berapa besar selisihnya murni karena adverse selection.
5. Ambang: strategi maker lulus hanya jika net/48j **≥ 60 bps** DAN fill rate ≥ 30% DAN
   kontrol taker-shadow tidak lebih baik.

Aturan aturan-aturan: pra-registrasi di-commit **sebelum** evaluasi; ambang hanya boleh memperketat;
label **DESKRIPTIF** sampai ada verifikasi forward.

— Hermes Anantara v3 — 2026-10-07
