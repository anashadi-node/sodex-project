# SoDEX Division RCA + A3 Recovery Plan — 2026-09-15

## D2 — Problem statement

Dashboard pusat menunjukkan kemajuan SoDEX tidak signifikan karena performa paper terlihat stagnan dan sebagian besar track belum melampaui target North Star:

- Target: >=0,7% dari total wallet per window/trade 1–30h.
- Current honest dashboard denominator: `$158,66` dari `.env.swing`, bukan fallback lama `$108,10`.
- Current progress: `1/8 track` melampaui target setelah denominator diperbaiki.
- Live status: tetap contained; kill switch ON.
- Deadline Owner: 15 Oktober 2026 = 30 hari dari 2026-09-15.

## D3 — Containment sekarang

- Live entry tetap terkunci: `REALWIDE_LIVE_KILL` dan `SPOT_LIVE_KILL` ON.
- Paper tetap jalan: REALWIDE, TWOWAY, Short-Bear baseline+variants, Swing, Spot, Donchian, Portfolio.
- Denominator dashboard diperbaiki: `SODEX_TOTAL_WALLET=158.66`, permission `.env.swing=600`.
- Tidak ada leverage/size/gate relaxation.

## KT IS / IS NOT

| Dimensi | IS | IS NOT | Distinction | Change/latent condition |
|---|---|---|---|---|
| WHAT | Paper progress tidak signifikan; hanya 1/8 track melampaui target saat wallet benar | Service tidak crash; watchdog sehat | Masalah ada di quality/edge, bukan uptime | Denominator lama 108,10 terlalu kecil; setelah update target $0,757 -> $1,111 |
| WHERE | Loss terbesar di CHOP regime dan multi-venue non-SoDEX proxy | BULL entries REALWIDE/TWOWAY profitable | Entry LONG bekerja saat BULL, gagal saat CHOP | Regime gate tidak cukup keras di mode relaxed data-collection |
| WHEN | Minggu W37: REALWIDE n=53 WR 34% net -$112,24 | W34 bullish: n=15 WR 87% net +$119,33 | Drawdown muncul saat BTC sideways/down, bukan saat trend up kuat | Market bergeser dari momentum bull ke chop; relaxed collection tetap entry |
| EXTENT | REALWIDE CHOP n=73 net -$145,85; TWOWAY CHOP n=97 net -$131,46 | REALWIDE BULL n=52 net +$283,64; TWOWAY BULL n=102 net +$281,22 | CHOP menghapus sebagian besar edge | Latent: dashboard menilai all-regime aggregate, bukan regime-conditioned quality |

## Root cause verified

### Root cause #1 — CHOP regime entry pada LONG-only paper track

Counterfactual `reports/SODEX_REGIME_COUNTERFACTUAL_2026-09-15.json`:

REALWIDE:

- baseline: `n=132`, net `$132,27`.
- BULL: `n=52`, WR `75,0%`, net `$283,64`.
- CHOP: `n=73`, WR `30,1%`, net `-$145,85`.
- BEAR: `n=7`, net `-$5,52`.

TWOWAY:

- baseline: `n=219`, net `$154,70`.
- BULL: `n=102`, WR `55,9%`, net `$281,22`.
- CHOP: `n=97`, WR `30,9%`, net `-$131,46`.
- BEAR: `n=20`, net `$4,94`.

Kesimpulan: CHOP adalah root cause utama karena menjelaskan lokasi masalah (track LONG), kapan terjadi (W37 sideways/down), dan extent (loss besar), sementara BULL entries justru profitable.

### Root cause #2 — Dashboard denominator stale

Sebelum fix:

- `.env.swing`: `$108,10`.
- wallet aktual: `$158,66`.
- bias: ROI terlalu optimis `31,9%`.
- target 0,7% berubah dari `$0,757` menjadi `$1,111`.

Dampak: dashboard lama bisa terlihat lebih baik dari realitas. Setelah diperbaiki, track yang melampaui target turun dari 2/8 menjadi 1/8.

### Root cause #3 — Short-Bear bukan stagnan karena service mati, tetapi karena regime/signal tidak valid

Telemetry baseline Short-Bear >4.800 rows:

- decisions: mayoritas `blocked_signal`.
- `bear_stack` sekitar 17%, `chk>=4` sekitar 7,3%.
- closed trades tetap `n=7`, net `-$2,19`.

Counterfactual Short-Bear gate calibration:

- spot `bear&chk4` positif kecil hanya h1-h4, negatif di h8-h16.
- futures `bear&chk4` negatif di semua horizon.

