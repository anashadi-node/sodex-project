#!/usr/bin/env python3
"""SODEX F2 DISCOVERY -- deskriptif struktur mikro dari OBI Nyata. READ-ONLY.

TIDAK MENGUJI H2. Tidak menyentuh data >=2026-09-01 (lockbox) dan tidak menyentuh F1/eval #42.
Output: statistik deskriptif untuk MEMILIH usulan H2, bukan untuk memutus P&L.

Pola onset (definisi deskriptif, dipilih SEBELUM melihat hasil drift, lihat git log):
  A = kejutan likuiditas : spread >= 2x median spread simbol (periode ini)
  B = imbalance buku     : OBI20 >= +0.35 selama >=3 snapshot berturut (<=8 menit)
  A&B  = keduanya
pathologi: cek juga seberapa sering B muncul <=10 menit SEBELUM A (interaksi pola).
forward drift: mid(t0+k menit, snapshot terdekat) / mid(t0) - 1 (k = 1,5,15,60,240), dalam bp.
net deskriptif = drift - 2*(half_spread@t0 + 2bp fee) - 4bp slip   (MASIH deskriptif; bukan putusan)
"""
from __future__ import annotations
import json, glob, statistics as st, sys
from bisect import bisect_left, insort
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBI = ROOT / "freqtrade_user_data/data/sodex/obi"
CUTOFF = "20260901"                      # eksklusif: hanya <=2026-08-31
KS = (1, 5, 15, 60, 240)                 # menit
B_LV, B_DUR, B_WIN_S = 0.35, 3, 480      # OBI20 threshold, snap berturut, jendela detik
A_MULT = 2.0
NEXT_IN = (0, 600)                       # B->A antologi 0..600 detik
INDEP_GAP_S = 4 * 3600                   # gap minimum antar-event yang dianggap independen
FEE_BP, SLIP_BP = 2.0, 4.0               # per sisi taker; slip total 2x2bp
SYMS = None                              # semua yang ada di data lama (3 simbol basis)

days = sorted({p.name[4:12] for p in OBI.glob("obi_*.jsonl") if p.name[4:12] < CUTOFF})
print(f"[F2-disc] hari <={days[-1]}  ({len(days)} hari, {days[0]}..{days[-1]})")


def load_sym(sym):
    """-> t_arr (s, sorted), obi20, spread, mid arrays sejajar"""
    t, o20, sp, mid = [], [], [], []
    for d in days:
        p = OBI / f"obi_{d}.jsonl"
        try:
            fh = open(p)
        except FileNotFoundError:
            continue
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("sym") != sym:
                continue
            t.append(float(r["ts"]) / 1000.0)
            o20.append(float(r.get("obi20", 0)) or 0.0)
            sp.append(float(r.get("spread", 0)) or 0.0)
            mid.append(float(r["mid"]))
    idx = sorted(range(len(t)), key=lambda i: t[i])
    return [t[i] for i in idx], [o20[i] for i in idx], [sp[i] for i in idx], [mid[i] for i in idx]


def at(arr_s, arr_v, ts):
    """snapshot terdekat <= ts (tolak jika gap > 70 detik)"""
    i = bisect_left(arr_s, ts + 1e-9) - 1
    if i < 0 or ts - arr_s[i] > 70:
        return None
    return arr_v[i]


def fwd_drift(t_arr, mid_arr, t0, k, mid0):
    """bp drift k menit, snapshot terdekat <= t0+k*60 (gap <=90 detik)"""
    j = bisect_left(t_arr, t0 + k * 60 + 1e-9) - 1
    if j < 0 or t0 + k * 60 - t_arr[j] > 90:
        return None
    return (mid_arr[j] / mid0 - 1.0) * 1e4


