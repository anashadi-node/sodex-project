# R5 MONITOR — RUNBOOK (read-only, tanpa order)

Protokol beku: `docs/sodex/R5_PROTOKOL_CLASSIFIER_REGIME.md` sha256 `3c8eb224d6bf385c…` (commit `eb18998`).
Runner: `scripts/research/r5_regime_classifiers.py` · 5 arm (RF0–RF4), gate arah, Holm-Bonferroni K=5.

## Unit systemd user

`~/.config/systemd/user/sodex-r5-monitor.service`
```ini
[Unit]
Description=R5 monitor 5 classifier regime SoDEX (READ-ONLY, tanpa order)
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/USER/anantara-sakti
ExecStart=/usr/bin/python3 /home/USER/anantara-sakti/scripts/research/r5_regime_classifiers.py
StandardOutput=append:/home/USER/anantara-sakti/logs/r5_monitor.log
StandardError=append:/home/USER/anantara-sakti/logs/r5_monitor.log
Nice=10
```

`~/.config/systemd/user/sodex-r5-monitor.timer`
```ini
[Unit]
Description=R5 monitor classifier regime — harian 08:20 WIB (01:20Z)

[Timer]
OnCalendar=*-*-* 01:20:00 UTC
Persistent=true
Unit=sodex-r5-monitor.service

[Install]
WantedBy=timers.target
```

## Perintah

```bash
systemctl --user list-timers 'sodex-r5*' --no-pager
/usr/bin/python3 scripts/research/r5_regime_classifiers.py
tail -3 reports/sodex/R5_MONITOR.md
python3 -c "import json;d=json.load(open('reports/sodex/R5_MONITOR.json'));print(d['verdict_status'],d['verdict']['winner_after_holm'])"
systemctl --user stop sodex-r5-monitor.timer
```

## Aturan pengambilan verdict (dari protokol beku)

- Sekali saja, saat kalender ≥ **31-Okt-2026** DAN `n_kept ≥ 40` pada arm terbaik (jendela **forward ≥ 11-Okt**).
- Semua syarat: n_kept ≥ 40 · WR_kept ≥ 45% · ΔWR ≥ +5 pp · binomial p < 0,05 · Holm K=5 (pemenang harus p < 0,0100) · WR_kept > kontrol RANDOM.
- Bila per 30-Nov belum mencapai n_kept ≥ 40 → **TIDAK KONKLUSIF**.
- Monitor harian = operasional, **bukan** dasar keputusan dini (anti optional-stopping).
