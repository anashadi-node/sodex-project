#!/usr/bin/env python3
"""sodex_capital_plan.py — Rencana target & sizing SoDEX, parameter modal.

Read-only. Tidak menyentuh state trading. Menjawab satu pertanyaan:
"dengan modal C, target apa yang bisa dipertanggungjawabkan, dan edge per trade
berapa yang wajib dibuktikan?"

Pakai:
    python3 scripts/sodex_capital_plan.py --capital 1000
    python3 scripts/sodex_capital_plan.py --capital 2000 --json
"""
import argparse, json, math, random

TIERS = {
    "T1_north_star": {
        "per_window": 0.008,
        "label": "North Star (harga mati, tidak diubah)",
        "note": "0.8% per 30 jam = 234%/tahun. Hanya sah bila Sharpe tahunan >= 5.8.",
    },
    "T2_operational": {
        "per_window": 0.0025,
        "label": "Target operasional (jalur A)",
        "note": "0.25% per 30 jam = 73%/tahun. Butuh Sharpe 1.8 @ vol 40%/thn.",
    },
    "T3_floor": {
        "per_window": 0.0010,
        "label": "Lantai minimum (jalur A, fase awal)",
        "note": "0.10% per 30 jam = 29%/tahun. Sharpe 1.46 @ vol 20%/thn.",
    },
}

CONCURRENT_PER_333 = 333.0  # 1 posisi per ~$333 modal, maksimum 10
MAX_POS = 10
LEVERAGE_DEFAULT = 2.0
MIN_NOTIONAL = 100.0


def positions(capital):
    n = int(round(capital / CONCURRENT_PER_333))
    return max(1, min(MAX_POS, n))


def required_edge_bps(target, leverage, hold_hours):
    """Edge NETTO per trade yang wajib ada agar target tercapai."""
    turns = 30.0 / hold_hours
    return target * 1e4 / (leverage * turns)


def n_required(sigma_bps, edge_bps, power=0.8):
    """Jumlah trade untuk 80% power mendeteksi edge tsb (alpha 5%, 2-sided)."""
    if edge_bps <= 0:
        return None
    return int(math.ceil((2.8 * sigma_bps / edge_bps) ** 2))


def proof_cost_pct(n, cost_bps, leverage, n_pos):
    """Biaya fee untuk menjalankan eksperimen, sebagai % modal."""
    return n * (cost_bps / 1e4) * leverage / n_pos


def dd_prob(target, annual_vol, nsim=4000, windows=292, seed=7):
    rng = random.Random(seed)
    mu = target
    sd = annual_vol / math.sqrt(windows)
    over = 0
    for _ in range(nsim):
        eq = peak = 1.0
        worst = 0.0
        for _ in range(windows):
            eq *= 1 + rng.gauss(mu, sd)
            peak = max(peak, eq)
            worst = min(worst, eq / peak - 1)
        if worst < -0.5:
            over += 1
    return over / nsim


def build(capital, leverage=LEVERAGE_DEFAULT):
    n_pos = positions(capital)
    notional = max(MIN_NOTIONAL, leverage * capital / n_pos)
    out = {
        "capital_usd": capital,
        "leverage": leverage,
        "concurrent_positions": n_pos,
        "notional_per_position_usd": round(notional, 2),
        "tiers": {},
        "required_net_edge_bps": {},
        "proof_cost": {},
    }
    for key, t in TIERS.items():
        pct = t["per_window"]
        out["tiers"][key] = {
            "label": t["label"],
            "pct_per_30h": pct,
            "usd_per_30h": round(pct * capital, 2),
            "annual_simple_pct": round(pct * 292 * 100, 1),
            "required_sharpe_ann": {
                f"vol_{int(v*100)}pct": round(pct * 292 / v, 2)
                for v in (0.20, 0.30, 0.40, 0.60)
            },
            "p_dd50_1yr": {
                f"vol_{int(v*100)}pct": round(dd_prob(pct, v), 3)
                for v in (0.20, 0.30, 0.40, 0.60)
            },
        }
        out["required_net_edge_bps"][key] = {
            f"hold_{h}h": round(required_edge_bps(pct, leverage, h), 1)
            for h in (1, 6, 24, 72)
        }
        for h in (1, 6, 24, 72):
            e = required_edge_bps(pct, leverage, h)
            sigma = {1: 150, 6: 400, 24: 700, 72: 1200}[h]
            n = n_required(sigma, e)
            fee = proof_cost_pct(n, 5.9, leverage, n_pos) if n else None
            out["proof_cost"][f"{key}_hold{h}h"] = {
                "n_trades_needed": n,
                "fee_cost_pct_of_capital": round(fee, 3) if fee is not None else None,
                "feasible": bool(fee is not None and fee <= 0.5),
            }
    out["gate"] = {
        "live_allowed": False,
        "reason": "Tidak ada edge netto yang lolos uji (R01 cascade FAIL; bounce 1h = artefak spread).",
        "unlock_condition": "Satu hipotesis lulus: net >= T2 required edge, OOS t>=2.0, CI95 hari-blok > 0.",
    }
    return out


def render(r):
    L = []
    L.append(f"MODAL ${r['capital_usd']:,.0f} | leverage {r['leverage']}x | {r['concurrent_positions']} posisi | notional/posisi ${r['notional_per_position_usd']:,.0f}")
    L.append("")
    L.append(f"{'tier':<16}{'%/30h':>7}{'$/30h':>10}{'%/thn':>8}   Sharpe@vol20/30/40/60   P(DD50)")
    for k, t in r["tiers"].items():
        sh = "/".join(str(v) for v in t["required_sharpe_ann"].values())
        dd = "/".join(f"{v*100:.0f}%" for v in t["p_dd50_1yr"].values())
        L.append(f"{k:<16}{t['pct_per_30h']*100:6.2f}%{t['usd_per_30h']:10.2f}{t['annual_simple_pct']:8.1f}   {sh:<24} {dd}")
    L.append("")
    L.append("Edge NETTO per trade yang wajib ada (bps):")
    for k, d in r["required_net_edge_bps"].items():
        L.append(f"  {k:<16}" + "  ".join(f"{h}={v:5.1f}" for h, v in d.items()))
    L.append("")
    L.append("Biaya fee untuk membuktikan edge (n trade, % modal):")
    for k, d in r["proof_cost"].items():
        if d["n_trades_needed"]:
            flag = "LAYAK" if d.get("feasible") else "TIDAK LAYAK (>50% modal)"
            L.append(f"  {k:<24} n={d['n_trades_needed']:5d}  fee={d['fee_cost_pct_of_capital']*100:9.1f}% modal  {flag}")
    feasible = [k for k, d in r["proof_cost"].items() if d.get("feasible")]
    L.append("")
    L.append("KONFIGURASI YANG BISA DIBUKTIKAN DENGAN MODAL INI: " + (", ".join(feasible) if feasible else "TIDAK ADA"))
    L.append("")
    L.append(f"GERBANG LIVE: {'BOLEH' if r['gate']['live_allowed'] else 'DITUTUP'} — {r['gate']['reason']}")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, required=True)
    ap.add_argument("--leverage", type=float, default=LEVERAGE_DEFAULT)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = build(a.capital, a.leverage)
    print(json.dumps(r, indent=2) if a.json else render(r))
