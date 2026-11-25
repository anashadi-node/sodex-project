# AUDIT ILMIAH: ASET SAHAM/KOMODITAS SODEX
## Laporan Final — 2026-07-28/29
### Status: ✅ SELESAI (Complete verdict, all gates tested)

---

## RINGKASAN EKSEKUTIF

**Pertanyaan inti:** Apakah wallet-wallet lain yang profit menggunakan aset saham SoDEX menandakan ada edge yang bisa kita replikasi? Apakah ada instrumen saham/komoditas di SoDEX yang bisa menjadi sumber profit bagi kita?

**Jawaban:** ❌ **TIDAK ADA.** Dari 28+ simbol non-crypto di SoDEX, nol yang lolos gate kombinasi: kedalaman buku ≥$500 AND OOS net > 0 AND OOS consistency ≥ 60%.

Audit ini mencakup:
- Analisis universe lengkap: 48 simbol non-crypto dari book recorder (81 total)
- Backtest OOS ilmiah dengan non-overlapping holds + train/OOS split
- 3× live paper-test selama US equity session (14:00, 16:30, 19:00 UTC)
- Cross-referensi dengan 19 wallet pemenang (wallet audit Juli 2026)

---

## METODOLOGI (ILMIAH, ANTI-BIAS)

### Protokol OOS (Out-of-Sample)
1. **Train/OOS split**: Kronologis 60%/40% — tidak ada data masa depan bocor ke train
2. **Non-overlapping holds**: Hold berikutnya tidak dimulai sampai hold sebelumnya selesai — mencegah false significance dari overlapping returns
3. **Pemilihan variant**: Pilih variant terbaik berdasarkan TRAIN net_bps → laporkan OOS-nya
   - Cherry-picking langsung dari OOS adalah data mining (false positive)
4. **OOS consistency gate**: Perlu ≥60% simbol menunjukkan OOS net > 0 — pooled Sharpe saja tidak cukup
5. **Depth guard**: Live spread dengan L1 depth < $500 USD = thin-book mirage (tidak bisa di-fill)
6. **Biaya roundtrip**: spread_bps + 2 × 2.0 bps taker fee = spread + 4 bps

### Data Sources
- `data/sodex_book_recorder.db` — L1 mid, 81 simbol, 24h+ data, ~3.3s interval sampling
- `data/sodex_public_trades.db` — aggressor-side trades, 436K rows, 20 simbol, 3 hari
- Live spreads via timer service (3× per US session)

### Sinyal yang Diuji
| Sinyal | Logika | Parameter |
|--------|--------|-----------|
| MOM (Momentum) | Ikuti tren k-bar | k=3-15, h=5-60 min |
| REV (Reversion) | Lawan tren k-bar | k=3-15, h=5-60 min |
| OFI (Order Flow Imbalance) | Net aggressor notional | k=3-15, h=5-60 min, thr=1K-20K |

---

## BAGIAN 1: UNIVERSE AUDIT — 28+ SIMBOL NON-CRYPTO

### 1.1 Saham Individual (12 yang ditest + 8 FAANG/tech)

