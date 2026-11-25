# PRAREG-LB-3 — Persistensi & level return trader SoDEX (per-akun, 1 tahun, bebas bias seleksi leaderboard) — DIKUNCI 2026-10-09
Menggantikan L2-2b (leaderboard hanya mengekspos 1.000 teratas; populasi penuh tak terjangkau). Dikunci SEBELUM mengunduh seri per-akun.
Data: `GET mainnet-data.sodex.dev/api/v1/wallet/portfolio/chart?account_id=X&window=1Y` (publik, endpoint yang dipakai situs sodextracker.com) → harian: account_value_usd, pnl_usd, spot/perps/vault pnl. Read-only.

## Sampel
- A (populasi, tak bias seleksi hasil): 1.500 account_id acak seragam dari [1000, 235000], seed 20261009; id tanpa wallet dibuang. Mewakili semua akun termasuk yang rugi/mati.
- B (pemenang, hanya DESKRIPTIF): 500 teratas leaderboard ALL_TIME (snapshot 09-Okt). Bias winner's-curse → tidak dipakai untuk inferensi OOS.

## Definisi (beku)
- Grid 48 jam dari titik terakhir mundur. Return r = ΔPnL / AV_awal; jendela dengan AV_awal < $1.000 dibuang. H1 = paruh pertama kalender (≈ 2025-10-10…2026-04-09), H2 = paruh kedua. (Seleksi pada H1, uji pada H2.)
- Akun eligible: ≥ 20 jendela aktif (ΔPnL≠0, AV_awal≥$1.000) di H1 dan ≥ 20 di H2.
- Sebaliknya: dilaporkan sebagai "tidak eligible" (n dan alasannya) — keterbatasan umur venue.

## Uji (pada sampel A saja)
U1 deskriptif: fraksi akun profitable seumur hidup (1Y), median ROI, distribusi.
U2 persistensi: Spearman ρ(Sharpe_48j H1, Sharpe_48j H2), p permutasi 10.000×.
U3 top-desil H1 → mean r H2 (CI95 bootstrap-akun), % >0 vs base-rate; kontrol: desil acak 1.000×.
U4 level target: berapa akun (n, % eligible) punya mean r H2 ≥ 0,8%/48j DAN Sharpe_48j H2 ≥ 0,4 (setara Sharpe tahunan >5, gerbang kita) DAN mean r H1 ≥ 0,8% (seleksi H1) — diuji sebagai replikasi OOS.
U5 (hanya B) deskriptif: komposisi PnL (spot / perps closed / unrealized / vault), ROI, volume/AV (proxy leverage-turnover), klasifikasi pola (rugi-tapi-volume-besar = indikasi farming poin).

## Kriteria (beku)
"Persistensi trader SoDEX TERDUKUNG" bila: U2 p<0,05 ∧ CI95 bawah mean r H2 top-desil > 0 ∧ di luar 95% kontrol acak.
"Level target dicapai OOS oleh ≥ 1 akun" bila U4 ≥ 1 akun; "dapat direplikasi sebagai strategi" HANYA bila ≥ 5 akun independen (bukan satu operator) — operator ganda tak terdeteksi → keterbatasan.
Selain itu: TIDAK TERDUKUNG. Bias diakui: survivorship (akun yang berhenti trading tidak eligible), ID bukan orang (multi-akun), PnL tanpa pembedaan sumber (poin/airdrop tidak masuk pnl_usd, hanya yang dihitung venue).
