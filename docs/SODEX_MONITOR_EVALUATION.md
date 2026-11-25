# SoDEX Monitoring & Evaluasi Read-Only

Sistem ini hanya membaca data. Tidak ada signed order, cancel order, atau eksekusi trading.

## Command

```bash
.venv-research/bin/python scripts/sodex_monitor_eval.py
.venv-research/bin/python scripts/sodex_monitor_eval.py --json
```

Output utama:

- `data/sodex_monitor_eval/latest.json`
- `data/sodex_monitor_eval/history.jsonl`
- `logs/sodex_monitor_eval.log` bila dijalankan lewat systemd

## Window Evaluasi

Mingguan: Sabtu 07:00 WIB sampai Sabtu 07:00 WIB berikutnya.

Secara UTC ini adalah Sabtu 00:00 UTC sampai Sabtu 00:00 UTC berikutnya.

Contoh periode berjalan:

```text
13 Juni 2026 - 20 Juni 2026 (weekly 20 sodex)
Snapshot final: 20 Juni 2026 07:00 WIB
```

## Sumber Data

- Ledger lokal `twin_engine.db`: volume transaksi lengkap, fee ledger, RT tertutup, realized PnL, win rate, rasio volume/fee.
- API SoDEX read-only: saldo spot/perps real, account value, aset trading berjalan, posisi perps terbuka, fee tier, trade/funding terbaru.

Jika API/DB gagal dibaca, laporan menandai `quality` sebagai degraded. Sistem tidak mengarang angka pengganti.

## Target Default

- Volume mingguan: 1,300,000 USD
- Win rate mingguan: minimal 69%
- Rasio volume/fee: minimal 1:6,400

Override via environment:

```bash
SODEX_EVAL_TARGET_WEEKLY_VOLUME=1300000
SODEX_EVAL_TARGET_WIN_RATE=0.69
SODEX_EVAL_TARGET_VOLUME_FEE_RATIO=6400
```

## Systemd User Timer

Unit tersedia di:

- `systemd/sodex-monitor-eval.service`
- `systemd/sodex-monitor-eval.timer`

Timer menjalankan collector setiap 15 menit dan juga eksplisit pada Sabtu 07:00 waktu lokal.

## Telegram

Command on-demand:

```text
/sodex-eval
/sodex-monitor
```

Keduanya membaca snapshot terakhir dari `data/sodex_monitor_eval/latest.json`.
Command Telegram tidak menjalankan order, cancel order, signing, atau API trading.

Push otomatis:

- Berkala: setiap jam pada menit `:10`.
- Weekly final: setiap Sabtu 07:02 WIB, membaca snapshot Sabtu 07:00 WIB.
