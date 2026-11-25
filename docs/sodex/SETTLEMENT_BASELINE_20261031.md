# BASELINE SETTLEMENT — alpha vs BTC (PRAREG-40)

Tanggal: 31-Okt-2026 · Sumber: `data/paper_test_*_state.json` → `reports/sodex/PRAREG40_SETTLED.jsonl`
Metode: `scripts/settle_paper_alpha.py` (5 tes unit lulus). Biaya 8 bps round-trip,
return **unlevered** dari harga, beta +1 long / −1 short, benchmark BTC spot 1h
(cache diperbarui otomatis dari Binance publik; trade di luar cakupan → `UNSETTLED`,
tidak dikarang).

## Hasil (n = 1.690 trade, 15 track)

| Track | n | alpha_net | t | p | BH thr (q=0,05) | Verdict |
|---|---|---|---|---|---|---|
| pasar_anantara_trade | 47 | **+0,446%** | +2,55 | 0,0142 | 0,0033 | gagal |
| spot_swing_v2 | 265 | −0,230% | −2,42 | 0,0164 | 0,0067 | gagal |
| portfolio | 97 | −0,276% | −2,21 | 0,0298 | 0,0100 | gagal |
| realwide | 341 | −0,135% | −1,31 | 0,190 | 0,0133 | gagal |
| shortbear | 58 | −0,163% | −1,18 | 0,245 | 0,0167 | gagal |
| aster | 272 | −0,154% | −1,02 | 0,308 | 0,0200 | gagal |
| hyperliquid | 242 | −0,161% | −0,87 | 0,388 | 0,0233 | gagal |
| shortbear_strict_rsi_volume | 5 | −0,459% | −0,94 | 0,401 | 0,0267 | gagal |
| donchian | 275 | −0,094% | −0,63 | 0,532 | 0,0300 | gagal |
| shortbear_strict_all_5 | 2 | +0,269% | +0,49 | 0,707 | 0,0333 | gagal |
| shortbear_venue_native_guard | 17 | +0,066% | +0,27 | 0,792 | 0,0367 | gagal |
| shortbear_baseline_control | 17 | +0,064% | +0,26 | 0,799 | 0,0400 | gagal |
| shortbear_fast_exit_2h | 19 | −0,043% | −0,25 | 0,808 | 0,0433 | gagal |
| shortbear_closed_candle_entry | 16 | −0,059% | −0,24 | 0,816 | 0,0467 | gagal |
| shortbear_sodex_mark_execution | 17 | −0,007% | −0,03 | 0,979 | 0,0500 | gagal |

## Tiga kesimpulan

1. **Tidak ada satu pun track yang punya alpha terbukti.** Setelah koreksi BH untuk
   15 track, kandidat terkuat (`pasar_anantara_trade`, +0,446%) pun gagal: p = 0,0142
   vs ambang 0,0033. Klaim "+0,45% per trade" tanpa koreksi multiple-testing akan salah.
2. **PnL paper hampir seluruhnya beta.** `realwide` raw +0,032% saat BTC +0,087%;
   `shortbear` raw −0,256% saat BTC +0,173%. Setelah fee 8 bps, tidak ada sisa skill.
3. **Tiga track secara statistik lebih buruk dari passif:** `spot_swing_v2` (t = −2,42),
   `portfolio` (t = −2,21, raw −0,396%), dan arah yang sama pada `aster`/`hyperliquid`.
   Ini bukan noise satu-dua trade; n-nya ratusan.

## Konsekuensi untuk target 0,8%/30 jam
Target tidak bisa dikejar dengan menambah track yang raw-nya positif saat BTC naik.
Gerbang seleksi harus menuntut **alpha > 0 setelah fee**, dan PRAREG-40 (reflection)
baru bernilai kalau ia menaikkan **alpha**, bukan raw. Baseline ini menjadi pembanding A
yang terukur — bukan asumsi.

## Batasan
- Benchmark 1h close; trade dengan exit di luar cakupan cache → `UNSETTLED` (n settled
  < n closed pada beberapa track), tidak diisi dengan harga karangan.
- Fee 8 bps konstan; funding perp belum dimodelkan (bias kecil untuk hold < 8 jam).
- State file hanya memuat trade yang masih tersimpan; tidak ada klaim bebas survivorship
  di luar cakupan itu.