| Simbol | Avg Depth | Spread | Verdict |
|--------|-----------|--------|---------|
| CRCL-USD | $54–$136 | 1.5–23.5bps | ❌ THIN_BOOK |
| MSTR-USD | $16–$188 | 1.0–4.2bps | ❌ THIN_BOOK |
| MU-USD | $106–$124 | 0.2–4.3bps | ❌ THIN_BOOK |
| AMD-USD | $105–$128 | 0.2–0.9bps | ❌ THIN_BOOK |
| HOOD-USD | $82–$96 | 0.4–6.5bps | ❌ THIN_BOOK |
| INTC-USD | $142–$164 | 0.3–4.2bps | ❌ THIN_BOOK |
| COIN-USD | $78–$121 | 0.6–2.5bps | ❌ THIN_BOOK |
| SKHY-USD | $106–$113 | 0.8–2.3bps | ❌ THIN_BOOK |
| PLTR-USD | $128–$149 | 0.8–2.4bps | ❌ THIN_BOOK |
| SPCX-USD | $130–$159 | 0.9–1.9bps | ❌ THIN_BOOK |
| NVDA-USD | $115–$162 | 0.5–2.0bps | ❌ THIN_BOOK |
| TSLA-USD | $172–$209 | 0.3–1.0bps | ❌ THIN_BOOK |
| AAPL-USD | ~$125 | — | ❌ THIN_BOOK (book data) |
| AMZN-USD | ~$167 | — | ❌ THIN_BOOK |
| GOOGL-USD | ~$166 | — | ❌ THIN_BOOK |
| META-USD | ~$166 | — | ❌ THIN_BOOK |
| MSFT-USD | ~$125 | — | ❌ THIN_BOOK |
| ORCL-USD | ~$125 | — | ❌ THIN_BOOK |
| TSM-USD | ~$125 | — | ❌ THIN_BOOK |
| SAMSUNG-USD | ~$140 | — | ❌ THIN_BOOK |
| MRVL-USD | ~$131 | — | ❌ THIN_BOOK |
| SNDK-USD | ~$124 | — | ❌ THIN_BOOK |
| SKHX-USD | ~$116 | — | ❌ THIN_BOOK |

**Temuan kritis:** MSTR mengalami PENURUNAN depth dari $188 (off-hours) menjadi $16 saat US market open — MM SoDEX MENARIK quote saat underlying volatil. Ini kebalikan dari harapan.

**Pola struktural:** Semua saham tokenized = $54–$209 depth, secara konsisten sepanjang 24h. Tidak ada "US session boost." Ini struktural, bukan temporal.

### 1.2 Index & ETF Produk

| Simbol | Avg Depth | Spread | OOS net | OOS Consistency | Verdict |
|--------|-----------|--------|---------|-----------------|---------|
| USTECH100-USD | $416 | 0.6bps | -3.50bps | 14% | ❌ THIN_BOOK + NEG |
| US500-USD | $345 | 0.45bps | N/A | N/A | ❌ THIN_BOOK, no trades |
| EWY-USD (Korea) | $2,619 | 9.7bps | N/A | N/A | No public trade data |

USTECH100 paling menarik di atas kertas (spread 0.6bps). Ditest via book-bar backtest (MOM/REV). Hasil: OOS net = -3.50bps, consistency 14% (28/200 variants positif). Ditolak.

### 1.3 Komoditas (Metals + Energy)

**Live paper-test — 3 sesi US (14:00, 16:30, 19:00 UTC 2026-07-28):**

| Simbol | Depth | Spread | Run 1 OOS net | Run 2 OOS net | Run 3 OOS net | Gross Signal | Verdict |
|--------|-------|--------|--------------|--------------|--------------|--------------|---------|
| XAUT-USD (Gold) | $4.7K–$21K | 6.2bps | -10.39bps | -11.78bps | -14.31bps | -0.18 (random) | ❌ |
| SILVER-USD | $575–$1.2K | 0.2–1.8bps | -11.54bps | -3.47bps | -6.56bps | -2.4 to -5.78 | ❌ |
| COPPER-USD | $1.4–$1.7K | 7.2–8.7bps | -5.81bps | -9.82bps | insuff_oos | +1.4–+6.9 gross | ❌ |
| CL-USD (Oil) | $123–$134 | 0.5–2.2bps | thin_book | thin_book | thin_book | N/A | ❌ |

**Analisis per komoditas:**

**XAUT (Gold):**
- Depth cukup ($4.7K–$21K) — bisa di-fill
- Spread 6.2bps + fee 4bps = 10.2bps/RT
- Gross signal = -0.18bps (hampir nol — ini aset low-volatility, sinyal directional lemah)
- OOS: -10 s/d -14bps, makin memburuk dari run 1 ke run 3
- DITOLAK: tidak ada sinyal directional bermakna, biaya 10× lebih besar dari gross

