#!/bin/bash
# TWIN-ENGINE LIVE DAEMON — anti-mati
# Usage: bash scripts/start_twin_live.sh

set -e
cd "$(dirname "$0")/.."

# S11 fix (audit 06-Okt-2026): dulu whitelist while-read cuma export 5 key
# (SODEX_*/TELEGRAM_*) sehingga TE_CAPITAL_USD dari .env DIBUANG lalu jatuh
# ke fallback 94 -- beda dgn jalur produksi watchdog (`set -a; source .env`
# = 30 dari .env). Cap risiko modal LEBIH BESAR di jalur manual dgn diam,
# tergantung pintu start. Sekarang load .env PENUH sama dgn watchdog:
# .env = satu sumber kebenaran, TE_CAPITAL_USD=30 kanonik.
set -a
source .env
set +a
# NOTE: semua variabel .env sekarang ter-export ke daemon child (single source
# of truth). Tidak ada fallback TE_CAPITAL_USD -- perubahan modal cukup dari
# .env saja (S11 fix).

export CONFIRM_LIVE=YES

# Activate venv
source .venv-research/bin/activate

echo "[$(date)] Starting Twin-Engine LIVE | Capital: $TE_CAPITAL_USD (dari .env, S11 fix) | Pairs: PEPE+SHIB"

# Start with auto-confirmation
echo "SAYA PAHAM RISIKONYA" | nohup python3 -u anantara/sodex_twin_engine.py run --live \
    >> logs/twin_live.log 2>&1 &

PID=$!
echo "[$(date)] Daemon PID: $PID"
echo $PID > /tmp/twin_engine_live.pid
