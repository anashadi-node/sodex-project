"""SARING KANDIDAT MESIN HORIZON 48 JAM — SoDEX.

DESKRIPTIF: memakai jendela historis yang sudah terpakai -> TIDAK sah jadi verdict
lulus/gagal. Tidak mengubah ambang, protokol, atau skrip beku mana pun.

Aturan yang dipakai (semuanya dinyatakan eksplisit, tak ada yang diam-diam):
  R1 (replikasi lintas-VENUE, interval bar SAMA) : tanda IC sama DAN |IC_sodex| >= 0.5*|IC_binance|
  R2 (lintas-FREKUENSI, venue sama)              : tanda IC sama — DILEMAHKAN karena
       nama mekanisme didefinisikan per-BAR, jadi MOM_L21 di 1d = 21 hari, di 1h = 21 jam
       => bukan mekanisme yang sama. Dilaporkan sebagai info, bukan gate.
  R3 (ekonomis)                                  : gross > 0 DAN turnover <= 1.5 DAN net(fee1x) > 0
  R4 (anti-drift)                                : IC kontrol acak ~ 0 (|IC_ctrl| < 0.005)

Jalankan: python3 scripts/research/sodex_48h_candidate_screen.py
Output : reports/sodex/SODEX_48H_CANDIDATE_SCREEN.json
"""
import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANELS = {"binance_1d": 365.0, "sodex_1d": 365.0, "sodex_1h": 365.0 * 24.0}
TO_MAX = 1.5
IC_CTRL_MAX = 0.005
T_MIN = 1.96
HOLD_48H = {"1d": (2,), "1h": (48,)}


def bps(panel_doc, key, variant="fee1x"):
    """-> dict ringkas satu varian arm, atau None bila arm di-skip/tidak ada."""
    a = panel_doc["results"].get(key)
    if not a or a.get("skip"):
        return None
    v = a.get(variant)
    if not v or not v.get("n"):
        return None
    c = a.get("ctrl") or {}
    gross = v["mean_bps_per_period"] + v["fee_bps"]
    ctrl_gross = (c["mean_bps_per_period"] + c["fee_bps"]) if c.get("n") else None
    return {
        "mech": a.get("mech"), "hold": a.get("hold"), "n": v["n"],
        "turnover": v["turnover"], "gross_bps": gross,
        "net_bps": v["mean_bps_per_period"], "sd_bps": v["sd_bps_per_period"],
        "ic": v["ic_mean"], "t": v["t_nw"], "p": v["p"],
        "seg_pos": v.get("segments_positive"),
        "ctrl_gross_bps": ctrl_gross, "ctrl_ic": c.get("ic_mean"),
        "ctrl_turnover": c.get("turnover"),
        "delta_vs_ctrl_bps": (gross - ctrl_gross) if ctrl_gross is not None else None,
        "pass_panel": a.get("pass"),
    }


def sharpe(row, ppy):
    return (row["gross_bps"] / row["sd_bps"]) * math.sqrt(ppy / row["hold"])


