#!/usr/bin/env python3
"""
Uji FORWARD MOMENTUM pada tape nyata SoDEX — sesuai pra-registrasi
docs/sodex/SODEX_FORWARD_MOMENTUM_PRAREG_2026-10-05.md (beku d9ffcec).

READ-ONLY terhadap lane: hanya MEMBACA berkas JSONL hasil collector + MENULIS laporan.
Tidak menyentuh gate/leverage/sizing/target. LOCKBOX (2026-09-01..10-05) TIDAK dibaca.
"""
from __future__ import annotations
import json, glob, os, statistics as st
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "freqtrade_user_data/data/sodex/trades"
O = ROOT / "freqtrade_user_data/data/sodex/obi"
REP = ROOT / "reports/sodex"
SYMS = ["BTC-USD", "ETH-USD", "SOL-USD"]
DEV_LO, DEV_HI = "20260522", "20260831"          # LOCKBOX >= 20260901 TIDAK disentuh
THETA = [0.010, 0.015, 0.020]                    # beku
WIN_MIN, CLUSTER_MIN, HOLD_H = 15, 60, 24        # beku
FEE_TAKER = 0.0002                               # 2 bp/sisi (konservatif; venue terukur 1,82 bp)
MIN_EP = 30


def dev_days():
    ds = set()
    for f in glob.glob(str(T / "trades_*.jsonl")):
        d = os.path.basename(f)[7:15]
        if DEV_LO <= d <= DEV_HI:
            ds.add(d)
    return sorted(ds)