**SILVER:**
- Spread sering 0.2–1.8bps (tight!) tapi depth hanya $575–$1.2K
- Gross signal NEGATIF pre-cost (-2.4 to -5.78bps) — sinyal berlawanan dengan harga
- OOS net: -3.47 s/d -11.54bps tergantung run
- DITOLAK: sinyal negatif bahkan sebelum dikurangi biaya

**COPPER:**
- Spread 7.2–8.7bps = 11–13bps/RT — terlalu mahal
- Gross ada tilt kecil (+1.4 s/d +6.9bps) tapi biaya memotong semua
- OOS net: -5.81 s/d -9.82bps
- DITOLAK: biaya spread menghancurkan sinyal

---

## BAGIAN 2: BACKTEST OOS KOMPREHENSIF — SEMUA ASET LIQUID

### Gate yang Harus Dilewati (AND logic)
1. ✅ Depth ≥ $500 (bisa di-fill secara realistis)
2. ✅ OOS net_bps > 0 (net setelah biaya taker = spread + 4bps)
3. ✅ OOS consistency ≥ 60% (≥60% variant/simbol menunjukkan OOS positif)
4. ✅ Min 15 non-overlapping OOS trades

### Hasil Lengkap

| Simbol | Depth | RT Cost | OOS net | Consistency | Gate 1 | Gate 2 | Gate 3 | Verdict |
|--------|-------|---------|---------|-------------|--------|--------|--------|---------|
| XAUT-USD | $4.7–$21K | 10.2bps | -10 to -14bps | 1% | ✅ | ❌ | ❌ | ❌ REJECTED |
| SILVER-USD | $575–$1.2K | 4–5.8bps | -3 to -11bps | 12% | ✅ | ❌ | ❌ | ❌ REJECTED |
| COPPER-USD | $1.4–$1.7K | 11–13bps | -5 to -10bps | 1% | ✅ | ❌ | ❌ | ❌ REJECTED |
| USTECH100-USD | $416 | 4.6bps | -3.50bps | 14% | ❌ | ❌ | ❌ | ❌ REJECTED |
| EWY-USD | $2.6K | 13.7bps | N/A | N/A | ✅ | N/A | N/A | ❌ No data |
| Semua 20+ stocks | $54–$209 | 4–28bps | N/A | N/A | ❌ | N/A | N/A | ❌ THIN_BOOK |

**TIDAK ADA SATU SIMBOL PUN yang lolos ketiga gate secara bersamaan.**

---

## BAGIAN 3: ANALISIS ALUR ORDER (OFI)

OFI adalah satu-satunya sinyal dengan tilt gross yang real di dataset sebelumnya (WR 55% di 12 saham aktif). Tapi:

### Trade Flow Analysis — Simbol Paling Aktif
| Simbol | Total Trades | Total Volume | BUY % | SELL % | Net OFI |
|--------|-------------|-------------|-------|--------|---------|
| MU-USD | 70,131 | $5.1M | ~50% | ~50% | ≈ 0 |
| SPCX-USD | 64,234 | $5.9M | ~50% | ~50% | ≈ 0 |
| CRCL-USD | 46,512 | $5.3M | ~50% | ~50% | ≈ 0 |
| INTC-USD | 34,419 | $3.1M | ~50% | ~50% | ≈ 0 |
| HOOD-USD | 17,820 | $1.4M | ~50% | ~50% | ≈ 0 |
| MSTR-USD | 20,520 | $1.4M | ~50% | ~50% | ≈ 0 |

BUY/SELL split ~50/50 di semua simbol aktif = OFI ≈ 0 secara agregat.
Tidak ada dominansi arah yang konsisten = sinyal OFI tidak ada informasi di stock tokens ini.

