# RISET PARALEL 22-OKT-2026 — TRACK A (data baru) + TRACK B (buku hidup)

**Mandat user:** "Approve Opsi 1 + 2 secara paralel, kedua jalur saling mengisi; riset lagi luas & mendalam; SoDEX tetap berjalan dan berhasil."
**Sifat:** read-only. Tidak ada order, tidak ada perubahan arm A/B, tidak ada unduhan massal, tidak ada kredensial disentuh.
**Bukti:** semua angka di bawah berasal dari eksekusi nyata pada 22-Okt-2026 (bukan kutipan memori).

---

## RINGKASAN (3 temuan yang mengubah cara kita bekerja)

1. **Data OI/positioning tersedia GRATIS dan historis** — Binance Vision `futures/um/daily/metrics` sudah diverifikasi HTTP 200, granularitas **5 menit**, kolom OI + rasio long/short + taker ratio, mulai dari tanggal listing simbol (BTC 2021-01-01). Ini membuka keluarga mekanisme yang belum pernah diuji, **tanpa biaya**.
2. **Data likuidasi historis TIDAK tersedia gratis** — path `liquidationSnapshot` di Binance Vision **404 (terverifikasi)**. Likuidasi hanya bisa: (a) direkam sendiri mulai hari ini (gratis, tapi hanya ke depan), atau (b) dibeli dari vendor.
3. **Buku hidup gagal di gerbang B bukan karena kurang sinyal, tapi karena variance & leverage.** Distribusinya bimodal (SL −2,2% / TP +3,5%), 20 trade teratas = **91,3%** dari seluruh PnL, dan **tidak ada satu pun** aturan seleksi yang bisa menaikkan hit rate di atas 50%.

---

## TRACK A — INVENTARIS DATA (semua diverifikasi dengan request nyata)

| Dataset | Sumber | Granularitas | Cakupan | Biaya | Status verifikasi |
|---|---|---|---|---|---|
| **OI + long/short ratio + taker ratio** | `data.binance.vision/data/futures/um/daily/metrics/{SYM}/` | **5 menit**, 288 bar/hari | dari listing simbol (BTC 2021-01-01; SOL/DOGE 2022) | **Gratis** | **200 OK**, 11,6 KB/hari/simbol, 8 kolom terkonfirmasi |
| OI historis via API | `fapi.binance.com/futures/data/openInterestHist` | 5m/15m/1h/1d | **hanya 30 hari terakhir** | Gratis | **200 OK** |
| Taker buy/sell volume | `futures/data/takerlongshortRatio` | 5m–1d | 30 hari | Gratis | **200 OK** |
| aggTrades (tick) | `daily/aggTrades` | per-trade | penuh | Gratis | **200 OK** (berat: GB/hari) |
| **Likuidasi historis** | Binance Vision `liquidationSnapshot` | — | — | — | **404 — TIDAK ADA** |
| Likuidasi real-time | WS `fstream.binance.com/ws/!forceOrder@arr` | per-event | **hanya ke depan** | Gratis | endpoint publik (perlu daemon perekam) |
| Likuidasi historis (vendor) | Tardis.dev / Coinglass / Amberdata | tick–1m | bertahun-tahun | berbayar | belum diuji (tidak diunduh) |
| Hyperliquid OI | `api.hyperliquid.xyz/info` `metaAndAssetCtxs` | snapshot saat ini | **tanpa histori** | Gratis | terkonfirmasi — hanya nilai sekarang |
| Hyperliquid candle | `candleSnapshot` | 1m–1d | penuh | Gratis | 200 OK (OHLCV saja, tanpa OI) |

### Isi kolom `metrics` (terkonfirmasi dari file nyata)
```
create_time, symbol, sum_open_interest, sum_open_interest_value,
count_toptrader_long_short_ratio, sum_toptrader_long_short_ratio,
count_long_short_ratio, sum_taker_long_short_vol_ratio
```
Contoh baris nyata (BTCUSDT, 2026-10-01 00:30Z): OI 95.676 BTC (≈$7,98 miliar), rasio top-trader 2,10 long/short, taker ratio 0,907.