def main():
    # simbol objektif: hadir di >=80% hari (basis lama saja; SILVER-USD dsb mati lebih awal → otomatis gugur)
    present = defaultdict(int)
    for d in days:
        for s in _syms_of(d):
            present[s] += 1
    syms = sorted(s for s, c in present.items() if c >= 0.8 * len(days))
    print("simbol (>=80% hari):", syms)
    rows = []
    for sym in syms:
        t_arr, o20, sp, mid = load_sym(sym)
        if len(t_arr) < 1000:
            print(f"  {sym}: data kurang ({len(t_arr)})"); continue
        med_sp = st.median([s for s in sp if s > 0])
        # --- onset events ---
        lastB = -10**9
        b_run = 0
        last_ev = defaultdict(lambda: -10**9)  # (sym,kind) -> t0 terakhir disimpan (INDEP_GAP)
        for i, ts in enumerate(t_arr):
            if o20[i] >= B_LV:
                b_run += 1
            else:
                b_run = 0
            if b_run == B_DUR and ts - lastB > B_WIN_S:
                if ts - last_ev[(sym, "B")] >= INDEP_GAP_S:
                    rows.append({"sym": sym, "t0": ts, "kind": "B", "mid0": mid[i], "sp0": sp[i]})
                    last_ev[(sym, "B")] = ts
                lastB = ts
        for i, ts in enumerate(t_arr):
            if sp[i] >= A_MULT * med_sp and sp[i] > 0 and ts - last_ev[(sym, "A")] >= INDEP_GAP_S:
                rows.append({"sym": sym, "t0": ts, "kind": "A", "mid0": mid[i], "sp0": sp[i]})
                last_ev[(sym, "A")] = ts
        # --- forward drift + net ---
        for r in rows:
            i0 = bisect_left(t_arr, r["t0"] + 1e-9) - 1
            r["mid_at0"] = mid[i0]
            r["hs_bp"] = r["sp0"] / 2 / r["mid_at0"] * 1e4
            f = {}
            for k in KS:
                f[k] = fwd_drift(t_arr, mid, r["t0"], k, r["mid_at0"])
            r["fwd"] = f
            if f.get(1) is not None:
                r["net1"] = f[1] - 2 * (r["hs_bp"] + FEE_BP) - 2 * SLIP_BP
            r["obi_at0"] = at(t_arr, o20, r["t0"])
    # --- ringkasan per pola ---
    def fmt(rows, tag):
        n = len(rows)
        if n < 5:
            print(f"{tag}: n={n} (<5, tidak dilaporkan)"); return
        for k in KS:
            v = sorted(x for r in rows if (x := r["fwd"].get(k)) is not None)
            lab = f"+ {tag}: n={n} drift{k}m mean={st.mean(v):+.2f}bp med={v[len(v)//2]:+.2f}bp"
            if k == 1:
                nets = [r["net1"] for r in rows if "net1" in r]
                if len(nets) >= 5:
                    lab += f"  net1(desk) mean={st.mean(nets):+.2f}bp"
            print(lab)
    print("\n== per pola (deskriptif) ==")
    for kind in ("A", "B"):
        fmt([r for r in rows if r["kind"] == kind], f"pola {kind}")
    # interaksi: A yang <=600 detik sebelumnya punya B
    bts = sorted((r["sym"], r["t0"]) for r in rows if r["kind"] == "B")
    a_all = [r for r in rows if r["kind"] == "A"]
    a_pre = [r for r in a_all if any(s == r["sym"] and 0 <= r["t0"] - tb <= NEXT_IN[1] for _, tb in bts)]
    fmt(a_pre, "A-dengan-B-dulu (<=10m)")
    fmt([r for r in a_all if r not in a_pre], "A-tanpa-B")
    # arus balik: distribusi net1 per simbol untuk pola B (apaini luar?)
    print("\n== net1(desk) per simbol (pola B) ==")
    for sym in syms:
        rr = [r for r in rows if r["kind"] == "B" and r["sym"] == sym and "net1" in r]
        if len(rr) >= 8:
            v = [r["net1"] for r in rr]
            print(f"  {sym:10s} n={len(rr):4d} mean={st.mean(v):+7.2f}bp p={sum(1 for x in v if x>0)/len(v)*100:4.0f}%")
    print("\n[catatan] SEMUA ANGKA DESKRIPTIF, TIDAK ADA PUTUSAN EDGE. H2 baru boleh diuji setelah pra-registrasi dan data forward >=2026-10-07.")


def _syms_of(day):
    s = set()
    try:
        with open(OBI / f"obi_{day}.jsonl") as fh:
            for _, line in zip(range(400), fh):
                try:
                    s.add(json.loads(line)["sym"])
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return s


if __name__ == "__main__":
    main()
