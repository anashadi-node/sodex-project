# FLIP RECONCILE 2026-11-12 — rekonsiliasi kontradiksi bukti "sinyal dibalik" (lane twoway)

- dibuat: 2026-11-12T02:37:33.879974+00:00
- skrip: `/home/USER/.hermes/profiles/sodex/cache/scratch/flip_reconcile_20261112.py`
- perintah: `unset PYTHONPATH && .venv-research/bin/python3 <skrip> <out.json>` (dari `/home/USER/anantara-sakti`)
- semua angka NET biaya **16 bps** round-trip, close-to-close, TANPA TP/SL kecuali bagian 5.
- CI95 = bootstrap **cluster blok 30 jam**, 10.000 resample, seed 20261112. WR = proporsi net > 0.

## Ringkasan (TL;DR)

- **Kontradiksi TERSELESAIKAN.** Angka flip +1,43pp per-trade (laporan 2026-11-07) **bukan milik lane twoway**. Ia dihitung atas set entry **LINTAS-LANE** (dedup ledger `data/paper_test_*.jsonl`); hanya 155/463 (33%) benar-benar dari lane `twoway`, 139/463 (30%) dari `twoway_p27`, 169/463 (37%) dari keluarga `swing`, dengan jendela hanya 1 Okt–6 Nov 2026.
- Pada **entry lane twoway NYATA** (`paper_test_twoway_state.json`, 512 SIGNAL / 90 RANDOM), **tidak ada** arah (asli maupun dibalik) yang CI95-nya mengecualikan 0 pada horizon 4/12/24/48j.
- Reproduksi sempurna: prosedur 2026-11-07 atas set lintas-lane menghasilkan **+1,430pp** (hard-dedupe n=255) — identik dengan laporan; tetapi begitu diterapkan ke lane twoway, flip ≈ 0 / negatif.
- **"flip" = membalik arah = efektif SHORT** (arm 470 LONG / 42 SHORT; kode `[-ret]`; config lane berjalan `invert_signal:true`). Bukan sinyal baru.
- **Jangan simpulkan "edge ada".** Bukti lane nyata (state twoway) mengalahkan angka lintas-lane.

## 1. Universe yang diuji

- **A. Lane twoway state, kline SoDEX** (`{PAIR}-USD`): 602 entry (skip 0).
- **B. Lane twoway state, kline Binance** (`{PAIR}USDT`, cache yang dipakai laporan 2026-11-07): 579 entry (skip 23).
- **C. Lintas-lane dedup** (replikasi `collect_entries`): 3376 entry total, duplikat buang 198, **SIGNAL 463** (inilah n=463 laporan) — memakai kline Binance.
- Arm lane: SIGNAL 512 (LONG 470 / SHORT 42) · RANDOM 90. Definisi SIGNAL: `track != RANDOM (replikasi D0.5)`.
- Realisasi lane: total PnL **-38.24 USD**, mean pnl_pct -0.0212pp (SIGNAL +0.0386pp, RANDOM -0.3614pp).

## 2. Hasil utama — lane twoway NYATA (Universe A, kline SoDEX)

### SIGNAL (n=512) — arah asli vs dibalik

| horizon | arah | n | mean pp | median pp | WR | CI95 | p(mean>0) |
|---|---|---|---|---|---|---|---|
| 4j | 512 | -0.053 | -0.206 | 0.412 | [-0.388,+0.262] | 0.381 |
| 4j (flip) | 512 | -0.267 | -0.114 | 0.447 | [-0.582,+0.068] | 0.058 |
| 12j | 512 | +0.099 | -0.160 | 0.473 | [-0.423,+0.619] | 0.643 |
| 12j (flip) | 512 | -0.419 | -0.160 | 0.469 | [-0.939,+0.103] | 0.062 |
| 24j | 512 | +0.274 | -0.194 | 0.469 | [-0.563,+1.131] | 0.733 |
| 24j (flip) | 512 | -0.594 | -0.126 | 0.475 | [-1.451,+0.243] | 0.085 |
| 48j | 512 | +0.602 | -0.330 | 0.459 | [-0.663,+1.984] | 0.814 |
| 48j (flip) | 512 | -0.922 | +0.010 | 0.502 | [-2.304,+0.343] | 0.079 |

### RANDOM kontrol (n=90) — arah asli vs dibalik

| horizon | arah | n | mean pp | median pp | WR | CI95 | p(mean>0) |
|---|---|---|---|---|---|---|---|
| 4j | 90 | -0.329 | -0.205 | 0.411 | [-0.865,+0.255] | 0.144 |
| 4j (flip) | 90 | +0.009 | -0.115 | 0.467 | [-0.575,+0.545] | 0.501 |
| 12j | 90 | -0.791 | -0.426 | 0.367 | [-1.438,+0.001] | 0.025 |
| 12j (flip) | 90 | +0.471 | +0.106 | 0.511 | [-0.321,+1.118] | 0.878 |
| 24j | 90 | -0.581 | -0.488 | 0.367 | [-1.408,+0.313] | 0.110 |
| 24j (flip) | 90 | +0.261 | +0.168 | 0.544 | [-0.633,+1.088] | 0.693 |
| 48j | 90 | -0.878 | -0.238 | 0.467 | [-2.542,+0.827] | 0.174 |
| 48j (flip) | 90 | +0.558 | -0.082 | 0.489 | [-1.147,+2.222] | 0.720 |

