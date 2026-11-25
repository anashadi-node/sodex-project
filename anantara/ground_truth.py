"""
ANANTARA SAKTI — Ground Truth Oracle v1.0

RS-2 (Audit Fable 5/6): Single source of truth finansial & konfigurasi.

Masalah yang dipecahkan:
  - Saldo di STATUS.md diketik manual → 2 insiden rekonsiliasi dalam 48 jam
  - Config terdokumentasi ≠ .env berjalan
  - Tidak ada deteksi mutasi modal tanpa catatan

Mekanisme:
  1. job_ground_truth (dipanggil daemon setiap 30 menit) memanggil refresh()
  2. refresh() query HL API (read-only), baca state file, baca env flags
  3. Hasilnya ditulis ke data/ground_truth.json (atomik)
  4. Jika delta modal > threshold → alert Telegram via callback
  5. Semua angka finansial di STATUS.md HARUS dari sini, bukan diketik tangan

READ-ONLY: module ini TIDAK pernah menulis order, mengubah posisi, atau memodifikasi
konfigurasi trading. Hanya membaca dan menulis ground_truth.json + capital_log.jsonl.

Pure stdlib + httpx (opsional — gracefully degrade jika tidak tersedia).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger("anantara.ground_truth")

try:
    import httpx as _httpx
except ImportError:
    _httpx = None  # type: ignore[assignment]

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_DIR    = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
_DATA_DIR       = _PROJECT_DIR / "data"
_GT_FILE        = _DATA_DIR / "ground_truth.json"
_GT_PREV_FILE   = _DATA_DIR / "ground_truth_prev.json"
_CAPITAL_LOG    = _DATA_DIR / "capital_log.jsonl"
_POSITIONS_FILE = Path.home() / ".local/share/anantara/pregain_positions.json"

HL_API          = "https://api.hyperliquid.xyz"
HL_TIMEOUT      = 10  # detik

# Alert jika delta modal > 5 USD tanpa entri di capital_log
CAPITAL_DELTA_ALERT_USD = 5.0


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.rename(path)
    except Exception as e:
        log.error(f"[GROUND_TRUTH] Gagal menulis {path.name}: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _read_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _mask_addr(addr: str) -> str:
    """Mask address for persisted operator-facing ground-truth snapshots."""
    return addr[:10] + "..." if addr else "(not configured)"


def _same_addr(a: str, b: str) -> bool:
    return bool(a and b and a.lower() == b.lower())


def _balance_float(balance: dict, key: str) -> float:
    try:
        return float(balance.get(key, 0.0) or 0.0)
    except Exception:
        return 0.0


def _combined_hl_totals(accounts: list[dict]) -> dict:
    """Aggregate independent HL accounts without double counting duplicates."""
    balances = [a.get("balance", {}) for a in accounts if isinstance(a, dict)]
    return {
        "spot_total_usdc": round(sum(_balance_float(b, "total_usdc") for b in balances), 4),
        "spot_available_usdc": round(sum(_balance_float(b, "available_usdc") for b in balances), 4),
        "perp_account_value": round(sum(_balance_float(b, "perp_account_value") for b in balances), 4),
        "margin_used_usd": round(sum(_balance_float(b, "margin_used_usd") for b in balances), 4),
        "observed_account_value_usd": round(
            sum(_balance_float(b, "total_usdc") + _balance_float(b, "perp_account_value") for b in balances),
            4,
        ),
        "n_open_positions": sum(int(a.get("n_open", 0) or 0) for a in accounts),
        "n_accounts": len(accounts),
    }


# ─────────────────────────────────────────────────────────────────────────────
# HL BALANCE FETCH (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_hl_balance(addr: str) -> dict:
    """
    Ambil saldo USDC dari HL spot wallet. READ-ONLY (POST /info).
    Returns: {"total_usdc": float, "available_usdc": float, "held_margin": float,
               "perp_account_value": float, "margin_usage_pct": float}
    """
    if not addr or _httpx is None:
        return {"error": "no_address_or_httpx", "total_usdc": 0.0}

    result: dict = {}
    try:
        # Spot balance
        r = _httpx.post(f"{HL_API}/info",
                        json={"type": "spotClearinghouseState", "user": addr},
                        timeout=HL_TIMEOUT)
        balances = r.json().get("balances", [])
        usdc = next((b for b in balances if b.get("coin") == "USDC"), {})
        total     = float(usdc.get("total", 0) or 0)
        hold      = float(usdc.get("hold", 0) or 0)
        available = max(0.0, total - hold)
        result.update({
            "total_usdc":    round(total, 4),
            "available_usdc": round(available, 4),
            "held_margin":   round(hold, 4),
        })
    except Exception as e:
        result["spot_error"] = str(e)

    try:
        # Perp account value
        r2 = _httpx.post(f"{HL_API}/info",
                         json={"type": "clearinghouseState", "user": addr},
                         timeout=HL_TIMEOUT)
        ms = r2.json().get("marginSummary", {})
        acv = float(ms.get("accountValue", 0) or 0)
        margin_used = float(ms.get("totalMarginUsed", 0) or 0)
        margin_pct  = round(margin_used / acv * 100, 1) if acv > 0 else 0.0
        result.update({
            "perp_account_value": round(acv, 4),
            "margin_used_usd":    round(margin_used, 4),
            "margin_usage_pct":   margin_pct,
        })
    except Exception as e:
        result["perp_error"] = str(e)

    return result


def _fetch_hl_positions(addr: str) -> list[dict]:
    """
    Ambil posisi perp terbuka dari HL. READ-ONLY.
    Returns: list of position dicts.
    """
    if not addr or _httpx is None:
        return []
    try:
        r = _httpx.post(f"{HL_API}/info",
                        json={"type": "clearinghouseState", "user": addr},
                        timeout=HL_TIMEOUT)
        positions = r.json().get("assetPositions", [])
        result = []
        for pos in positions:
            p = pos.get("position", {})
            if float(p.get("szi", 0) or 0) == 0:
                continue
            result.append({
                "coin":    p.get("coin", "?"),
                "szi":     float(p.get("szi", 0) or 0),
                "entry":   float(p.get("entryPx", 0) or 0),
                "unrealized_pnl": float(p.get("unrealizedPnl", 0) or 0),
                "leverage": p.get("leverage", {}).get("value", 0),
            })
        return result
    except Exception as e:
        log.warning(f"[GROUND_TRUTH] fetch HL positions: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# LOCAL STATE READERS (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def _read_local_positions() -> list[dict]:
    """Baca tracker posisi Pre-Gain dari file JSON lokal."""
    data = _read_json_safe(_POSITIONS_FILE)
    if not data:
        return []
    positions = data if isinstance(data, list) else data.get("positions", [])
    return [
        {
            "coin":   p.get("coin", "?"),
            "side":   p.get("side", "?"),
            "entry":  p.get("entry_price", 0),
            "mode":   p.get("mode", "PAPER"),
            "sig_type": p.get("sig_type", "SHORT"),
        }
        for p in positions
        if isinstance(p, dict)
    ]


def _clean_env_val(raw: str) -> str:
    """Strip inline comments dari nilai env var.
    .env sering berisi: AUTOTRADE_LIVE=0    # v9.0: PAUSE...
    Hanya ambil nilai sebelum '#'.
    """
    return raw.split("#")[0].strip()


def _read_live_flags() -> dict:
    """Baca flag live dari environment (sumber kebenaran runtime)."""
    return {
        "AUTOTRADE_LIVE":      _clean_env_val(os.environ.get("AUTOTRADE_LIVE", "")),
        "PREGAIN_LIVE":        _clean_env_val(os.environ.get("PREGAIN_LIVE", "")),
        "SODEX_SPOT_FARM_LIVE": _clean_env_val(os.environ.get("SODEX_SPOT_FARM_LIVE", "")),
        "FUNDING_LIVE":        _clean_env_val(os.environ.get("FUNDING_LIVE", "")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CAPITAL DELTA DETECTION (RS-2)
# ─────────────────────────────────────────────────────────────────────────────

def _previous_ground_truth_snapshot() -> dict:
    """Last committed ground-truth snapshot before the current refresh."""
    return _read_json_safe(_GT_FILE) or _read_json_safe(_GT_PREV_FILE) or {}


def _nested_float(data: dict, path: tuple[str, ...], default: float) -> float:
    cur: object = data
    try:
        for key in path:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(key)
        return float(cur if cur is not None else default)
    except Exception:
        return default


def _detect_capital_delta(current_total: float,
                          alert_callback: Optional[Callable[[str], None]] = None) -> float:
    """
    Bandingkan saldo sekarang dengan snapshot sebelumnya.
    Jika delta > CAPITAL_DELTA_ALERT_USD dan tidak ada entri di capital_log → alert.

    Returns: delta_usd (positif = naik, negatif = turun).
    """
    prev = _previous_ground_truth_snapshot()
    prev_total = _nested_float(prev, ("hl_balance", "total_usdc"), current_total)
    delta = current_total - prev_total

    if abs(delta) > CAPITAL_DELTA_ALERT_USD:
        # Periksa apakah ada entri capital_log yang menjelaskan delta ini
        capital_log_recent = _read_recent_capital_log(hours=2)
        if not capital_log_recent:
            msg = (
                f"⚠️ *Ground Truth Alert*\n"
                f"Delta modal tidak tercatat: {delta:+.2f} USD\n"
                f"Sebelumnya: {prev_total:.2f} → Sekarang: {current_total:.2f}\n"
                f"Tidak ada entri di `data/capital_log.jsonl` dalam 2 jam terakhir.\n"
                f"Tambahkan entri manual atau periksa posisi."
            )
            log.warning(f"[GROUND_TRUTH] {msg}")
            if alert_callback:
                try:
                    alert_callback(msg)
                except Exception:
                    pass

    return round(delta, 4)


def _detect_observed_total_delta(current_total: float) -> float:
    """
    Non-alerting delta for all observed HL accounts.

    This is telemetry only. The alerting capital-delta contract remains scoped to
    HL_ADDRESS so existing operator workflows do not get false positives when an
    additional monitored account is introduced.
    """
    prev = _previous_ground_truth_snapshot()
    prev_total = _nested_float(prev, ("hl_total", "observed_account_value_usd"), current_total)
    if not prev.get("hl_total"):
        prev_total = _nested_float(prev, ("hl_balance", "total_usdc"), current_total)
    return round(current_total - prev_total, 4)


def _read_recent_capital_log(hours: int = 2) -> list[dict]:
    """Baca entri capital_log.jsonl dalam N jam terakhir."""
    if not _CAPITAL_LOG.exists():
        return []
    cutoff = time.time() - hours * 3600
    result = []
    try:
        for line in _CAPITAL_LOG.read_text().splitlines():
            try:
                entry = json.loads(line)
                if entry.get("ts", 0) >= cutoff:
                    result.append(entry)
            except Exception:
                pass
    except Exception:
        pass
    return result


def log_capital_event(event_type: str, amount_usd: float, note: str = "") -> None:
    """
    Catat perubahan modal secara eksplisit ke capital_log.jsonl.
    Dipanggil MANUAL oleh operator atau oleh modul yang melakukan deposit/withdraw.

    Args:
        event_type: "deposit" | "withdraw" | "pnl_realized" | "fee" | "note"
        amount_usd: jumlah USD (positif = masuk, negatif = keluar)
        note: keterangan bebas
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts":         time.time(),
        "utc":        _utc_iso(),
        "event_type": event_type,
        "amount_usd": round(amount_usd, 4),
        "note":       note,
    }
    with open(_CAPITAL_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    log.info(f"[CAPITAL_LOG] {event_type}: {amount_usd:+.2f} USD — {note}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN REFRESH
# ─────────────────────────────────────────────────────────────────────────────

def refresh(startup_git_sha: str = "(unknown)",
            alert_callback: Optional[Callable[[str], None]] = None) -> dict:
    """
    Kumpulkan semua "truth" dan tulis ke data/ground_truth.json.

    Dipanggil oleh job_ground_truth di daemon setiap 30 menit.
    READ-ONLY: tidak ada order, tidak ada modifikasi trading.

    Returns: ground_truth dict (juga tersimpan di file).
    """
    hl_addr = os.environ.get("HL_ADDRESS", "").strip()
    hl_harvest_addr = os.environ.get("HL_HARVEST_ADDRESS", "").strip()

    # Query HL (read-only API calls)
    hl_balance   = _fetch_hl_balance(hl_addr)
    hl_positions = _fetch_hl_positions(hl_addr)
    harvest_same_as_primary = _same_addr(hl_addr, hl_harvest_addr)
    if hl_harvest_addr and harvest_same_as_primary:
        hl_harvest_balance = hl_balance
        hl_harvest_positions = hl_positions
    elif hl_harvest_addr:
        hl_harvest_balance = _fetch_hl_balance(hl_harvest_addr)
        hl_harvest_positions = _fetch_hl_positions(hl_harvest_addr)
    else:
        hl_harvest_balance = {"total_usdc": 0.0, "scope": "not_configured"}
        hl_harvest_positions = []

    # Baca state lokal
    local_positions = _read_local_positions()
    live_flags      = _read_live_flags()

    # Deteksi delta modal
    total_usdc = hl_balance.get("total_usdc", 0.0)
    capital_delta = _detect_capital_delta(total_usdc, alert_callback)

    hl_accounts: list[dict] = []
    if hl_addr:
        hl_accounts.append({
            "role": "primary",
            "address": _mask_addr(hl_addr),
            "balance": hl_balance,
            "positions": hl_positions,
            "n_open": len(hl_positions),
        })
    if hl_harvest_addr and not harvest_same_as_primary:
        hl_accounts.append({
            "role": "harvest",
            "address": _mask_addr(hl_harvest_addr),
            "balance": hl_harvest_balance,
            "positions": hl_harvest_positions,
            "n_open": len(hl_harvest_positions),
        })
    elif hl_harvest_addr and harvest_same_as_primary:
        hl_accounts.append({
            "role": "harvest_alias",
            "address": _mask_addr(hl_harvest_addr),
            "balance": hl_harvest_balance,
            "positions": hl_harvest_positions,
            "n_open": len(hl_harvest_positions),
            "deduplicated": True,
        })

    n_open_hl_total = len(hl_positions)
    if hl_harvest_addr and not harvest_same_as_primary:
        n_open_hl_total += len(hl_harvest_positions)

    hl_total = _combined_hl_totals([
        a for a in hl_accounts if not a.get("deduplicated")
    ] or hl_accounts)
    observed_delta = _detect_observed_total_delta(hl_total.get("observed_account_value_usd", 0.0))

    gt = {
        "generated_utc":    _utc_iso(),
        "git_sha":          startup_git_sha,
        "hl_address":       _mask_addr(hl_addr),
        "hl_balance":       hl_balance,
        "hl_positions":     hl_positions,
        "hl_harvest_address": _mask_addr(hl_harvest_addr),
        "hl_harvest_balance": hl_harvest_balance,
        "hl_harvest_positions": hl_harvest_positions,
        "hl_accounts":      hl_accounts,
        "hl_total":         hl_total,
        "local_positions":  local_positions,
        "live_flags":       live_flags,
        "capital_delta_usd": capital_delta,
        "capital_delta_observed_usd": observed_delta,
        "n_open_hl":        len(hl_positions),
        "n_open_hl_harvest": len(hl_harvest_positions),
        "n_open_hl_total":  n_open_hl_total,
        "n_open_local":     len(local_positions),
        "capital_delta_scope": "HL_ADDRESS",
        "capital_delta_observed_scope": "deduplicated_observed_hl_accounts",
    }

    # Simpan snapshot sebelumnya untuk deteksi delta berikutnya
    prev = _read_json_safe(_GT_FILE)
    if prev:
        _write_atomic(_GT_PREV_FILE, prev)

    _write_atomic(_GT_FILE, gt)
    log.info(
        f"[GROUND_TRUTH] Refreshed: HL={total_usdc:.2f} USDC, "
        f"positions=HL:{len(hl_positions)}/harvest:{len(hl_harvest_positions)}/"
        f"total:{n_open_hl_total}/local:{len(local_positions)}, "
        f"delta={capital_delta:+.2f} USD"
    )
    return gt


def read() -> Optional[dict]:
    """Baca ground_truth.json terakhir. None jika belum ada."""
    return _read_json_safe(_GT_FILE)


# ─────────────────────────────────────────────────────────────────────────────
# CLI UTILITY
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sha = sys.argv[1] if len(sys.argv) > 1 else "(cli)"
    result = refresh(startup_git_sha=sha)
    print(json.dumps(result, indent=2, ensure_ascii=False))