def pearson(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def main():
    docs = {p: json.load(open(os.path.join(
        ROOT, f"reports/sodex/PRAREG_PANEL_PANJANG_{p}.json"))) for p in PANELS}

    # ---------- 1. semua arm horizon 48 jam ----------
    arms48 = []
    for p, ppy in PANELS.items():
        iv = "1h" if p.endswith("1h") else "1d"
        for key, a in docs[p]["results"].items():
            if a.get("skip") or a.get("hold") not in HOLD_48H[iv]:
                continue
            r = bps(docs[p], key)
            if not r:
                continue
            r["panel"], r["interval"] = p, iv
            r["sharpe_gross"] = sharpe(r, ppy)
            r["sharpe_net"] = (r["net_bps"] / r["sd_bps"]) * math.sqrt(ppy / r["hold"])
            arms48.append(r)
    arms48.sort(key=lambda r: (r["panel"], -r["gross_bps"]))

    print("=== ARM HORIZON 48 JAM (hold=2 di 1d, hold=48 di 1h) ===")
    print(f"{'panel':<12}{'mech':<12}{'n':>6}{'to':>7}{'gross':>9}{'net':>9}{'IC':>9}"
          f"{'Sh_grs':>8}{'ctrl_grs':>10}{'Δctrl':>8}{'seg+':>6}")
    for r in arms48:
        print(f"{r['panel']:<12}{r['mech']:<12}{r['n']:>6}{r['turnover']:>7.3f}"
              f"{r['gross_bps']:>9.2f}{r['net_bps']:>9.2f}{r['ic']:>9.4f}"
              f"{r['sharpe_gross']:>8.2f}"
              f"{(r['ctrl_gross_bps'] if r['ctrl_gross_bps'] is not None else float('nan')):>10.2f}"
              f"{(r['delta_vs_ctrl_bps'] if r['delta_vs_ctrl_bps'] is not None else float('nan')):>8.2f}"
              f"{str(r['seg_pos']):>6}")

    # ---------- 2. replikasi R1 (lintas-venue, interval sama) ----------
    print("\n=== R1 REPLIKASI LINTAS-VENUE (interval bar SAMA) ===")
    print(f"{'mech':<12}{'hold':>5}{'IC_binance':>12}{'IC_sodex':>11}{'rasio':>8}"
          f"{'tanda':>7}{'R1':>5}{'gross_b':>10}{'gross_s':>10}")
    repl = []
    for iv, ppy in (("1d", 365.0),):
        for hold in HOLD_48H[iv] + (5,):
            for key, a in docs["binance_1d"]["results"].items():
                if a.get("mech") is None or a.get("hold") != hold or a.get("skip"):
                    continue
                rb = bps(docs["binance_1d"], key)
                rs = bps(docs["sodex_1d"], key)
                if not rb:
                    continue
                if not rs:
                    repl.append({"mech": rb["mech"], "hold": hold, "status": "tak_ada_pasangan_sodex",
                                 "ic_binance": rb["ic"], "ic_sodex": None, "r1": False})
                    print(f"{rb['mech']:<12}{hold:>5}{rb['ic']:>12.4f}{'-':>11}{'-':>8}"
                          f"{'-':>7}{'N/A':>5}{rb['gross_bps']:>10.2f}{'-':>10}")
                    continue
                ratio = abs(rs["ic"]) / abs(rb["ic"]) if rb["ic"] else float("nan")
                same = (rb["ic"] * rs["ic"]) > 0
                ok = bool(same and ratio >= 0.5)
                repl.append({"mech": rb["mech"], "hold": hold, "status": "ok",
                             "ic_binance": rb["ic"], "ic_sodex": rs["ic"], "rasio": ratio,
                             "tanda_sama": same, "r1": ok})
                print(f"{rb['mech']:<12}{hold:>5}{rb['ic']:>12.4f}{rs['ic']:>11.4f}{ratio:>8.2f}"
                      f"{('ya' if same else 'TIDAK'):>7}{('LULUS' if ok else 'gagal'):>5}"
                      f"{rb['gross_bps']:>10.2f}{rs['gross_bps']:>10.2f}")

    n_ok = sum(1 for x in repl if x["r1"])
    n_pairs = sum(1 for x in repl if x["status"] == "ok")
    print(f"\nR1 lulus {n_ok}/{n_pairs} pasangan yang punya data di kedua venue "
          f"({len(repl)} mekanisme-hold diperiksa, sisanya tanpa data SoDEX)")

    # ---------- 3. saringan kandidat ----------
    r1_pass = {(x["mech"], x["hold"]) for x in repl if x["r1"]}
    short = []
    for r in arms48:
        reasons = []
        # R1 hanya bisa dievaluasi di 1d (Binance tak punya panel 1h)
        if r["interval"] == "1h":
            reasons.append("tak_bisa_diuji_R1(tak_ada_panel_Binance_1h)")
        elif (r["mech"], r["hold"]) not in r1_pass:
            reasons.append("gagal_R1")
        if not (r["gross_bps"] > 0):
            reasons.append("gross_<=_0")
        if not (r["turnover"] <= TO_MAX):
            reasons.append(f"turnover>{TO_MAX}")
        if not (r["net_bps"] > 0):
            reasons.append("net_<=_0")
        if r["ctrl_ic"] is not None and abs(r["ctrl_ic"]) >= IC_CTRL_MAX:
            reasons.append("kontrol_IC_tak_nol")
        if abs(r["t"] or 0) < T_MIN:
            reasons.append(f"t<{T_MIN}")
        row = dict(r)
        row["lolos"] = not reasons
        row["alasan_gagal"] = reasons
        short.append(row)

    print("\n=== SARINGAN KANDIDAT 48 JAM (R1 + R3 + R4 + R5) ===")
    for r in short:
        tag = "LOLOS" if r["lolos"] else "gagal"
        print(f"  [{tag:>5}] {r['panel']:<11}{r['mech']:<12} gross={r['gross_bps']:>7.2f}"
              f" net={r['net_bps']:>7.2f} to={r['turnover']:>5.3f} Sh={r['sharpe_gross']:>5.2f}"
              f"  Δctrl={r['delta_vs_ctrl_bps'] if r['delta_vs_ctrl_bps'] is None else round(r['delta_vs_ctrl_bps'],2)}"
              f"  {'; '.join(r['alasan_gagal']) if r['alasan_gagal'] else ''}")

    lolos = [r for r in short if r["lolos"]]
    print(f"\nKANDIDAT LOLOS = {len(lolos)}")

    # ---------- 4. catatan struktural ----------
    blocker = ("Tidak ada panel Binance 1h. Semua arm horizon-48-jam di kerangka 1h "
               "(termasuk RANGEPOS_H48 +16,93) TIDAK BISA diuji replikasi lintas-venue, "
               "karena syarat R1 butuh seri kedua pada interval bar yang sama. "
               "Konsekuensi: jalur 48 jam ber-kerangka 1h secara STRUKTURAL tidak "
               "tersertifikasi di bawah protokol saat ini, sekuat apa pun gross-nya.")
    print(f"\nCATATAN STRUKTURAL: {blocker}")

    # --- ringkas: arm 48 jam ber-interval 1d yang positif di KEDUA venue ---
    by = {}
    for r in arms48:
        by.setdefault((r["mech"], r["hold"]), {})[r["panel"]] = r
    dua_venue = []
    for (m, h), ps in sorted(by.items()):
        if h != 2 or "binance_1d" not in ps or "sodex_1d" not in ps:
            continue
        gb, gs = ps["binance_1d"]["gross_bps"], ps["sodex_1d"]["gross_bps"]
        dua_venue.append({"mech": m, "hold": h, "gross_binance": gb, "gross_sodex": gs,
                          "dua2nya_positif": gb > 0 and gs > 0,
                          "r1": (m, h) in r1_pass,
                          "t_binance": ps["binance_1d"]["t"], "n_binance": ps["binance_1d"]["n"],
                          "t_sodex": ps["sodex_1d"]["t"], "n_sodex": ps["sodex_1d"]["n"]})
    print("\n=== ARM 48 JAM (interval 1d) POSITIF DI KEDUA VENUE? ===")
    for x in dua_venue:
        print(f"  {x['mech']:<12} bin={x['gross_binance']:>7.2f}(n={x['n_binance']},t={x['t_binance']:>5.2f})"
              f" sodex={x['gross_sodex']:>7.2f}(n={x['n_sodex']},t={x['t_sodex']:>5.2f})"
              f"  dua2nya_positif={x['dua2nya_positif']}  R1={'LULUS' if x['r1'] else 'gagal'}")

    # --- mutu-panel: korelasi IC <-> PnL (harus positif; kalau tidak, panel tak
    #     boleh dipakai sebagai bukti ekonomi meski IC-nya bagus) ---
    konsist = {}
    print("\n=== MUTU PANEL: corr(IC, gross) antar-mekanisme ===")
    for p in PANELS:
        ics, gg = [], []
        for a in docs[p]["results"].values():
            v = a.get("fee1x")
            if not v:
                continue
            ics.append(v["ic_mean"])
            gg.append(v["mean_bps_per_period"] + v["fee_bps"])
        c = pearson(ics, gg) if len(ics) > 2 else float("nan")
        se = 1.0 / math.sqrt(len(ics) - 1) if len(ics) > 2 else float("nan")
        konsist[p] = {"n_arm": len(ics), "corr_ic_gross": c, "se_kasar": se,
                      "searah": bool(c > 0)}
        print(f"  {p:<12} n_arm={len(ics):>3}  corr={c:>+7.3f} (se~{se:.3f})  "
              f"{'SEARAH' if c > 0 else 'MENYIMPANG'}")

    out = {
        "generated_utc": "2026-10-08",
        "disclaimer": ("DESKRIPTIF — jendela historis sudah terpakai; tidak sah sebagai "
                       "verdict lulus/gagal. Tidak ada ambang yang diubah."),
        "aturan": {"R1": "replikasi lintas-venue interval sama (tanda IC sama & rasio>=0.5)",
                   "R2": "lintas-frekuensi dilemahkan: nama mekanisme per-BAR, bukan per-waktu",
                   "R3": f"gross>0 & turnover<={TO_MAX} & net(fee1x)>0",
                   "R4": f"|IC_ctrl| < {IC_CTRL_MAX}",
                   "R5": f"|t_nw| >= {T_MIN} pada arm yang disaring"},
        "arm_48jam": arms48, "replikasi_R1": repl,
        "mutu_panel": konsist,
        "positif_dua_venue": dua_venue,
        "n_R1_lulus": n_ok, "n_pasangan_teruji": n_pairs,
        "saringan": short, "kandidat_lolos": [r for r in short if r["lolos"]],
        "catatan_struktural": blocker,
    }
    dest = os.path.join(ROOT, "reports/sodex/SODEX_48H_CANDIDATE_SCREEN.json")
    with open(dest, "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(f"[ditulis] {dest}")


if __name__ == "__main__":
    main()
