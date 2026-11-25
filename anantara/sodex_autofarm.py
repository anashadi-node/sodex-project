#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  ANANTARA SAKTI — SoDEX AutoFarm v3.1                      ║
║  "Sentiment-aware, Intel-driven, Guardian-protected"       ║
╚══════════════════════════════════════════════════════════════╝

PHILOSOPHY (post-10-RT calibration + intel integration):
  - T+0 ONLY (T+1 unreliable — market shifts past order)
  - PRIME TIME 24/7 (327K snapshots: spread varies only 0.007% across hours)
  - INTEL-DRIVEN capital sizing (F&G-based: 0.5x-2.0x)
  - DYNAMIC spread threshold (0.25%-0.35% based on regime)
  - SPREAD GUARDIAN: monitor every 15s, cancel if < threshold
  - DUST COMBINER: auto-merge small balances into sellable lots
  - SINGLE PAIR: PEPE/USDC only (only pair with spread >0.30%)
  - CAPITAL-AWARE: never deploy >90% of free balance
  - EMERGENCY STOP: circuit breaker on 3 consecutive losses
  - MACRO CIRCUIT BREAKER: F&G extreme greed + liq cascade

NEW v3.1 — Intel Layer Integration:
  ✓ Fear & Greed-based capital multiplier
  ✓ Dynamic spread threshold by regime
  ✓ Macro circuit breaker (F&G >85, liq cascade)
  ✓ Intel summary logged every RT

USAGE:
  python3 anantara/sodex_autofarm.py           # single RT
  python3 anantara/sodex_autofarm.py --loop    # continuous
  python3 anantara/sodex_autofarm.py --dry     # scan only
  python3 anantara/sodex_autofarm.py --dust    # combine dust
