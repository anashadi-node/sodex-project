# SODEX — Opposite Audit Target Feasibility

Tanggal: 2026-09-10 08:19 WIB
Scope: Project SoDEX only. Metode: opposite/devil-advocate, triangulasi data lokal, bootstrap CI, RCA, bottleneck analysis.

## Pertanyaan utama
Apakah target SoDEX mungkin tercapai?

Target user: profit minimal 0,7% dari total wallet per swing window/trade 1–30 jam.
Wallet real sync saat audit: perps $93,63 + spot $14,07 = $107,70. Target 0,7% = $0,754/trade.

## Verdict jujur
Mungkin tercapai, tapi bukan oleh semua track. Saat ini hanya REAL-wide yang punya bukti cukup mendekati valid, dan hanya setelah toxic pairs SUI/ADA/HYPE/ONDO dipastikan tidak bisa masuk execution. SHORT-BEAR adalah prioritas strategis karena market bearish, tetapi belum live-ready karena forward n=1 closed + 1 open.

Tidak ada jaminan pasti. Yang mungkin adalah membangun sistem probabilistik dengan positive expectancy, gate ketat, abstain saat market buruk, dan sizing aman. Klaim "pasti profit" tidak ilmiah.

## Data utama

### REAL-wide
- Raw: n=128, sum +$137,22, avg +$1,072, WR 49,2%, PF 1,43, bootstrap CI95 avg -$0,243..+$2,422, P(avg>0)=94,7%.
- Execution-eligible setelah block SUI/ADA/HYPE/ONDO: n=103, sum +$225,00, avg +$2,185, WR 54,4%, PF 2,03, bootstrap CI95 avg +$0,643..+$3,738, P(avg>0)=99,8%.
- Toxic-only: n=25, sum -$87,78, avg -$3,511, WR 28,0%, PF 0,10, P(avg>0)=0,0%.

AHA: target bukan gagal karena strategi utama jelek. Target gagal kalau toxic pairs ikut aktif. Setelah pair toxic dibuang, edge REAL-wide menjadi jauh lebih jelas.

### SHORT-BEAR
- Closed: n=1, sum -$1,54, WR 0%, PF 0.
- Open paper sekarang: BTC SHORT @78238,41; mark-to-market terakhir +0,079% gross, est net +$0,03 (+0,032% wallet).
- Latest telemetry: SCAN ok=6 err=0 signal=0/open=1; FUNNEL sufficient=6 bear_stack=1 chk4=3 r1neg=6 candidate=1 max_chk=4.
- Status: prioritas #1 untuk market bearish, tetapi belum boleh live sampai n≥50 dan target metrics pass.

AHA: SHORT-BEAR bukan mati; bug fetch limit 200 membuatnya buta 26 jam. Sudah diperbaiki ke limit 300 + test. Sekarang mulai menghasilkan candidate/open paper.

### Track lain
- Donchian: n=83, avg -$0,10, WR 37,3%, PF 0,96. Belum edge.
- Spot swing v2: n=36, avg ~$0, WR 30,6%, PF 1,00, duplicate indikasi 10. Belum edge kuat.
- Portfolio: n=13, avg -$1,19, WR 23,1%, PF 0,26. Tidak layak live.
- Pasar-Anantara trade: n=21, avg -$3,66, WR 28,6%, PF 0,05. Anti-edge kuat; jangan live.
- Hyperliquid paper: n=22, avg -$4,10, WR 13,6%, PF 0,14. Tidak layak.
- Aster paper: n=49, avg -$0,94, WR 34,7%, PF 0,78. Tidak layak.

## Opposite case: alasan target bisa gagal
1. Target 0,7% per total wallet makin berat saat modal membesar jika notional tidak ikut naik.
2. Sebagian besar track negatif; kalau dibiarkan voting/aggregate, edge REAL-wide tertutup oleh losers.
3. Live SoDEX pernah punya phantom-state/CLI mismatch; exchange sync wajib jadi source of truth.
4. Gate generator sempat menghapus REAL-wide toxic-pair pause. Ini evidence/execution divergence berbahaya.
5. SHORT-BEAR belum punya sample; live sekarang = gambling.
6. SoDEX venue risk: liquidity, spread, API drift, fill mismatch. Paper belum sama dengan live sampai fill real terkonfirmasi.
7. Bear market membuat long-only track harus sering abstain; sistem yang memaksa trading akan loss.

## Opposite case: alasan target masih possible
1. REAL-wide eligible setelah toxic-pair block punya avg +$2,185/trade vs target $0,754 — sekitar 2,9x target.
2. Bootstrap CI95 lower bound eligible +$0,643 mendekati target dan positif; P(avg>0)=99,8%.
3. Toxic pairs jelas merusak: -$87,78 total, avg -$3,511, P(avg>0)=0,0%.
4. Gate fail-closed + realtime sync sudah mengurangi risiko phantom/execution mismatch.
5. SHORT-BEAR sekarang sudah punya telemetry funnel; saat bearish sejati, bisa jadi hedge/engine utama, tetapi harus dibuktikan forward.

## AHA utama
SoDEX bukan butuh "lebih banyak strategi". SoDEX butuh role specialization:
- REAL-wide = profit engine saat regime long aman.
- SHORT-BEAR = prioritas riset/live-candidate saat bearish.
- Track negatif = jangan diberi modal; pakai sebagai sensor/research only.
- Abstain = posisi aktif yang benar saat market tidak cocok.

## Keputusan ilmiah saat ini
- LIVE boleh: REAL-wide saja, dengan forced toxic-pair block aktif.
- PAPER wajib prioritas: SHORT-BEAR sampai n≥50.
- STOP live promotion: Portfolio, Donchian, Pasar-Anantara trade, Hyperliquid paper, Aster paper.
- Monitor wallet/exchange sync terus; jangan percaya CLI lama.

## Acceptance criteria menuju live SHORT-BEAR
- n≥20: evaluasi awal.
- n≥50: kandidat live.
- WR > 50%, PF > 1,5, avg PnL > $0,754/trade, bootstrap CI95 lower bound ideally > 0.
- Max drawdown tidak melanggar session/day cap.
- No fetch_err burst, no insufficient bug, no phantom state.

## Action yang sudah dilakukan saat audit ini
- Fixed gate drift source: `scripts/paper_test_learning.py` sekarang punya `FORCED_PAIRS_PAUSE` untuk REAL-wide.
- Runtime gate restored: SUI/ADA/HYPE/ONDO blocked=True; BTC/SOL/UNI blocked=False.
- Regression test added: `tests/test_sodex_learning_gate_forced_pause.py`.
- Validation: 17/17 scoped tests pass.
- Commit: `701802f fix(sodex): prevent REAL-wide toxic pair gate drift`.

## Kesimpulan akhir
Target SoDEX possible, tetapi belum system-wide. Target possible pada jalur sempit dan disiplin: REAL-wide eligible + toxic-pair block + abstain saat regime buruk + SHORT-BEAR dibuktikan dulu. Jika semua track negatif tetap diberi bobot, target tidak possible. Jika sistem fokus hanya ke edge terbukti dan menolak trading saat kondisi tidak cocok, target realistis secara probabilistik, bukan pasti.
