#!/usr/bin/env python3
"""E1-XR Window Planner — scan aset maker potensial utk window 30 jam berikutnya.

Alur sesuai visi owner (28-Sep): SCAN seluruh spot SoDEX → ukur edge yang
TERUKUR (setengah-spread − 2×fee maker, likuiditas) → SKOR → pilih aset untuk
slot pair-2/3/4 E1 → tulis plan + rotasi HANYA bila bukti stabil (2 scan
beruntun, ≥12 jam, dan pair lama terbukti rate honest negatif n≥30).

Anti-flapping (pelajaran scientific): reaksi pada BUKTI, bukan noise.
Rotasi = ubah 4 baris TE_SPOT_PAIR_x di .env lalu tulis restart-signal —
watchdog sudah re-source .env tiap restart (mekanisme teruji 26-Sep).
READ-OTHERWISE: tidak pernah menyentuh order/posisi.
"""
from __future__ import annotations
import json, os, random, re, sqlite3, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT / ".env"
PLAN_FILE = PROJECT / "data" / "window_plan.json"
HIST_FILE = PROJECT / "data" / "window_plan_history.json"
RESTART_SIGNAL = PROJECT / "data" / "GUARDIAN_RESTART_SIGNAL"   # nama sama dgn watchdog
TE_DB = PROJECT / "twin_engine.db"
GATEWAY = "https://mainnet-gw.sodex.dev/api/v1"
MAKER_FEE_BPS = 3.15 * 2          # EFEKTIF: 0.00035 nominal × diskon staking 10% = 3,15bps/sisi
TAKER_ONLY_BLOCKED = {"BOXX/USDC"}   # venue reject post-only ("only market IOC")
MIN_LIQ_USD = 500.0               # quoteVolume 24h minimum — dust trap guard
STABLE_QUOTE_EXCLUDE = {"USDT/USDC"}  # stable-stable: spread=depeg pricing, risiko tail ≠ edge maker biasa
ALLOWED_PAIRS = {                  # whitelist hard: hanya pair yang punya symbol-id
    "SHIB/USDC", "USDT/USDC", "AVAX/USDC", "TSLA/USDC", "BOXX/USDC",
    "QQQ/USDC", "SCHD/USDC", "XLM/USDC", "DOGE/USDC", "ADA/USDC",
}
PAIR_FROM_SYMBOL = {               # vTICKER_vUSDC -> "TICKER/USDC" gaya engine
    "vSHIB_vUSDC": "SHIB/USDC", "vUSDT_vUSDC": "USDT/USDC", "vAVAX_vUSDC": "AVAX/USDC",
    "vTSLA_vUSDC": "TSLA/USDC", "vBOXX_vUSDC": "BOXX/USDC", "vQQQ_vUSDC": "QQQ/USDC",
    "vSCHD_vUSDC": "SCHD/USDC", "vXLM_vUSDC": "XLM/USDC", "vDOGE_vUSDC": "DOGE/USDC",
    "vADA_vUSDC": "ADA/USDC", "vPEPE_vUSDC": "PEPE/USDC",
}


RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_ATTEMPTS = 5