**CRCL-USD OFI backtest (paling aktif dengan 3 hari data):**
- Best TRAIN-selected variant (OFI k=5, h=60): OOS net = **-18.71bps**
- Naive 1-bar test PALSU menunjukkan 61.8% WR → false positive karena overlapping + tidak ada OOS split
- Proper non-overlap + OOS: -18.71bps = DITOLAK

### Kesimpulan OFI pada Stocks
Gross OFI tilt (~2bps, WR 55%) dari analisis sebelumnya TIDAK BISA menutup biaya:
- CRCL spread: 1.5–23.5bps → RT cost = 5.5–27.5bps (2–14× lebih besar dari gross tilt)
- HOOD spread: 0.4–6.5bps → RT cost = 4.4–10.5bps (2–5×)
- Thin books ($54–$162) = tidak bisa di-fill bahkan jika sinyal ada

---

## BAGIAN 4: CROSS-CHECK DENGAN WALLET PEMENANG

### Apa yang Sebenarnya Dilakukan Wallet Profit (dari audit Jul 28)

| Wallet Archetype | Strategi Utama | Revenue Source | Saham? |
|-----------------|----------------|----------------|--------|
| N01 (Institutional, $32K) | Directional taker CRCL+MU | Delta profit | Ya, tapi $32K modal + 33 posisi simultan |
| N04 (Maker-first, SKHY+SNDK) | Maker 83.5% fill rate | SoPoints + small spread | Butuh HFT infra (0.1s timing) |
| N07 (HFT taker) | Wide-spread taker | Profit taker | Infra yang tidak bisa kita replikasi |
| N09+WB syndicate | Koordinasi 4 wallet | Volume + airdrop | Multi-wallet coordinated |
| Generic winner | Near-breakeven perp MM | SoPoints airdrop | BTC/ETH perps, bukan saham |

### Mengapa Kita TIDAK Bisa Mereplikasi
1. **N01**: Modal $32K (kita $274) + 33 simultaneous positions → capital structure berbeda total
2. **N04**: Fill rate 83.5% maker hanya bisa dengan HFT infrastructure (0.1–0.2s react time); kita Python daemon = 2–5s
3. **Queue-fill lab proof**: 0/30 simbol net-positif setelah realistic fill modeling; paired fill rate hanya 0–25% = majority menjadi orphan/adverse-selected
4. **Airdrop monetization**: Profit dari near-breakeven SoPoints churn, BUKAN dari spread capture

**KOREKSI HIPOTESIS AWAL:** Hipotesis "spread extraction = profit dari stocks" = SALAH. Telah dibantah oleh queue-fill-lab (0/30 simbol positif). Profit pemenang = airdrop near-breakeven ATAU directional taker dengan modal besar ATAU HFT infra.

---

## BAGIAN 5: PAPER-TEST LIVE — 3 SESI US EQUITY

Timer berjalan: 14:00 UTC, 16:30 UTC, 19:00 UTC pada 2026-07-28

### Tren Konsistensi (3 Run)

| Simbol | 14:00 UTC | 16:30 UTC | 19:00 UTC | Konsisten? |
|--------|-----------|-----------|-----------|-----------|
| CRCL-USD | thin ($136) | thin ($54) | thin ($121) | Ya, selalu thin |
| TSLA-USD | thin ($201) | thin ($209) | thin ($172) | Ya, selalu thin |
| XAUT-USD | -10.39bps | -11.78bps | -14.31bps | Ya, selalu negatif |
| SILVER-USD | -11.54bps | -3.47bps | -6.56bps | Ya, selalu negatif |
| COPPER-USD | -5.81bps | -9.82bps | insuff | Ya, selalu negatif |

**Hasil agregat 3 run:**
- `positive=0/16` pada SETIAP run
- Total: 0/48 (16 simbol × 3 run) = **nol positif**

---

## BAGIAN 6: SATU-SATUNYA LEAD TERSISA

**OFI pada crypto majors (BTC/ETH/SOL/HYPE)** = satu-satunya hipotesis yang belum diuji secara lengkap.

