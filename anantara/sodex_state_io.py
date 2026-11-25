from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_json(path: Path, payload: dict) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def backup_file(path: Path) -> Path | None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.corrupt-{ts}.bak")
    try:
        os.replace(path, backup)
    except OSError:
        return None
    return backup


def read_json_dict(path: Path, *, backup_invalid: bool = False) -> tuple[dict | None, str]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None, "MISSING"
    except json.JSONDecodeError:
        if backup_invalid:
            backup_file(path)
        return None, "JSONDecodeError"
    except Exception as exc:
        return None, type(exc).__name__
    if not isinstance(data, dict):
        if backup_invalid:
            backup_file(path)
        return None, f"INVALID_ROOT_{type(data).__name__}"
    return data, "OK"
