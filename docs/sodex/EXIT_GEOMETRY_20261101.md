# Geometri Exit — Paper Swing (SoDEX) — 1 Nov 2026

**Status:** riset read-only, TIDAK mengubah engine. Sumber: `data/paper_test_swing_state.json` (820 trade tertutup).
**Skrip:** `scripts/research/swing_exit_geometry_study.py` (deterministik, seed tetap).
**Output angka:** `reports/sodex/SWING_EXIT_GEOMETRY.json`.

---

## 1. Pertanyaan & hipotesis

- **H0:** mengganti aturan exit pada **set entry yang sama** tidak mengubah rata-rata return per trade.
- **H1:** aturan exit tertentu (hold lebih lama / TP lebih lebar / tanpa REGIME_FLIP) menghasilkan return lebih tinggi.

Desain: **entry dibekukan** (820 trade apa adanya), hanya aturan exit divariasikan. Satu variabel berubah → tidak ada bias seleksi entry.

## 2. Data & validasi

| Item | Nilai |
|---|---|
| Trade tertutup | 820 (semua **LONG**) |
| Rentang | 1 Agu – 1 Nov 2026 (87 hari) |
| Frekuensi | **11,8 trade per window 30 jam** |
| Path primer | SoDEX 1h (`data/sodex_klines/1h`), deviasi \|close_bar−entry\| median **0,25%** |
| Path sekunder | Binance 1h (paginasi penuh) — untuk triangulasi |
| Biaya | `_rt_cost()` engine: **median 0,120% round-trip** (min 0,106%, max 0,240%) |

**Bug yang ditemukan & dibuang (anti-khayalan):** versi pertama studi memakai cache Binance `limit=1000` (41 hari) sehingga trade Agustus dipetakan ke bar September → hasil fantastis **+7%/24 jam**. Cache dihapus, paginasi diterapkan, dan ditambahkan **guard plausibilitas** (sumber ditolak bila \|mean H24\| > 5%). Hasil di bawah hanya dari path yang lolos guard.

## 3. Kontrol negatif (entry acak sudah ada di dalam arm)

| Track | n | mean/trade | total $ | hit 0,8% |
|---|---:|---:|---:|---:|
| TANPA_TRACK (config lama) | 374 | +0,073% | +136,31 | 33% |
| RANDOM (kontrol) | 384 | −0,188% | −360,07 | 4% |
| SIGNAL | 62 | −0,455% | −141,00 | 18% |

SIGNAL − RANDOM = **−0,267 pp**, CI95 [−0,601; +0,083], p_boot = **0,127** (n SIGNAL hanya 62).
→ **Belum terbukti** SIGNAL berbeda dari acak; titik estimasi justru lebih buruk. Tidak ada klaim edge entry.

## 4. Hasil varian exit (paired, biaya sama)

Path SoDEX (n=819) — mean net per trade, CI95 bootstrap:

| Varian | mean | CI95 | total $ | hit 0,8% | Δ vs aktual | p | q(BH) |
|---|---:|---|---:|---:|---:|---:|---:|
| **AKTUAL** | −0,088% | — | −358,91 | 18% | — | — | — |
| H6 | −0,090% | [−0,26; +0,08] | −369,35 | 25% | −0,003 | 0,965 | 0,965 |
| H12 | −0,024% | [−0,25; +0,20] | −100,20 | 30% | +0,063 | 0,558 | 0,737 |
| **H24** | **+0,110%** | [−0,21; +0,44] | +449,05 | 36% | +0,197 | 0,203 | 0,456 |
| H30 | +0,010% | [−0,35; +0,38] | +38,91 | 34% | +0,097 | 0,574 | 0,737 |
| NRF (tanpa REGIME_FLIP) | −0,213% | [−0,33; −0,10] | −873,89 | 30% | −0,126 | **0,006** | **0,058** |
| NOTP (tanpa TP) | −0,212% | [−0,40; −0,00] | −870,13 | 19% | −0,125 | 0,161 | 0,456 |
| WIDE-TP 4% | −0,130% | [−0,27; +0,02] | −534,10 | 24% | −0,043 | 0,469 | 0,737 |
| WIDE-SL 1,5% | −0,181% | [−0,32; −0,05] | −739,52 | 37% | −0,093 | 0,085 | 0,380 |
| BOTH-WIDE | −0,096% | [−0,26; +0,07] | −392,84 | 30% | −0,008 | 0,928 | 0,965 |

