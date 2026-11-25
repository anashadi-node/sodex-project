#!/usr/bin/env python3
"""Tracker maturasi SoDEX — DUA GATE TERPISAH (keputusan user 2026-09-28).

Gate dijalankan TERPISAH per metode futures, sampelnya TIDAK PERNAH digabung:
  GATE 1 · REAL-WIDE  — geometri paper TP6/SL1.5 (forward sejak 2026-09-05),
                        counterpart uang nyata: data/realwide_micro_live_state.json
  GATE 2 · TWO-WAY    — geometri paper TP4/SL2 (long+short), belum ada jalur live

Tiap gate punya verdict sendiri. Penggabungan sampel antar metode akan
menyamarkan metode yang lemah di balik metode yang kuat, jadi dilarang di sini.

Definisi target (user, harga mati): >=0.8% dari TOTAL wallet divisi (spot+perps)
per window 30 jam, AKUMULASI. Karena itu gate ROI memakai akumulasi per window
(bukan rata-rata per trade) dan butuh >=10 window penuh agar bermakna.

READ-ONLY. Tidak menyentuh live/state.
"""
from __future__ import annotations
import json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / "data" / "sodex_maturation_status.json"

# Gate statistik minimum (approved 2026-09-05, dipakai sama untuk kedua gate).
MIN_N = 50
MIN_WR = 0.50
MIN_PF = 1.5
MIN_WINDOW_ROI = 0.008    # >=0.8% TOTAL wallet per window 30h (target user)
MIN_WINDOWS = 10
WINDOW_H = 30.0
SNAPSHOT_MAX_AGE_H = 6.0
WALLET_FALLBACK = 108.10

# ── AMANDEMEN DEFINISI TARGET (approval Mas Anas, 10-Okt-2026) ───────────────
# Target 0,8% sekarang diukur sebagai DUA syarat sekaligus (A DAN B):
#   A = MEAN window >= 0,8%   (akumulasi)
#   B = MEDIAN window > 0 DAN hit(window >= 0,8%) >= 50%   (konsistensi)
# dihitung pada GRID TETAP 30 jam dengan jangkar absolut (bukan grid dari span
# sampel, yang membuat hasil bergantung subset). Window KOSONG dilewati (tidak
# dihitung 0,0%) supaya subset sebanding; jumlahnya dilaporkan sebagai n_empty.
# Alasan: median mendekati 0 & hit mendekati 50% membuat B sangat sensitif pada
# pilihan grid → grid harus dipatok agar verdict tidak bisa digeser.
ANCHOR_FIXED_TS = datetime(2026, 8, 3, 0, 0, tzinfo=timezone.utc).timestamp()

# Geomteri baru REAL-WIDE mulai 2026-09-05 02:20 UTC (paper-only sejak itu).
RW_CUTOVER = datetime(2026, 9, 5, 2, 20, 0, tzinfo=timezone.utc).timestamp()

# Konfigurasi dua gate terpisah. `cutover=None` = pakai seluruh riwayat track.
GATES = [
    {
        "id": "REAL-WIDE",
        "geometry": "paper TP6/SL1.5 · live TP6/SL3",
        "state": "data/paper_test_realwide_state.json",
        "cutover": RW_CUTOVER,
        "exclude_paused": True,
        "live_state": "data/realwide_micro_live_state.json",
        "note": "long-only futures 3x, TIME_STOP 24h",
    },
    {
        "id": "TWO-WAY",
        "geometry": "paper TP4/SL2",
        "state": "data/paper_test_twoway_state.json",
        "cutover": None,
        "exclude_paused": False,
        "live_state": None,
        "note": "long+short futures 3x, TP4/SL2, belum ada jalur uang nyata",
    },
]

