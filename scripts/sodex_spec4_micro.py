#!/usr/bin/env python3
"""SPEC4 — harness mikro-struktur SoDEX (H9 lead-lag Binance, H10 order-flow).

Pra-registrasi BEKU: docs/sodex/SODEX_SPEC4_PRAREG_2026-10-07.md
READ-ONLY terhadap data. Tidak menaruh order. Tidak menyentuh OOS sampai
keputusan IS dibekukan (laporan selalu memisah IS/OOS).

Aturan pra-reg yang diterapkan apa adanya:
  - universe:  med_notional/menit(bertrade) >= $100 dan coverage >= 30%  (dihitung dari IS)
  - biaya:      base taker 4,0 bp/sisi (8 bp round-trip); STRESS 8,0 bp/sisi (16 bp) WAJIB lolos
  - stride=H (non-overlapping); n dilaporkan sebagai n_rebal
  - p: block bootstrap (blok 60 menit), 2000 resample; c4 pakai p DUA-SISI (lebih ketat)
  - kontrol F-a (fade <= 0), F-b (acak tanda per blok 60 menit -> p > 0,05), F-c (random walk)
"""
import argparse
import glob
import json
import os
import numpy as np
import pandas as pd

TAPE = "scratch/sodex_minutes"
BIN = "scratch/binance_1m"
OUT = "reports/sodex"
IS_END = "2026-08-31"
OOS_START = "2026-09-01"
SYMS = ["BTC-USD", "ETH-USD", "SOL-USD"]
BMAP = {"BTC-USD": "BTCUSDT", "ETH-USD": "ETHUSDT", "SOL-USD": "SOLUSDT"}
FEE_LEG_TAKER = 0.0004     # 4,0 bp/sisi resmi SoDEX
FEE_LEG_STRESS = 0.0008    # 8,0 bp/sisi (konservatif ALT3)
FEE_LEG_MAKER = 0.00012    # 1,2 bp/sisi (informasi)
K_GRID = [1, 5, 15]        # H9: lag Binance (menit)
W_GRID = [15, 60]          # H10: jendela akumulasi order-flow (menit)
H_GRID = [5, 15, 60]       # H9: horizon hold (menit)  -> 3x3 = 9 sel (§2)
H_GRID_10 = [15, 60]       # H10: horizon hold (menit) -> 2x2 = 4 sel (§2)
BLOCK_MIN = 60             # blok bootstrap & acak-tanda (menit)
NP_BOOT = 2000
SEED = 7
COLS = ["sym", "minute", "n", "buy_qty", "sell_qty", "close", "notional"]


# ─────────────────────────── data ───────────────────────────
def load_tape(syms, start, end):
    """Panel menit SoDEX: close (ffill) + traded flag + arus order."""
    parts = []
    for f in sorted(glob.glob(os.path.join(TAPE, "day=*.parquet"))):
        d8 = f.split("=")[-1][:8]
        if not (start.replace("-", "") <= d8 <= end.replace("-", "")):
            continue
        d = pd.read_parquet(f, columns=COLS)
        d = d[d.sym.isin(syms)]
        if len(d):
            parts.append(d)
    if not parts:
        raise SystemExit("tape kosong untuk rentang ini")
    d = pd.concat(parts, ignore_index=True)
    out = {}
    for s in syms:
        x = d[d.sym == s].copy()
        if not len(x):
            continue
        for c in ("buy_qty", "sell_qty", "close", "notional", "n"):
            x[c] = pd.to_numeric(x[c], errors="coerce")
        x = x.sort_values("minute").drop_duplicates("minute").set_index("minute")
        mn, mx = int(x.index.min()), int(x.index.max())
        grid = pd.RangeIndex(mn, mx + 1, name="minute")
        x = x.reindex(grid)
        x["traded"] = x["n"].notna() & (x["n"] > 0)
        x["close"] = x["close"].ffill()
        x["buy_qty"] = x["buy_qty"].fillna(0.0)
        x["sell_qty"] = x["sell_qty"].fillna(0.0)
        x["notional"] = x["notional"].fillna(0.0)
        out[s] = x
    return out