"""

import subprocess
import json
import time
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# ── State I/O (GPT addition) ────────────────────────────────
try:
    from anantara.sodex_state_io import read_json_dict
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from anantara.sodex_state_io import read_json_dict

# ── Intel Layer ─────────────────────────────────────────────
try:
    from anantara.sodex_intel_layer import IntelLayer
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from anantara.sodex_intel_layer import IntelLayer
    except ImportError:
        IntelLayer = None

if IntelLayer is not None:
    try:
        intel = IntelLayer()
        HAS_INTEL = True
    except Exception:
        HAS_INTEL = False
        intel = None
else:
    HAS_INTEL = False
    intel = None

# ── External Event Shock Guard ──────────────────────────────
try:
    from anantara.sodex_event_shock_guard import fetch_event_risk
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from anantara.sodex_event_shock_guard import fetch_event_risk
    except ImportError:
        fetch_event_risk = None

# ── SPOT Governor (GAP 3+4+5) ───────────────────────────────
HAS_GOVERNOR = False
try:
    from anantara.sodex_spot_governor import (
        get_state, get_risk, get_calibrator,
        spot_expectancy_gate, SpotState, RiskMonitor, FillRateCalibrator
    )
    HAS_GOVERNOR = True
except ImportError:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from anantara.sodex_spot_governor import (
            get_state, get_risk, get_calibrator,
            spot_expectancy_gate, SpotState, RiskMonitor, FillRateCalibrator
        )
        HAS_GOVERNOR = True
    except ImportError:
        pass

if HAS_GOVERNOR:
    _spot_state = get_state()
    _risk_monitor = get_risk()
    _fill_cal = get_calibrator()
else:
    _spot_state = None
    _risk_monitor = None
    _fill_cal = None

# ── CONFIG ──────────────────────────────────────────────────
SYMBOL = "PEPE/USDC"
SYMBOL_ID = 5
PROJECT_DIR = Path(__file__).resolve().parent.parent
SODEX_BIN = os.environ.get("SODEX_BIN", str(PROJECT_DIR / "bin" / "sodex"))
SAFETY_HALT_FILE = PROJECT_DIR / "data" / "SAFETY_HALT"
PNL_HALT_FILE = PROJECT_DIR / "data" / "PNL_HALT"
SPOT_SELL_BLOCK_FILE = PROJECT_DIR / "data" / "SODEX_SPOT_SELL_BLOCKED"
MIN_SPREAD_PCT = 0.30       # must be >0.30% to deploy
COST_PCT = 0.17             # 0.035%×2 fees + 0.10% buffer
MIN_NET_PCT = 0.05          # minimum net after costs
MIN_NOTIONAL = 10.0         # SoDEX minimum order
ORDER_TIMEOUT_S = 900        # 15min — ASK queue is 113M deep, sells take longer (data-proven)
PRIME_START_UTC = 0      # 24/7 — 327K snapshots prove spreads consistent
PRIME_END_UTC = 24       # Best/worst hour differ only 0.007% (0.3259% vs 0.3189%)
MAX_CONSECUTIVE_LOSSES = 3  # emergency stop
GUARDIAN_INTERVAL_S = 15    # spread check interval
LOCK_FILE = Path.home() / ".local/share/anantara/sodex_autofarm.lock"
EVENT_GUARD_BLOCK_LEVELS = {"ORANGE", "RED"}
EVENT_STATUS_FILE = PROJECT_DIR / "data" / "sodex" / "research" / "autonomous_status.json"
EVENT_STATUS_MAX_AGE_S = int(os.environ.get("SODEX_EVENT_STATUS_MAX_AGE_S", "180"))
POLICY_STATUS_MAX_AGE_S = int(os.environ.get("SODEX_POLICY_STATUS_MAX_AGE_S", "300"))
LIVE_ROUTE = "SPOT_LONG"


def live_order_blocked() -> str | None:
    if SAFETY_HALT_FILE.exists():
        return "SAFETY_HALT"
    if PNL_HALT_FILE.exists():
        return "PNL_HALT"
    if SPOT_SELL_BLOCK_FILE.exists():
        return "SPOT_SELL_CAPABILITY_BLOCKED"
    # ── GERBANG IZIN LIVE (audit mendalam 30-Sep-2026) ───────────────────────
    # Mesin ini dipanggil `job_sodex_spot_farm` tiap 15 menit lewat
    # `scripts/sodex_spot_daemon.py once`, dan `--dry` bersifat OPT-IN (baris
    # argparse) → artinya **live adalah DEFAULT**. Flag `SODEX_SPOT_FARM_LIVE`
    # sebelumnya punya 0 kemunculan di file ini, jadi `SODEX_SPOT_FARM_LIVE=0`
    # TIDAK melindungi jalur ini sama sekali — penahannya hanya kondisi data
    # (event-risk stale), yaitu keberuntungan, bukan desain.
    # Sekarang wajib EKSPLISIT: tanpa SODEX_SPOT_FARM_LIVE=1 → tidak ada order.
    if os.environ.get("SODEX_SPOT_FARM_LIVE", "0") != "1":
        return "LIVE_NOT_APPROVED"
    return None

# ── STATE ───────────────────────────────────────────────────
class State:
    def __init__(self):
        self.rt_count = 0
        self.consecutive_losses = 0
        self.total_pnl = 0.0
        self.emergency_stop = False
        self.start_balance = 0.0

state = State()

def acquire_process_lock():
    """Prevent overlapping live autofarm processes from double-deploying capital."""
    try:
        import fcntl
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        fh = LOCK_FILE.open("w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n")
        fh.flush()
        return fh
    except BlockingIOError:
        return None

def _load_cached_event_risk() -> tuple[dict | None, str]:
    """Fast local event-risk cache from autonomous research status."""
    # Force-allow bypass for BULL market or explicit override
    if os.environ.get("SODEX_EVENT_GUARD_FORCE_ALLOW", "0") == "1":
        return {"level": "NORMAL", "live_gate": "ALLOW_WITH_CAUTION", 
                "reason": "FORCE_ALLOW_BYPASS", "categories": []}, "FORCE_ALLOW"
    
    data, read_reason = read_json_dict(EVENT_STATUS_FILE, backup_invalid=True)
    if data is None:
        return None, f"EVENT_RISK_CACHE_ERROR_{read_reason}"
    try:
        risk = data.get("event_risk")
        if not isinstance(risk, dict):
            return None, "NO_EVENT_RISK_IN_STATUS"
        ts_raw = str(data.get("ts") or risk.get("ts") or "")
        if not ts_raw:
            return None, "NO_EVENT_RISK_TS"
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        if age_s > EVENT_STATUS_MAX_AGE_S:
            return None, f"EVENT_RISK_STALE_{int(age_s)}s"
        risk = dict(risk)
        risk["from_local_status"] = True
        risk["status_age_s"] = round(age_s, 1)
        return risk, "OK"
    except Exception as exc:
        return None, f"EVENT_RISK_CACHE_ERROR_{type(exc).__name__}"

def external_event_gate() -> tuple[bool, str, dict]:
    """Block live farming during external headline shock events."""
    if os.environ.get("SODEX_EVENT_GUARD_DISABLE") == "1":
        return True, "EVENT_GUARD_DISABLED", {"level": "DISABLED"}

    risk, cache_reason = _load_cached_event_risk()
    if risk is None:
        if os.environ.get("SODEX_EVENT_GUARD_LIVE_FETCH") == "1" and fetch_event_risk is not None:
            try:
                risk = fetch_event_risk()
            except Exception as exc:
                return False, f"EVENT_RISK_UNKNOWN_FETCH_ERROR_{type(exc).__name__}", {
                    "level": "UNKNOWN", "live_gate": "BLOCK_LIVE", "reason": cache_reason,
                }
        else:
            return False, f"EVENT_RISK_UNKNOWN_{cache_reason}", {
                "level": "UNKNOWN", "live_gate": "BLOCK_LIVE", "reason": cache_reason,
            }

    level = str(risk.get("level", "NORMAL"))
    live_gate = str(risk.get("live_gate", "ALLOW_WITH_CAUTION"))
    if level in EVENT_GUARD_BLOCK_LEVELS or live_gate == "BLOCK_LIVE":
        # ── FORCE_ALLOW: unconditional bypass (independent of BULL_BYPASS) ──
        if os.environ.get("SODEX_EVENT_GUARD_FORCE_ALLOW", "0") == "1":
            return True, f"EVENT_RISK_{level}_FORCE_ALLOW", risk
        # ── BULL regime override: strong uptrend provides buffer against event shocks ──
        bypass_env = os.environ.get("SODEX_EVENT_GUARD_BULL_BYPASS", "1")
        if bypass_env == "1":
            try:
                # Try importing regime detection
                import importlib
                sf = importlib.import_module("anantara.sodex_farming")
                regime_dir, regime_conf = sf._read_regime_direction()
                if regime_dir == "long" and regime_conf >= 0.85:
                    # FIX: BULL_BYPASS returned a 2-tuple here vs the 3-tuple
                    # signature → live ValueError: unpack (unittest flagged when
                    # regime was BULL). Match the contract: (bool, reason, risk).
                    return True, f"EVENT_RISK_{level}_BULL_BYPASS(conf={regime_conf:.0%})", risk
            except Exception:
                pass  # fall through to block
        reason = str(risk.get("reason", "external event shock"))[:160]
        return False, f"EVENT_RISK_{level}_{reason}", risk
    return True, f"EVENT_RISK_{level}", risk

def _load_cached_research_status(max_age_s: int) -> tuple[dict | None, str]:
    data, read_reason = read_json_dict(EVENT_STATUS_FILE, backup_invalid=True)
    if data is None:
        return None, f"STATUS_CACHE_ERROR_{read_reason}"
    try:
        ts_raw = str(data.get("ts") or "")
        if not ts_raw:
            return None, "NO_STATUS_TS"
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_s = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        if age_s > max_age_s:
            return None, f"STATUS_STALE_{int(age_s)}s"
        return data, "OK"
    except Exception as exc:
        return None, f"STATUS_CACHE_ERROR_{type(exc).__name__}"

def adaptive_policy_gate(expected_route: str = LIVE_ROUTE) -> tuple[bool, str, dict]:
    """Fail-closed learned-policy gate for the live route."""
    if os.environ.get("SODEX_ADAPTIVE_POLICY_DISABLE") == "1":
        return True, "POLICY_DISABLED", {"status": "DISABLED"}
    data, status_reason = _load_cached_research_status(POLICY_STATUS_MAX_AGE_S)
    if data is None:
        return False, f"POLICY_UNKNOWN_{status_reason}", {}
    policy = data.get("adaptive_policy")
    if not isinstance(policy, dict):
        return False, "POLICY_UNKNOWN_NO_ADAPTIVE_POLICY", {}
    if policy.get("external_live_gate") == "BLOCK_LIVE":
        return False, "POLICY_BLOCKED_BY_EVENT_RISK", policy

    promoted = [
        item for item in policy.get("promote", []) or []
        if isinstance(item, dict) and item.get("route") == expected_route
    ]
    if promoted:
        return True, f"POLICY_PROMOTED_{expected_route}", {"evidence": promoted[0]}

    blocked = [
        item for item in policy.get("block", []) or []
        if isinstance(item, dict) and item.get("route") == expected_route
    ]
    if blocked:
        evidence = blocked[0]
        return False, (
            f"POLICY_BLOCK_ROUTE_{expected_route}_"
            f"wr={evidence.get('win_rate')}_edge={evidence.get('avg_edge_return_pct')}"
        ), policy
    return False, f"POLICY_NO_PROMOTE_{expected_route}", policy

# ── CLI HELPERS ─────────────────────────────────────────────
def _dotenv_value(path: Path, key: str) -> str:
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip("'\"")
    except OSError:
        return ""
    return ""

def _env():
    """Return env dict with SoDEX credentials. Reads from os.environ, falls back to .env file."""
    env = os.environ.copy()
    # Fallback: read from .env file if vars not in environment
    for key in ["SODEX_PRIVATE_KEY", "SODEX_ACCOUNT_ID", "SODEX_ADDRESS"]:
        if key not in env or not env[key]:
            val = _dotenv_value(PROJECT_DIR / ".env", key)
            if val:
                env[key] = val
    return env

def _sodex(args, timeout=30):
    """Run bin/sodex with proper error handling. Returns (success, output_text)."""
    try:
        result = subprocess.run(
            [SODEX_BIN] + args,
            capture_output=True, text=True,
            timeout=timeout, env=_env(), cwd=PROJECT_DIR
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "notional is invalid" in stderr:
                return False, "NOTIONAL_TOO_SMALL"
            if "insufficient" in stderr.lower():
                return False, "INSUFFICIENT_BALANCE"
            return False, stderr[:200]
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)[:200]

def get_balance():
    """Get spot balances as dict {coin: total_float}.

    Robust terhadap bentuk respons tak terduga: venue bisa membalas objek
    (bukan list) atau field hilang. Versi lama melempar TypeError dan bisa
    MEMATIKAN pemanggil (termasuk snapshot saldo sebelum kirim order).
    """
    env = _env()
    addr = env.get("SODEX_ADDRESS", "")
    args = ["balance", "spot", "--format", "json"]
    if addr:
        args += ["--address", addr]
    ok, out = _sodex(args)
    if not ok:
        return {}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        data = data.get("data") or data.get("balances") or []
    if not isinstance(data, list):
        return {}
    out_map = {}
    for c in data:
        if not isinstance(c, dict):
            continue
        try:
            total = float(c.get("total") or 0)
        except (TypeError, ValueError):
            continue
        if total > 0.0001:
            out_map[str(c.get("coin"))] = total
    return out_map

def get_free_usdc():
    """Get free USDC balance."""
    bal = get_balance()
    return bal.get("vUSDC", 0.0)

def get_orderbook(depth=3):
    """Get orderbook for SYMBOL. Returns (bids_list, asks_list) or (None, None)."""
    ok, out = _sodex(["orderbook", "spot", SYMBOL, "--depth", str(depth), "--format", "json"])
    if not ok:
        return None, None
    try:
        data = json.loads(out)
        bids = [(float(b["price"]), float(b["quantity"])) for b in data["bids"]]
        asks = [(float(a["price"]), float(a["quantity"])) for a in data["asks"]]
        return bids, asks
    except (json.JSONDecodeError, KeyError, IndexError):
        return None, None

def get_orders():
    """Daftar order terbuka, atau None bila venue TIDAK TERBACA.

    MENGAPA None (bukan []): audit mendalam 30-Sep-2026 — versi lama mengembalikan
    `[]` ketika CLI gagal, lalu pemanggil membacanya sebagai "tidak ada order" =
    "sudah terisi / rescue selesai". Artinya **error jaringan berubah menjadi
    klaim posisi** (fail-open) di mesin uang nyata. Pemanggil WAJIB membedakan
    None (tidak tahu) dari [] (benar-benar kosong).
    """
    ok, out = _sodex(["orders", "list", "spot", "--format", "json"])
    if not ok:
        return None
    try:
        rows = json.loads(out)
    except json.JSONDecodeError:
        return None
    return rows if isinstance(rows, list) else None


_SYMBOL_ID_CACHE: dict[str, int] = {}


def _spot_coin_for(symbol: str | None = None) -> str:
    """Coin saldo venue untuk SYMBOL.

    Menerima dua bentuk: pasangan ("PEPE/USDC" -> "vPEPE") dan simbol venue
    ("vSHIB_vUSDC" -> "vSHIB").
    """
    raw = str(symbol or SYMBOL).strip()
    if "_" in raw:                      # bentuk venue: vSHIB_vUSDC
        return raw.split("_")[0]
    base = raw.split("/")[0].strip()
    return base if base.startswith("v") else "v" + base


def _resolve_zero_oid(cl_id: str, coin: str, bal_before: float | None,
                      qty: float, side: str):
    """Putuskan status order yang venue balas dengan `orderID=0`.

    Asumsi lama — "OrderID=0 is SoDEX CLI cosmetic bug: order IS placed" — tidak
    punya bukti apa pun dan merupakan sumber kelas **fill-phantom**. Yang bisa
    DIBUKTIKAN hanya dua:
      1. order muncul di daftar order terbuka  → terpasang (id venue nyata);
      2. saldo venue bergerak ± qty            → TERISI.
    Selain itu status TIDAK DIKETAHUI → (None, None): pemanggil tidak boleh
    mencatat posisi, tidak boleh menaikkan counter, dan tidak boleh menembak lagi.
    """
    time.sleep(1)
    orders = get_orders()
    for o in (orders or []):
        if o.get("clOrdID") == cl_id:
            return o.get("orderID"), cl_id
    if bal_before is None:
        print("   ⛔ orderID=0 & saldo acuan tak tersedia — status TIDAK DIKETAHUI "
              "(fail-closed: order tidak diklaim terpasang)", flush=True)
        return None, None
    try:
        bal_after = float((get_balance() or {}).get(coin) or 0.0)
    except Exception:  # noqa: BLE001
        return None, None
    moved = (bal_after - bal_before) if side == "buy" else (bal_before - bal_after)
    if moved >= qty * 0.999:
        print(f"   ✅ orderID=0, tapi saldo {coin} bergerak {moved:.8f} ≈ qty → "
              f"TERISI (bukti saldo venue, bukan asumsi)", flush=True)
        return 0, cl_id
    print(f"   ⛔ orderID=0 & saldo {coin} TIDAK bergerak (Δ={moved:.8f}) → order "
          f"TIDAK terkonfirmasi (fail-closed: tidak diklaim terpasang)", flush=True)
    return None, None


def _symbol_id_for(symbol: str) -> int | None:
    """ID simbol RESMI venue untuk `symbol` (mis. "PEPE/USDC" -> 5).

    SATU sumber kebenaran = `markets spot`. Menggantikan pemakaian konstanta
    `SYMBOL_ID` yang hardcode; dulu ada dua sumber (SYMBOL_ID vs
    COIN_TO_SODEX_SYMBOL) yang bisa menyimpang. None = tak bisa dipastikan →
    pemanggil WAJIB fail-closed (jangan kirim cancel dengan id tebakan), karena
    cancel dengan symbol-id salah gagal senyap dan order tetap hidup (kelas UNI).
    """
    key = str(symbol).strip()
    if key in _SYMBOL_ID_CACHE:
        return _SYMBOL_ID_CACHE[key]
    ok, out = _sodex(["markets", "spot", "--format", "json"])
    if not ok:
        return None
    try:
        rows = json.loads(out)
    except json.JSONDecodeError:
        return None
    if isinstance(rows, dict):
        rows = rows.get("data") or []
    if not isinstance(rows, list):
        return None
    for r in rows:
        if not isinstance(r, dict):
            continue
        if key in (str(r.get("displayName")), str(r.get("name"))):
            raw = r.get("id")
            if raw is None:
                return None
            try:
                sid = int(raw)
            except (TypeError, ValueError):
                return None
            _SYMBOL_ID_CACHE[key] = sid
            return sid
    return None

def cancel_order(order_id, cl_ord_id, symbol: str | None = None):
    """Cancel + VERIFIKASI order benar-benar hilang dari venue.

    Dua cacat lama (audit mendalam 30-Sep-2026) — keduanya kelas insiden UNI:
      1. `--symbol-id` HARDCODE (`SYMBOL_ID = 5`) sementara ada map
         `COIN_TO_SODEX_SYMBOL` = sumber kebenaran kedua yang bisa menyimpang.
         Cancel dengan symbol-id salah GAGAL SENYAP → order tetap hidup.
      2. Hasil cancel DIABAIKAN di semua pemanggil → cancel gagal dianggap sukses.
    Sekarang: symbol-id dari metadata venue (`markets spot`), dan sukses HANYA
    bila order terbukti hilang dari daftar order terbuka.
    """
    sym = symbol or SYMBOL
    sid = _symbol_id_for(sym)
    if sid is None:
        print(f"   ⛔ cancel {sym}: symbol-id venue TAK TERBACA — cancel dibatalkan "
              f"(fail-closed; cancel dengan id salah = order nyangkut, kelas UNI)")
        return False
    ok, out = _sodex([
        "orders", "cancel", "spot",
        "--symbol-id", str(sid),
        "--order-id", str(order_id),
        "--cl-ord-id", str(cl_ord_id)
    ])
    if not ok:
        print(f"   ⚠️  cancel rc!=0 ({sym} order {order_id}) — dianggap BELUM batal")
        return False
    for _ in range(3):
        orders = get_orders()
        if orders is None:
            print(f"   ⚠️  cancel {sym}: venue tak terbaca saat verifikasi — "
                  f"status BELUM terverifikasi (fail-closed)")
            return False
        gone = not any(str(o.get("orderID")) == str(order_id)
                       or str(o.get("clOrdID")) == str(cl_ord_id) for o in orders)
        if gone:
            return True
        time.sleep(1)
    print(f"   ⚠️  cancel {sym} order {order_id}: MASIH ADA di venue setelah 3x cek")
    return False

def place_order(side, price, qty):
    """Place a limit order. Returns (order_id, cl_ord_id) or (None, None)."""
    blocked = live_order_blocked()
    if blocked:
        print(f"   Error: LIVE_ORDER_BLOCKED_{blocked}")
        return None, None
    # Snapshot saldo SEBELUM kirim — satu-satunya bukti sah untuk memutuskan
    # status ketika venue membalas `orderID=0` (lihat _resolve_zero_oid).
    coin = _spot_coin_for()
    _raw_before = (get_balance() or {}).get(coin)
    bal_before = float(_raw_before) if _raw_before is not None else None
    ok, out = _sodex([
        "orders", "place", "spot",
        "--symbol", SYMBOL,
        "--side", side,
        "--price", str(price),
        "--qty", str(qty),
        "--type", "limit",
        "--tif", "gtc",
        "--format", "json"
    ])
    if not ok:
        return None, None
    try:
        data = json.loads(out)
        if isinstance(data, list) and data:
            data = data[0]
        oid = data.get("orderID", 0)
        cl_id = data.get("clOrdID", "")
        # OrderID=0 is SoDEX CLI cosmetic bug — order IS placed.
        # Look up real orderID by matching clOrdID.
        if oid == 0 or oid == "0":
            # orderID=0 BUKAN bukti "order sudah terpasang" (asumsi lama =
            # sumber kelas fill-phantom). Buktikan: daftar order terbuka atau
            # delta saldo venue; selain itu fail-closed.
            return _resolve_zero_oid(cl_id, coin, bal_before, float(qty), side)
        return oid, cl_id
    except (json.JSONDecodeError, KeyError):
        return None, None

def _num_order_field(order: dict, *names: str, default: float = 0.0) -> float:
    """Parse numeric order fields that may arrive as ints, floats, or strings."""
    for name in names:
        if name in order and order.get(name) not in (None, ""):
            try:
                return float(order.get(name))
            except (TypeError, ValueError):
                continue
    return default

def _order_matches(order: dict, order_id, cl_ord_id) -> bool:
    if cl_ord_id and order.get("clOrdID") == cl_ord_id:
        return True
    if order_id not in (None, "", 0, "0") and str(order.get("orderID")) == str(order_id):
        return True
    return False

def emergency_sell_pepe(reason: str) -> bool:
    """Last-resort inventory cleanup. Sells PEPE at best bid regardless of size."""
    bal = get_balance()
    pepe_qty = int(bal.get("vPEPE", 0))
    bids, _ = get_orderbook(depth=1)
    if not bids or pepe_qty <= 0:
        print(f"   🛑 Emergency sell unavailable: no bid/PEPE ({reason})")
        return False

    bid_price = bids[0][0]
    sell_qty = int(pepe_qty * 0.999)
    # v4.4: Lowered threshold — sell even tiny amounts to clear inventory
    MIN_DUST = 0.50  # $0.50 minimum, not $10 — dust blocking is worse than small loss
    if sell_qty * bid_price < MIN_DUST:
        print(f"   🛑 Emergency sell skipped: PEPE value < ${MIN_DUST:.2f} ({reason})")
        return False

    print(f"   🛟 Emergency SELL {sell_qty:,} PEPE @ bid {bid_price:.8f} ({reason})")
    sell_id, sell_cl = place_order("sell", bid_price, sell_qty)
    if sell_id is None:
        return False
    result = guardian_wait(sell_id, sell_cl, "sell", 0.0)
    return result in ("FILLED", "PARTIALLY_FILLED_CANCELLED")

# ── SPREAD ANALYSIS ─────────────────────────────────────────
def analyze_spread():
    """Analyze current spread. Returns dict or None."""
    bids, asks = get_orderbook(depth=3)
    if not bids or not asks:
        return None

    best_bid = bids[0][0]
    best_ask = asks[0][0]
    spread_pct = (best_ask - best_bid) / best_bid * 100
    net_pct = spread_pct - COST_PCT

    # T+0 depth
    bid_depth = bids[0][0] * bids[0][1]
    ask_depth = asks[0][0] * asks[0][1]

    return {
        "bid": best_bid,
        "ask": best_ask,
        "spread_pct": spread_pct,
        "net_pct": net_pct,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "viable": net_pct >= MIN_NET_PCT and spread_pct >= MIN_SPREAD_PCT,
    }

# ── PRIME TIME GATE ─────────────────────────────────────────
def _utc_hour():
    """Get UTC hour via epoch seconds (most reliable cross-platform)."""
    try:
        result = subprocess.run(["date", "+%s"], capture_output=True, text=True, timeout=5)
        epoch = int(result.stdout.strip())
        from datetime import datetime, timezone
        return datetime.utcfromtimestamp(epoch).hour
    except Exception:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).hour

def is_prime_time():
    """Check if we're in the optimal trading window (uses OS clock)."""
    return PRIME_START_UTC <= _utc_hour() < PRIME_END_UTC

