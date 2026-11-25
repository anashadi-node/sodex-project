# SoDEX Harness Re-evaluation — 2026-10-02
**Status:** T1 FAIL. Tidak ada strategi/gate/leverage/exit yang diubah. Lane uang nyata tetap FROZEN.
## Metode
- Harness: `/home/USER/anantara-sakti/docs/handover/RISET_TO_DIVISI_2026-10-01/harness`; self-test 18/18 PASS sebelum evaluasi.
- Returns: `pnl_pct` / `pnl_per_trade`; market beta: BTCUSDT Binance spot 1h close at/before entry→exit.
- Fee: SoDEX tier-0 8 bps RT; harness cost stress 1×/1,5×/2×.
- Registry trial: `/home/USER/anantara-sakti/reports/sodex/sodex_trial_registry.json`; count 235.

## Hasil 3 track
| Track | n | WR input | excess_mean | median | Sharpe ann | CI95 mean | cost 1× mean | cost 2× mean | PASS | alasan gagal utama |
|---|---:|---:|---:|---:|---:|---|---:|---:|---|---|
| swing | 445 | 33.708% | -0.165% | -0.715% | -1.98 | [-0.312%; -0.015%] | -0.245% | -0.325% | False | level_decision: net_pos_1x, net_pos_2x, ci95_lower_positive, dsr_passed |
| twoway | 512 | 39.648% | 0.029% | -0.351% | 0.27 | [-0.150%; 0.205%] | -0.051% | -0.131% | False | level_decision: net_pos_1x, net_pos_2x, ci95_lower_positive, dsr_passed |
| realwide | 298 | 44.966% | -0.112% | -0.342% | -1.07 | [-0.337%; 0.108%] | -0.192% | -0.272% | False | level_decision: net_pos_1x, net_pos_2x, ci95_lower_positive, dsr_passed |

## Arm split — signal vs kontrol RANDOM (D0.5)
Track dinilai dari **arm sinyal saja**. Arm `track=RANDOM` (kontrol negatif, label a-priori) dan tampilan lama (campur) dilaporkan berdampingan supaya bias pengukuran tetap terlihat.
| Track | n_signal | n_control | excess signal | excess legacy(campur) | bias arm-split (bps) | excess control |
|---|---:|---:|---:|---:|---:|---:|
| swing | 445 | 623 | -0.165% | -0.155% | -1.03 | -0.147% |
| twoway | 512 | 90 | 0.029% | -0.002% | 3.08 | -0.177% |
| realwide | 298 | 184 | -0.112% | -0.173% | 6.06 | -0.271% |

### Guard integritas arm
- `control_smuggling_checked`: baris `regime=RANDOM_CONTROL` tanpa label `track=RANDOM` membuat track DITOLAK untuk dinilai (fail-closed), bukan diam-diam masuk arm sinyal.

## CI95 — baris (dipakai gate) vs cluster 30 jam (diagnostik)
Gate memakai CI baris demi komparabilitas laporan lama. RISET mengukur aturan baris ini over-fire **3,6-8,2 %** vs nominal 2,5 %; kolom cluster disertakan supaya salah-kalibrasi itu tetap terlihat. **Keputusan Owner 2026-10-04: gate TETAP CI baris; cluster diagnostik saja; tinjau ulang saat T1 mendekati lulus.**
| Track | n | CI95 baris (gate) | CI95 cluster 30 h | lebar baris (bps) | lebar cluster (bps) | rasio |
|---|---:|---|---|---:|---:|---:|
| swing | 445 | [-0.312%; -0.015%] | [-0.340%; 0.011%] | 29.8 | 35.1 | 1.18 |
| twoway | 512 | [-0.150%; 0.205%] | [-0.234%; 0.291%] | 35.5 | 52.5 | 1.48 |
| realwide | 298 | [-0.337%; 0.108%] | [-0.431%; 0.252%] | 44.5 | 68.3 | 1.53 |

## SHORT-side terpisah — twoway 42 SHORT
- n=42; WR input=33.333%; excess_mean=0.609%; Sharpe=5.31; CI95=[-0.078%; 1.267%].
- Cost 1× mean=0.529%; cost 2× mean=0.449%.
- Funding/borrow nyata: **FAIL-CLOSED** — 42/42 rows tidak punya field funding/borrow; PASS=False; alasan=level_decision: ci95_lower_positive, dsr_passed; funding_required_but_missing: 42/42 rows without funding/borrow field.

## Jarak ke target 48 jam
- Wallet current priced: $242.72 (perps $217.43 + spot $25.28); denominator final OK=True.
- Start 48h proxy: 2026-11-22T22:00:29.002617+00:00 equity $230.83 (boundary 2026-11-22T23:04:41.761367+00:00). Current priced: $242.72.
- Anchor fail-closed: valid=True; dikoreksi dari pilihan naif=False (naif: 2026-11-22T22:00:29.002617+00:00 equity $230.83). Snapshot equity $0,00 tidak boleh membuka jendela — pernah membuat laporan ini menulis jarak_ke_target=12500% padahal sebenarnya negatif.
- Wallet equity delta 48h: $11.890 = 4.899%. Target: $1.942.
- **jarak_ke_target wallet-delta = 612.3%** dari target 0,8%/48h.
- Local engine trading stats 48h: round-trip=0, net=$0.000; **jarak_ke_target trading-only = 0.0%**.

