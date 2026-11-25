#!/bin/bash
# Deprecated safety stub.
#
# This script used to run an ad-hoc PEPE monitor and place a follow-up sell.
# It is intentionally disabled because it bypasses the current SoDEX SPOT
# governor, event-risk gate, adaptive policy gate, process lock, and partial-fill
# guardian in anantara/sodex_autofarm.py.
#
# Use the guarded wrapper instead:
#   python3 scripts/sodex_spot_daemon.py status
#   python3 scripts/sodex_spot_daemon.py once
set -euo pipefail
cd "$(dirname "$0")/.."

echo "auto_rt_monitor.sh is deprecated and disabled."
echo "Use scripts/sodex_spot_daemon.py so live orders pass all current SoDEX gates."
python3 scripts/sodex_spot_daemon.py status
exit 1