def time_to_prime():
    """Seconds until next prime time start."""
    h = _utc_hour()
    if h >= PRIME_END_UTC:
        return (24 - h + PRIME_START_UTC) * 3600
    elif h < PRIME_START_UTC:
        return (PRIME_START_UTC - h) * 3600
    return 0  # Already in prime time

# ── DUST COMBINER ───────────────────────────────────────────
def combine_dust():
    """Check for dust balances and try to sell them."""
    bal = get_balance()
    dust = {}
    for coin, amount in bal.items():
        if coin == "vUSDC":
            continue
        # Estimate USD value using rough mark (or orderbook)
        if coin == "vPEPE":
            bids, _ = get_orderbook(depth=1)
            if bids:
                usd_val = amount * bids[0][0]
                if usd_val < MIN_NOTIONAL and usd_val > 0.50:
                    dust[coin] = (amount, usd_val, bids[0][0])
        elif coin == "vSHIB":
            # Check SHIB orderbook
            ok, out = _sodex(["orderbook", "spot", "SHIB/USDC", "--depth", "1", "--format", "json"])
            if ok:
                try:
                    shib_bid = float(json.loads(out)["bids"][0]["price"])
                    usd_val = amount * shib_bid
                    if usd_val < MIN_NOTIONAL and usd_val > 0.50:
                        dust[coin] = (amount, usd_val, shib_bid)
                except:
                    pass

    if not dust:
        return

    print("\n🧹 DUST CHECK:")
    total_dust_usd = sum(d[1] for d in dust.values())
    for coin, (amt, usd, px) in dust.items():
        print(f"   {coin}: {amt:.4f} (≈${usd:.2f})")

    # If total dust > $10, we could combine... but different coins can't combine.
    # Strategy: buy more of the same coin to reach $10, then sell all.
    # For now, just report.
    if total_dust_usd > 0:
        print(f"   ⚠️  Total dust: ≈${total_dust_usd:.2f} — will absorb in next RT")

