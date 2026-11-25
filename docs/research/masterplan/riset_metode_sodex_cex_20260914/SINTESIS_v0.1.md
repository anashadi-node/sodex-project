# SINTESIS v0.1 — Peta Metode ↔ Karakteristik SoDEX & CEX-Binance
**Dasar: 24 paper terverifikasi (P01–P24) + karakteristik empiris internal terverifikasi.**
**Status: DRAFT BERTAHAP — akan diperbarui tiap batch. Belum final.**

---

## BAGIAN 1 — KARAKTERISTIK TERVERIFIKASI (input sintesis)

### SoDEX
```
Venue      : DEX perpetual (ekosistem Hyperliquid-style), EIP-712 signing
Horizon    : swing 1–30 jam
Target     : ≥0,8% kumulatif/30 jam dari TOTAL modal wallet (spot+perps) — HARGA MATI
Empiris    : 544 trade gabungan, WR 44,12%, mean +0,18%, MEDIAN −0,40%
             SWING 203 | WR 40,4% | mean +0,08% | median −1,03%
             TWOWAY 211 | WR 45,0% | mean +0,19% | median −0,20%
               └ SHORT n=42 WR 33,3% mean −0,45%  ← sisi terlemah
             REALWIDE 130 | WR 48,5% | mean +0,34% | median −0,16%
Governor   : leverage invers-vol, SL dinamis, scoring aset, threshold probability, master gate expectancy
Signal     : OBI/OFI multi-window + spread gate + realized-vol regime gate
Aset infra : OBI 1-menit (172K baris, 50MB), snapshot order book
Status lane: paper/research-only (uang nyata stop+disabled 30-09; LIQ_DRY=1)
```

### CEX-Binance
```
Venue      : Binance USDM Futures (+spot), FreqTrade + FreqAI LightGBM
Horizon    : swing 1–30 jam
TARGET     : ≥0,8% kumulatif/30 jam dari TOTAL modal wallet — HARGA MATI
Empiris    : 90d n=94 | WR 36,17% | total wallet −2,4998% | expectancy gate FAIL
             SPRT REJECT_EDGE (llr −7,551) | monthly projection −1,269%
             7d n=8 WR 25% +0,2715% | 30d n=49 WR 22,45% −1,8635%
Deep loop  : r6_bear_v8.2 n=23 WR 69,6% E +0,547% PF 1,609 (BOOST)
             r8_neutral   n=32 WR 40,6% E +0,318% PF 1,275 (BOOST)
             r8_freqai    n=21 WR  9,5% E −1,959% PF 0,142   ← memenuhi kriteria veto, TAK dive
             r8_trend     n=14 WR 14,3% E −1,776% PF 0,115   ← memenuhi kriteria veto, TAK dive
             → vetoed=[] padahal keduanya lolos uji binomial (p=0,00011 / 0,00647)
Blocklist  : LINK_SHORT hard (n=6 WR 16,7%) | ONDO_SHORT soft (n=3 WR 0%)
Regime     : HMM gate; v2.8 BULL→LONG, BEAR→SHORT-only, CHOP→FLAT
Data infra : 30 simbol × 18 bulan (1h/4h/1d + funding 1h + mark), 275K baris 1h
```

---

## BAGIAN 2 — PETA METODE (masing-masing dengan dasar bukti)

### A. UNTUK SoDEX (masalah inti: MEDIAN NEGATIF, WR <50%)

