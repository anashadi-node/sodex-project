# REPLAY EXIT-GEOMETRY — bukti mentah (revisi 2026-11-06)

- dibuat: 2026-11-06T13:42:53Z UTC (20:42 WIB)
- perintah: .venv-research/bin/python scripts/research/replay_exit_geometry_20261107.py
- KOREKSI: baris "cur" sebelumnya mengurangi biaya 0,10pp padahal ledger pnl_pct SUDAH net → cur terlalu buruk 0,10pp. Sudah diperbaiki.
- asumsi varian simulasi: SL didahulukan bila TP & SL tersentuh di bar 1h yang sama; biaya 0,10pp/round-trip; entry & SL asli lane

```
lane     varian        n   mean%      t       p
twoway   cur         578  +0.002  +0.02  0.9846
twoway   no_ts72     578  -0.004  -0.04  0.9706
twoway   no_ts168    578  -0.102  -0.92  0.3554
twoway   tp15r       578  +0.055  +0.56  0.5753
twoway   tp1r        578  +0.029  +0.35  0.7229
twoway   trail1r     578  +0.074  +0.79  0.4280
twoway   trail15_72  578  +0.043  +0.42  0.6738
twoway   [skip no-data: 23]
realwide cur           0  (kurang)
realwide no_ts72       0  (kurang)
realwide no_ts168      0  (kurang)
realwide tp15r         0  (kurang)
realwide tp1r          0  (kurang)
realwide trail1r       0  (kurang)
realwide trail15_72    0  (kurang)
realwide [skip no-data: 0]
swing    cur         899  -0.102  -2.27  0.0231
swing    no_ts72     899  +0.014  +0.26  0.7978
swing    no_ts168    899  +0.015  +0.27  0.7868
swing    tp15r       899  -0.035  -0.86  0.3918
swing    tp1r        899  -0.092  -2.77  0.0055
swing    trail1r     899  +0.055  +1.24  0.2164
swing    trail15_72  899  +0.047  +1.00  0.3196
swing    [skip no-data: 30]
partial  cur         970  -0.099  -2.96  0.0030
partial  no_ts72     970  +0.007  +0.13  0.8931
partial  no_ts168    970  +0.001  +0.03  0.9794
partial  tp15r       970  -0.038  -0.97  0.3297
partial  tp1r        970  -0.097  -3.04  0.0023
partial  trail1r     970  +0.064  +1.49  0.1362
partial  trail15_72  970  +0.041  +0.89  0.3741
partial  [skip no-data: 37]
```