Path Binance (n=815) — arah efek utama sama: H24 **+0,143%** (Δ +0,234 pp; p=0,138), NRF −0,166% (Δ −0,075 pp; p=0,109), NOTP −0,202% (Δ −0,110 pp; p=0,200).

**Dua sumber path sepakat arah** untuk H24, NRF, dan NOTP. **Tidak ada varian lolos BH-FDR q<0,05**; q terendah 0,058 (NRF SoDEX). Jadi hasil hanya bukti indikatif, bukan dasar mengubah parameter.

## 5. Hipotesis yang tidak terkonfirmasi (penting, jangan diulang sebagai fakta)

1. **"Exit terlalu cepat membunuh PnL"** — hanya indikatif. Hold 24 jam menambah **+0,197 pp**, tapi CI95 melewati nol, p=0,203, q=0,456. **Tidak signifikan.**
2. **"REGIME_FLIP penyebab kerugian"** — arah data justru berlawanan. Menghapus REGIME_FLIP memperburuk SoDEX (−0,213% vs −0,088%, p=0,006), tetapi tidak lolos BH-FDR (q=0,058); Binance sama arah dengan p=0,109. Exit regime *mungkin* pelindung, belum terkonfirmasi lintas-sumber/FDR.
3. **"TP memotong pemenang"** — arah **tidak didukung**. Tanpa TP hasilnya lebih buruk (SoDEX −0,212%; Binance −0,202%), tetapi p>0,05; ini bukan bukti final bahwa TP 2,5% optimal.
4. **"Hold bucket 24–30 jam positif → hold lama lebih baik"** — **BIAS SURVIVORSHIP.** Bucket itu hanya berisi trade yang *bertahan*, bukan trade yang dipaksa bertahan. Kontrafaktual menunjukkan keunggulannya kecil dan tidak stabil.

## 6. Bottleneck sebenarnya: biaya vs kebutuhan

- Kebutuhan: 0,8% wallet per window ÷ 11,8 trade = **0,068% net per trade**.
- Aktual: **−0,088% net per trade** (rugi).
- Biaya round-trip sudah **0,120%** — artinya **biaya > separuh target per trade**; gross harus **≥0,188%** per trade hanya untuk menyentuh target.
- H24 (bila nyata) → gross ≈0,230%, net +0,110% → akumulasi ≈**+1,30%/window** (lolos 0,8% di atas kertas), **tetapi** CI95 memuat nol dan eksposur kotor 11,8 × $500 ≈ $5.900 pada wallet ~$500 (**11,8× gross leverage**) — risiko ruin tinggi bila edge tidak nyata.

**Kesimpulan:** data **tidak memverifikasi** geometri exit sebagai bottleneck utama. Constraint arithmetic tetap **edge entry bersih setelah biaya**: biaya 12 bps menetapkan lantai; tanpa edge entry > ~19 bps gross per trade, target 0,8%/window tidak tercapai dengan frekuensi sekarang.

## 7. Rekomendasi (belum dieksekusi — butuh persetujuan)

1. **Forward-test arm hold-24h** sebagai instance terisolasi (env `PAPER_EXIT_MODE` baru / state terpisah), paper-only, 30 hari, bandingkan vs arm aktif. Bukan mengganti arm produksi.
2. **Uji hipotesis biaya:** apakah exit maker (limit) pada TP bisa menurunkan 12 bps → ~8 bps; ukur fill-rate nyata, bukan asumsi.
3. **Turunkan frekuensi** hanya jika terbukti gross/trade naik lebih dari proporsi penurunan n (uji dengan data yang sama).
4. **Jangan** menaikkan TP/SL atau melepas REGIME_FLIP sekarang — tidak ada varian lolos BH-FDR q<0,05; arah tanpa REGIME_FLIP malah lebih buruk.

## 8. Batasan

- Path 1h tidak menyelesaikan urutan intrabar; TP dan SL dalam satu bar dianggap **SL lebih dulu** (konservatif).
- 47% trade adalah kontrol RANDOM → statistik campuran; analisis per-track disajikan terpisah.
- Kontrafaktual bukan hasil fill nyata; slippage/antrean maker belum dimodelkan per bar.
- n SIGNAL = 62 → daya statistik rendah untuk klaim entry.