### Cross-check Universe B (lane twoway, kline Binance — metode laporan 2026-11-07)

| horizon | arah | n | mean pp | median pp | WR | CI95 | p(mean>0) |
|---|---|---|---|---|---|---|---|
| 4j | 501 | +0.155 | -0.156 | 0.441 | [-0.210,+0.506] | 0.800 |
| 4j (flip) | 501 | -0.475 | -0.164 | 0.423 | [-0.826,-0.110] | 0.006 |
| 12j | 501 | +0.294 | -0.105 | 0.483 | [-0.249,+0.831] | 0.855 |
| 12j (flip) | 501 | -0.614 | -0.215 | 0.457 | [-1.151,-0.071] | 0.013 |
| 24j | 501 | +0.505 | -0.074 | 0.491 | [-0.356,+1.374] | 0.872 |
| 24j (flip) | 501 | -0.825 | -0.246 | 0.457 | [-1.694,+0.036] | 0.030 |
| 48j | 501 | +0.802 | -0.263 | 0.467 | [-0.488,+2.200] | 0.884 |
| 48j (flip) | 501 | -1.122 | -0.057 | 0.491 | [-2.520,+0.168] | 0.046 |

Pada data lane twoway yang sama, flip justru **negatif** (mis. h24 flip -0.825pp, CI95 [-1.694,+0.036], p(>0)=0.030). Arah asli hanya sedikit di atas 0 dan CI-nya memuat 0.

## 3. Belah dua waktu (Universe A) — tidak stabil

| horizon/arah | paruh-1 mean | paruh-2 mean |
|---|---|---|
| 4j orig | +0.251pp | -0.357pp |
| 4j flip | -0.571pp | +0.037pp |
| 12j orig | +0.658pp | -0.461pp |
| 12j flip | -0.978pp | +0.141pp |
| 24j orig | +0.950pp | -0.401pp |
| 24j flip | -1.270pp | +0.081pp |
| 48j orig | +1.949pp | -0.744pp |
| 48j flip | -2.269pp | +0.424pp |

Arah asli ganti tanda antar paruh (h24: +0,950 → −0,401); flip pun mati di paruh-2 (h24 flip: −1,270 → +0,081). Tidak ada sisi yang konsisten.

## 4. Reproduksi laporan 2026-11-07 (Universe C — lintas-lane)

| horizon | arah | n | mean pp | median pp | WR | CI95 | p(mean>0) |
|---|---|---|---|---|---|---|---|
| 4j | 463 | -0.655 | -0.341 | 0.361 | [-1.119,-0.295] | 0.000 |
| 4j (flip) | 463 | +0.335 | +0.021 | 0.505 | [-0.025,+0.799] | 0.964 |
| 12j | 463 | -0.712 | -0.377 | 0.419 | [-1.330,-0.182] | 0.004 |
| 12j (flip) | 463 | +0.392 | +0.057 | 0.510 | [-0.138,+1.010] | 0.919 |
| 24j | 463 | -1.606 | -1.232 | 0.328 | [-2.722,-0.447] | 0.003 |
| 24j (flip) | 463 | +1.286 | +0.912 | 0.629 | [+0.127,+2.402] | 0.984 |
| 48j | 463 | -2.523 | -2.433 | 0.235 | [-3.687,-1.242] | 0.000 |
| 48j (flip) | 463 | +2.203 | +2.113 | 0.708 | [+0.922,+3.367] | 0.999 |

- **Reproduksi persis:** hard-dedupe n=255, flip h24 = +1.400pp @16bps; pada model biaya laporan (0,10pp+funding 0,01%/8j = 0,13pp) menjadi +1.430pp = **+1.430pp** laporan. ENTRY_EDGE h24 (flat 0,10pp) = -1.546pp vs laporan -1.546pp — juga ter-reproduksi.
- Komposisi SIGNAL lintas-lane: {'swing': 70, 'swing_partial': 60, 'swing_strict': 39, 'twoway': 155, 'twoway_p27': 139}.
- Jendela lintas-lane hanya ~37 hari (1 Okt–6 Nov 2026), vs lane twoway ~92 hari.

### Dekomposisi per lane (h24, arah asli) — di mana efek negatifnya berada

| lane | n | h24 arah asli | h24 flip net |
|---|---|---|---|
| swing | 70 | -2.146pp | +1.986pp |
| swing_partial | 60 | -2.326pp | +2.166pp |
| swing_strict | 39 | -0.676pp | +0.516pp |
| twoway | 155 | -0.665pp | +0.505pp |
| twoway_p27 | 139 | -1.799pp | +1.639pp |

### Subset: hanya lane twoway vs hanya lane swing (flip h24)

