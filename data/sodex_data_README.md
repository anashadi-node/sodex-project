# Layout data runtime SoDEX (TIDAK di-commit)

Seluruh isi `data/` diabaikan git (lihat `.gitignore`). Berkas yang dibaca/ditulis kode:

| File | Penulis | Fungsi |
|---|---|---|
| `sodex_real_sync_snapshot.json` | `scripts/sodex_realtime_sync.py` | snapshot venue (posisi, saldo, open orders) untuk rekonsiliasi |
| `sodex_watchdog_status.json` | `scripts/sodex_live_watchdog.py` | status OK/CRITICAL/FAILED/ERROR, dibaca preflight |
| `sodex_daemon_fills.jsonl` | daemon | jurnal fill/close (sumber rekonsiliasi kuantitas) |
| `sodex_promotion_ledger.jsonl` | promotion gate | riwayat gerbang promosi target |
| `paper_test_*_state.json` | lane paper | `closed_trades`/`closed`/`trades` — dibaca `scripts/sodex_fleet_edge_audit.py` |
| `DEADMAN_HEARTBEAT.json` | deadman | heartbeat |

Kredensial venue: `secrets/sodex.env` (tidak ada di repo; hanya `secrets/*.template`). Jangan pernah dicetak/di-log.