# ── GUARDIAN MONITOR ────────────────────────────────────────
def guardian_wait(order_id, cl_ord_id, expected_side, entry_spread):
    """
    Guardian monitor during order fill.
    - Checks every GUARDIAN_INTERVAL_S
    - Cancels if spread tightens below threshold
    - Cancels if order exceeds ORDER_TIMEOUT_S
    Returns: "FILLED", "PARTIALLY_FILLED_CANCELLED", "CANCELLED_SPREAD",
             "CANCELLED_TIMEOUT", "ERROR"
    """
    start = time.time()
    last_status = "NEW"

    while True:
        elapsed = time.time() - start

        # Timeout check
        if elapsed > ORDER_TIMEOUT_S:
            print(f"   ⏰ Timeout ({ORDER_TIMEOUT_S}s) — cancelling")
            cancel_order(order_id, cl_ord_id)
            return "CANCELLED_TIMEOUT"

        # Spread guardian (more aggressive on SELL side)
        analysis = analyze_spread()
        if analysis:
            spread_drop = entry_spread - analysis["spread_pct"]
            if spread_drop > 0.10:  # Spread dropped >0.10%
                print(f"   ⚠️  Spread dropped {spread_drop:.3f}% — cancelling!")
                cancel_order(order_id, cl_ord_id)
                return "CANCELLED_SPREAD"

        # Check order status
        orders = get_orders()
        if orders is None:
            # Venue TIDAK TERBACA: jangan simpulkan apa pun. Versi lama membaca
            # [] (hasil kegagalan baca) sebagai "No open orders = filled" →
            # error jaringan berubah menjadi klaim FILLED di mesin uang nyata.
            print("   ⚠️  Order venue tak terbaca — status BELUM terverifikasi "
                  "(fail-closed, tidak menyimpulkan terisi)", flush=True)
            return "UNVERIFIED_VENUE_UNREADABLE"
        if not orders:
            return "FILLED"

        for o in orders:
            if _order_matches(o, order_id, cl_ord_id):
                status = o.get("status", "")
                filled = _num_order_field(o, "executedQty", "filledQty", "filled", default=0.0)
                orig = _num_order_field(o, "origQty", "quantity", "qty", default=1.0)
                pct = int(filled * 100 / orig) if orig else 0

                if status != last_status:
                    print(f"   [{elapsed:.0f}s] {status} ({pct}%)", flush=True)
                    last_status = status

                if status == "FILLED":
                    return status
                if status == "PARTIALLY_FILLED":
                    # v4.0: Don't cancel immediately — wait for more fills.
                    # Maker orders on thin books often fill in chunks.
                    # Only cancel if we've waited >60s with no progress.
                    if elapsed < 60:
                        continue  # give it more time
                    print(f"   ⚠️  Partial fill ({pct}%) after {elapsed:.0f}s — cancelling remainder")
                    cancel_order(order_id, cl_ord_id)
                    return "PARTIALLY_FILLED_CANCELLED"
                if status in ("CANCELLED", "EXPIRED", "REJECTED"):
                    return status
                break

        time.sleep(GUARDIAN_INTERVAL_S)

