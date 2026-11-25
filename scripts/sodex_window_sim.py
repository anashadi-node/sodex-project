#!/usr/bin/env python3
"""SODEX -- simulasi tingkat DOMPET per jendela 48 jam + uji kerapuhan (READ-ONLY, DEV saja).

Tidak membaca LOCKBOX (>=20260901). Tidak ada jalur order. Memakai ulang events()/build()
dari sodex_forward_momentum.py (definisi beku) supaya angka konsisten dengan pra-registrasi.
Uji: (1) metrik jendela 48j, (2) sensitivitas delay masuk + slippage, (3) ketergantungan top-k episode.
"""
import json, random, statistics as st, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sodex_forward_momentum as fm  # noqa: E402

WIN_H = 48
TARGET = 0.008


def px_at(d, t, fwd=3):
    for k in range(fwd + 1):
        if t + k in d:
            return d[t + k], t + k
    return None, None


def episodes(ser, hs, theta, delay_min=0, slip_bp=0.0):
    """-> list of (t_exit_min, t_entry_min, sym, net_return)"""
    out = []
    for s in fm.SYMS:
        pts = ser[s]
        d = dict(pts)
        cost = 2 * (hs.get(s, 0.0) / 1e4 + fm.FEE_TAKER) + slip_bp / 1e4
        for t_ev, dr in fm.events(pts, theta):
            p_in, t_in = px_at(d, t_ev + delay_min)
            if p_in is None:
                continue
            p_out, t_out = px_at(d, t_in + fm.HOLD_H * 60)
            if p_out is None:
                continue
            out.append((t_out, t_in, s, dr * (p_out / p_in - 1.0) - cost))
    out.sort()
    return out


def window_pnl(eps, f, t_lo, t_hi, max_gross=1.0):
    """posisi f*wallet tiap episode; tolak jika gross terbuka melebihi max_gross (tanpa leverage)."""
    open_pos = []  # (t_exit, f)
    taken = []
    for t_out, t_in, s, r in sorted(eps, key=lambda x: x[1]):
        open_pos = [(te, ff) for te, ff in open_pos if te > t_in]
        if sum(ff for _, ff in open_pos) + f > max_gross + 1e-12:
            continue
        open_pos.append((t_out, f))
        taken.append((t_out, f * r))
    nw = (t_hi - t_lo) // (WIN_H * 60)
    w = [0.0] * nw
    for t_out, pnl in taken:
        i = (t_out - t_lo) // (WIN_H * 60)
        if 0 <= i < nw:
            w[i] += pnl
    return w, len(taken)


def boot_ci(w, n=5000, seed=3):
    rng = random.Random(seed)
    ms = sorted(st.mean([w[rng.randrange(len(w))] for _ in w]) for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def summarize(tag, eps, t_lo, t_hi, f):
    w, ntaken = window_pnl(eps, f, t_lo, t_hi)
    if not w:
        print(tag, "tanpa jendela"); return None
    hit = sum(1 for x in w if x >= TARGET) / len(w)
    nz = sum(1 for x in w if x != 0) / len(w)
    lo, hi = boot_ci(w)
    print(f"{tag:34s} f={f:4.2f} ambil={ntaken:3d}/{len(eps):3d}  jendela={len(w)}  mean/48j={st.mean(w)*100:+.3f}%  "
          f"median={st.median(w)*100:+.3f}%  CI95=[{lo*100:+.3f},{hi*100:+.3f}]  hit>=0,8%={hit*100:4.1f}%  ada-trade={nz*100:4.1f}%  "
          f"worst={min(w)*100:+.2f}%")
    return w


def main():
    days = fm.dev_days()
    hs = fm.half_spread_bp(days)
    ser = fm.build(days)
    allt = [t for s in fm.SYMS for t, _ in ser[s]]
    t_lo, t_hi = min(allt), max(allt)
    ndays = (t_hi - t_lo) / 1440
    print(f"[DEV] {days[0]}..{days[-1]} hari={len(days)} rentang={ndays:.1f} hari  jendela48j={int((t_hi-t_lo)//(WIN_H*60))}")
    for theta in (0.020, 0.015):
        print(f"\n=== theta={theta*100:.1f}% ===")
        base = episodes(ser, hs, theta)
        r = [x[3] for x in base]
        print(f"episode={len(base)}  rate={len(base)/ndays:.3f}/hari  mean_net={st.mean(r)*100:+.4f}%  median={st.median(r)*100:+.4f}%  "
              f"WR={100*sum(1 for x in r if x>0)/len(r):.1f}%  std={st.stdev(r)*100:.3f}%")
        print("-- (1) metrik jendela 48j, tanpa leverage (gross<=1x), dompet 100% mode --")
        for f in (0.25, 0.50, 1.00):
            summarize(f"baseline", base, t_lo, t_hi, f)
        print("-- (2) kerapuhan eksekusi (f=1.0): delay masuk + slippage tambahan di entry --")
        for dl, sl in ((1, 0), (2, 0), (5, 0), (0, 5), (0, 10), (0, 20), (1, 10), (2, 20)):
            e2 = episodes(ser, hs, theta, delay_min=dl, slip_bp=sl)
            rr = [x[3] for x in e2]
            w, _ = window_pnl(e2, 1.0, t_lo, t_hi)
            print(f"  delay={dl}m slip={sl:>2}bp  n={len(e2):3d} mean/ep={st.mean(rr)*100:+.4f}%  mean/48j={st.mean(w)*100:+.3f}%  hit={100*sum(1 for x in w if x>=TARGET)/len(w):4.1f}%")
        print("-- (3) ketergantungan top-k episode (f=1.0) --")
        order = sorted(base, key=lambda x: -x[3])
        for k in (0, 1, 2, 3, 5):
            rest = order[k:]
            rest.sort()
            w, _ = window_pnl(rest, 1.0, t_lo, t_hi)
            rr = [x[3] for x in rest]
            print(f"  buang {k} terbaik: n={len(rest):3d} mean/ep={st.mean(rr)*100:+.4f}%  mean/48j={st.mean(w)*100:+.3f}%")
        print("  5 episode terbesar:", [(datetime.fromtimestamp(x[1]*60, timezone.utc).strftime('%m-%d %H:%M'), x[2][:3], round(x[3]*100, 2)) for x in order[:5]])
        print("  5 episode terburuk:", [(datetime.fromtimestamp(x[1]*60, timezone.utc).strftime('%m-%d %H:%M'), x[2][:3], round(x[3]*100, 2)) for x in order[-5:]])
        # kontribusi per simbol & per bulan (konsentrasi)
        bysym, bymon = {}, {}
        for t_out, t_in, s, rr in base:
            bysym.setdefault(s, []).append(rr)
            bymon.setdefault(datetime.fromtimestamp(t_in*60, timezone.utc).strftime('%Y-%m'), []).append(rr)
        print("  per simbol:", {s: (len(v), round(st.mean(v)*100, 3)) for s, v in bysym.items()})
        print("  per bulan :", {m: (len(v), round(st.mean(v)*100, 3)) for m, v in sorted(bymon.items())})
    print("\nlockbox_read: False")


if __name__ == "__main__":
    main()