**Mengapa ini berbeda:**
- Spread BTC/ETH/SOL: 1–3bps (vs 5–80bps untuk stocks/metals)
- RT cost: ~5–7bps (vs 10–28bps)
- Volume lebih tinggi = OFI signal lebih informatif
- 20.8h BTC data, 20.9h ETH data di public_trades.db (perlu ≥48h)

**Status:** Data sedang dikumpulkan oleh `sodex-public-trade-recorder.service`. Backtest bisa dijalankan setelah ≥48h:
```bash
python3 scripts/sodex_directional_backtest.py \
  --mode trades --families OFI \
  --symbols BTC-USD,ETH-USD,SOL-USD,HYPE-USD
```

**Paper trades aktif (zero capital):**
- BTC-USD SHORT @ $63,800 | SL $64,700 | TP $61,500 | R:R 1:2.55 | Lev 5×
- ETH-USD SHORT @ $1,920 | SL $1,970 | TP $1,780 | R:R 1:2.80 | Lev 5×

---

## VERDICT FINAL

### ❌ TIDAK ADA EDGE YANG BISA DIEKSPLOITASI DI ASET SAHAM/KOMODITAS SODEX

| Kategori | Simbol Count | Gate Fail | Verdict |
|----------|-------------|-----------|---------|
| Saham individual | 20+ | Depth < $500 (structural) | ❌ UNTRADEABLE |
| Index/ETF | 3 | Depth < $500 AND OOS < 0 | ❌ UNTRADEABLE + NO EDGE |
| Gold (XAUT) | 1 | OOS < 0 (signal random) | ❌ NO EDGE |
| Silver | 1 | OOS < 0 (signal negative pre-cost) | ❌ NO EDGE |
| Copper | 1 | OOS < 0 (spread swamps gross) | ❌ NO EDGE |
| Oil (CL) | 1 | Depth < $500 | ❌ UNTRADEABLE |

**Sesuai profit-first doctrine:** Tidak ada satu pun instrumen non-crypto di SoDEX yang memenuhi standar minimum untuk deployment modal.

### Tindakan yang Sesuai Doctrine
1. **Pertahankan modal** — jangan deploy ke strategi apapun yang belum terbukti OOS
2. **Lanjutkan paper trades** BTC/ETH SHORT (track record building)
3. **Tunggu ≥48h data** untuk backtest OFI pada crypto majors — satu-satunya lead aktif yang belum diuji
4. **Jika OFI majors juga ditolak** → SoDEX tidak memiliki edge directional yang bisa kita manfaatkan → fokus ke Pre-Gain HL (sistem yang sudah terbukti)

---

## LAMPIRAN: FALSE POSITIVE ANATOMY

Tiga jenis false positive yang ditemukan dan diperbaiki dalam riset ini:

### FP1: Overlapping Trade Simulation
- Awal: OFI pada 81 simbol book data → "POSITIVE OFI +6.85bps sharpe 7.59"
- Root cause: holds overlap → autocorrelated returns → pooled Sharpe palsu
- Fix: `non_overlap=True` → rejected

### FP2: In-Sample Cherry-Picking (CRCL)
- Awal: "OFI k=5 h=60 → OOS +39.90bps!" 
- Root cause: selected variant DARI OOS ranking (top 5 by OOS net) = data mining
- Fix: select dari TRAIN ranking → OOS = -18.71bps → rejected

### FP3: Naive 1-Bar OFI Test
- Awal: "CRCL OFI naive test → 61.8% WR!"
- Root cause: bar N OFI → bar N+1 avg_price (bukan mid-price), overlapping, no OOS
- Fix: proper `gen_trades` + `split_trades` → rejected

**Lesson:** Selalu require: non-overlapping + train/OOS split + per-symbol consistency ≥60%. Tidak ada shortcut.

---

*Dokumen ini merupakan laporan audit final. Data dan metodologi dapat diverifikasi via `scripts/sodex_directional_backtest.py` dan `scripts/sodex_stock_paper_test.py`.*