| # | Metode | Dasar bukti | Kecocokan | Label |
|---|---|---|---|---|
| A1 | **Bracket exit mekanis** (TP/SL terstruktur, bukan diskresi) | P04: agen produksi Hyperliquid — 43,2% capai ≥+300bps dalam 24j tapi 49,3% ditutup negatif; bracket mekanis memulihkan **+39,0 bps/posisi** | █████ langsung (venue sama: Hyperliquid perps, horizon 24j) | CONFIRMED |
| A2 | **Ladder/trailing exit berlapis** (sell-limit + trailing) | P18: trailing stop + sell limit terbukti OPTIMAL secara matematis (optimal double stopping) | ████ | CONFIRMED (teori) |
| A3 | **SaR/ESaR/TSaR + penalti konsentrasi** untuk sizing & buffer likuidasi | P15: kerangka forward-looking dari order book HYPERLIQUID; terbukti leading indicator stres (kaskade 10 Okt 2025) | █████ venue identik | CONFIRMED |
| A4 | **L2 liquidity STATE sebagai prediktor lapis-1**; OFI dilapis di atasnya, bukan pengganti | P14: state L2 kasar menang kuat; logit L2 kontinu gagal memperbaiki; OFI hanya menambah bila di atas state | █████ menantang desain sinyal kita saat ini | CONFIRMED |
| A5 | **Fitur clock-phase / quarter-hour** (opening order imbalance → return 4–12 jam) | P13: 6 kontrak perp Binance; prediktabel OOS; imbalance pembukaan memprediksi 4–12 jam | █████ horizon persis milik kita | CONFIRMED |
| A6 | **Perpustakaan fitur mikro-struktur portabel** (OI, spread, adverse selection) | P17: 1-detik Binance futures 2022–2025; peringkat fitur & SHAP STABIL lintas aset | ████ | CONFIRMED |
| A7 | **Skor risiko populasi = kompresi varian taker order-flow** (bukan alarm pola krisis) | P20: satu-satunya regularitas bertahan di 7 kaskade; placebo 300-onset p≈5e-6; level populasi, bukan per-event | ████ | CONFIRMED |
| A8 | **Kerangka maker/perp** (dekomposisi PnL 5-komponen, Kelly+ruin, APY-VaR) | P05: teori lengkap market making perp zero-fee, ambang entry-exit, hedge regime trichotomy | ████ | CONFIRMED (teori) |
| A9 | **Eksekusi TWAP TERLIHAT** untuk order besar | P02: Hyperliquid — TWAP terlihat biaya LEBIH RENDAH & permanent impact lebih kecil; menarik likuiditas | ████ kontra-intuitif, venue identik | CONFIRMED |
| A10 | RL untuk alokasi likuiditas (tekan ekor kiri) | P11: menekan ekor kiri distribusi PnL | ███ | PROMISING |

### B. UNTUK CEX-BINANCE (masalah inti: AGGREGATE NEGATIF, bocor dari 2 path)

| # | Metode | Dasar bukti | Kecocokan | Label |
|---|---|---|---|---|
| B1 | **Karantina path** — r8_freqai & r8_trend memenuhi kriteria veto (p=0,00011 / 0,00647) tapi `vetoed=[]` | Audit internal + verifikasi binomial | █████ | CONFIRMED |
| B2 | **Ganti LOSS, bukan model**: GMADL (direction-aware, selaras kinerja trading) | P21: GMADL superior vs loss regresi/klasifikasi; P17 memakainya; P09: head > backbone | █████ kita pakai MSE | CONFIRMED |
| B3 | **Output head distribusi (kuantil/mixture), bukan titik** | P09: mixture density +3,7pp CRPS; nilai terbesar di regime volatil tinggi | █████ | CONFIRMED |
| B4 | **Low-volatility gating + vol scaling + kontrol turnover** | P08: prediktabilitas return terkonsentrasi di regime VOL RENDAH; naif gagal, tapi vol-scaling+low-vol gating+kontrol turnover memperbaiki kinerja defensif | █████ langsung menyasar aggregate kita | CONFIRMED |
| B5 | **Regime-conditioned deployment** (path hanya di habitatnya) | P08 + internal (r6_bear 69,6% muncul di regime bear) + P06 | █████ | CONFIRMED |
| B6 | **Trend-following 6-jam + portofolio adaptif + trailing stop kalibrasi vol + alokasi 70/30** | P06: AdaptiveTrend Sharpe 2,41 / MaxDD −12,7% / Calmar 3,18 (150+ pair, 36 bln OOS) | █████ horizon hampir identik | PROMISING |
| B7 | **Pairs trading kointergrasi dinamis** (half-life OU, look-back optimal) | P19: mengalahkan buy-and-hold, MaxDD rendah, di Bitmex | ████ jalur market-neutral | CONFIRMED |
| B8 | **Penolakan agen overfit via uji hipotesis PBO** | P24: agen kurang-overfit memberi return lebih tinggi pada periode crash | █████ | CONFIRMED |
| B9 | **Gate DSR + PBO + SPA + MinTRL + stabilitas regime** sebelum adopsi | P23: 359.062 backtest; AUROC 0,989 sintetik — TAPI rho=0,013, p=0,40 pada data nyata | █████ sebagai GATE KELAYAKAN | CONFIRMED (sebagai gate, BUKAN prediktor) |
| B10 | Fitur clock-phase & opening imbalance | P13 | █████ | CONFIRMED |

