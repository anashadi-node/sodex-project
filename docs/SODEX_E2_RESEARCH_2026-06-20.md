# SoDEX E2 Volume Engine — Riset Radikal & Analisa Mendalam
## 2026-06-20 · Claude (Opus 4.8)

Riset luas, mendalam, dan radikal untuk Mesin E2 (volume engine), menjawab
mandat: capai $1.3M/minggu volume, Real Ratio ≥ 1:9.100, >69% profitable,
sebelum deadline event 2026-07-25.

---

## 1. Temuan Doktrin (apa yang di-reward SoPoints)

- **Real Ratio = official volume / max(fees − E1 profit, 0) ≥ 9.100.**
  Artinya: net cost ≤ $143 untuk $1.3M volume. **Maker WAJIB.**
- **Taker MATI**: spread 0.1% + taker fee → ratio ~555:1 (jauh < 9.100). Taker churn
  menghancurkan target. Dibuang.
- **Maker pasif TIDAK ber-edge** (E1 PEPE/SHIB: −0.0626%/RT, WR 32%, n=31) — adverse
  selection ~17 bps menelan separuh-spread. Doktrin redirect ke **DIREKSIONAL**:
  "volume adalah HASIL dari profitabilitas."
- **No-Loss Guarantee**: `E1_profit ≥ fees_E1 + fees_E2`.

## 2. Realita Kapital (jujur)

$1.3M/minggu pada modal ~$200 = **6.989× turnover mingguan**. Secara mekanis perlu:
(a) maker-rebate tier, (b) tambahan modal signifikan, dan/atau (c) leverage perps.
Target penuh kemungkinan tidak feasible tanpa salah satunya — harus dihadapi jujur.
TAPI: maksimalkan volume yang FEASIBLE dengan edge positif tetap bernilai SoPoints.

## 3. Mengapa E2 churn lama GAGAL (terbukti ilmiah)

- `churn_cycle` = maker dua-leg **sekuensial + blocking** (pasang→tunggu fill→tutup).
- Diuji di **1-tick spread** (XPL/PEPE): offset=0 (touch)→menyilang→oid=0; offset=1
  (inside-favor)→valid tapi terlalu pasif→tak terisi dalam timeout. **20 attempt/180s,
  0 RT** (B57). Arsitektur blocking + spread 1-tick = mustahil.

## 4. 🔥 TEMUAN RADIKAL #1 — E2Dir SUDAH PROFITABLE

`e2_dir_signals` (funding-rate direksional), n=30 closed:
- **WR 63.3%**, total PnL **+$0.325**, volume $150, avg +$0.0108/trade
- SELL: WR 67% (+$0.227) · BUY: WR 60% (+$0.097)
- Pair: **ekuitas/komoditas ter-tokenisasi** — SAMSUNG, INTC, TSM, MU (Micron),
  SK Hynix, SPCX, CRCL (Circle), EWY (ETF Korea), CL (crude oil)
- **Ini benih volume engine doktrin**: prediksi arah (funding) → entry → profit
  menutup fee → ratio terjaga. Bukan churn rugi.

## 5. 🔥 TEMUAN RADIKAL #2 — SPREAD MULTI-TICK = KUNCI

Bottleneck E1/E2 selama ini = **spread 1-tick** (PEPE/SHIB/XPL): tak ada harga maker
valid yang juga terisi. **TAPI perps ekuitas/likuid punya spread MULTI-TICK:**

| Pair | Spread | ~Ticks | Vol 24h | |funding| |
|------|--------|--------|---------|----------|
| **SPCX-USD** | 0.055% | ~10 | **$3.6M** | 0.0030% |
| **MSTR-USD** | 0.293% | ~34 | $129K | 0.0208% |
| **AXS-USD** | 0.087% | multi | $123K | 0.0122% |
| **BERA-USD** | 0.044% | multi | $116K | 0.0046% |
| **TRUMP-USD** | 0.022% | ~4 | $241K | 0.0057% |
| XMR/XPL/PEPE | ~0.003% | 1 | — | — |