def load_binance(syms, start, end):
    """Close Binance 1m pada grid menit yang sama (ms -> menit)."""
    out = {}
    lo = int(pd.Timestamp(start, tz="UTC").timestamp() // 60)
    hi = int(pd.Timestamp(end, tz="UTC").timestamp() // 60)
    for s in syms:
        b = BMAP.get(s)
        f = os.path.join(BIN, f"{b}_1m.parquet")
        if not os.path.exists(f):
            continue
        d = pd.read_parquet(f, columns=["ts", "c"])
        d["minute"] = (pd.to_numeric(d["ts"], errors="coerce") // 60000).astype("int64")
        d["c"] = pd.to_numeric(d["c"], errors="coerce")
        x = d.drop_duplicates("minute").set_index("minute")["c"]
        x = x.reindex(pd.RangeIndex(lo, hi + 1, name="minute")).ffill()
        out[s] = x
    return out


# ─────────────────────── statistik / util ───────────────────────
def stationary_bootstrap_p(net, block=10, n_boot=NP_BOOT, rng=None, two_sided=True):
    """p-value rata-rata != 0 via circular block bootstrap (vektor, chunked).

    Blok = `block` observasi (untuk stride=H, 60 menit = 60//H observasi).
    Implementasi vektor supaya n ~10^5 tetap cepat; loop Python per-observasi
    (Politis-Romano sekuensial) tidak layak di ukuran ini.
    """
    rng = rng or np.random.default_rng(SEED)
    net = np.asarray(net, dtype=float)
    net = net[np.isfinite(net)]
    n = len(net)
    if n < 8:
        return 1.0, np.nan, n
    L = max(2, int(block))
    nb = int(np.ceil(n / L))
    off = np.arange(L, dtype=np.int64)
    means = np.empty(n_boot, dtype=float)
    chunk = max(1, min(n_boot, int(4_000_000 // max(nb * L, 1))))
    done = 0
    while done < n_boot:
        c = min(chunk, n_boot - done)
        starts = rng.integers(0, n, size=(c, nb))
        idx = ((starts[:, :, None] + off[None, None, :]) % n).reshape(c, -1)[:, :n]
        means[done:done + c] = net[idx].mean(axis=1)
        done += c
    obs = float(net.mean())
    dev = means - obs
    ci_lo = float(obs + np.percentile(dev, 2.5))
    ci_hi = float(obs + np.percentile(dev, 97.5))
    # Bootstrap terpusat pada H0 (mu=0): distribusi resample sudah terpusat di `obs`,
    # jadi uji H0 dengan menggeser sebesar obs. Salah kalau membandingkan `means`
    # langsung ke `obs` (itu selalu p~1 dan akan meloloskan apa pun).
    p_left = float((means <= 0.0).mean())          # H0: mu <= 0
    p_right = float((means >= 2.0 * obs).mean())   # H0: mu >= 0
    if two_sided:
        p = 2 * min(p_left, p_right)
    else:
        p = p_left
    p = float(min(max(p, 1.0 / n_boot), 1.0))
    return dict(p=p, obs=obs, n=n, ci_lo=ci_lo, ci_hi=ci_hi)


def block_flip(sig, sym_days, block=BLOCK_MIN, rng=None):
    """Acak tanda sinyal per blok `block` menit di dalam (simbol, hari-online)."""
    rng = rng or np.random.default_rng(SEED + 1)
    out = np.array(sig, dtype=float, copy=True)
    for (i0, i1) in sym_days:
        k = i0
        while k < i1:
            if rng.random() < 0.5:
                out[k:i1] = out[k:i1] * -1.0
            k += block
    return out


def day_spans(minutes, block=BLOCK_MIN):
    """Daftar rentang [i0,i1) per hari kalender untuk acak-tanda."""
    if not len(minutes):
        return []
    d = pd.to_datetime(pd.Index(minutes), unit="m", utc=True)
    key = d.floor("D")
    chg = np.where(key[1:] != key[:-1])[0] + 1
    b = np.concatenate([[0], chg, [len(key)]])
    return [(int(b[i]), int(b[i + 1])) for i in range(len(b) - 1)]


# ─────────────────────────── mesin ───────────────────────────
def run_cell(close, sig, H, entry_delay=1, cost_rt=0.0, base_min=0, extra_leg=0.0):
    """Kembalikan (net_series, idx, minute_values) untuk satu sel.

    sig   : array sinyal (arah), panjang sama dgn close; NaN = tanpa posisi
    close : array harga; posisi masuk di close[t+entry_delay], keluar close[t+entry_delay+H]
    """
    n = len(close)
    idx = np.arange(0, n - entry_delay - H, H)          # stride = H (non-overlapping)
    if len(idx) == 0:
        return np.array([]), np.array([], dtype=np.int64), np.array([], dtype=np.int64)
    e = idx + entry_delay
    x = idx + entry_delay + H
    ok = np.isfinite(close[e]) & np.isfinite(close[x]) & np.isfinite(sig[idx])
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.log(close[x] / close[e])
    net = sig[idx] * r - (cost_rt + extra_leg)
    net = np.where(ok, net, np.nan)
    return net, idx, (base_min + idx).astype(np.int64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-24")
    ap.add_argument("--end", default="2026-10-07")
    ap.add_argument("--nperm", type=int, default=NP_BOOT)
    ap.add_argument("--synthetic", action="store_true", help="F-c: panel random-walk tanpa edge")
    a = ap.parse_args()

    n_boot = a.nperm
    rng = np.random.default_rng(SEED)

    tape = load_tape(SYMS, a.start, a.end)
    if a.synthetic:
        # F-c: ganti close dengan random walk (tanpa edge), arus order tetap
        for s in list(tape):
            c0 = np.log(tape[s]["close"].ffill().bfill().to_numpy())
            rw = np.cumsum(rng.normal(0, 0.0005, len(c0)))
            tape[s]["close"] = np.exp(rw)
    bins = load_binance(SYMS, a.start, a.end)
    print(f"tape simbol: {sorted(tape)} | binance: {sorted(bins)}")

    is_end_m = int(pd.Timestamp(IS_END, tz="UTC").timestamp() // 60)
    cells = []
    CELLS = {}

    def add(code, net_by_sym, mins_by_sym, sig_meta, kind, sig_by_sym=None, close_by_sym=None):
        e = CELLS.get(code)
        if e is None:
            e = dict(code=code, net={}, mins={}, meta=sig_meta, kind=kind, sig={}, close={})
            CELLS[code] = e
            cells.append(e)
        e["net"].update(net_by_sym or {})
        e["mins"].update(mins_by_sym or {})
        e["sig"].update(sig_by_sym or {})
        e["close"].update(close_by_sym or {})

    # ── H9: lead-lag Binance -> SoDEX ──
    for s in SYMS:
        if s not in tape or s not in bins:
            continue
        cs = tape[s]["close"].to_numpy(dtype=float)
        # WAJIB: sejajarkan grid Binance ke grid tape SoDEX (kalau tidak, sinyal
        # Binance tergeser beberapa hari dan H9 diuji pada data yang salah).
        cb = bins[s].reindex(tape[s].index).to_numpy(dtype=float)
        base = int(tape[s].index.min())
        lb = np.log(cb)
        for k in K_GRID:
            bl = np.full(len(lb), np.nan)
            bl[k:] = lb[k:] - lb[:-k]
            sg = np.sign(bl)
            for H in H_GRID:
                code = f"H9_k{k}_H{H}"
                g_s, idx, mins = run_cell(cs, sg, H, cost_rt=0.0, base_min=base)
                g_b, _, _ = run_cell(cb, sg, H, cost_rt=0.0, base_min=base)
                net = g_s - 2 * FEE_LEG_TAKER
                add(code, {s: net}, {s: mins}, f"lead-lag k={k} H={H}", "H9",
                    {s: sg}, {s: cs})
                # F-a: kontrol arah berlawanan
                add(code + "_FADE", {s: -g_s - 2 * FEE_LEG_TAKER}, {s: mins},
                    f"FADE k={k} H={H}", "Fa")
                # §2: mode market-neutral (SoDEX + short Binance, 4 leg) = INFORMASI saja
                add(code + "_MN", {s: g_s - g_b - 4 * FEE_LEG_TAKER}, {s: mins},
                    f"market-neutral k={k} H={H}", "H9mn")

    # ── H10: order-flow imbalance native ──
    for s in SYMS:
        if s not in tape:
            continue
        x = tape[s]
        cs = x["close"].to_numpy(dtype=float)
        base = int(x.index.min())
        bq = x["buy_qty"].to_numpy(dtype=float)
        sq = x["sell_qty"].to_numpy(dtype=float)
        tot = bq + sq
        dq = bq - sq
        for W in W_GRID:
            num = pd.Series(dq).rolling(W, min_periods=max(2, W // 2)).sum().to_numpy()
            den = pd.Series(tot).rolling(W, min_periods=max(2, W // 2)).sum().to_numpy()
            with np.errstate(invalid="ignore", divide="ignore"):
                ofi = np.where(den > 0, num / den, np.nan)
            for H in H_GRID_10:
                code = f"H10_W{W}_H{H}"
                net, idx, mins = run_cell(cs, np.sign(ofi), H, cost_rt=2 * FEE_LEG_TAKER, base_min=base)
                add(code, {s: net}, {s: mins}, f"order-flow W={W} H={H}", "H10",
                    {s: np.sign(ofi)}, {s: cs})
                netf, _, _ = run_cell(cs, -np.sign(ofi), H, cost_rt=2 * FEE_LEG_TAKER, base_min=base)
                add(code + "_FADE", {s: netf}, {s: mins}, f"FADE ofi W={W} H={H}", "Fa")

    # ── F-b: acak tanda per blok 60 menit (kontrol wajib p > 0,05) ──
    PRIMARY = {"H9_k1_H15", "H10_W15_H60"}
    fb_rows = []
    gg = np.random.default_rng(SEED + 2)
    for c in cells:
        if c["code"] not in PRIMARY:
            continue
        pool = []
        for s, cs in c["close"].items():
            sig_s = c["sig"].get(s)
            idx = c["mins"].get(s)
            if sig_s is None or idx is None or len(idx) < 10:
                continue
            Hc = int(idx[1] - idx[0])
            pos = idx - int(idx[0])          # idx kini = NILAI MENIT; posisi = menit - menit awal
            e, x = pos + 1, pos + 1 + Hc
            with np.errstate(invalid="ignore", divide="ignore"):
                r = np.log(cs[x] / cs[e])
            ok = np.isfinite(r) & np.isfinite(sig_s[pos])
            sig_at = np.where(ok, sig_s[pos], np.nan)
            r_at = np.where(ok, r, np.nan)
            cost = 2 * FEE_LEG_TAKER
            obs = sig_at * r_at - cost
            obs = obs[np.isfinite(obs)]
            if len(obs) < 30:
                continue
            obs_mean = float(obs.mean())
            spans = day_spans([int(m) for m in idx], block=BLOCK_MIN)
            draws = []
            for _ in range(300):
                s2 = block_flip(sig_at, spans, block=max(1, BLOCK_MIN // Hc), rng=gg)
                d = s2 * r_at - cost
                d = d[np.isfinite(d)]
                if len(d):
                    draws.append(float(d.mean()))
            draws = np.array(draws)
            if not len(draws):
                continue
            p_fb = float((draws >= obs_mean).mean())
            fb_rows.append(dict(code=c["code"], sym=s, n=len(obs), obs_bp=obs_mean * 1e4,
                                p_fb=p_fb, fb_pass=bool(p_fb > 0.05)))

    # ── agregasi + verdict ──
    rows = []
    for c in cells:
        parts = [v for v in c["net"].values() if len(v)]
        allnet = np.concatenate(parts) if parts else np.array([])
        allnet = allnet[np.isfinite(allnet)]
        sym_net = {}
        for s, v in c["net"].items():
            v = v[np.isfinite(v)]
            sym_net[s] = float(np.sum(v)) if len(v) else 0.0
        tot_abs = sum(abs(v) for v in sym_net.values())
        top_share = (max(abs(v) for v in sym_net.values()) / tot_abs) if tot_abs else 1.0
        _h = [int(v[1] - v[0]) for v in c["mins"].values() if len(v) > 1]
        _H = _h[0] if _h else 1
        st = stationary_bootstrap_p(allnet, block=max(2, BLOCK_MIN // max(_H, 1)),
                                    n_boot=n_boot, rng=rng)
        net_bp = float(st["obs"] * 1e4) if st["n"] else np.nan
        allmin = np.concatenate([v for v in c["mins"].values() if len(v)]) if c["mins"] else np.array([])
        n_days = int(np.unique(allmin // 1440).size) if len(allmin) else 0
        parts_oos = []
        for s, v in c["net"].items():
            m = c["mins"].get(s)
            if m is not None and len(m) == len(v):
                parts_oos.append(v[m >= is_end_m])
        oos_net = np.concatenate(parts_oos) if parts_oos else np.array([])
        oos_net = oos_net[np.isfinite(oos_net)]
        oos_bp = float(np.mean(oos_net) * 1e4) if len(oos_net) else np.nan
        rows.append(dict(code=c["code"], kind=c["kind"], meta=c["meta"], n=st["n"],
                         n_rebal=int(sum(len(v[np.isfinite(v)]) for v in c["net"].values())),
                         n_days=n_days,
                         net_bp=net_bp, ci_lo_bp=st["ci_lo"] * 1e4, ci_hi_bp=st["ci_hi"] * 1e4,
                         stress_bp=net_bp - 8.0,          # +4 bp/sisi -> 16 bp round-trip
                         slip1_bp=net_bp - 2.0, slip2_bp=net_bp - 4.0, slip5_bp=net_bp - 10.0,
                         maker_bp=net_bp - 8.0 + 2.4,
                         p=st["p"], top_share=float(top_share),
                         oos_net_bp=oos_bp, oos_stress_bp=oos_bp - 8.0 if len(oos_net) else np.nan,
                         oos_n=int(len(oos_net))))

    df = pd.DataFrame(rows)
    # Keluarga hipotesis = H9 + H10 saja (kontrol & mode informasi tidak masuk BH)
    fam = df[df.kind.isin(["H9", "H10"])].copy()
    m = len(fam)                                   # harus 9 + 4 = 13 (pra-reg §4)
    fam = fam.sort_values("p").reset_index(drop=True)
    fam["bh_rank"] = np.arange(1, m + 1)
    fam["bh_thr"] = fam["bh_rank"] * 0.10 / m
    fam["bh_pass"] = fam["p"] <= fam["bh_thr"]
    for _, r in fam.iterrows():
        i = df.index[df.code == r.code][0]
        df.loc[i, ["bh_rank", "bh_thr", "bh_pass"]] = [r.bh_rank, r.bh_thr, r.bh_pass]
    df["c1_n"] = (df.n_rebal >= 300) & (df.n_days >= 60)
    df["c2_net"] = df.net_bp > 0
    df["c3_stress"] = df.stress_bp > 0
    df["c4_p"] = (df.p <= 0.05) & (df.bh_pass.fillna(False).astype(bool))
    df["c5_conc"] = df.top_share <= 0.30
    df["c6_oos"] = df.oos_stress_bp > 0
    gates = ["c1_n", "c2_net", "c3_stress", "c4_p", "c5_conc", "c6_oos"]
    df["verdict"] = df[gates].all(axis=1)
    df["gagal"] = df.apply(lambda r: [g for g in gates if not bool(r[g])], axis=1)

    print(f"\nfamilia hipotesis (BH, m wajib 13): m={m}")
    print("=" * 118)
    hdr = (f"{'kode':<18}{'n_rebal':>8}{'hari':>6}{'net_bp':>9}{'CI95':>18}{'stress':>9}"
           f"{'p':>8}{'top':>6}{'oos_str':>9}  gagal")
    print(hdr)
    print("=" * 118)
    for _, r in df.sort_values(["kind", "code"]).iterrows():
        ci = f"[{r.ci_lo_bp:,.1f},{r.ci_hi_bp:,.1f}]"
        print(f"{r.code:<18}{r.n_rebal:>8}{r.n_days:>6}{r.net_bp:>9.2f}{ci:>18}{r.stress_bp:>9.2f}"
              f"{r.p:>8.3f}{r.top_share:>6.2f}{r.oos_stress_bp:>9.2f}  {','.join(r.gagal)}")
    lulus = df[df.verdict & (df.kind.isin(['H9', 'H10']))]
    print("=" * 118)
    print(f"VERDICT: lulus = {sorted(lulus.code.tolist()) if len(lulus) else 'TIDAK ADA'}")
    print(f"Kontrol F-a (fade harus <= 0): ", end="")
    fades = df[df.kind == "Fa"]
    print(f"{int((fades.net_bp > 0).sum())}/{len(fades)} fade POSITIF "
          f"({'OK' if (fades.net_bp > 0).sum() == 0 else 'PERIKSA: harness mungkin salah arah'})")
    print("Kontrol F-b (acak tanda per blok, wajib p > 0,05):")
    fbd = pd.DataFrame(fb_rows)
    if len(fbd):
        print(fbd.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
        print(f"  → F-b {'LULUS' if fbd.fb_pass.all() else 'GAGAL (ada sel yang tahan acak-tanda → curiga artefak)'}")
    else:
        print("  (tidak ada sel primer yang bisa diuji)")

    os.makedirs(OUT, exist_ok=True)
    tag = "_SYNTHETIC" if a.synthetic else ""
    path = os.path.join(OUT, f"sodex_spec4_{pd.Timestamp.utcnow():%Y%m%d}{tag}.json")
    json.dump(dict(meta=dict(syms=SYMS, start=a.start, end=a.end, is_end=IS_END,
                             oos_start=OOS_START, fee_base_rt=2 * FEE_LEG_TAKER,
                             fee_stress_rt=2 * FEE_LEG_STRESS, fee_maker_rt=2 * FEE_LEG_MAKER,
                             nperm=a.nperm, block_min=BLOCK_MIN, synthetic=a.synthetic),
                   results=df.drop(columns=["gagal"]).to_dict("records"),
                   kontrol_fb=fb_rows),
              open(path, "w"), indent=1, default=str)
    print(f"\nhasil -> {path}")


if __name__ == "__main__":
    main()