# ── v4.2 SWEEP IDLE ASSETS TO USDC ──────────────────────────

# SoDEX symbol mapping for coins in spot balance
COIN_TO_SODEX_SYMBOL = {
    "vPEPE": "PEPE/USDC",
    "vSHIB": "SHIB/USDC",
    "vAVAX": "AVAX/USDC",
    "vXLM": "XLM/USDC",
    "vARB": "ARB/USDC",
}


def _get_orderbook_for_symbol(symbol: str, depth: int = 1):
    """Get orderbook for any SoDEX spot symbol."""
    ok, out = _sodex(["orderbook", "spot", symbol, "--depth", str(depth), "--format", "json"])
    if not ok:
        return None, None
    try:
        data = json.loads(out)
        bids = [(float(b["price"]), float(b["quantity"])) for b in data["bids"]]
        asks = [(float(a["price"]), float(a["quantity"])) for a in data["asks"]]
        return bids, asks
    except (json.JSONDecodeError, KeyError, IndexError):
        return None, None


def _place_order_for_symbol(symbol: str, side: str, price: float, qty: int):
    """Place a limit order on any SoDEX spot symbol. Returns (order_id, cl_ord_id)."""
    blocked = live_order_blocked()
    if blocked:
        print(f"   Error: LIVE_ORDER_BLOCKED_{blocked}")
        return None, None
    coin = _spot_coin_for(symbol)
    _raw_before = (get_balance() or {}).get(coin)
    bal_before = float(_raw_before) if _raw_before is not None else None
    ok, out = _sodex([
        "orders", "place", "spot",
        "--symbol", symbol,
        "--side", side,
        "--price", str(price),
        "--qty", str(qty),
        "--type", "limit",
        "--tif", "gtc",
        "--format", "json",
    ])
    if not ok:
        return None, None
    try:
        data = json.loads(out)
        if isinstance(data, list) and data:
            data = data[0]
        oid = data.get("orderID", 0)
        cl_id = data.get("clOrdID", "")
        if oid == 0 or oid == "0":
            # Sama seperti place_order: orderID=0 wajib DIBUKTIKAN, bukan diasumsikan.
            return _resolve_zero_oid(cl_id, coin, bal_before, float(qty), side)
        return oid, cl_id
    except (json.JSONDecodeError, KeyError):
        return None, None


def sweep_all_to_usdc() -> float:
    """
    Sell ALL non-USDC spot assets at best bid to convert to USDC.
    Returns total USDC value recovered.
    Skips coins not in COIN_TO_SODEX_SYMBOL (untradeable dust).
    """
    bal = get_balance()
    total_recovered = 0.0
    swept = []

    for coin, qty in bal.items():
        if coin == "vUSDC" or qty <= 0:
            continue

        symbol = COIN_TO_SODEX_SYMBOL.get(coin)
        if not symbol:
            continue  # untradeable on SoDEX (WSOSO, vUSSI, etc.)

        # Get current bid for this coin
        bids, _ = _get_orderbook_for_symbol(symbol, depth=1)
        if not bids:
            continue

        bid_price = bids[0][0]
        value_usd = qty * bid_price

        # Primary trading symbol MUST be swept clean to prevent PEPE_BALANCE_MISMATCH.
        # Use $1 floor for primary, standard $10 MIN_NOTIONAL for other coins.
        is_primary = (symbol == SYMBOL)
        if not is_primary and value_usd < MIN_NOTIONAL:
            continue  # non-primary dust: skip
        if is_primary and value_usd < 0.10:
            continue  # truly negligible primary dust
        if is_primary and value_usd < MIN_NOTIONAL:
            print(f"   🧹 {coin}: ${value_usd:.2f} (below ${MIN_NOTIONAL} but primary symbol — sweeping to prevent mismatch)")

        # Sell at best bid (marketable limit — should fill quickly)
        sell_qty = int(qty) if qty >= 1 else int(qty * 0.999)
        if sell_qty <= 0:
            continue

        print(f"   🧹 {coin}: {qty:,.2f} (≈${value_usd:.2f}) → selling at ${bid_price:.8f}")
        oid, cl_id = _place_order_for_symbol(symbol, "sell", bid_price, sell_qty)
        if oid is None:
            print(f"   ⚠️  {coin}: sell placement failed — skipping")
            continue

        # Quick wait for fill (30s max per coin — marketable order)
        start = time.time()
        filled = False
        while time.time() - start < 30:
            orders = get_orders()
            if orders is None:
                # Fail-closed: baca gagal != "sudah terisi". Versi lama menandai
                # `filled = True` di sini → mencetak "✅ filled +$X recovered"
                # tanpa bukti apa pun.
                print(f"   ⚠️  {coin}: venue tak terbaca — sweep dihentikan "
                      f"(fail-closed, tidak mengklaim recovered)")
                break
            still_open = any(
                str(o.get("orderID")) == str(oid) or o.get("clOrdID") == cl_id
                for o in orders
            )
            if not still_open:
                filled = True
                break
            time.sleep(3)

        if filled:
            total_recovered += value_usd
            swept.append(f"{coin}=${value_usd:.2f}")
            print(f"   ✅ {coin}: filled — +${value_usd:.2f} USDC")
        else:
            # Cancel and check partial
            cancel_order(oid, cl_id)
            print(f"   ⚠️  {coin}: not filled in 30s — cancelled")

    if swept:
        print(f"   🧹 Sweep complete: {', '.join(swept)} → +${total_recovered:.2f} USDC recovered")
    else:
        print(f"   🧹 No idle assets to sweep")

    return total_recovered