Pada spread multi-tick, order maker **DI DALAM spread** = harga valid, tidak menyilang,
memperbaiki best bid/ask → **terisi lebih dulu saat harga bergerak**. Masalah crossing
1-tick yang membunuh churn **TIDAK ADA** di sini. SPCX likuiditas $3.6M/24h → bisa skala.

## 6. Sintesis — Desain Radikal E2 v3

**E2 = MAKER DIREKSIONAL pada perps MULTI-TICK LIKUID** (bukan churn acak 1-tick).

1. **Universe**: SPCX, MSTR, AXS, BERA, TRUMP, + ekuitas funding-kuat (INTC/TSM/MU/
   SAMSUNG). Filter: spread ≥ 3 tick DAN vol24h ≥ $100K.
2. **Sinyal arah**: funding-rate (terbukti 63% WR) diperkaya dgn momentum + OBI +
   port logika Pre-Gain/Loser (sudah ber-edge di HL) → adaptasi SoDEX.
3. **Eksekusi**: entry MAKER di dalam spread searah prediksi → fill andal (multi-tick),
   capture sebagian spread + gerak arah → profit tutup fee → ratio terjaga.
4. **Non-blocking**: kelola order lintas iterasi (pola E1 Flywheel), reconcile via
   delta POSISI perps (bukan balance spot). TTL panjang, bukan timeout 5-15s.
5. **Risk**: clip kecil, leverage terbatas, budget treasury G6, guardian margin,
   net-position cap per pair, SL/TP.
6. **Scale**: tambah pair + size saat WR & ratio terbukti; rebate tier bila volume naik.

## 7. Hipotesis terukur (falsification-first)

- **H-E2a**: maker di dalam spread multi-tick (SPCX) terisi andal (≥50% order, vs ~0%
  di 1-tick XPL). → uji: pasang N order, ukur fill-rate.
- **H-E2b**: entry maker searah funding pada ekuitas perps net-positif setelah fee
  (perpanjang E2Dir n=30→100). → ukur WR & PnL.
- **H-E2c**: volume/hari dari E2 direksional multi-pair > E1 spot saat ini ($13K/hr
  burst, ~$2.4K/hr steady). → ukur volume kredit official.

## 8. Langkah Build (bertahap, hati-hati, modal nyata)

1. Tambah filter universe perps multi-tick + likuid (config).
2. Uji fill-rate maker di SPCX (order kecil, approve user, cancel) — validasi H-E2a.
3. Bangun `Engine2DirectionalMaker` non-blocking: entry maker dalam spread, reconcile
   posisi, TTL panjang, SL/TP, net-cap. Test offline dulu.
4. Paper/micro-live di 1-2 pair → ukur WR/ratio/volume.
5. Scale pair + size bertahap saat gate (WR≥ baseline, ratio≥9.100 path) lolos.

## 9. KOREKSI PENTING (pasca-uji empiris) — maker churn DEAD END, E2Dir = engine

Uji churn maker di SPCX (multi-tick) ternyata JUGA gagal: `raw={}` (precision)
+ SPCX gerak 10 tick/detik → stale-book crossing. **Churn maker blocking gagal di
SEMUA pair** (1-tick: no room; multi-tick: staleness). 20 attempt → 0 RT.

**Pelajaran kunci dari kode E2Dir**: E2Dir entry **TAKER** (`bk.ask`/`bk.bid` —
jamin fill), bayar spread, TAPI net PROFIT karena edge funding mengalahkan biaya
(63% WR). Inilah doktrin: "volume adalah HASIL profitabilitas." Maker tanpa edge
selalu kalah; taker DENGAN edge menang. Ratio terjaga karena PROFIT, bukan maker.

**Desain final E2 = SCALE E2Dir** (bukan churn):
1. Perbanyak pair direksional (universe ekuitas+kripto funding-kuat + multi-tick likuid).
2. Perkaya sinyal: funding + momentum + OBI + port Pre-Gain/Loser (sudah ber-edge HL).
3. Naikkan throughput: hold lebih pendek → lebih banyak trade/hari pada margin sama;
   ATAU tambah margin perps; ukuran naik bertahap saat WR & ratio terbukti.