WALLET = WALLET_FALLBACK
WALLET_SOURCE = "belum-dibaca"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_live_wallet() -> tuple[float, str]:
    """Denominator ROI = TOTAL wallet divisi SoDEX (spot equity + perps vUSDC).

    Snapshot on-chain didahulukan atas env: .env.swing menyimpan angka statis
    ($174.55) yang tidak ikut bergerak saat equity berubah -> ROI ter-inflasi.
    """
    snap = PROJECT / "data" / "sodex_real_sync_snapshot.json"
    try:
        d = json.loads(snap.read_text())
        gen = datetime.fromisoformat(str(d.get("generated_utc")).replace("Z", "+00:00"))
        if (datetime.now(timezone.utc) - gen).total_seconds() / 3600.0 <= SNAPSHOT_MAX_AGE_H:
            spot = float(d.get("spot_equity_usd") or 0)
            spot_flag = ""
            if spot <= 0:
                # FIX 2026-10-25: mark-to-market spot gagal (mis. HTTP 429) -> spot_equity_usd
                # TIDAK ditulis. Sebelumnya spot=0 lolos guard (perps>=20) sehingga denominator
                # UNDERSTATED ~21% dan semua ROI% ter-inflasi (bug kelas fail-open, Rule 7).
                sv = d.get("spot_vusdc") or {}
                spot = float(sv.get("total") or 0) if isinstance(sv, dict) else 0.0
                if d.get("spot_mark_error"):
                    spot_flag = "+SPOT_UNMARKED(lower-bound)"
            pb = d.get("perps_balance") or {}
            perps = float(pb.get("total") or 0) if isinstance(pb, dict) else 0.0
            if spot + perps >= 20:
                return spot + perps, (f"onchain_snapshot@{gen.strftime('%m-%d %H:%M')}Z"
                                      f"{spot_flag}")
    except Exception:
        pass
    env = os.environ.get("SODEX_TOTAL_WALLET")
    if env:
        try:
            return float(env), "env_SODEX_TOTAL_WALLET"
        except ValueError:
            pass
    try:
        m = re.search(r"^SODEX_TOTAL_WALLET=([\d.]+)", (PROJECT / ".env.swing").read_text(), re.M)
        if m:
            return float(m.group(1)), ".env.swing(statis)"
    except Exception:
        pass
    return WALLET_FALLBACK, "fallback_hardcoded"


def _gate_paused_pairs():
    """Pairs di-pause pair-gate REAL-wide. Fail-safe ke list riset bila gagal baca."""
    fallback = {"SUI", "ADA", "HYPE", "ONDO"}
    try:
        g = json.loads((PROJECT / "data" / "paper_test_edge_gate.json").read_text())
        paused = (g.get("pairs_pause") or {}).get("REAL-wide") or []
        return (set(paused) | fallback) if paused else fallback
    except Exception:
        return fallback


def _parse_ts(v):
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _norm_trades(doc):
    """Normalisasi skema beda antar track -> list {exit_ts, pnl_usd, pnl_pct, sym}."""
    for key in ("closed", "closed_trades", "trades"):
        rows = doc.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        out = []
        for t in rows:
            # Exit terlambat (feed mati): PnL dihitung pada harga saat proses pulih,
            # bukan pada harga ketika exit seharusnya terjadi -> tidak sah untuk gate.
            if t.get("stale_exit"):
                continue
            ts = t.get("exit_ts")
            if ts is None:
                for f in ("exit_iso", "exit_time"):
                    if t.get(f):
                        ts = _parse_ts(t.get(f))
                        break
            usd = t.get("pnl_usd")
            if ts is None or usd is None:
                continue
            pct = t.get("pnl_pct")
            out.append({"exit_ts": float(ts), "pnl_usd": float(usd),
                        "pnl_pct": float(pct) if pct is not None else None,
                        "sym": t.get("sym") or t.get("pair"),
                        "direction": t.get("direction") or t.get("side")})
        return out
    return []


def load_gate_trades(gate):
    p = PROJECT / gate["state"]
    if not p.exists():
        return []
    trades = _norm_trades(json.loads(p.read_text()))
    if gate.get("cutover"):
        trades = [t for t in trades if t["exit_ts"] > gate["cutover"]]
    if gate.get("exclude_paused"):
        blk = _gate_paused_pairs()
        trades = [t for t in trades if str(t.get("sym") or "").split("/")[0] not in blk]
    return trades


