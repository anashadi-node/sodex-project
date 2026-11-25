#!/usr/bin/env python3
"""Eksekutor DUA LAPIS (spot 1× + perp ekstra) — DRY-RUN HANYA. Tidak ada order, tidak ada kredensial, tidak ada jaringan.

  hybrid_exec.py --plan <fwd_dir>    # hitung intent order dari ledger terakhir (tanpa menulis state)
  hybrid_exec.py --apply <fwd_dir>   # tulis fill paper ke <fwd_dir>/paper_exec_hybrid.jsonl

Mengapa aman: skrip ini menolak berjalan bila ada penanda live (LIVE_ARMED / PREGAIN_LIVE / SODEX_LIVE / HL_API_SECRET).
Menaikkannya ke live = pekerjaan terpisah dengan 3 kunci live + GO eksplisit pengguna, bukan flag di file ini.
"""
from __future__ import annotations
import json, os, sys, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))

PLAN = {"cells": {"B2": 1.5, "A": 2.0}, "primary": "B2", "min_notional_usdc": 10.0,
        "cost_spot": 0.00065, "cost_perp": 0.00045, "equity_usdc": 243.02}          # notional paper; bisa ditimpa --equity
LIVE_FLAGS = ("LIVE_ARMED", "PREGAIN_LIVE", "SODEX_LIVE", "HL_API_SECRET", "BINANCE_API_SECRET")


class LiveRefused(RuntimeError):
    pass


def guard_live(environ=None):
    env = os.environ if environ is None else environ
    hot = [k for k in LIVE_FLAGS if str(env.get(k, "")).strip() not in ("", "0", "false", "False")]
    if hot:
        raise LiveRefused(f"LIVE ditolak: penanda aktif {hot}. PRAREG-36 hanya dry_run.")


def _read(p):
    return [json.loads(x) for x in open(p) if x.strip()] if os.path.exists(p) else []


def latest_target(fdir: str, arm: str = "B2") -> dict:
    recs = [r for r in _read(os.path.join(fdir, "ledger.jsonl")) if r.get("kind") == "rec"]
    if not recs:
        raise SystemExit("ledger kosong: jalankan hybrid36.py record dulu")
    return recs[-1]


def state_path(fdir): return os.path.join(fdir, "exec_hybrid_state.json")


def load_state(fdir: str) -> dict:
    p = state_path(fdir)
    return json.load(open(p)) if os.path.exists(p) else {"spot": {}, "perp": {}, "equity_usdc": PLAN["equity_usdc"] or 1000.0}


def intents(rec: dict, state: dict, arm: str = "B2") -> list:
    """Dua lapisan terpisah: spot = target; perp = target*(L-1). Notional = berat × ekuitas."""
    L = PLAN["cells"][arm]; eq = float(state.get("equity_usdc") or 1000.0); out = []
    for k, w in rec["targets"][arm].items():
        for layer, mult, fee in (("spot", 1.0, PLAN["cost_spot"]), ("perp", L - 1.0, PLAN["cost_perp"])):
            tgt = float(w) * mult; cur = float(state.get(layer, {}).get(k, 0.0)); d = tgt - cur
            notional = abs(d) * eq
            if abs(d) < 1e-6 or notional < PLAN["min_notional_usdc"]:
                continue
            out.append({"layer": layer, "asset": k, "from_w": round(cur, 6), "to_w": round(tgt, 6),
                        "delta_usdc": round(d * eq, 2), "notional_usdc": round(notional, 2),
                        "fee_usdc": round(notional * fee, 3), "dry_run": True})
    return out


def apply(fdir: str, rec: dict, state: dict, orders: list) -> dict:
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    for o in orders:
        state.setdefault(o["layer"], {})[o["asset"]] = o["to_w"]
        with open(os.path.join(fdir, "paper_exec_hybrid.jsonl"), "a") as f:
            f.write(json.dumps({**o, "asof": rec["asof"], "utc": stamp, "mode": "PAPER_ONLY"}, sort_keys=True) + "\n")
    json.dump(state, open(state_path(fdir), "w"), indent=1, sort_keys=True)
    return state


def main(argv):
    guard_live()
    if len(argv) < 3 or argv[1] not in ("--plan", "--apply"):
        raise SystemExit("pakai: hybrid_exec.py --plan|--apply <fwd_dir> [arm] [--equity N]")
    fdir, arm = argv[2], (argv[3] if len(argv) > 3 and not argv[3].startswith("--") else PLAN["primary"])
    if "--equity" in argv:
        PLAN["equity_usdc"] = float(argv[argv.index("--equity") + 1])
    rec = latest_target(fdir, arm); st = load_state(fdir); os_ = intents(rec, st, arm)
    if argv[1] == "--plan":
        print(json.dumps({"asof": rec["asof"], "arm": arm, "L": PLAN["cells"][arm], "mode": "DRY_RUN",
                          "n_order": len(os_), "orders": os_, "total_fee_usdc": round(sum(o["fee_usdc"] for o in os_), 3)}, indent=2))
    else:
        apply(fdir, rec, st, os_); print(json.dumps({"asof": rec["asof"], "arm": arm, "applied": len(os_), "mode": "PAPER_ONLY"}, indent=2))


if __name__ == "__main__":
    try:
        main(sys.argv)
    except LiveRefused as e:
        print(json.dumps({"status": "REFUSED", "pesan": str(e)})); sys.exit(3)