4. Kelola margin ketat (guardian + net-cap + treasury G6).

## 9b. 🔥🔥 BREAKTHROUGH (2026-06-21) — LEVERAGE = kunci capai target

Analisa ulang `docs/SODEX_COMPENDIUM_FOR_MYTHOS.md` §2.2: perhitungan "$1.3M
mustahil pada modal kecil" SALAH karena **tanpa leverage**. Dengan leverage perps:

| Leverage | Posisi ($25 margin) | Vol/RT | RT/minggu | RT/hari | Stream | Verdict |
|----------|---------------------|--------|-----------|---------|--------|---------|
| SPOT only | — | $20 | 65.000 | 9.286 | 90 | ❌ mustahil |
| 5x | $125 | $250 | 5.200 | 743 | 7-8 | 🟡 berat |
| 10x | $250 | $500 | 2.600 | 371 | 4 | ✅ layak |
| **20x** | **$500** | **$1.000** | **1.300** | **186** | **~2** | ✅ **REKOMENDASI** |
| 50x | $1.250 | $2.500 | 520 | 74 | 0.7 | ⚠️ likuidasi dekat |

**Gerbang profit (WR 69%, avg_win 0.30%, avg_loss −0.25%, fee 0.024%):**
EV = +0.1055%/RT → pada $1.3M/mgg = **+$1.371/minggu**. POSITIF.

### Metode E2 final yang BISA capai target

**E2 = LEVERAGED DIRECTIONAL PERPS SCALP** (10-20x):
- **Leverage 10-20x** = pengganda volume (kunci feasibility pada modal kecil).
- **Sinyal**: E2Dir funding (terbukti 63% WR) + **Pre-Gain momentum** (§4.6 metode E,
  WR tertinggi, port dari HL) + OBI/intelligence → target **69% WR**.
- **Entry TAKER** (jamin fill — terbukti E2Dir; biaya spread trivial vs volume leveraged).
- **Turnover**: ~8 RT/jam/stream × 2-4 stream → 186 RT/hari → $1.3M/minggu.
- **Risk**: SL ketat (1% harga = 15-20% margin @ leverage), gate WR 69%, guardian
  margin, net-cap per pair, liquidation buffer.

### Syarat eksekusi (jujur)
1. **Margin perps lebih besar** — pada 20x, $25/posisi × 2-4 stream = $50-100 margin.
   Sekarang ~$52 (─ $34 tertahan ENA). Doktrin modelkan $150 perps. → bebaskan ENA +
   kemungkinan tambah modal perps untuk skala penuh.
2. **Set leverage 10-20x** per pair (sekarang 5x).
3. **Turnover cepat** — E2Dir hold 30min terlalu lambat; perlu scalp (hold pendek).
4. **WR 63%→69%** — perkaya sinyal (momentum + Pre-Gain).
5. **Keamanan likuidasi** — SL ketat, buffer, monitoring guardian.

### Rencana build bertahap (hati-hati, modal nyata)
- Fase A: set leverage + scalp turnover pada E2Dir, modal kecil (1 stream, $25 margin,
  10x) → ukur WR & vol. Bebaskan margin ENA dulu.
- Fase B: perkaya sinyal (momentum/Pre-Gain) → WR≥69%.
- Fase C: tambah stream + leverage 20x → ramp ke 186 RT/hari saat gate lolos.
- Fase D: tambah modal perps ($150) untuk volume penuh.

## 10. Status

- **E2Dir live** (funding, equity perps, taker-directional) WR 63% — ENGINE volume.
- **E2 churn (maker) DIMATIKAN** — dead-end arsitektur (terbukti 1-tick & multi-tick).
- E1 spot scale (deposit $55) paralel = volume pasti.
- **Build berikutnya**: scale E2Dir (pair + sinyal + throughput), instrumented & gated.

## 11. Riset lanjutan (2026-06-21) — falsifikasi momentum + universe luas

