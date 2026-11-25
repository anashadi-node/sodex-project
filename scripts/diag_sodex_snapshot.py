#!/usr/bin/env python3
"""Watchdog probe: verify SoDEX-native marks exist for SHORT-BEAR venue gate."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
SNAP = PROJ / "data" / "sodex_real_sync_snapshot.json"
d = json.loads(SNAP.read_text())
gen = d.get("generated_utc")
age = None
if gen:
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(gen.replace("Z", "+00:00"))).total_seconds()
print("snapshot_age_s", round(age, 1) if age else None)
print("top_level_keys", sorted(d.keys()))
print("has_perps_marks", "perps_marks" in d, "has_perps_prices", "perps_prices" in d)
print("perps_balance_total", (d.get("perps_balance") or {}).get("total"))
print("spot_equity_usd", d.get("spot_equity_usd"))
print("spot_unpriced", d.get("spot_unpriced"))
print("perps_positions", [(p.get("symbol"), p.get("size")) for p in (d.get("perps_positions") or [])])
print("spot_marks_count", len(d.get("spot_marks") or []))
for m in (d.get("spot_marks") or [])[:20]:
    print("  mark:", m)
