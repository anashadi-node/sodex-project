# GO-LIVE 1 DESEMBER 2026 — RENCANA LIVE FULL SIZE (keputusan Owner, 2026-11-07)

Keputusan Owner: **live full size dengan target 0,7%/window**, sadar risiko.
Dokumen ini mencatat **angka konsekuensinya** + syarat yang tidak boleh dilewati
sebelum tombol live ditekan. Bukan penolakan; ini kontrol risiko.

## 1. Angka yang harus dibaca sebelum live (dari ledger + replay, bukan asumsi)

| konfigurasi | mean/trade | 6,54 trade/window | $1.000 | $5.000 | $10.000 |
|---|---|---|---|---|---|
| exit apa adanya (flip ON, time-stop 30h) | −0,202% | **−1,32%/window** | −13,2 | −66,1 | −132,1 |
| flip OFF + tanpa time-stop (replay) | +0,007% | +0,05%/window | +0,5 | +2,3 | +4,6 |
| flip OFF + trail 1R (replay) | +0,055% | +0,36%/window | +3,6 | +18,0 | +36,0 |

Target 0,7%/window ⇒ butuh **gross ≥ 0,205%/trade** (biaya 0,098pp).
Gross sekarang 0,00–0,10pp/trade ⇒ **shortfall ~0,10–0,20pp/trade**.

Bulanan (asumsi window 30 jam ⇒ 24 window/bulan, dihitung program):
- konfigurasi sekarang: **−27,3%/bulan** (0,727×)
- flip OFF + tanpa time-stop: **+1,2%/bulan** (1,012×)
- flip OFF + trail 1R: **+9,0%/bulan** (1,090×)

Angka terbaik (+9,0%/bulan) masih di bawah target 0,7%/window berkelanjutan
(0,7%×24 ≈ +18,2%/bulan).

## 2. Perubahan yang SUDAH live (bukan wacana)

1. Lane `partial`: `SW_BTC_GATE=1` (A/B 4) — entry baru diblokir saat BTC mom30 < 0.
2. Lane `partial`: `SW_REGIME_FLIP=0` (A/B 5, disetujui Owner) — exit flip dimatikan.
3. Lane `swing` = **arm kontrol** (flip ON, gate OFF) untuk DiD.
4. State tidak hilang saat restart: closed=1004, open=1 (sesudah = sebelum).
5. Test suite gate: 18 passed. Governor `--selfcheck`: PASS.

## 3. Prasyarat live 1 Des (tidak bisa dikompromikan)

| # | syarat | alasan |
|---|---|---|
| 1 | Gross edge ≥0,205pp/trade, n≥200 OOS, p<0,05, BH-corrected | tanpa ini live = transfer kekayaan statistik |
| 2 | `dry_run=false` hanya setelah GO-LIVE decision tertulis per 1 Des | red line #2/#6 |
| 3 | Kill-switch: stop semua entry saat equity −5% harian | mencegah ruin |
| 4 | Cap per lane & per pair (bukan "full size" tanpa batas) | 1 pair rusak ≠ akun rusak |
| 5 | Rekonsiliasi venue (SoDEX ledger) harian otomatis | deteksi drift/slippage |
| 6 | Modal per lane ≤25% total; sisanya idle reserve | Kelly fractional |
| 7 | Spot vs perps dipisah akun/lane | likuidasi perps tidak menyentuh spot |

"Full size" tetap tunduk pada #3–#6. Tanpa itu, full size = 1 trade buruk
menghapus seluruh modal (lihat EMERGENCY_SL −2,24%/trade × leverage).

## 4. Yang belum diketahui (butuh jawaban Owner)

- **Modal live (USD)** — belum dijawab; semua angka $ di atas diskalakan.
- Spot + perps sekaligus atau bertahap?
- Batas kerugian harian yang dapat diterima (usulan: 5% equity).
- Apakah 1 Des tetap dipakai walau gross edge < 0,205pp saat itu?

## 5. Jadwal sampai 1 Des (24 hari)

| tanggal | target |
|---|---|
| 7–14 Nov | A/B 4 & 5 kumpulkan data; uji entry-edge (pair whitelist + mom gate) |
| 15–21 Nov | kandidat entry-edge diuji OOS 200 trade; BH-correct |
| 22–27 Nov | paper forward dengan konfigurasi final (exit + entry gate) |
| 28–30 Nov | venue test sodex.com: order kecil, latensi, fee, rekonsiliasi |
| 1 Des | keputusan GO/NO-GO berbasis angka, bukan tanggal |