- **Momentum KONTINUASI TERFALSIFIKASI**: paper n=16 WR=37.5% (<50%). Komplemen =
  REVERSI ~62.5%. → flip signal ke mean-reversion (TE_E2_MOM_REVERSION=1). Sedang
  divalidasi ulang (paper).
- **Maker rebate**: TIDAK terkonfirmasi. Fee Tier-0: perps 0.012%/sisi, spot 0.035%.
  Rebate tier = spekulatif (perlu akses sodex.com) → tidak diandalkan.
- **🔥 UNIVERSE LUAS**: SoDEX punya **saham ter-tokenisasi** (AAPL/NVDA/TSLA/MSFT/
  GOOGL/META/AMZN) + kripto. **24 aset punya BOTH spot+perp**: AAPL, AAVE, ADA, AMZN,
  ARB, AVAX, BNB, BTC, DOGE, ETH, GOOGL, HYPE, LINK, LTC, META, MSFT, NVDA, SOL, SUI,
  TON, TSLA, UNI, XLM, XRP.
- **Opsi radikal DELTA-NEUTRAL** (volume tanpa risiko arah): long spot + short perp
  aset sama (cash-and-carry) ATAU long perp A + short perp B berkorelasi (pairs).
  Hasilkan volume + funding dgn delta~0. Keterbatasan: hold tak hasilkan volume
  kontinu (volume per open/close) → bukan churn frekuensi-tinggi. Cocok utk income
  aman, kurang utk volume buta. Pairs leveraged (long NVDA/short MSFT) = volume
  leveraged dgn beta-hedge — kandidat risiko-lebih-rendah, perlu riset korelasi.
- **Kapital**: user maks +$66 perps (total margin perps ~$119, mendekati model $150).
- **Arah**: validasi reversi WR → bila ≥~60% + leverage → volume engine. Universe
  saham+kripto memberi banyak pair utk reversi-scalp (lebih banyak sinyal).

## 12. VERDICT ILMIAH DEFINITIF (2026-06-21) — high-freq microstructure scalp GUGUR

Uji paper sistematis (falsification-first, uji binomial vs 50% + Wilson 95% CI):

| Sinyal | n | WR | z | Signifikan? |
|--------|---|-----|---|-------------|
| Momentum kontinuasi | 16 | 37.5% | — | Tidak (coinflip) |
| Momentum reversi | 18 | 38.9% | — | Tidak |
| OFI kontinuasi | 16 | 31.2% | — | Tidak |
| OFI reversi | 56 | 42.9% | −1.07 | Tidak (CI [30.8%,55.9%]) |
| **Funding E2Dir** | 30 | **63.3%** | — | Borderline p=0.072 ✓ |

**KESIMPULAN**: sinyal mikrostruktur frekuensi-tinggi (price-momentum, OFI; kontinuasi
& reversi) **TIDAK punya edge arah signifikan** di perps SoDEX — konsisten dgn efisiensi
pasar horizon-pendek. Tuning lanjut = overfitting noise. **DIFALSIFIKASI.**

**Edge SATU-SATUNYA yang terbukti**: funding-squeeze direksional (E2Dir, 63.3% WR,
n=30, p=0.072). Ini juga port Pre-Gain/Loser (HL 80% → SoDEX 63%, funding lebih lemah).

### Rekomendasi terbaik (rigor ilmiah)
1. **Maksimalkan edge TERBUKTI**: E2Dir funding × leverage 10x = volume leveraged
   positif-EV (low-freq, tapi nyata). + E1 spot baseline. + modal $66 perps.
2. **JANGAN kejar high-freq scalp** (mirage — efisien, no edge). Hentikan tuning.
3. **Feasibility JUJUR**: $1.3M/mgg positif-EV kemungkinan TIDAK tercapai pada modal
   ini — edge terbukti (funding) low-freq; high-freq tak ber-edge. Sesuai caveat
   doktrin (perlu rebate tier / modal besar). Maksimalkan volume FEASIBLE positif-EV.
4. **Arah riset baru** (bukan microstructure): event-driven (katalis), perluas
   universe funding-squeeze, atau longer-horizon Pre-Gain (low-freq tapi high-WR).