| subset | n | arah asli h24 | flip h24 | CI95 flip | p(mean>0) |
|---|---|---|---|---|---|
| twoway + twoway_p27 | 294 | -1.361pp | +1.041pp | [-0.182,+2.299] | 0.949 |
| swing family | 169 | -2.031pp | +1.711pp | [+0.584,+3.027] | 0.998 |

→ Efek anti-predictive terkonsentrasi di **lane swing** (flip h24 +1,711pp, CI95 mengecualikan 0). Subset **twoway saja** lemah dan CI95 flip-nya **memuat 0** ([−0,182,+2,299]). Jadi klaim flip tidak berlaku untuk lane twoway.

## 5. Geometri lane berjalan (TP 1,5% / SL 6% / TS 24j, SL-first, 16 bps) — pada entry yang sama

| arm | arah | n | mean pp | median pp | WR | CI95 | p(mean>0) |
|---|---|---|---|---|---|---|---|
| SIGNAL orig | 512 | -0.209 | +1.340 | 0.617 | [-0.566,+0.137] | 0.121 |
| SIGNAL flip | 512 | -0.520 | +1.340 | 0.596 | [-0.979,-0.085] | 0.007 |
| RANDOM orig | 90 | -0.472 | +0.733 | 0.578 | [-1.145,+0.204] | 0.095 |
| RANDOM flip | 90 | -0.044 | +1.340 | 0.667 | [-0.648,+0.479] | 0.430 |

Bandingkan dengan hold-to-24j (Universe A): SIGNAL orig +0.274pp vs geometri orig -0.209pp — keduanya ≈ 0 dan CI memuat 0. Geometri pada arah **flip** justru **negatif** (-0.520pp, CI [-0.979,-0.085]).

Catatan: geometri tercatat historis di state = TP ~3,72%/SL ~2,0%. Skenario TP1,5%/SL6% sesuai config lane berjalan sekarang (`data/paper_test_twoway_ab9*_funnel.json`: `tp_pct=0.015, sl_pct=0.06, invert_signal=true`).

## 6. Penjelasan diskrepansi (463 vs 512 vs 578)

| angka | artinya | bukti |
|---|---|---|
| **463** | SIGNAL dari **lintas-lane dedup** `paper_test_*.jsonl` (jendela 1 Okt–6 Nov) | `cross_lane_replica.n_signal_replay_kline=463`, komposisi per lane |
| **512** | SIGNAL **lane twoway state** (`track != RANDOM`) | `arms.n_signal=512` |
| **578/579** | entry `paper_test_twoway.jsonl` yang punya kline | `REPLAY_EXIT_GEOMETRY_20261106.md` (n=578) |

**Sebab utama kontradiksi:** laporan flip 2026-11-07 memilih entry dari **ledger lintas-lane**, bukan lane twoway. Bukti tekstual: skrip `scripts/research/flip_hardening_20261107.py` & `signal_flip_test_20261107.py` memanggil `G.collect_entries()` (baca `data/paper_test_*.jsonl`, dedup `(pair, menit, arah)`) — lihat `scripts/research/edge_grid_walkforward_20261107.py:60-99`. Bukti angka: 155/463 entry berasal dari lane `twoway`, sisanya swing/swing_partial/swing_strict/twoway_p27.

**Arti "flip":** = membalik arah entry (kode `[-ret]` di `flip_hardening_20261107.py:108`). Karena arm isinya 470 LONG / 42 SHORT, flip ≈ **SHORT**. Diperkuat `SIGNAL_MOMENTUM_RC_20261107.md` yang aturan menangnya adalah "short apa adanya" (OOS +1,670pp @24j), dan config lane berjalan `invert_signal:true`. **Tidak ambigu.**

## 7. Kesimpulan

KONTRADIKSI TERSELESAIKAN: angka flip +1,43pp berasal dari set entry LINTAS-LANE (swing 169 + twoway 294, jendela 1 Okt-6 Nov), BUKAN lane twoway. Pada entry lane twoway NYATA (512 SIGNAL) tidak ada arah (asli maupun dibalik) dengan CI95 robust pada horizon 4/12/24/48j. 'flip' = membalik arah = efektif SHORT (arm 470 LONG/42 SHORT).

- Ketiga klaim tak bisa benar sekaligus; yang menang = **bukti lane nyata** (state twoway, D05/D05B: excess 2,91 bps, CI95 [−22,98,+29,77]) dan hasil uji ini: pada entry twoway tidak ada edge, asli maupun dibalik.
- Angka flip +1,43pp adalah **artefak komposisi entry lintas-lane** (dominan swing, jendela pendek) — bukan properti lane twoway. Bahkan subset twoway dari set lintas-lane pun tidak robust (CI flip memuat 0).
- Tindak lanjut disarankan: setiap uji flip/lintas-lane **wajib menyatakan lane sumbernya** dan diperiksa ulang per-lane; jangan menaikkan bobot atas dasar n gabungan yang dikuasai lane lain.

## Keamanan
- Riset murni read-only pada data; tidak mengubah strategi/gate/exit/leverage, tidak menaruh order.