def load_live_evidence(rel):
    """Counterpart uang nyata sebuah gate (kalau ada). Terpisah dari sampel paper."""
    if not rel:
        return None
    p = PROJECT / rel
    if not p.exists():
        return None
    try:
        cl = _norm_trades(json.loads(p.read_text()))
    except Exception:
        return None
    if not cl:
        return {"n_real": 0, "note": "belum ada trade uang nyata"}
    usd = [t["pnl_usd"] for t in cl]
    wins = sum(1 for t in cl if t["pnl_usd"] > 0)
    return {"n_real": len(cl), "usd_real": round(sum(usd), 2),
            "wr_real": round(wins / len(cl), 4),
            "best_real": round(max(usd), 2), "worst_real": round(min(usd), 2)}


def window_metrics(trades, wallet):
    """GERBANG RESMI (sejak 10-Okt-2026): akumulasi PnL per window 30 jam pada
    GRID TETAP (jangkar 2026-08-03Z). Window kosong DILEWATI + dilaporkan."""
    pts = sorted((float(t["exit_ts"]), float(t["pnl_usd"] or 0)) for t in trades if t.get("exit_ts"))
    if len(pts) < 2:
        return None
    b: dict[int, float] = {}
    for ts, usd in pts:
        k = int((ts - ANCHOR_FIXED_TS) // (WINDOW_H * 3600))
        if k < 0:
            continue
        b[k] = b.get(k, 0.0) + usd
    if len(b) < 2:
        return None
    vals = [100.0 * b[k] / wallet for k in sorted(b)]
    nw = len(vals)
    srt = sorted(vals)
    med = srt[nw // 2] if nw % 2 else 0.5 * (srt[nw // 2 - 1] + srt[nw // 2])
    hit = sum(1 for v in vals if v >= MIN_WINDOW_ROI * 100)
    span = max(b) - min(b) + 1
    mean_pct = sum(vals) / nw
    # Tangga target resmi (AMANDEMEN_TANGGA_TARGET_RESMI_2026-10-22, Opsi 2):
    # tingkat tertinggi yang lolos A&B (mean>=ambang, median>0, hit>=50%).
    # Gate A&B lama di 0,8% TETAP dihitung apa adanya di bawah -- ini TAMBAHAN
    # konteks, bukan pengganti.
    tangga = []
    for nama, amb in (("lantai", 0.10), ("sasaran", 0.25), ("stretch", 0.40), ("penuh", 0.80)):
        h = sum(1 for v in vals if v >= amb)
        if mean_pct >= amb and med > 0 and (h / nw) >= 0.5:
            tangga.append(nama)
    tingkat_tangga = tangga[-1] if tangga else "belum_lantai"
    return {"n_windows": nw, "grid": "fixed-anchor-2026-08-03Z",
            "n_empty": span - nw, "w_pertama": min(b), "w_terakhir": max(b),
            "span_h": round((max(b) - min(b)) * WINDOW_H, 1),
            "mean_pct": mean_pct, "median_pct": med,
            "hit": hit, "hit_rate": hit / nw,
            "worst_pct": min(vals), "best_pct": max(vals),
            "gate_A_mean": (mean_pct) >= MIN_WINDOW_ROI * 100,
            "gate_B_konsisten": (med > 0 and (hit / nw) >= 0.5),
            "tingkat_tangga": tingkat_tangga,
            }


def window_metrics_span(trades, wallet):
    """PEMBANDING (definisi lama): grid dari span sampel, window kosong = 0,0%.
    Tidak lagi dipakai untuk verdict — hanya untuk jejak/komparabilitas."""
    pts = sorted((float(t["exit_ts"]), float(t["pnl_usd"] or 0)) for t in trades if t.get("exit_ts"))
    if len(pts) < 2:
        return None
    t0, t1 = pts[0][0], pts[-1][0]
    span_h = (t1 - t0) / 3600.0
    nw = int(span_h // WINDOW_H)
    if nw < 1:
        return None
    b: dict[int, float] = {}
    for ts, usd in pts:
        k = min(int((ts - t0) // (WINDOW_H * 3600)), nw - 1)
        b[k] = b.get(k, 0.0) + usd
    vals = [100.0 * b.get(i, 0.0) / wallet for i in range(nw)]
    srt = sorted(vals)
    med = srt[len(srt) // 2] if len(srt) % 2 else 0.5 * (srt[len(srt) // 2 - 1] + srt[len(srt) // 2])
    hit = sum(1 for v in vals if v >= MIN_WINDOW_ROI * 100)
    return {"n_windows": nw, "span_h": round(span_h, 1), "mean_pct": sum(vals) / nw,
            "median_pct": med, "hit": hit, "hit_rate": hit / nw,
            "worst_pct": min(vals), "best_pct": max(vals)}


def evaluate_trades(trades, wallet=None, gate_id="?", geometry="?"):
    """Evaluasi SATU gate. Tidak menerima gabungan sampel antar metode."""
    wallet = WALLET if wallet is None else wallet
    n = len(trades)
    out = {"gate": gate_id, "geometry": geometry, "n": n, "target_n": MIN_N,
           "wallet_usd": round(wallet, 2), "wallet_source": WALLET_SOURCE}
    if n == 0:
        out["verdict"] = "COLLECTING — belum ada trade pada sampel gate ini"
        return out
    pcts = [t["pnl_pct"] for t in trades if t.get("pnl_pct") is not None]
    usds = [float(t["pnl_usd"] or 0) for t in trades]
    wins = sum(1 for p in pcts if p > 0)
    gp = sum(p for p in pcts if p > 0)
    gl = -sum(p for p in pcts if p <= 0)
    wr = (wins / len(pcts)) if pcts else None
    pf = (gp / gl) if gl > 0 else float("inf")
    out.update({
        "wr": round(wr, 4) if wr is not None else None,
        "pf": (round(pf, 3) if pf != float("inf") else 999) if pcts else None,
        "avg_pct_per_trade": round(100 * sum(pcts) / len(pcts), 4) if pcts else None,
        "per_trade_roi_pct": round(100 * (sum(usds) / n) / wallet, 4),
        "total_usd": round(sum(usds), 2),
    })
    wm = window_metrics(trades, wallet)
    wms = window_metrics_span(trades, wallet)
    if wm:
        out.update({"window_grid": wm["grid"], "n_windows": wm["n_windows"],
                    "window_n_empty": wm["n_empty"],
                    "window_span_h": wm["span_h"],
                    "window_mean_pct": round(wm["mean_pct"], 4),
                    "window_median_pct": round(wm["median_pct"], 4),
                    "window_hit": wm["hit"], "window_hit_rate": round(wm["hit_rate"], 3),
                    "window_worst_pct": round(wm["worst_pct"], 3),
                    "window_best_pct": round(wm["best_pct"], 3),
                    "gate_A_mean": wm["gate_A_mean"], "gate_B_konsisten": wm["gate_B_konsisten"],
                    "tingkat_tangga": wm["tingkat_tangga"]})
    if wms:
        # jejak definisi lama (grid span, kosong=0,0%) — TIDAK dipakai untuk verdict
        out.update({"span_median_pct": round(wms["median_pct"], 4),
                    "span_mean_pct": round(wms["mean_pct"], 4),
                    "span_hit_rate": round(wms["hit_rate"], 3)})
    G = " (grid tetap)"      # label amandemen 10-Okt-2026
    gates = {f"n>={MIN_N}": n >= MIN_N,
             "WR>=50%": (wr is not None and wr >= MIN_WR),
             "PF>=1.5": (pcts and pf >= MIN_PF)}
    key = f"window_mean>=0.8%{G}"
    if wm is None or wm["n_windows"] < MIN_WINDOWS:
        gates[key] = False
        out["roi_gate_note"] = (f"butuh >={MIN_WINDOWS} window 30h penuh (grid tetap); "
                                f"tersedia {wm['n_windows'] if wm else 0}")
    else:
        gates[key] = wm["mean_pct"] >= MIN_WINDOW_ROI * 100
    # ── GERBANG KETAT (approval Mas Anas 30-Sep-2026, diperluas 10-Okt-2026) ──
    # Sebelumnya median & hit-rate hanya "caution" (himbauan) sehingga verdict GO
    # bisa lolos karena MEAN saja. Bukti nyata: `mean +1,86% · median +0,00% ·
    # hit 16/43 (37%)` → GO, padahal window TIPIKAL tidak untung dan mayoritas
    # window tidak capai target. Mean tertarik OUTLIER (window terbaik +37%).
    # 10-Okt-2026: syarat A (mean) DAN B (median>0 & hit>=50%) kini diukur pada
    # GRID TETAP 30 jam (lihat AMANDEMEN di atas) — keduanya wajib lolos.
    if wm is not None and wm["n_windows"] >= MIN_WINDOWS:
        gates[f"window_median>0{G}"] = wm["median_pct"] > 0
        gates[f"window_hit>=50%{G}"] = wm["hit_rate"] >= 0.5
        gates[f"window_A&B{G}"] = bool(wm["gate_A_mean"] and wm["gate_B_konsisten"])
    else:
        gates[f"window_median>0{G}"] = False
        gates[f"window_hit>=50%{G}"] = False
        gates[f"window_A&B{G}"] = False
    out["gates"] = gates
    if wm:
        caut = []
        if wm["median_pct"] < MIN_WINDOW_ROI * 100:
            caut.append(f"median window {wm['median_pct']:+.2f}% < 0.8%")
        if wm["hit_rate"] < 0.5:
            caut.append(f"hanya {wm['hit']}/{wm['n_windows']} window capai 0.8%")
        if wm["worst_pct"] <= -10:
            caut.append(f"window terburuk {wm['worst_pct']:+.1f}%")
        if caut:
            out["caution"] = "; ".join(caut)
    failed = [k for k, v in gates.items() if not v]
    if not failed:
        out["verdict"] = "GO"
    elif n < MIN_N:
        out["verdict"] = f"COLLECTING — {n}/{MIN_N} trade"
    else:
        out["verdict"] = f"NO-GO — gate gagal: {', '.join(failed)}"
    return out


def main():
    global WALLET, WALLET_SOURCE
    WALLET, WALLET_SOURCE = _read_live_wallet()
    res = {"generated_utc": now_iso(), "wallet_usd": round(WALLET, 2),
           "wallet_source": WALLET_SOURCE, "mode": "DUA GATE TERPISAH",
           "gates": {}, "verdicts": {}}
    print(f"=== MATURASI SoDEX — DUA GATE TERPISAH — {res['generated_utc'][:19]} UTC ===")
    print(f"Wallet (TOTAL spot+perps): ${res['wallet_usd']} [{WALLET_SOURCE}]")
    print(f"Target: >=0.8% wallet per window 30h = ${WALLET * 0.008:.2f}\n")
    for g in GATES:
        trades = load_gate_trades(g)
        ev = evaluate_trades(trades, WALLET, g["id"], g["geometry"])
        ev["note"] = g.get("note", "")
        ev["live"] = load_live_evidence(g.get("live_state"))
        res["gates"][g["id"]] = ev
        res["verdicts"][g["id"]] = ev["verdict"]
        print(f"── GATE {g['id']} ({g['geometry']})")
        print(f"   sampel gate ini saja: n={ev['n']}" + (
            f" WR={ev['wr']*100:.1f}% PF={ev['pf']}" if ev.get("wr") else ""))
        if "n_windows" in ev:
            print(f"   window 30h: n={ev['n_windows']} mean={ev['window_mean_pct']:+.3f}% "
                  f"median={ev['window_median_pct']:+.3f}% hit={ev['window_hit']}/{ev['n_windows']} "
                  f"worst={ev['window_worst_pct']:+.2f}%")
        print(f"   gate: {ev['gates']}")
        if ev.get("caution"):
            print(f"   ⚠ caution: {ev['caution']}")
        lv = ev.get("live")
        if lv:
            print(f"   uang nyata: n={lv.get('n_real', 0)} net=${lv.get('usd_real', 0)} "
                  f"WR={lv.get('wr_real')} wins={lv.get('best_real')} worst={lv.get('worst_real')}")
        print(f"   VERDICT: {ev['verdict']}\n")
    # Key legacy dipertahankan (= gate REAL-WIDE) agar dashboard tetap kompatibel.
    primary = res["gates"]["REAL-WIDE"]
    res.update({"n_forward": primary["n"], "target_n": MIN_N,
                "verdict": f"[REAL-WIDE] {primary['verdict']}"})
    OUT.write_text(json.dumps(res, indent=1))
    print(f"Snapshot: {OUT}")


if __name__ == "__main__":
    main()
