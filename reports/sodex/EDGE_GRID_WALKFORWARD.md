# Grid walk-forward geometri exit (2026-11-07)

Entry unik dipakai: **3076** (duplikat lintas lane dibuang: 197).
Split waktu: IS ≤ 2026-10-26T08:17:39+00:00Z, sisanya OOS. Grid: TP {0,5–4%} × SL {0,5–3%} × horizon {12,24,48,72,168} jam = 240 konfigurasi.

Aturan: entry TIDAK diubah (persis seperti yang dipakai lane), SL didahulukan bila TP & SL tersentuh di bar yang sama, mulai bar +1 (tanpa look-ahead), biaya 0,10pp round-trip, ambang roster +0,205pp, koreksi BH-FDR atas seluruh grid.

## 12 teratas menurut OOS

| TP% | SL% | horizon | n | IS | OOS | semua | q(BH) |
|---|---|---|---|---|---|---|---|
| 4.0 | 0.5 | 12j | 3076 | +0.199 | +0.165 | +0.189 | 0.07777 |
| 4.0 | 0.75 | 12j | 3076 | +0.145 | +0.133 | +0.142 | 0.178992 |
| 3.0 | 0.5 | 12j | 3076 | +0.147 | +0.132 | +0.142 | 0.103902 |
| 4.0 | 0.5 | 24j | 3076 | +0.171 | +0.117 | +0.155 | 0.178992 |
| 3.0 | 0.5 | 24j | 3076 | +0.129 | +0.115 | +0.125 | 0.178992 |
| 4.0 | 1.0 | 12j | 3076 | +0.105 | +0.114 | +0.108 | 0.282065 |
| 2.0 | 0.5 | 24j | 3076 | +0.072 | +0.103 | +0.082 | 0.164454 |
| 2.5 | 0.5 | 12j | 3076 | +0.115 | +0.099 | +0.110 | 0.178992 |
| 2.0 | 0.5 | 12j | 3076 | +0.077 | +0.096 | +0.083 | 0.178542 |
| 2.5 | 0.5 | 24j | 3076 | +0.109 | +0.094 | +0.105 | 0.178992 |
| 3.0 | 0.75 | 12j | 3076 | +0.101 | +0.091 | +0.098 | 0.282449 |
| 2.0 | 0.5 | 48j | 3076 | +0.078 | +0.091 | +0.082 | 0.178992 |

## Yang IS>0 DAN OOS>0

Jumlah: **20 dari 240** konfigurasi.

| TP% | SL% | horizon | n | IS | OOS | q(BH) |
|---|---|---|---|---|---|---|
| 1.5 | 0.5 | 12j | 3076 | +0.034 | +0.067 | 0.199974 |
| 1.5 | 0.5 | 24j | 3076 | +0.035 | +0.072 | 0.178992 |
| 1.5 | 0.5 | 48j | 3076 | +0.034 | +0.071 | 0.18768 |
| 1.5 | 0.5 | 72j | 3076 | +0.035 | +0.068 | 0.202827 |
| 1.5 | 0.5 | 168j | 3076 | +0.034 | +0.068 | 0.202827 |
| 2.0 | 0.5 | 12j | 3076 | +0.077 | +0.096 | 0.178542 |
| 2.0 | 0.5 | 24j | 3076 | +0.072 | +0.103 | 0.164454 |
| 2.0 | 0.5 | 48j | 3076 | +0.078 | +0.091 | 0.178992 |
| 2.0 | 0.5 | 72j | 3076 | +0.080 | +0.088 | 0.178992 |
| 2.0 | 0.5 | 168j | 3076 | +0.083 | +0.088 | 0.178992 |
| 2.0 | 0.75 | 12j | 3076 | +0.028 | +0.058 | 0.680318 |
| 2.0 | 0.75 | 24j | 3076 | +0.025 | +0.049 | 0.944305 |

## Kesimpulan (jujur, tanpa dibumbui)
- Terbaik di antara yang IS>0 & OOS>0: **TP4.0%/SL0.5%/h12 → OOS +0.165pp** (IS +0.199pp, q-BH 0.07777) → di bawah ambang roster +0,205pp dan **tidak signifikan** setelah koreksi 240 uji.

- Artinya: **tidak ada geometri exit** yang menyelamatkan entry sekarang. Perbaikan wajib datang
  dari sisi entry (lihat `ENTRY_EDGE_HORIZON_20261107.md` dan `SIGNAL_FLIP_TEST_20261107.md`).
- Angka plafon exit ≈ +0,16pp konsisten dengan analisis replay sebelumnya (≈ +0,16pp).

Reproduksi: `.venv-research/bin/python scripts/research/edge_grid_walkforward_20261107.py` (output mentah: `data/research/replay_20261107/grid_summary.json`).