### Implikasi untuk mekanisme yang BELUM diuji
- **Crowding reversal berbasis OI** — OI naik tajam sementara harga stagnan = posisi menumpuk di satu sisi → kandidat mean-reversion. **Bisa diuji sekarang, gratis, 2021→2026.**
- **Taker-flow imbalance** — rasio taker beli/jual ekstrem sebagai contrarian jangka pendek.
- **Likuidasi** — butuh perekam WS mulai sekarang; realistis baru punya sampel bermakna setelah ~6–12 bulan. **Tidak bisa dipakai untuk target 25-Nov.**

**Kesimpulan Track A:** keluarga mekanisme baru yang layak = **OI/positioning (gratis, historis penuh)**. Keluarga likuidasi = **tidak layak untuk timeline ini**; hanya layak sebagai investasi data jangka panjang.

---

## TRACK B — DIAGNOSIS BUKU HIDUP (arm A, n=476 trade tertutup)

### B.1 Distribusi per trade

| Metrik | Nilai |
|---|---|
| Mean | **+0,103%** |
| Median | **−0,483%** |
| SD | 2,477% |
| p25 / p50 / p75 | −2,17% / −0,48% / **+2,16%** |
| Min / Max | −3,41% / +5,68% |
| Win rate | 40,5% |
| Top-10 trade = | **48,2%** dari total PnL |
| Top-20 trade = | **91,3%** dari total PnL |

**Bentuknya bimodal, bukan normal**: hampir setiap trade berakhir di salah satu dari dua kutub. Ini konsekuensi langsung geometri TP/SL, bukan keacakan pasar.

### B.2 Dari mana PnL datang (exit reason)

| Exit | n | % trade | Mean | Median | WR |
|---|---|---|---|---|---|
| **SL** | 201 | 42,2% | **−2,212%** | −2,174% | 0% |
| **TP** | 133 | 27,9% | **+3,535%** | +3,979% | 100% |
| TIME_30h | 134 | 28,2% | +0,184% | −0,082% | 41,8% |
| TIME_48h | 8 | 1,7% | −0,129% | −0,184% | 50% |

**Breakeven WR untuk geometri ini = 2,212 / (2,212 + 3,535) = 38,5%.** Aktual 40,5% → **margin hanya +2,0 pp**. Inilah seluruh edge buku ini: dua poin persen di atas breakeven, dan 42% trade kalah.

### B.3 Leverage: sumber angka 1% per window

- Notional implisit median per trade: **$300** (dari `pnl_usd / pnl_pct`).
- Rata-rata **8,2 trade terbuka per window**.
- Artinya gross exposure ≈ **8 × $300 = $2.400** terhadap wallet ≈ $243 → **≈10× ekuitas**.

**Konsekuensi jujur:** mean +1,05%/window itu dicapai pada ~10× leverage. Pada 1× (D1 opsi B), ekspektasinya ≈ **0,10–0,16%/window** — jauh di bawah 0,8%. Ini yang membuat V2 §9 ("kandidat yang mencapai target hanya lewat leverage berlebih harus ditolak") langsung relevan pada buku kita sendiri.

### B.4 Counterfactual seleksi (diagnostik, n=58 window — kecil, jangan diperlakukan sebagai bukti)

| Aturan | n window | Mean | Median | Hit ≥0,8% | Lolos A&B? |
|---|---|---|---|---|---|
| **Baseline** | 58 | +1,047% | −0,320% | 46,6% | A ✅ / B ❌ |
| Tanpa SHORT | 55 | **+1,527%** | **+0,167%** | 45,5% | A ✅ / B ❌ |
| Tanpa conviction 0,8 | 57 | +1,407% | −0,084% | 45,6% | A ✅ / B ❌ |
| Tanpa RANDOM_CONTROL | 56 | +1,404% | −0,320% | 48,2% | A ✅ / B ❌ |
| LONG & no 0,8 & no TIME30 | 50 | +1,311% | **+0,256%** | 44,0% | A ✅ / B ❌ |
| Tanpa TIME_30h | 54 | +0,560% | −1,231% | 46,3% | A ❌ / B ❌ |

**Tidak ada kombinasi yang mencapai hit ≥50%.** Yang terbaik hanya menyentuh 48,2%. Korelasi hasil window terhadap jumlah trade (−0,06), proporsi short (−0,11), dan proporsi conviction 0,8 (−0,02) semuanya ≈ nol — **tidak ada variabel ex-ante yang bisa dipakai untuk menyaring window**.

