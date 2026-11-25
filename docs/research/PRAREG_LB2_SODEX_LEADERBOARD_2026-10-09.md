# PRAREG-LB-2 — Leaderboard SoDEX: berapa PnL top-wallet yang benar-benar HASIL TRADING & persisten? — DIKUNCI 2026-10-09
Dikunci setelah pengumpulan snapshot (top-1000 per window 7D/30D/90D/ALL_TIME, `mainnet-data.sodex.dev/api/v1/leaderboard`, publik GET) dan SEBELUM analisis. Observasi yang sudah terlihat saat pengumpulan: beberapa top-PnL punya volume ≈ 0 (tidak dipakai untuk memilih hipotesis, hanya memotivasi klasifikasi).
Leaderboard SoDEX tidak memuat ekuitas → ROI tidak bisa dihitung; hanya pnl_usd & volume_usd. Keterbatasan diakui.

## Klasifikasi (beku)
- NON-TRADING: volume_usd < 5% × |pnl_usd| (PnL bukan dari perputaran trading; mis. nilai aset/airdrop/spot-hold/mirror).
- TRADING: volume_usd ≥ 20× |pnl_usd| (edge ≤ 500 bp dari volume — plausibel hasil trading).
- ANTARA: sisanya.

## Hipotesis
- L2-1: Fraksi PnL positif top-100 (per window) yang berklasifikasi TRADING ≤ 50% → "leaderboard didominasi non-trading".
- L2-2: Persistensi: overlap(top-100 ALL_TIME ∩ top-1000 7D) vs ekspektasi acak 100×1000/136.492=0,73 wallet; uji eksak hipergeometrik.
- L2-3: Edge per volume: untuk wallet TRADING dengan volume ≥ $100 rb, median & p90 pnl/volume (bp). Bandingkan dengan biaya taker RT 8 bp.
- L2-4 (replikabilitas): jumlah wallet TRADING yang pnl_30D ≥ 12,7% dari… tidak dapat dihitung (tanpa ekuitas) → dilaporkan "TIDAK DAPAT DIUJI"; diganti proksi: pnl_30D/volume_30D ≥ 8 bp ∧ volume ≥ $1 jt.

## AMANDEMEN-1 (memperketat; ditulis setelah melihat L2-1/L2-3 tetapi karena cacat LOGIKA, bukan hasil)
L2-2 di atas TIDAK VALID: window 7D⊂30D⊂90D⊂ALL_TIME bersarang → overlap mekanis. Dicabut sebagai bukti. Pengganti L2-2b:
populasi PENUH (semua wallet, sort pnl desc, page_size 50) untuk 30D dan 90D; periode terpisah P_prior = pnl90 − pnl30 (hari ≈ −90…−30), P_recent = pnl30.
Syarat: volume90 − volume30 ≥ $10.000 DAN volume30 ≥ $10.000 (aktif di kedua periode). Uji: Spearman ρ(P_prior, P_recent), p permutasi 10.000×;
top-desil P_prior → % dengan P_recent>0 vs base-rate, CI95 bootstrap. Kontrol negatif: desil acak. Keterbatasan: pnl90−pnl30 mengasumsikan kedua snapshot sama ts; selisih ts dilaporkan.

## Kriteria
"Ada bukti trader SoDEX berskill yang persisten" hanya bila L2-2 p<0,05 (BH, 3 uji) ∧ ada ≥ 20 wallet TRADING dengan pnl/volume > 8 bp di 90D DAN positif di 30D.
Selain itu: TIDAK TERDUKUNG. Bias: top-N = seleksi atas hasil (winner's curse); wallet dapat multi-akun/sybil; PnL mungkin tidak diperbaiki untuk funding/fee.
