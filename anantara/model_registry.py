#!/usr/bin/env python3
"""
ANANTARA SAKTI — Model registry + champion/challenger governance (pure + tested).

Institutional MLOps gap: a retrain could silently SHIP A WORSE MODEL. This adds
governance so every retrain is logged and a new model (challenger) only becomes
the live model (champion) if it BEATS the incumbent out-of-sample by a margin —
the champion/challenger pattern used by model-risk teams. Otherwise the champion
is kept and we alert (visibility + rollback signal).

  • should_promote(challenger_oos, champion_oos, margin)  — pure decision
  • record_and_decide(path, model, oos, margin)           — log run + decide + persist
  • history(path, model)                                   — audit trail per model

Registry persisted as JSON (freqtrade_user_data/models/registry.json). Decision
logic is pure (unit-tested); persistence is thin I/O. OOS metric = higher-is-better
(e.g. directional accuracy or PF). Stdlib only.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone

REGISTRY_PATH = "freqtrade_user_data/models/registry.json"
PROMOTE_MARGIN = 0.0       # challenger must be ≥ champion + margin to promote (sustained gain)


def should_promote(challenger_oos: float, champion_oos: float | None,
                   margin: float = PROMOTE_MARGIN) -> bool:
    """Pure rule: promote the challenger only if it beats the champion OOS by `margin`.
    First-ever model (no champion) is promoted iff its OOS is positive/finite."""
    if champion_oos is None:
        return challenger_oos is not None and challenger_oos > 0
    if challenger_oos is None:
        return False
    return challenger_oos >= champion_oos + margin


def _load(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def record_and_decide(path: str, model: str, challenger_oos: float,
                      margin: float = PROMOTE_MARGIN, ts: str | None = None) -> dict:
    """Log a retrain run; promote to champion if it beats the incumbent OOS. Returns
    {promoted, champion_oos, challenger_oos, action}. Append-only audit per model."""
    ts = ts or datetime.now(timezone.utc).isoformat()
    reg = _load(path)
    entry = reg.setdefault(model, {"champion_oos": None, "champion_ts": None, "runs": []})
    champ = entry.get("champion_oos")
    promoted = should_promote(challenger_oos, champ, margin)
    entry["runs"].append({"ts": ts, "oos": challenger_oos, "promoted": promoted})
    entry["runs"] = entry["runs"][-50:]                 # bound audit trail
    if promoted:
        entry["champion_oos"] = challenger_oos
        entry["champion_ts"] = ts
    _save(path, reg)
    action = ("promoted (new champion)" if promoted else
              f"kept champion (challenger {challenger_oos} < champion {champ})")
    return {"model": model, "promoted": promoted, "champion_oos": entry["champion_oos"],
            "challenger_oos": challenger_oos, "action": action}


def history(path: str, model: str) -> list:
    return _load(path).get(model, {}).get("runs", [])


def champion(path: str, model: str):
    return _load(path).get(model, {}).get("champion_oos")