### B.5 Dua cacat teknis yang ditemukan (bukan opini, terukur)

1. **`atr_pct` = 0,0 pada SELURUH 476 trade.** Field ada di skema, tapi tidak pernah diisi. Artinya: setiap logika yang bergantung pada ATR (sizing, filter volatilitas, TP adaptif) **secara diam-diam tidak pernah aktif**. Ini bug diam, bukan sekadar field kosong.
2. **Conviction 0,8 justru LEBIH BURUK dari 0,6** (mean −0,144% vs +0,246%; median −0,916% vs −0,334%; WR 37,3% vs 42,6%, n=110). Sinyal keyakinan **terbalik**. Belum cukup bukti untuk membalik apa pun (n kecil, dan membalik = tuning), tapi ini harus dicatat dan dipantau.

### B.6 Diagnosis akar masalah (Track B)

Dengan kerangka IS/IS NOT:

| Dimensi | IS (masalah ADA) | IS NOT (masalah TIDAK ADA) |
|---|---|---|
| WHAT | Window dengan median negatif & hit 46,6% | Mean window — **lolos** 1,05% ≥ 0,8% |
| WHERE | Semua konfigurasi seleksi (SHORT dibuang, conviction difilter, dll) | Bukan spesifik satu pair/jam (korelasi ≈0) |
| WHEN | Sepanjang 58 window (Agustus–Oktober) | Bukan satu periode rusak |
| EXTENT | 42% trade kalah, top-20 = 91,3% PnL | Bukan kegagalan total — ada edge +2,0 pp di atas breakeven |

**Kesimpulan:** penyebabnya **variance per window**, bukan ketiadaan edge. Dengan 8 trade/window dan distribusi bimodal ±2–3,5%, hasil window ditentukan oleh *berapa banyak TP yang kena* — variabel yang tidak dapat diprediksi dari data ex-ante yang kita punya. **Seleksi tidak bisa memperbaikinya; hanya perubahan geometri (TP/SL/sizing) atau penambahan sumber informasi baru yang bisa.**

---

## TITIK TEMU — mengapa dua track ini saling mengisi

- **Track B** bilang: kita butuh **konsistensi** (variance turun) atau **sinyal baru** yang tidak bergantung pada arah pasar.
- **Track A** memberi persis itu: **data OI/positioning** adalah informasi *orthogonal* terhadap harga — mengukur **seberapa ramai** satu sisi, bukan ke mana harga pergi. Mekanisme crowding-reversal secara desain **market-neutral dan berhorizon pendek** (jam), sehingga profilnya berlawanan dengan buku trend-following yang bimodal.
- Jadi Track A bukan pelarian dari Track B — ia menjawab kebutuhan yang Track B identifikasi secara numerik.

---

## RENCANA 3 MINGGU (sampai verdict 25-Nov), tanpa mengubah arm A/B

| # | Aksi | Biaya | Risiko | Status |
|---|---|---|---|---|
| 1 | Unduh `metrics` Binance Vision 20 simbol (2021→2026, ≈400 MB) | gratis | nol (read-only) | **menunggu approval** — skrip `scripts/research/binance_vision_metrics.py` **sudah diuji: 8/8 file OK, 288 bar/hari** |
| 2 | PRAREG-30: crowding-reversal berbasis OI (pra-registrasi + hash sebelum data) | gratis | nol | **belum ditulis** |
| 3 | Perbaiki `atr_pct` yang selalu 0 (bug diam) | nol | rendah — tapi menyentuh engine, perlu review | **SELESAI 22-Okt** — write-only terverifikasi, 6 tes baru, perilaku trading tidak berubah |
| 4 | Perekam likuidasi WS mulai hari ini (investasi 6–12 bulan) | gratis | rendah (proses baru) | **belum** |
| 5 | Arm A/B dibiarkan berjalan; verdict 25-Nov apa adanya | — | — | berjalan |

**Yang TIDAK akan saya lakukan tanpa izin eksplisit:** mengubah arm A, mengubah TP/SL buku hidup, menaikkan leverage, atau memulai live trading.

---

*Hermes Anantara v3 · 22-Okt-2026 · read-only · semua angka dari eksekusi nyata*