# ── SINGLE ROUND TRIP ───────────────────────────────────────
def execute_round_trip(capital=10.0, force=False):
    """
    Execute a single T+0 round trip.
    Returns: (pnl_usd, pnl_pct, error_msg)
    """
    print(f"\n{'═'*60}")
    print(f"🔄 RT #{state.rt_count + 1} — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
    print(f"{'═'*60}")

    # ── PRE-FLIGHT CHECKS ──
    if state.emergency_stop:
        return 0, 0, "EMERGENCY_STOP_ACTIVE"

    event_ok, event_reason, event_risk = external_event_gate()
    if not event_ok:
        print(f"   🛑 External event guard: {event_reason}")
        print(f"   🧯 live_gate={event_risk.get('live_gate')} score={event_risk.get('risk_score')}")
        return 0, 0, event_reason

    policy_ok, policy_reason, policy = adaptive_policy_gate()
    if not policy_ok:
        print(f"   🛑 Adaptive policy guard: {policy_reason}")
        print(f"   📊 policy_status={policy.get('status')} route={LIVE_ROUTE}")
        return 0, 0, policy_reason

    # Intel check (v3.1)
    if HAS_INTEL:
        cb_ok, cb_reason = intel.circuit_breaker_ok()
        if not cb_ok:
            print(f"   🛑 Macro CB: {cb_reason}")
            return 0, 0, f"MACRO_CB_{cb_reason}"
        trade_ok, trade_reason = intel.should_trade()
        if not trade_ok:
            print(f"   ⚠️  Intel skip: {trade_reason}")
            return 0, 0, f"INTEL_SKIP_{trade_reason}"
        intel_mult = intel.get_capital_mult()
        intel_spread_min = intel.get_spread_min()
        intel_summary = intel.summary()
        print(f"   🧠 {intel_summary}")
    else:
        intel_mult = 1.0
        intel_spread_min = MIN_SPREAD_PCT

    if not is_prime_time() and not force:
        wait_s = time_to_prime()
        print(f"   ⏸️  Outside prime time — next window in {wait_s/3600:.1f}h")
        return 0, 0, "NOT_PRIME_TIME"

    analysis = analyze_spread()
    if not analysis:
        return 0, 0, "ORDERBOOK_FAILED"

    # Dynamic viability check (v3.1)
    dynamic_viable = analysis["net_pct"] >= MIN_NET_PCT and analysis["spread_pct"] >= intel_spread_min
    if not dynamic_viable:
        print(f"   ❌ Spread {analysis['spread_pct']:.3f}% < min {intel_spread_min:.2f}%")
        return 0, 0, "SPREAD_TOO_THIN"

    # ── SIZE CALC ──
    free_usdc = get_free_usdc()
    effective_capital = capital * intel_mult
    # Cap: never exceed base capital during testing (2x causes larger orders that are harder to fill)
    effective_capital = min(effective_capital, capital * 1.0)  # TODO: remove cap after fill-rate proven at scale
    # ── SPOT Governor Gate (GAP 3+4) ──
    if HAS_GOVERNOR:
        decision = spot_expectancy_gate(
            spread_pct=analysis["spread_pct"],
            cost_pct=COST_PCT,
            free_capital=get_free_usdc(),
            risk=_risk_monitor,
            calibrator=_fill_cal,
            intel_mult=intel_mult,
            intel_spread_min=intel_spread_min,
        )
        if not decision.go:
            print(f"   🛑 Governor veto: {decision.reason}")
            return 0, 0, f"GOVERNOR_{decision.reason}"
        deploy = min(decision.max_capital, capital, max(capital * 0.5, free_usdc * 0.60))  # At least 50% base, max base, capped at 60% free
        print(f"   🎯 Governor: GO | deploy=${deploy:.2f} (suggested=${decision.max_capital:.2f})")
    else:
        deploy = min(effective_capital, free_usdc * 0.60)  # Never >60% of free
    if deploy < MIN_NOTIONAL:
        print(f"   ❌ Deploy ${deploy:.2f} < min ${MIN_NOTIONAL:.0f} (free: ${free_usdc:.2f}, cap: 55%)")
        return 0, 0, "INSUFFICIENT_CAPITAL"

    bid_price = analysis["bid"]
    ask_price = analysis["ask"]
    
    # ── v4.2 PRE-TRADE: Sweep ALL idle assets to USDC ──
    # Converts PEPE, SHIB, AVAX, XLM, ARB — any non-USDC balance — to USDC
    # before trading. This recovers capital from partial fills and prevents
    # PEPE_BALANCE_MISMATCH errors. Idempotent: safe to run every cycle.
    swept_usdc = sweep_all_to_usdc()
    if swept_usdc > 0:
        # Refresh capital after sweep — coins became USDC
        free_usdc = get_free_usdc()
        if HAS_GOVERNOR:
            deploy = min(decision.max_capital, capital, max(capital * 0.5, free_usdc * 0.60))
        else:
            deploy = min(effective_capital, free_usdc * 0.60)
        if deploy < MIN_NOTIONAL:
            return 0, 0, f"INSUFFICIENT_CAPITAL_AFTER_SWEEP_${free_usdc:.2f}"
    
    # ── v4.3: Snapshot pre-trade baseline for total portfolio PnL ──
    pre_trade_bal = get_balance()
    existing_pepe_before = int(pre_trade_bal.get("vPEPE", 0))
    
    # ── v4.0 DEPTH-AWARE SIZING ──
    # Don't order more PEPE than available at the best bid level.
    # This prevents partial fills from oversized orders.
    raw_buy_qty = int(deploy / bid_price)
    bid_depth_usd = analysis.get("bid_depth", 0) or 0
    max_qty_from_depth = int(bid_depth_usd / bid_price) if bid_depth_usd > 0 else raw_buy_qty
    buy_qty = min(raw_buy_qty, max_qty_from_depth)
    
    # Safety floor: must be at least MIN_NOTIONAL
    if buy_qty * bid_price < MIN_NOTIONAL:
        return 0, 0, f"BID_DEPTH_TOO_THIN=${bid_depth_usd:.2f}_need=${deploy:.2f}"
    
    if buy_qty < raw_buy_qty:
        print(f"   📏 Depth-aware: {buy_qty:,} PEPE (capped from {raw_buy_qty:,} — bid depth ${bid_depth_usd:.2f})")

    print(f"   📊 Spread: {analysis['spread_pct']:.4f}% (net: {analysis['net_pct']:+.4f}%)")
    print(f"   💰 Deploy: ${deploy:.2f} | Free: ${free_usdc:.2f}")
    print(f"   🎯 T+0: BUY@{bid_price:.8f} → SELL@{ask_price:.8f}")

    # ── STEP 1: BUY (with retry on partial fill) ──
    print(f"\n   ▸ BUY {buy_qty:,} PEPE @ {bid_price:.8f}...")
    buy_id, buy_cl = place_order("buy", bid_price, buy_qty)
    if buy_id is None:
        return 0, 0, "BUY_PLACE_FAILED"
    print(f"     ID: {buy_id}")
    _buy_start = time.time()

    buy_result = guardian_wait(buy_id, buy_cl, "buy", analysis["spread_pct"])
    buy_fill_time = time.time() - _buy_start
    if HAS_GOVERNOR:
        _fill_cal.record_buy(buy_fill_time)

    # ── v4.0 RETRY: partial fill recovery ──
    if buy_result != "FILLED":
        bal_after_buy = get_balance()
        actual_pepe = int(bal_after_buy.get("vPEPE", 0))
        actual_usd = actual_pepe * bid_price
        
        if actual_usd < MIN_NOTIONAL:
            # Calculate remaining to deploy
            remaining_usd = deploy - actual_usd
            retry_qty = int(remaining_usd / bid_price)
            if retry_qty * bid_price >= MIN_NOTIONAL:
                print(f"   🔄 Partial fill (${actual_usd:.2f}) — retrying ${remaining_usd:.2f} more")
                buy_id2, buy_cl2 = place_order("buy", bid_price, retry_qty)
                if buy_id2 is not None:
                    buy_result2 = guardian_wait(buy_id2, buy_cl2, "buy", analysis["spread_pct"])
                    bal2 = get_balance()
                    actual_pepe = int(bal2.get("vPEPE", 0))
                    actual_usd = actual_pepe * bid_price
                    if actual_usd < MIN_NOTIONAL:
                        return 0, 0, f"BUY_{buy_result}_RETRY_{buy_result2}"
                else:
                    return 0, 0, f"BUY_{buy_result}"
            else:
                return 0, 0, f"BUY_{buy_result}"
        
        print(f"   ⚠️  BUY {buy_result}, but sellable PEPE exists: {actual_pepe:,}")
        buy_qty = actual_pepe

    # ── STEP 2: SELL ──
    # Re-check spread before selling (market may have shifted)
    time.sleep(2)
    analysis2 = analyze_spread()
    if not analysis2 or analysis2["spread_pct"] < intel_spread_min:
        # Sell at whatever ask is available (may be breakeven or small loss)
        if analysis2:
            sell_price = analysis2["ask"]
            print(f"   ⚠️  Spread tightened — selling at best ask {sell_price:.8f}")
        else:
            print(f"   ❌ Cannot get orderbook for sell")
            if emergency_sell_pepe("SELL_ORDERBOOK_FAILED"):
                analysis2 = analysis
                sell_result = "FILLED"
                sell_fill_time = 0.0
                goto_pnl = True
            else:
                return 0, 0, "SELL_ORDERBOOK_FAILED"
    else:
        sell_price = analysis2["ask"]

    goto_pnl = locals().get("goto_pnl", False)

    # Get actual PEPE balance (may have dust from previous RTs)
    if not goto_pnl:
        bal = get_balance()
        pepe_qty = int(bal.get("vPEPE", 0))
        if pepe_qty < buy_qty * 0.99:
            print(f"   ⚠️  PEPE balance {pepe_qty:,} < expected {buy_qty:,}")
            # v4.4: Don't error on mismatch — sell whatever PEPE we have.
            # Emergency sell only works for ≥$10; dust-level PEPE would
            # block the cycle with PEPE_BALANCE_MISMATCH forever.
            if pepe_qty > 0:
                print(f"   💡 Selling available {pepe_qty:,} PEPE instead of aborting")
                # Fall through to normal sell with actual balance
                buy_qty = pepe_qty  # use actual, not expected
            else:
                # Truly no PEPE — something went wrong with the buy
                if emergency_sell_pepe("PEPE_BALANCE_MISMATCH_ZERO"):
                    sell_result = "FILLED"
                    sell_fill_time = 0.0
                    goto_pnl = True
                else:
                    return 0, 0, "PEPE_BALANCE_MISMATCH_ZERO"

    # Include any existing dust in the sell
    if not goto_pnl:
        sell_qty = min(pepe_qty, int(pepe_qty * 0.999))  # leave tiny dust
        sell_notional = sell_qty * sell_price

    if not goto_pnl:
        print(f"\n   ▸ SELL {sell_qty:,} PEPE @ {sell_price:.8f} (≈${sell_notional:.2f})...")
        sell_id, sell_cl = place_order("sell", sell_price, sell_qty)

        if sell_id is None:
            # Order may have been placed (OrderID=0 bug)
            # Check if there's an order
            orders = get_orders()
            if orders is None:
                # Fail-closed (audit 30-Sep-2026): dulu None([]) jatuh ke
                # `emergency_sell_pepe` → MENEMBAK LAGI berdasarkan venue yang
                # tidak terbaca. Jangan pernah menambah order tanpa data.
                print("   ⛔ SELL: status order tak terbaca — tidak menembak lagi "
                      "(fail-closed).", flush=True)
                return 0, 0, "SELL_STATUS_UNVERIFIED"
            if orders:
                sell_id = orders[0].get("orderID", 0)
                sell_cl = orders[0].get("clOrdID", "")
            elif emergency_sell_pepe("SELL_PLACE_FAILED"):
                sell_result = "FILLED"
                sell_fill_time = 0.0
                goto_pnl = True
            else:
                return 0, 0, "SELL_PLACE_FAILED"

    if not goto_pnl:
        print(f"     ID: {sell_id}")
        _sell_start = time.time()  # GAP 5

        sell_result = guardian_wait(sell_id, sell_cl, "sell", analysis2["spread_pct"] if analysis2 else analysis["spread_pct"])
        sell_fill_time = time.time() - _sell_start
    if HAS_GOVERNOR:
        _fill_cal.record_sell(sell_fill_time)

    if sell_result not in ("FILLED", "PARTIALLY_FILLED_CANCELLED"):
        if not emergency_sell_pepe(f"SELL_{sell_result}"):
            return 0, 0, f"SELL_{sell_result}_EXIT_FAILED"

    # ── P&L CALC (v4.3: total portfolio, not USDC-only) ──
    # USDC-only PnL is misleading: buying PEPE reduces USDC but adds PEPE value.
    # Track total portfolio = USDC + PEPE_value to get real profit/loss.
    final_bal = get_balance()
    final_usdc = final_bal.get("vUSDC", 0)
    final_pepe = int(final_bal.get("vPEPE", 0))

    # Use current bid for PEPE valuation (conservative)
    pepe_price_for_pnl = bid_price  # from original analysis
    initial_portfolio = free_usdc + (existing_pepe_before * pepe_price_for_pnl)
    final_portfolio = final_usdc + (final_pepe * pepe_price_for_pnl)

    print(f"\n   ✅ RT #{state.rt_count + 1} COMPLETE")
    print(f"   💵 USDC: {free_usdc:.4f} → {final_usdc:.4f}")
    print(f"   📦 PEPE: {existing_pepe_before:,} → {final_pepe:,}")
    print(f"   💰 Portfolio: ${initial_portfolio:.2f} → ${final_portfolio:.2f}")

    # Real PnL = total portfolio change (accounts for inventory conversion)
    pnl = final_portfolio - initial_portfolio
    pnl_pct = (pnl / deploy) * 100 if deploy > 0 else 0
    buy_notional = buy_qty * bid_price
    executed_volume = buy_notional + float(locals().get("sell_notional", deploy))
    fee_est_usd = deploy * COST_PCT / 100

    # GAP 4: Update risk monitor + persist state
    if HAS_GOVERNOR:
        _risk_monitor.update(pnl, final_usdc, volume_usd=executed_volume, fee_est_usd=fee_est_usd)
        _spot_state.fill_times_buy.append(buy_fill_time)
        _spot_state.fill_times_sell.append(sell_fill_time)
        _spot_state.spread_samples.append(analysis["spread_pct"])
        _spot_state.save()

    return pnl, pnl_pct, None

# ── MAIN ────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="SoDEX AutoFarm v3.1")
    parser.add_argument("--loop", action="store_true", help="Continuous farming")
    parser.add_argument("--dry", action="store_true", help="Scan only, no trade")
    parser.add_argument("--dust", action="store_true", help="Dust check only")
    parser.add_argument("--force", action="store_true", help="Bypass prime-time gate")
    parser.add_argument("--capital", type=float, default=10.0, help="Capital per RT")
    parser.add_argument("--max-rt", type=int, default=0, help="Max RTs (0=unlimited)")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════════╗")
    print("║  SoDEX AutoFarm v3.1 — Intel-Driven T+0            ║")
    print("╚══════════════════════════════════════════════════════╝")
    print(f"   Pair: {SYMBOL} | Base min spread: {MIN_SPREAD_PCT}% | Cost: {COST_PCT}%")
    if HAS_INTEL:
        r = intel.get_regime()
        print(f"   🧠 F&G: {r['fg_value']} ({r['fg_label']}) | Dynamic spread≥{intel.get_spread_min():.2f}% | Capital: {intel.get_capital_mult():.1f}x")
    print(f"   Capital/RT: ${args.capital:.0f} | Prime: {PRIME_START_UTC}-{PRIME_END_UTC} UTC")
    print()

    # Startup cleanup: cancel any stale orders from previous runs
    startup_orders = get_orders()
    if startup_orders is None:
        # Fail-closed: tanpa daftar order lama kita tidak bisa menjamin tidak ada
        # order menggantung. Versi lama melanjutkan siklus → bisa menumpuk order
        # baru di atas order lama (kelas insiden UNI).
        print("   ⛔ Order lama di venue TIDAK TERBACA — siklus dibatalkan "
              "(fail-closed, tidak menembak apa pun).")
        return
    if startup_orders:
        print(f"   🧹 Cleaning {len(startup_orders)} stale orders...")
        for o in startup_orders:
            cancel_order(o.get("orderID", 0), o.get("clOrdID", ""))
            print(f"      Cancelled {o.get('orderID')}")
        time.sleep(2)
    
    # Rescue: check for stuck PEPE from crashed previous session
    bal = get_balance()
    stuck_pepe = bal.get("vPEPE", 0)
    if stuck_pepe > 100000:  # >$0.27 worth, sellable
        bids, _ = get_orderbook(depth=1)
        if bids:
            rescue_px = bids[0][0]
            rescue_qty = int(stuck_pepe * 0.999)
            rescue_notional = rescue_qty * rescue_px
            if rescue_notional >= MIN_NOTIONAL:
                print(f"   🚑 Rescuing {rescue_qty:,} stuck PEPE @ {rescue_px:.8f}...")
                rid, rcl = place_order("sell", rescue_px, rescue_qty)
                if rid is not None:
                    print(f"      SELL placed: ID={rid}")
                    # Quick guardian wait (shorter timeout for rescue)
                    for _ in range(40):  # ~10 min max
                        time.sleep(15)
                        orders = get_orders()
                        if orders is None:
                            # Fail-closed: "tak terbaca" != "rescue selesai".
                            # Versi lama mencetak "✅ Rescue complete!" di sini
                            # padahal posisi mungkin masih terbuka.
                            print("      ⚠️  venue tak terbaca — rescue TIDAK "
                                  "boleh disimpulkan selesai")
                            continue
                        if not orders:
                            print(f"      ✅ Rescue complete!")
                            break
                    else:
                        # Timeout: cancel and try at any price
                        remaining = get_orders()
                        if remaining is None:
                            print("      ⚠️  venue tak terbaca — force-sell DIBATALKAN "
                                  "(fail-closed, tidak menembak tanpa data)")
                        elif remaining:
                            cancel_order(remaining[0].get("orderID", 0), remaining[0].get("clOrdID", ""))
                            # Sell remaining at whatever bid is
                            bids2, _ = get_orderbook(depth=1)
                            if bids2:
                                r2id, r2cl = place_order("sell", bids2[0][0], int(get_balance().get("vPEPE", 0) * 0.999))
                                if r2id is not None:
                                    print(f"      Force sell: ID={r2id}")
                else:
                    print(f"   ⚠️  Stuck PEPE ${rescue_notional:.2f} < min $10 — will absorb in next RT")
    print()

    if args.dust:
        combine_dust()
        return

    if args.dry:
        if HAS_INTEL:
            print(f"   🧠 {intel.summary()}")
            print()
        analysis = analyze_spread()
        if analysis:
            print(f"   Bid: {analysis['bid']:.8f} | Ask: {analysis['ask']:.8f}")
            print(f"   Spread: {analysis['spread_pct']:.4f}% | Net: {analysis['net_pct']:+.4f}%")
            print(f"   Viable: {'✅ YES' if analysis['viable'] else '❌ NO'}")
            print(f"   Prime time: {'✅ YES' if is_prime_time() else '❌ NO'}")
        combine_dust()
        return

    # ── EXECUTION LOOP ──
    lock_fh = acquire_process_lock()
    if lock_fh is None:
        print("   ❌ Error: AUTOFARM_ALREADY_RUNNING")
        return

    state.start_balance = get_free_usdc()

    try:
        while True:
            if state.emergency_stop:
                print("\n🛑 EMERGENCY STOP — 3 consecutive losses")
                break

            if not is_prime_time() and not args.force:
                wait_s = time_to_prime()
                print(f"\n⏸️  Outside prime time. Next window in {wait_s/3600:.1f}h. Waiting...")
                # Wait but check every 5min
                while wait_s > 0:
                    snooze = min(wait_s, 300)
                    time.sleep(snooze)
                    wait_s -= snooze
                    if is_prime_time():
                        break
                continue

            # Combine dust before RT
            combine_dust()

            pnl, pnl_pct, error = execute_round_trip(args.capital, args.force)

            state.rt_count += 1

            if error:
                print(f"   ❌ Error: {error}")
                # Only count actual trading losses, not placement failures
                if error in ("BUY_PLACE_FAILED", "SELL_PLACE_FAILED", "BUY_TIMEOUT", "BUY_CANCELLED_SPREAD", 
                             "NOT_PRIME_TIME", "SPREAD_TOO_THIN", "INSUFFICIENT_CAPITAL", "ORDERBOOK_FAILED"):
                    pass  # Non-critical, don't count as loss
                elif "BUY_" in error or "SELL_" in error:
                    state.consecutive_losses += 1
                    print(f"   ⚠️  Consecutive failures: {state.consecutive_losses}")
                    if state.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                        state.emergency_stop = True
                # Non-critical or critical — if not looping, stop
                if not args.loop:
                    break
                time.sleep(30)
                continue
            else:
                state.consecutive_losses = 0
                state.total_pnl += pnl
                print(f"   📈 P&L: ${pnl:+.4f} ({pnl_pct:+.2f}%) | Total: ${state.total_pnl:+.4f}")

            if args.max_rt > 0 and state.rt_count >= args.max_rt:
                print(f"\n✅ {args.max_rt} RTs completed.")
                break

            if not args.loop:
                break

            # Brief pause between RTs
            time.sleep(5)

    except KeyboardInterrupt:
        print("\n\n⏹️  Interrupted by user")

    # ── FINAL REPORT ──
    final_balance = get_free_usdc()
    print(f"\n{'═'*60}")
    print(f"📊 SESSION REPORT")
    print(f"{'═'*60}")
    print(f"   RTs: {state.rt_count}")
    print(f"   Total P&L: ${state.total_pnl:+.4f}")
    print(f"   Balance: ${state.start_balance:.4f} → ${final_balance:.4f}")
    print(f"   ROI: {(final_balance - state.start_balance) / state.start_balance * 100:+.2f}%")
    combine_dust()

if __name__ == "__main__":
    main()