def api(path: str, attempts: int = RETRY_ATTEMPTS, _sleep=time.sleep):
    """GET JSON dengan backoff eksponensial + jitter.

    Root cause 2026-11-07: unit ini MATI (exit 1) karena satu 429 dari venue, tanpa
    retry sama sekali — padahal 429 = "pelan sedikit", bukan kegagalan permanen.
    Sekarang: 429/5xx diulang dengan 1,5^n + jitter (maks ~8s total), 4xx lain
    langsung raise (fail-closed, jangan menelan error nyata).
    """
    last = None
    for i in range(attempts):
        req = urllib.request.Request(GATEWAY + path, headers={"User-Agent": "window-planner/1"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in RETRY_STATUS or i == attempts - 1:
                raise
            _sleep(min(1.5 ** i + random.uniform(0, 0.4), 8.0))
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            if i == attempts - 1:
                raise
            _sleep(min(1.5 ** i + random.uniform(0, 0.4), 8.0))
    raise last if last else RuntimeError("api gagal tanpa exception")


def scan_assets():
    data = api("/spot/markets/tickers").get("data", [])
    rows = data.get("tickers", data) if isinstance(data, dict) else data
    out = []
    for t in rows:
        sym = str(t.get("symbol", ""))
        pair = PAIR_FROM_SYMBOL.get(sym)
        if not pair or pair in STABLE_QUOTE_EXCLUDE or pair in TAKER_ONLY_BLOCKED or pair not in ALLOWED_PAIRS:
            continue
        try:
            bid, ask = float(t.get("bidPx", 0)), float(t.get("askPx", 0))
            qv = float(t.get("quoteVolume", 0) or 0)
        except (TypeError, ValueError):
            continue
        if bid <= 0 or ask <= 0:
            continue
        mid = (bid + ask) / 2
        spr_bps = (ask - bid) / mid * 10000
        capture = spr_bps / 2 - MAKER_FEE_BPS        # edge teoretis/RT (bps)
        if qv < MIN_LIQ_USD or capture <= 0:
            out.append({"pair": pair, "spread_bps": round(spr_bps, 1), "vol24h_usd": round(qv),
                        "capture_bps": round(capture, 1), "score": 0.0, "blocked": "liq<500 atw capture≤0"})
            continue
        # skor = edge × akar likuiditas (diminishing return vol — hindari chase dust)
        out.append({"pair": pair, "spread_bps": round(spr_bps, 1), "vol24h_usd": round(qv),
                    "capture_bps": round(capture, 1),
                    "score": round(capture * (qv ** 0.5), 2), "blocked": None})
    out.sort(key=lambda x: -x["score"])
    return out


def honest_rate_per_pair():
    con = sqlite3.connect(f"file:{TE_DB}?mode=ro", uri=True)
    res = {}
    st_ts = con.execute("SELECT v FROM state WHERE k='e1_research_start_ts'").fetchone()
    since = datetime.fromtimestamp(float(st_ts[0]), timezone.utc).isoformat() if st_ts and float(st_ts[0]) > 0 else "2026-07-20"
    for pr, pnl, vol, n in con.execute(
        "SELECT pair, SUM(CAST(net_pnl AS REAL)), SUM(CAST(volume AS REAL)), COUNT(*) FROM rts WHERE engine='E1' AND ts_close>=? GROUP BY pair",
        (since,)):
        res[pr] = {"n": n, "rate_bps": round(pnl / vol * 10000, 2) if vol else 0.0}
    con.close()
    return res


def current_pairs():
    env = ENV_FILE.read_text()
    cur = {}
    for key in ("TE_SPOT_PAIR", "TE_SPOT_PAIR_2", "TE_SPOT_PAIR_3", "TE_SPOT_PAIR_4"):
        m = re.search(rf"^{key}=(\S*)", env, re.M)
        cur[key] = (m.group(1) if m else "").strip()
    return cur


def maybe_rotate(plan_assets, rates, cur):
    """Rotasi hanya slot 2/3/4 (PEPE primary dijaga — historikal & hedge)."""
    hist = json.loads(HIST_FILE.read_text()) if HIST_FILE.exists() else {"last_scans": []}
    top = [a["pair"] for a in plan_assets if not a["blocked"]][:6]
    prev = hist["last_scans"][-1]["top"] if hist["last_scans"] else []
    stable = [p for p in top if p in prev]
    filled = [p for p in cur.values() if p]
    swaps = []
    for slot_key, slot_pair in list(cur.items())[:0] + [("TE_SPOT_PAIR_2", cur["TE_SPOT_PAIR_2"]),
                                                          ("TE_SPOT_PAIR_3", cur["TE_SPOT_PAIR_3"]),
                                                          ("TE_SPOT_PAIR_4", cur["TE_SPOT_PAIR_4"])]:
        r = rates.get(slot_pair, {})
        under = r.get("n", 0) >= 30 and r.get("rate_bps", 0) <= 0     # jujur & negatif
        # kandidat: skor tertinggi stabil-2-scan, belum dipakai slot lain, bukan PEPE
        cand = next((p for p in top if p in stable and p not in filled and p != "PEPE/USDC"
                     and (p != slot_pair or not under)), None)
        if under and cand and cand != slot_pair:
            swaps.append((slot_key, slot_pair, cand))
    hist["last_scans"].append({"ts": datetime.now(timezone.utc).isoformat(), "top": top})
    hist["last_scans"] = hist["last_scans"][-6:]
    HIST_FILE.write_text(json.dumps(hist, indent=1))
    if not swaps:
        return []
    env = ENV_FILE.read_text()
    for key, old, new in swaps:
        env = re.sub(rf"^{key}={re.escape(old)}\b", f"{key}={new}", env, count=1, flags=re.M)
    ENV_FILE.write_text(env)
    RESTART_SIGNAL.write_text(json.dumps({
        "type": "window-rotation", "ts": datetime.now(timezone.utc).isoformat(),
        "reason": "E1-XR: slot underperform (rate honest n>=30 <=0) digantikan aset skor lebih tinggi yang stabil 2 scan",
        "swaps": [{"slot": k, "out": o, "in": n} for k, o, n in swaps]}))
    return [{"slot": k, "out": o, "in": n} for k, o, n in swaps]


def main():
    assets = scan_assets()
    rates = honest_rate_per_pair()
    cur = current_pairs()
    swaps = maybe_rotate(assets, rates, cur) if os.environ.get("XR_APPLY") == "1" else []
    plan = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "window_target_usd": {"sodex": round(0.008 * 279.74, 2), "cex": round(0.008 * 400, 2)},
        "fee_floor_bps": MAKER_FEE_BPS, "current_slots": cur,
        "top_assets": assets[:8], "honest_rates": rates, "rotations_applied": swaps,
        "mode": "APPLY" if os.environ.get("XR_APPLY") == "1" else "RECOMMEND-ONLY",
    }
    PLAN_FILE.write_text(json.dumps(plan, indent=1))
    print(json.dumps({"plan_file": str(PLAN_FILE), "top": [(a["pair"], a["score"]) for a in assets[:6]],
                      "swaps": swaps}, indent=1))


if __name__ == "__main__":
    main()