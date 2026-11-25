# R4 MONITOR — RUNBOOK (read-only, tanpa order)

Monitor harian gate regime. Protokol: `docs/sodex/R4_PROTOKOL_GATE_REGIME.md` sha256 `7586262101d93098…` (commit `b304923`).

## Unit systemd user

`~/.config/systemd/user/sodex-r4-monitor.service`
```ini
[Unit]
Description=R4 monitor gate regime SoDEX (READ-ONLY, tanpa order)
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/USER/anantara-sakti
ExecStart=/usr/bin/python3 /home/USER/anantara-sakti/scripts/research/r4_monitor_regime_gate.py
StandardOutput=append:/home/USER/anantara-sakti/logs/r4_monitor.log
StandardError=append:/home/USER/anantara-sakti/logs/r4_monitor.log
Nice=10
```

`~/.config/systemd/user/sodex-r4-monitor.timer`
```ini
[Unit]
Description=R4 monitor gate regime — harian 08:15 WIB (01:15Z)

[Timer]
OnCalendar=*-*-* 01:15:00 UTC
Persistent=true
Unit=sodex-r4-monitor.service

[Install]
WantedBy=timers.target
```

## Perintah operasional

```bash
systemctl --user list-timers sodex-r4-monitor.timer --no-pager   # jadwal
/usr/bin/python3 scripts/research/r4_monitor_regime_gate.py      # jalankan manual
tail -5 reports/sodex/R4_MONITOR.md                              # log harian
python3 -c "import json;d=json.load(open('reports/sodex/R4_MONITOR.json'));print(d['regime_now'],d['verdict_status'])"
systemctl --user stop sodex-r4-monitor.timer                     # hentikan
```

## Isi keluaran

- `reports/sodex/R4_MONITOR.json` — hasil lengkap (retrospektif = label deskriptif, forward = kandidat verdict).
- `reports/sodex/R4_MONITOR.md` — satu baris per hari (regime, WR sinyal/kontrol, kept G12).
- `logs/r4_monitor.log` — stdout/err unit.

## Batas yang harus diingat

- Metrik window pooled (`windows_kept`) **mencampur skala notional antar track = hanya indikatif**; metrik resmi = `windows_kept_twoway_only`.
- Verdict diambil **sekali** saat kalender ≥ 17-Okt DAN n_kept(G12) ≥ 40. Monitor harian **bukan** dasar keputusan dini.
- Monitor tidak menulis ke state track, tidak mengirim order, tidak menyentuh flag live. Aman dijalankan kapan saja.