## D0.2 canonical gate equity — normalized trading-only
- Series role: **CANONICAL_D0_2_TRADING_ONLY_GATE_SERIES**; raw wallet: **DIAGNOSTIC_RCA_ONLY_NOT_GATE_SERIES**; denominator=CURRENT_TOTAL_WALLET.
- Window 2026-11-22T22:00:29.002617+00:00 → 2026-11-24T22:00:11.392618+00:00; normalized delta=$12.415; target=$1.942; **jarak_ke_target canonical=639.4%**.

## Sharpe rolling 90 hari wallet
- **INVALID / FAIL-CLOSED**: FAIL-CLOSED: equity discontinuities/zero values make 90d wallet Sharpe not interpretable as strategy Sharpe. Raw untrusted Sharpe (aritmetika)=2.22; **Sharpe log=+2.69**; jumps>20% count=3; zero/negative snapshots=6. Selisih tanda antara keduanya = artefak aritmetika, bukan edge.

## Capital discontinuity RCA evidence
- Source: `/home/USER/anantara-sakti/data/reconcile/state_reconcile.jsonl`; reconciled-event net=$-18.987.
- id=1 2026-09-30T14:12:31.303139+00:00 realwide_micro_live UNI VENUE_RECONCILE_LIQUIDATED: pnl=$-19.055.
- id=2 2026-09-30T14:12:31.303210+00:00 spot_live_test ETH VENUE_SOLD_BY_SPOT_LIQUIDATOR: pnl=$0.094.
- id=3 2026-09-30T14:17:24.155426+00:00 spot_live_test ETH FREEZE_FLATTEN_MANUAL: pnl=$-0.025.

## Funding mapper — SHORT-side
- Verdict: **FAIL_CLOSED**; coverage=0.0%; exact=0; rate_estimated=0; missing=0; reason=no short trade inside rate-archive window; n_pre_archive=42 excluded (exited before archive start) -> fail-closed.

## Funding rate collector — D0.1
- Verdict: **OK**; rows=100; appended=0; archive=`/home/USER/anantara-sakti/data/sodex_funding/funding_rates_history.jsonl`.
- Current range: min=-0.530 bps, max=5.993 bps.

## Normalized equity builder — trading-only
- **Verdict: True** — OK: deret trading-only dibangun dari `observed_delta_usd` (TILING, non-overlapping). `stats.net_6h` TIDAK dipakai sebagai sumber -- ia rolling 6 jam pada sampel ~4,8 jam (sum net_6h=-458.560 vs observed -503.538 = 0.9107x), sehingga versi lama over-count dan melahirkan maxdd -115,473% yang mustahil. Angka itu tidak kembali: `sharpe_ann_6h_trading_only` tetap NaN dan `maxdd_trading_only` dihitung dari kurva observed serta dibatasi [-1, 0].
- Series role: `TRADING_ONLY_TILING_OBSERVED_DELTAS`; rows=733; snapshot equity<=0 yang dibuang=25.
- Equity teramati: $746.78 -> $243.24 (delta $-503.538).
- `sum(net_6h)`=$-458.560 vs observed -> **over-count 0.9107x** (jendela rolling 6 jam, sampel ~4,8 jam). Reconcile venue=$-18.987.
- MaxDD trading-only: **-99.66%**; Sharpe (log/geometrik, KANONIK): **-0.21**; versi aritmetika +2.39 **TIDAK interpretabel** (ekuitas menyusut -> mean positif palsu).
- Kurva: $746.78 -> $243.24, min $4.07; interval median 5.991 jam; lompatan>20% = 38. AGREGAT semua lane (wallet), BUKAN Sharpe satu strategi. 38 lompatan >20% (likuidasi/freeze 30-Sep) SENGAJA tidak dibuang; sepuluh delta terburuk saja melebihi total kerugian. Pakai sharpe_ann_trading_only (log/geometrik); versi aritmetika positif secara palsu karena ekuitas menyusut. Snapshot equity<=0 dibuang.

## Keputusan operasional
- T1: **FAIL**. Tidak ada track yang boleh dipromosikan.
- Build mesin strategi baru sekarang: **NO**. Sesuai dokumen: ukur dulu; T1 belum lulus.
- Pembangunan yang boleh lanjut: measurement pipeline + data mapping funding/capital + verifikasi RISET/monitor.
- Unfreeze lane uang nyata: **NO**.
- Exit/leverage/position sizing/gate: **tidak disentuh**.