Kesimpulan: memaksa Short-Bear entry akan meningkatkan loss, bukan mempercepat target.

## Bottleneck utama (TOC)

Constraint sistem saat ini: **regime-conditioned edge quality**, bukan jumlah service.

Urutan bottleneck:

1. **Regime gate** — CHOP menghapus edge BULL.
2. **Wallet denominator** — target sebenarnya lebih besar dari yang dashboard lama tampilkan.
3. **Live readiness blocker** — exchange/local mismatch: AAVE-USD 0,35 ada di exchange, local open kosong.
4. **Venue-native signal gap** — beberapa paper masih memakai Binance proxy; SoDEX mark baru mulai dipakai pada variants.
5. **Sample maturity** — Short-Bear variants belum punya closed trades forward.

## D5 — Corrective actions yang sudah dieksekusi

1. `paper_test_realwide.py`
   - Tambah `btc_daily_regime()` BULL/BEAR/CHOP.
   - Entry LONG baru diblok saat BTC daily CHOP.
   - Posisi open tetap dikelola exit; tidak ada force close.
   - Trade baru menulis `btc_regime`.

2. `paper_test_twoway.py`
   - Tambah CHOP gate sama untuk entry LONG baru.
   - SHORT leg tetap disabled sesuai evidence lama.
   - Posisi open tetap dikelola exit.

3. `sodex_wallet_denominator.py`
   - Denominator final tidak lagi diblok oleh dust immaterial `vsMAG7.ssi`.
   - Material unpriced tetap fail-closed.
   - Applied: `.env.swing SODEX_TOTAL_WALLET=158.66`.
   - Permission dikoreksi: `.env.swing=600`.

4. `sodex_progress_report.py`
   - Dashboard/report membaca `.env.swing` langsung.
   - Header sekarang menampilkan source: `wallet $158.66 (.env.swing)`.

5. Test baru:
   - `tests/test_realwide_chop_gate.py`.
   - `tests/test_twoway_chop_gate.py`.
   - `tests/test_sodex_progress_report.py`.
   - `tests/test_sodex_wallet_denominator.py` diperkuat.

## D6 — Validation

- Targeted tests: `13 passed`.
- Full suite: `3712 passed, 8 skipped, 292 warnings, 83 subtests passed`.
- Services restarted:
  - `anantara-paper-realwide.service`: active.
  - `anantara-paper-twoway.service`: active.
- Watchdog: `SEMUA SEHAT`.
- Live kills: ON.
- Dashboard report now: `wallet $158.66 (.env.swing)`.

## SMART plan sampai 15 Oktober 2026

### Specific

Fokus SoDEX nomor 1: ubah paper dari all-regime collection menjadi quality-forward evidence system, lalu siapkan live only jika gate evidence dan reconciliation bersih.

### Measurable

Milestone wajib:

- 2026-09-18: dashboard denominator, regime tags, live containment, paper health stabil 72 jam.
- 2026-09-22: regime-conditioned leaderboard harian: BULL/CHOP/BEAR per track.
- 2026-09-29: candidate pruning: track dengan n>=20 dan negative expectancy dipause; BULL-only tracks dievaluasi.
- 2026-10-06: live readiness audit: exchange/local reconciliation, denominator final, watchdog zero critical.
- 2026-10-12: canary plan final kalau semua evidence pass.
- 2026-10-15: full live hanya bila GO-LIVE user approval + all gates pass.

### Achievable / honest constraint

Saya akan bekerja untuk membuat SoDEX siap, tetapi tidak akan menjamin profit palsu. Jika data forward tidak lulus, keputusan profesional adalah tidak membuka full live walau tanggal sudah dekat. Target harga mati = disiplin menuju edge, bukan izin melanggar risk.

### Relevant

Semua aksi langsung terkait target 0,7%: blok CHOP loss, pakai denominator benar, prioritaskan track BULL-positive, tahan live sampai reconciliation valid.

### Time-bound

Review harian 06:00 WIB, checkpoint milestone dua kali seminggu, live gate final 12–15 Okt.

## Next actions

1. Tambahkan leaderboard regime-conditioned ke dashboard pusat.
2. Tambahkan alert jika CHOP gate memblok >24 jam agar dashboard menjelaskan stagnasi sebagai `regime protective wait`, bukan service macet.
3. Audit open TWOWAY 6 posisi — pastikan exit-management sehat dan tidak perlu intervention.
4. Reconcile AAVE-USD live mismatch sebelum live canary.
5. Evaluasi Short-Bear variants hanya setelah n>=20 per variant; jangan paksa entry.