def minute_series(day: str, sym: str) -> dict[int, float]:
    """harga trade terakhir per menit (epoch-menit -> harga)"""
    out: dict[int, float] = {}
    p = T / f"trades_{day}.jsonl"
    if not p.exists():
        return out
    with open(p) as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("sym") != sym:
                continue
            try:
                ts = float(r["ts"]) / 1000.0
                px = float(r["price"])
            except (KeyError, TypeError, ValueError):
                continue
            if px > 0:
                out[int(ts // 60)] = px
    return out


def half_spread_bp(days) -> dict[str, float]:
    """median setengah-spread (bp) per simbol dari berkas OBI NYATA"""
    acc: dict[str, list[float]] = defaultdict(list)
    for d in days:
        p = O / f"obi_{d}.jsonl"
        if not p.exists():
            continue
        with open(p) as fh:
            for i, line in enumerate(fh):
                if i % 7:                    # subsampel 1/7 agar cepat, tak bias
                    continue
                try:
                    r = json.loads(line)
                    bid, ask, mid = float(r["bid"]), float(r["ask"]), float(r["mid"])
                except Exception:
                    continue
                if bid > 0 and ask > bid and mid > 0:
                    acc[r["sym"]].append((ask - bid) / mid / 2 * 1e4)
    return {s: (st.median(v) if v else 0.0) for s, v in acc.items()}


def build(days):
    """per simbol: daftar (epoch_menit, harga) gabungan lintas hari DEV"""
    ser: dict[str, list[tuple[int, float]]] = {}
    for s in SYMS:
        pts: list[tuple[int, float]] = []
        for d in days:
            pts.extend(sorted(minute_series(d, s).items()))
        ser[s] = pts
    return ser


def events(pts, theta):
    """event |r_15m|>=theta; episode digabung bila <60 menit; ambil event PERTAMA klaster"""
    ev, last = [], None
    idx = {t: i for i, (t, _) in enumerate(pts)}
    for t, p in pts:
        t0 = t - WIN_MIN
        if t0 not in idx:
            continue
        p0 = pts[idx[t0]][1]
        if p0 <= 0:
            continue
        r = p / p0 - 1.0
        if abs(r) >= theta:
            if last is None or (t - last) >= CLUSTER_MIN:
                ev.append((t, 1 if r > 0 else -1))
            last = t
    return ev


def episode_return(pts, t_ev, direction):
    """masuk taker di menit event, keluar taker 24 jam kemudian; None bila data tak ada"""
    idx = {t: i for i, (t, _) in enumerate(pts)}
    if t_ev not in idx:
        return None
    t_ex = t_ev + HOLD_H * 60
    if t_ex not in idx:
        return None
    p_in, p_out = pts[idx[t_ev]][1], pts[idx[t_ex]][1]
    if p_in <= 0:
        return None
    return direction * (p_out / p_in - 1.0)


def signflip_p(vals, n=10000, seed=7):
    """permutasi tanda: p = P(mean acak >= mean nyata), dua sisi"""
    import random
    rng = random.Random(seed)
    obs = st.mean(vals)
    ge = 0
    for _ in range(n):
        s = sum(v if rng.random() < 0.5 else -v for v in vals)
        if abs(s / len(vals)) >= abs(obs):
            ge += 1
    return (ge + 1) / (n + 1)


def day_cluster_p(vals_by_day, n=10000, seed=11):
    """bootstrap blok-hari: p = P(mean resample >= mean nyata)"""
    import random
    rng = random.Random(seed)
    days = [d for d, v in vals_by_day.items() if v]
    obs = st.mean([st.mean(vals_by_day[d]) for d in days])
    ge = 0
    for _ in range(n):
        samp = [st.mean(vals_by_day[rng.choice(days)]) for _ in days]
        if st.mean(samp) >= obs:
            ge += 1
    return (ge + 1) / (n + 1)


def bh(pvals, q=0.10):
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    ok = [False] * m
    for rank, i in enumerate(order, 1):
        if pvals[i] <= rank * q / m:
            for j in order[:rank]:
                ok[j] = True
    return ok


def main() -> int:
    days = dev_days()
    hs = half_spread_bp(days)
    ser = build(days)
    print(f"[DEV] hari={len(days)}  {days[0]}..{days[-1]}  setengah-spread median (bp): "
          + ", ".join(f"{s}={hs.get(s,0):.2f}" for s in SYMS))
    res = {}
    for theta in THETA:
        rows, rows_fade, byday, byday_f = [], [], defaultdict(list), defaultdict(list)
        ep_per_sym = {}
        for s in SYMS:
            pts = ser[s]
            ev = events(pts, theta)
            ep_per_sym[s] = len(ev)
            cost = 2 * (hs.get(s, 0.0) / 1e4 + FEE_TAKER)   # 2 sisi taker
            for t_ev, d in ev:
                g = episode_return(pts, t_ev, d)
                if g is None:
                    continue
                day = datetime.fromtimestamp(t_ev * 60, timezone.utc).strftime("%Y%m%d")
                rows.append(g - cost); rows_fade.append(-g - cost)
                byday[day].append(g - cost); byday_f[day].append(-g - cost)
        n = len(rows)
        if n < 3:
            res[f"{theta:.3f}"] = {"n": n, "note": "terlalu sedikit"}
            continue
        seg = [rows[i * n // 3:(i + 1) * n // 3] for i in range(3)]
        segm = [st.mean(x) for x in seg if x]
        res[f"{theta:.3f}"] = {
            "theta_pct": theta * 100, "n_episode": n, "ep_per_symbol": ep_per_sym,
            "mean_net_24h_pct": st.mean(rows) * 100,
            "median_net_24h_pct": st.median(rows) * 100,
            "sr_annual": (st.mean(rows) / st.stdev(rows) * (365 ** 0.5)) if len(rows) > 2 and st.stdev(rows) > 0 else 0.0,
            "win_rate_pct": 100 * sum(1 for x in rows if x > 0) / n,
            "segments_pct": [round(x * 100, 4) for x in segm],
            "segments_positive": sum(1 for x in segm if x > 0),
            "p_signflip": signflip_p(rows), "p_day_cluster": day_cluster_p(byday),
            "control_fade_mean_net_pct": st.mean(rows_fade) * 100,
            "control_fade_p": signflip_p(rows_fade),
            "beats_control": st.mean(rows) > st.mean(rows_fade),
            "cost_bp_roundtrip": 2 * (hs.get(SYMS[0], 0) + FEE_TAKER * 1e4),
            "passes_040pct": st.mean(rows) * 100 >= 0.40,
        }
    ps = [res[k]["p_signflip"] for k in res if "p_signflip" in res[k]]
    ok = bh(ps, q=0.10)
    for kk, vv in zip([k for k in res if "p_signflip" in res[k]], ok):
        res[kk]["bh_pass"] = vv
        vv = res[kk]
        vv["verdict"] = "LULUS" if (vv["bh_pass"] and vv["mean_net_24h_pct"] > 0
                                    and vv["p_day_cluster"] < 0.05 and vv["segments_positive"] >= 2
                                    and vv["n_episode"] >= MIN_EP and vv["beats_control"]
                                    and vv["passes_040pct"]) else "GAGAL"
        vv["fail_reasons"] = [r for r, c in [
            ("n<30", vv["n_episode"] < MIN_EP), ("mean<=0", vv["mean_net_24h_pct"] <= 0),
            ("BH gagal", not vv["bh_pass"]), ("day_cluster>=0,05", vv["p_day_cluster"] >= 0.05),
            ("segmen<2/3", vv["segments_positive"] < 2), ("kalah kontrol", not vv["beats_control"]),
            ("<0,40%", not vv["passes_040pct"])] if c]
    out = {"prereg": "docs/sodex/SODEX_FORWARD_MOMENTUM_PRAREG_2026-10-05.md (beku d9ffcec)",
           "phase": "DEV", "range": [DEV_LO, DEV_HI], "lockbox_read": False,
           "symbols": SYMS, "half_spread_bp": {s: round(hs.get(s, 0), 3) for s in SYMS},
           "fee_taker_bp_per_side": FEE_TAKER * 1e4, "hypotheses": res}
    REP.mkdir(parents=True, exist_ok=True)
    (REP / "SODEX_FORWARD_MOMENTUM_dev_results.json").write_text(json.dumps(out, indent=1))
    print()
    for k, v in res.items():
        if "n_episode" not in v:
            print(f"  theta={k}: {v}"); continue
        print(f"  theta={v['theta_pct']:.1f}%  n={v['n_episode']:<4} "
              f"mean24j={v['mean_net_24h_pct']:+.4f}%  SR={v['sr_annual']:+.2f}  "
              f"WR={v['win_rate_pct']:.1f}%  seg+={v['segments_positive']}/3  "
              f"p_sf={v['p_signflip']:.4f}  p_day={v['p_day_cluster']:.4f}  "
              f"kontrol_fade={v['control_fade_mean_net_pct']:+.4f}%  BH={v['bh_pass']}  -> {v['verdict']}")
        if v["fail_reasons"]:
            print(f"      gagal karena: {', '.join(v['fail_reasons'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
