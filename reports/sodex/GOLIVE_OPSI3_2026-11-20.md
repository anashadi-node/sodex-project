# KEPUTUSAN OWNER — OPSI 3: LIVE 1 DES 2026 + FULL PERBAIKAN/UPGRADE SEMUA LINI

Tanggal keputusan: 2026-11-20 (UTC+07:00)
Keputusan (verbatim user): "saya pilih Opsi 3 dengan Full Perbaikan dan Upgrade di semua lini dan segi"
Status gate saat keputusan: T1 FAIL (semua track), preflight BELUM_SIAP, lane real FROZEN.

## Makna keputusan ini
1. Owner memilih target hard date 1 Des 2026 untuk real live SoDEX, dengan syarat
   **full perbaikan & upgrade di semua lini** dieksekusi lebih dulu.
2. Opsi 3 TIDAK menghapus gerbang keselamatan. Yang diubah adalah jadwal, bukan
   standar bukti. Lane real tetap FROZEN sampai checklist arm di bawah 100%.
3. Waiver risiko: karena T1 (30 hari paper) mustahil lulus sebelum 1 Des, live 1 Des
   hanya sah jika Owner menandatangani waiver tertulis (bagian di bawah) dan preflight
   sudah 11/11 + SODX tidak ada KILL. Tanpa waiver tertulis → live TIDAK boleh di-arm.

## Checklist arm (semua WAJIB, fase BEKU mulai 25 Nov)
| # | Item | Pemilik | Bukti lulus |
|---|---|---|---|
| 1 | `secrets/sodex.env` terisi (API key venue, permission trade tanpa withdraw) | **OWNER** | preflight secret_env OK |
| 2 | Waiver risiko Opsi 3 ditandatangani (teks di bawah) | **OWNER** | file ini + konfirmasi Owner di chat |
| 3 | Preflight 11/11 lulus, fase BEKU, exit 0 | Agent | `python3 scripts/sodex_live_preflight.py` exit 0 |
| 4 | Deadman aktif + heartbeat < 8 menit | Agent | `sodex-deadman.service` active, `data/sodex/deadman_*` |
| 5 | Equity ledger segar (< 6 jam) 48 jam berturut | Agent | `reports/sodex/EQUITY_LEDGER.jsonl` |
| 6 | Funding archive READY + map tidak FAIL_CLOSED untuk simbol yang akan ditrade | Agent | `sodex_forward_reeval_latest.json` funding_map |
| 7 | SHORT diblokir sampai funding/borrow evidence lengkap (fail-closed 42/42 rows) | Agent | config engine: shorts_disabled=true |
| 8 | Rehearsal dry-run penuh mode_a_live (order routing, reject path, kill path) | Agent | log rehearsal + checklist lulus |
| 9 | Kill-switch test: file KILL diuji menghentikan engine < 60 detik | Agent | log uji |
| 10 | Tidak ada posisi terbuka paper yang menyimpang saat arm | Agent | reconcile 0 mismatch |
| 11 | GO-LIVE verbal/written Owner pada hari-H | **OWNER** | chat/log |

## Waiver risiko (untuk ditandatangani Owner sebelum arm)
"Saya memahami bahwa pada 1 Des 2026 gate T1 belum lulus (tidak ada track yang
net-positif di biaya 2×), funding SHORT belum terverifikasi, dan jarak target
0,8%/48h masih negatif. Saya memutuskan tetap live dengan size mikro, SHORT
diblokir, kill-switch aktif, dan menerima risiko kerugian modul awal."
— Owner, tanda tangan/paraf + tanggal: ____________

## Rencana upgrade 11 hari (semua lini)
### Lini A — Engine & strategi (SoDEX)
- A1. RCA kenapa ketiga track gagal di cost 2× (fee 8bps RT): dekomposisi edge
  bruto vs biaya per track; identifikasi track dengan edge bruto tertinggi.
- A2. Proposal parameter yang legal (butuh backtest OOS n≥30): exit/hold-time
  filter, spread filter, simbol filter — bukan mengubah SL/TP fundamental.
- A3. Perketat gate: hanya simbol dengan funding evidence + likuiditas cukup
  yang boleh masuk universe live.
### Lini B — Data & measurement
- B1. Funding mapping: biarkan arsip tumbuh (READY, 90.327 baris/99 simbol);
  re-run map setiap hari; SHORT tetap diblokir sampai in-window evidence ada.
- B2. Klines: 9 simbol delisted dipisahkan dari gate (SELESAI 2026-11-20);
  arsipkan file delisted ke subfolder agar gate & fleet report bersih.
- B3. Sharpe rolling 90d wallet: gunakan hanya seri canonical trading-only
  (log/geometrik); versi aritmetika dilarang masuk laporan.
### Lini C — Monitoring & safety
- C1. Pulse 30-menit sudah diperbaiki (interpreter venv) — pantau 1 siklus penuh.
- C2. Watchdog live: pastikan `sodex-live-watchdog` siap jalan saat LIVE phase.
- C3. Latency/reject telemetry dari venue untuk rehearsal.
### Lini D — CEX-Binance (tetap paper)
- D1. WR Spot-OFI 26,5% dan Σ -$11.05: pair-level audit 7d rolling, blok pair
  yang gagal (kriteria COIN_BLOCK: WR<40%, n≥20, p<0.05, BH-FDR).
- D2. Futures SIGNAL lane idle karena gate — jalankan evaluasi gate mingguan.

## Catatan eksekusi
- 2026-11-20: preflight 10/11 (blocker tunggal secret_env). Fix klines gate
  (delisted symbols) — 7/7 test PASS. Pulse CEX fix terverifikasi.
- Berikutnya: Lini A1 (RCA biaya) dan B2 (arsip delisted) hari ini.

## A1 — RCA biaya (HASIL, 2026-11-20)
Dekomposisi dari `reports/sodex/sodex_forward_reeval_latest.json`
(excess_mean = edge bruto net-of-beta pra-biaya; cost 1×/2× = setelah biaya):
| Track | Edge bruto/trade | Biaya 8bps RT | Net 1× | Net 2× |
|---|---:|---:|---:|---:|
| swing | -0.165% | 0.080% | -0.245% | -0.325% |
| twoway | **+0.029%** | 0.080% | -0.051% | -0.131% |
| realwide | -0.112% | 0.080% | -0.192% | -0.272% |

Kesimpulan KT: **satu-satunya track dengan edge bruto positif adalah twoway
(+2.9 bps/trade), dan fee 8 bps RT lebih besar dari edge itu** — ini penyebab
IS kegagalan semua track di level_decision net_pos_1x/2x, dan menjelaskan
IS-NOT (bukan masalah sizing/leverage: edge-nya sendiri yang tipis).
Jalur upgrade yang sah (evidence OOS dulu):
1. Maker-only entry untuk memangkas biaya efektif < 2.9 bps (fill predictor
   River sudah ada: AUC 0.79-0.83).
2. Filter selektivitas sub-kelompok twoway dengan edge bruto > 8 bps
   (analisis per simbol/regime/jam — harus n≥30 OOS).
3. Holding lebih panjang untuk amortisasi biaya per window (batas TF 30 jam).
Sembilan simbol delisted TIDAK dipindah (konsumen lain glob file itu);
cukup difilter di gate (sudah).
