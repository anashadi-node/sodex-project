#!/usr/bin/env python3
"""S1 — Uji forward SOL (protokol DIBEKUKAN 2026-10-05).

Implementasi persis dari docs/sodex/S1_PROTOKOL_SOL_FORWARD_2026-10-05.md:
  - sumber lane DIBEKUKAN (5 berkas), filter sym^SOL
  - grid 48 jam non-overlap, anchor tetap 2026-10-02T00:00:00Z
  - p_worst = maks(p_window, p_day_cluster, p_sign); semuanya harus < 0,05
  - 3/3 segmen positif; sensitivitas 2x biaya > 0
  - ambang: PASS / FAIL / INCONCLUSIVE / INCONCLUSIVE-STALLED

READ-ONLY. Tidak menulis ke lane mana pun; hanya laporan.
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = [
    "data/paper_test_realwide.jsonl",
    "data/paper_test_realwide_atrvol.jsonl",
    "data/paper_test_realwide_atrvolopen.jsonl",
    "data/paper_test_donchian.jsonl",
    "data/paper_test_pasar_anantara_trade.jsonl",
]
ANCHOR = datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc).timestamp()  # DIBEKUKAN
WINDOW_H = 48
MIN_WINDOWS = 30            # DIBEKUKAN
P_MAX = 0.05                # DIBEKUKAN
FEE_2X = 2 * 0.00024        # 1x RT maker ekstra (MAKER_FEE=2,4 bps) = 4,8 bps
N_SIM = 5000
SEED = 20261005

# BM-1 stall: tidak ada trade SOL baru selama 14 hari
STALL_DAYS = 14


def load_sol() -> list[dict]:
    out = []
    for rel in SRC:
        p = ROOT / rel
        if not p.exists():
            continue
        try:
            for line in p.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sym = str(r.get("sym") or r.get("pair") or "").upper()
                if not sym.startswith("SOL"):
                    continue
                t = r.get("exit_ts")
                if t is None or float(t) < ANCHOR:
                    continue
                pnl = r.get("pnl_pct")
                if pnl is None:
                    continue
                out.append({"src": rel, "t": float(t), "ret": float(pnl),
                            "hold_h": r.get("hold_h")})
        except OSError:
            continue
    return sorted(out, key=lambda x: x["t"])


def grid_windows(trades: list[dict]) -> tuple[list[float], int]:
    """Jendela 48j anchor tetap; jendela tanpa trade DIBUANG (dilaporkan)."""
    buckets: dict[int, list[float]] = {}
    total_slots = 0
    for tr in trades:
        k = int((tr["t"] - ANCHOR) // (WINDOW_H * 3600))
        buckets.setdefault(k, []).append(tr["ret"])
    max_k = max(buckets) if buckets else -1
    total_slots = max(max_k + 1, 0)
    vals = [st.mean(buckets[k]) for k in sorted(buckets)]
    return vals, total_slots


def signflip_p(vals: list[float]) -> float:
    n = len(vals)
    if n < 5:
        return float("nan")
    obs = st.mean(vals)
    rng = random.Random(SEED)
    hit = 0
    for _ in range(N_SIM):
        m = sum(v if rng.getrandbits(1) else -v for v in vals) / n
        if abs(m) >= abs(obs):
            hit += 1
    return (hit + 1) / (N_SIM + 1)


def day_cluster_p(trades: list[dict]) -> float:
    """Sign-flip di level CLUSTER HARI (metode census D14, BUG#1 fix)."""
    byday: dict[str, list[float]] = {}
    for tr in trades:
        d = datetime.fromtimestamp(tr["t"], tz=timezone.utc).strftime("%Y-%m-%d")
        byday.setdefault(d, []).append(tr["ret"])
    gs = [(sum(g), len(g)) for g in byday.values()]
    if len(gs) < 5:
        return float("nan")
    obs = st.mean([tr["ret"] for tr in trades])
    rng = random.Random(SEED + 1)
    ng = len(gs)
    hit = 0
    for _ in range(N_SIM):
        ssum = 0.0
        ncnt = 0.0
        for _g in range(ng):
            a, b = gs[rng.randrange(ng)]
            if rng.getrandbits(1):
                a = -a
            ssum += a
            ncnt += b
        if ncnt and abs(ssum / ncnt) >= abs(obs):
            hit += 1
    return (hit + 1) / (N_SIM + 1)


def sign_test_p(vals: list[float]) -> float:
    """Binomial satu sisi: H0 proporsi positif = 0,5."""
    n = len(vals)
    if n < 5:
        return float("nan")
    k = sum(1 for v in vals if v > 0)
    # P(X >= k) dengan X~Bin(n, 0,5)
    tail = sum(math.comb(n, i) for i in range(k, n + 1)) / (2 ** n)
    return tail


def segments(vals: list[float], k: int = 3) -> dict:
    if len(vals) < k * 3:
        return {"assessable": 0, "positive": 0, "means": []}
    size = len(vals) // k
    parts = [vals[i * size:(i + 1) * size] if i < k - 1 else vals[i * size:] for i in range(k)]
    means = [st.mean(p) for p in parts]
    return {"assessable": k, "positive": sum(1 for m in means if m > 0), "means": means}


def control_series(vals: list[float]) -> float:
    """Kontrol negatif: deret acak mean & sd sama -> p tak berarti (bukan bukti)."""
    if len(vals) < 5:
        return float("nan")
    m, s = st.mean(vals), st.pstdev(vals)
    rng = random.Random(SEED + 7)
    fake = [rng.gauss(m, s) for _ in vals]
    return signflip_p(fake)


def main() -> int:
    trades = load_sol()
    vals, slots = grid_windows(trades)
    net2x = [v - FEE_2X for v in vals]

    p_win = signflip_p(vals)
    p_day = day_cluster_p(trades)
    p_sign = sign_test_p(vals)
    ps = [p for p in (p_win, p_day, p_sign) if p == p]
    p_worst = max(ps) if ps else float("nan")

    seg = segments(vals)
    mean2x = st.mean(net2x) if net2x else float("nan")
    n = len(vals)

    # ---- putusan (DIBEKUKAN) ----
    last_t = max((tr["t"] for tr in trades), default=0.0)
    days_idle = (datetime.now(timezone.utc).timestamp() - last_t) / 86400 if last_t else 999
    if days_idle >= STALL_DAYS:
        verdict = "INCONCLUSIVE-STALLED"
    elif n < MIN_WINDOWS:
        verdict = "INCONCLUSIVE"
    elif p_worst == p_worst and p_worst < P_MAX and seg["positive"] == seg["assessable"] \
            and seg["assessable"] > 0 and mean2x > 0:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    out = {
        "protocol": "S1_PROTOKOL_SOL_FORWARD_2026-10-05",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "n_windows": n,
        "n_slots_elapsed": slots,
        "fill_ratio": (n / slots) if slots else 0.0,
        "n_trades": len(trades),
        "mean_window_pct": st.mean(vals) * 100 if vals else float("nan"),
        "sd_window_pct": st.pstdev(vals) * 100 if len(vals) > 1 else float("nan"),
        "p_window": p_win, "p_day_cluster": p_day, "p_sign": p_sign, "p_worst": p_worst,
        "segments_positive": seg["positive"], "segments_assessable": seg["assessable"],
        "segment_means_pct": [m * 100 for m in seg["means"]],
        "mean_window_2x_cost_pct": mean2x * 100 if net2x else float("nan"),
        "control_random_p": control_series(vals),
        "days_since_last_sol_trade": days_idle,
        "thresholds": {"n_windows_min": MIN_WINDOWS, "p_max": P_MAX, "segments": "3/3",
                       "cost_2x_positive": True, "stall_days": STALL_DAYS},
        "anchor": "2026-10-02T00:00:00Z",
        "sources_frozen": SRC,
    }

    rep = ROOT / "reports/sodex"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "S1_sol_forward_latest.json").write_text(json.dumps(out, indent=1))
    with (rep / "S1_sol_forward_registry.jsonl").open("a") as fh:
        fh.write(json.dumps(out) + "\n")

    md = [
        "# S1 — Uji Forward SOL (status)",
        "",
        f"**Putusan: `{verdict}`**  ·  dibuat {out['generated_utc'][:19]}Z",
        "",
        f"- Jendela 48j berisi trade: **{n}** / ambang {MIN_WINDOWS} "
        f"(slot terlewat: {slots}, rasio isi {out['fill_ratio']*100:.0f}%)",
        f"- n trade SOL forward: {len(trades)} · terakhir {days_idle:.1f} hari lalu",
        f"- Mean jendela: {out['mean_window_pct']:+.4f}% (sd {out['sd_window_pct']:.4f}%)",
        f"- p_worst: {p_worst:.4f} (p_win {p_win:.4f} · p_day {p_day:.4f} · p_sign {p_sign:.4f})",
        f"- Segmen: {seg['positive']}/{seg['assessable']} "
        f"(means: {', '.join(f'{m*100:+.3f}%' for m in seg['means']) or '-'})",
        f"- 2× biaya: {out['mean_window_2x_cost_pct']:+.4f}%",
        f"- Kontrol acak p: {out['control_random_p']:.4f}",
        "",
        "Ambang dibekukan di `docs/sodex/S1_PROTOKOL_SOL_FORWARD_2026-10-05.md`; "
        "tidak diubah setelah hasil.",
        "",
    ]
    (rep / "S1_sol_forward_latest.md").write_text("\n".join(md))

    print(f"S1 verdict={verdict} n_windows={n}/{MIN_WINDOWS} n_trades={len(trades)} "
          f"p_worst={p_worst:.4f} seg={seg['positive']}/{seg['assessable']} "
          f"mean2x={out['mean_window_2x_cost_pct']:+.3f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