### C. BERLAKU UNTUK KEDUANYA — META

| # | Prinsip | Dasar bukti |
|---|---|---|
| C1 | **Rantai translasi alpha**: info → sinyal stabil → posisi feasible → order executable → net return | P16 |
| C2 | **Evaluasi > model**: tidak ada studi peer-reviewed yang mengalahkan baseline naif lintas regime pada horizon pendek | P07 |
| C3 | **Purge & embargo di batas split**; hindari same-close entry | P01, P22 |
| C4 | **AUC tinggi ≠ profit** (avg precision 0,134 walaupun AUC 0,89) | P01 |
| C5 | **Lapisan operasional > teks strategi** (risk slider +0,425/level; agent FE 60% varian) | P04 |
| C6 | **Sizing HARUS sadar-volatilitas** (median 5x di semua sextile = cacat; 11% book = 62% likuidasi) | P04 |
| C7 | **Skor robustness bukan prediktor profit** | P23 |

---

## BAGIAN 3 — JALUR YANG SUDAH TERBUKTI GAGAL (jangan ulangi)

```
[DITOLAK-1] "ML memprediksi candle → profit di Binance Spot"
            Bukti: P01 — AUC 0,874-0,896 tapi avg precision 0,134; −6,72%/19 siklus @31bps; 3W/16L
[DITOLAK-2] "Kalahkan baseline naif dengan model prediksi di horizon jam-an"
            Bukti: P07 — tidak ada studi peer-reviewed yang berhasil lintas regime
[DITOLAK-3] "Alarm risiko dari pola satu krisis"
            Bukti: P20 — tidak ada variabel event-invariant; outlier Okt 2025
[DITOLAK-4] "Ganti backbone/model untuk memperbaiki akurasi"
            Bukti: P09 — ganti backbone <1,5% CRPS; head/loss dominan
[DITOLAK-5] "Robustness score tinggi = jaminan profit"
            Bukti: P23 — rho=0,013, p=0,40 pada data nyata
[DITOLAK-6] "OFI saja cukup sebagai sinyal"
            Bukti: P14 — order flow menambah nilai HANYA di atas L2 state, tidak portabel lintas-simbol
[DITOLAK-7] "Uji strategi tanpa purge/embargo di batas split"
            Bukti: P01 (audit forensik menolak holdout cacat), P22
```

---

## BAGIAN 4 — HIPOTESIS FALSIFIABLE PRIORITAS (siap diuji di data kita)

Semua data uji TERSEDIA lokal: 30 simbol × 18 bulan 1h/4h/1d + funding 1h, OBI 1-menit.

```
[H1 · SoDEX+CEX] Bracket exit mekanis memulihkan sebagian besar kerugian median-negatif.
   UJI: pada 544 trade SoDEX + 94 trade CEX, replikasi bracket TP/SL tetap →
        hitung perubahan mean/median/WR. Prediksi P04: ≈ +39 bps/posisi.
   FALSIFIKASI: jika median tidak naik ≥ 50% jarak menuju 0 → hipotesis gugur.

[H2 · SoDEX+CEX] Clock-phase (quarter-hour) order imbalance memprediksi return 4–12 jam.
   UJI: bangun fitur menit-dalam-jam + opening imbalance dari candle 1h/15m →
        uji prediktif OOS ketat (purged CV). Prediksi P13: signifikan.
   FALSIFIKASI: AUC OOS ≤ 0,50 + CI memuat nol.

[H3 · CEX] Low-volatility gating memperbaiki kinerja jauh lebih besar daripada pergantian model.
   UJI: pisahkan 94 trade (dan backtest) per sextile volatilitas → bandingkan E[R]
        di regime vol rendah vs tinggi. Prediksi P08: terkonsentrasi di vol rendah.
   FALSIFIKASI: E[R] tidak berbeda antar sextile.

[H4 · CEX] Mengganti MSE → GMADL memperbaiki kinerja trading tanpa mengubah arsitektur.
   UJI: latih ulang LightGBM (atau model setara) dengan GMADL, evaluasi walk-forward
        + PBO. Prediksi P21/P09: perbaikan pada metrik trading.
   FALSIFIKASI: kinerja trading OOS tidak berbeda (CI memuat nol).

[H5 · SoDEX] OFI di atas L2-state lebih baik daripada OFI saja.
   UJI: bandingkan model (a) OFI-only, (b) L2-state-only, (c) L2-state+OFI, pada OBI 1-menit.
        Prediksi P14: (c) > (a), dan (b) mendekati/kalah dari (c).
   FALSIFIKASI: (a) ≥ (c).

[H6 · BERSAMA] Mean-reversion kripto pada horizon 1–30 jam: rasio edge/biaya lebih baik
   daripada 15 menit, ATAU tidak.
   UJI: ukur reversal setelah aggressive taker flow pada horizon 1h/4h/1d; hitung
        edge gross vs biaya round-trip nyata venue kita.
        Prediksi P03 (15m gagal lolos biaya); horizon kita BELUM diuji.
   FALSIFIKASI: edge gross < biaya pada semua horizon.

[H7 · SoDEX] Skor risiko populasi (kompresi varian taker order-flow) memisahkan periode
   stres dari periode normal.
   UJI: hitung dari data trade/OBI; uji vs episode volatilitas ekstrem.
        Prediksi P20: satu-satunya prekursor bertahan.
   FALSIFIKASI: tidak ada pemisahan atau CI memuat nol.
```

---

## BAGIAN 5 — CATATAN METODOLOGIS WAJIB (dari P01/P16/P22/P23)

```
1. Setiap uji: PURGED & EMBARGOED cross-validation. Jangan same-close entry.
2. Setiap klaim prediktif: sertakan baseline NAIF (harga terakhir / acak / buy-hold).
3. Sertakan ZERO dalam grid hyperparameter (jangan mengasumsikan fitur berguna).
4. Laporkan AVERAGE PRECISION, bukan hanya AUC (P01).
5. Setiap kandidat: estimasi PBO; tolak bila overfit (P24).
6. Gate adopsi: DSR + PBO + SPA + MinTRL + stabilitas regime (P23) — sebagai GATE, bukan ramalan.
7. Uji biaya: pakai biaya round-trip RIIL venue (bukan asumsi 5 bps generik).
8. Day-clustered inference + permutation null (P04).
9. Laporkan interval kepercayaan, bukan titik tunggal.
10. Rantai translasi alpha (P16): berhenti di "sinyal" = belum cukup.
```

---

## BAGIAN 6 — CHECKPOINT / NEXT BATCH

```
SELESAI:
 [x] Masterplan + acuan target terkoreksi (0,8% kumulatif/30j, SoDEX & CEX terpisah)
 [x] Kanal riset: harvest.py + litsearch.py (arXiv HTML + Crossref + OpenAlex)
 [x] Audit data lokal: 30 simbol × 18 bln 1h/4h/1d/funding/mark; OBI 1-menit 172K baris
 [x] 24 paper terverifikasi abstract (P01–P24) + digest
 [x] Sintesis v0.1: peta metode, jalur ditolak, 7 hipotesis falsifiable

BERIKUTNYA (Batch 6+):
 [ ] Perluas korpus: ~30-40 paper tambahan (exit geometry, regime, funding, eksekusi,
     ML-loss, portofolio, Hyperliquid/DEX-spesifik)
 [ ] Ekstraksi lebih dalam 6-8 paper kunci (full-text bila open-access tersedia)
 [ ] Uji empiris H1 & H6 di data lokal (bracket exit; mean reversion 1-30 jam)
 [ ] Uji empiris H3 (low-vol gating) di 94 trade CEX + backtest
 [ ] Bandingkan target 0,8% kumulatif/30j: berapa trade/posisi yang dibutuhkan
 [ ] Laporan final + rekomendasi bertingkat + rencana adopsi bertahap
```
