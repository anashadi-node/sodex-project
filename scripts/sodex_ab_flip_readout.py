#!/usr/bin/env python3
"""Readout A/B exit REGIME_FLIP per arm (post-restart, bukan window 24 jam).

Arm:
  TREATMENT flip=0 : anantara-paper-swing, anantara-paper-swing-partial
  KONTROL  flip=1  : anantara-paper-swing-strict

Cut time = ActiveEnterTimestamp unit (trade sebelum restart masih pakai aturan
lama -> tidak boleh dihitung). Ambang verdict: n>=20 per arm, lalu bootstrap
CI95 atas mean pnl_pct; verdict hanya sah bila CI95 tidak memuat 0.

Dijalankan berkala oleh sodex-ab-flip-readout.timer; keluaran di-append ke
reports/sodex/AB_REGIMEFLIP_READOUT.md supaya keputusan tidak bergantung sesi.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sodex_lane_edge_24h as lane_edge  # noqa: E402

OUT = ROOT / "reports" / "sodex" / "AB_REGIMEFLIP_READOUT.md"
ARMS = [
    ("TREATMENT flip=0", "anantara-paper-swing", "data/paper_test_swing.jsonl"),
    ("TREATMENT flip=0+BTCgate", "anantara-paper-swing-partial",
     "data/paper_test_swing_partial.jsonl"),
    ("KONTROL flip=1", "anantara-paper-swing-strict", "data/paper_test_swing_strict.jsonl"),
    ("REFERENSI flip=0 (kontrol A/B 8)", "anantara-paper-swing", "data/paper_test_swing.jsonl"),
    ("AB8a geometri ATR", "anantara-paper-ab8atr", "data/paper_test_swing_ab8atr.jsonl"),
    ("AB8b trailing +1R", "anantara-paper-ab8trail", "data/paper_test_swing_ab8trail.jsonl"),
    ("AB9a sinyal-dibalik (geometri lama)", "anantara-paper-ab9a", "data/paper_test_twoway_ab9a.jsonl"),
    ("AB9b sinyal-dibalik + geometri OOS", "anantara-paper-ab9b", "data/paper_test_twoway_ab9b.jsonl"),
    ("AB9c hanya setup sudah-naik >=3% (root cause H5)", "anantara-paper-ab9c", "data/paper_test_twoway_ab9c.jsonl"),
]
MIN_N = 20


def unit_start(unit: str) -> datetime | None:
    try:
        raw = subprocess.run(
            ["systemctl", "--user", "show", "-p", "ActiveEnterTimestamp",
             "--timestamp=unix", unit],
            capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if "=" not in raw:
        return None
    val = raw.split("=", 1)[1].strip()
    if not val:
        return None
    if val.startswith("@"):          # --timestamp=unix -> "@1793938151"
        val = val[1:]
    try:
        return datetime.fromtimestamp(int(val), tz=timezone.utc)
    except ValueError:
        try:
            return datetime.fromisoformat(val).astimezone(timezone.utc)
        except ValueError:
            return None


def load_closed(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or '"pnl_pct"' not in line:
            continue
        i = line.find("{")
        if i > 0:
            line = line[i:]
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(rec.get("status", "")).upper() != "CLOSED":
            continue
        if not isinstance(rec.get("pnl_pct"), (int, float)):
            continue
        t = lane_edge.ts_of(rec)
        if t is None:
            continue
        rec["_t"] = t
        rows.append(rec)
    return rows


def ci95(vals: list[float]) -> tuple[float, float] | None:
    if len(vals) < 8:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    x = np.array(vals) * 100.0
    rng = np.random.default_rng(7)
    boot = x[rng.integers(0, len(x), size=(10000, len(x)))].mean(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return float(lo), float(hi)


def welch_p(a: list[float], b: list[float]) -> float | None:
    """p dua sisi uji Welch (varian tidak sama) antara dua arm."""
    if len(a) < 8 or len(b) < 8:
        return None
    try:
        from scipy import stats as sps
    except ImportError as exc:
        raise RuntimeError("Welch unavailable: install scipy in the analysis environment") from exc
    a_arr, b_arr = list(a), list(b)
    if len(set(a_arr)) == len(set(b_arr)) == 1:
        return 1.0 if a_arr[0] == b_arr[0] else 0.0
    result = sps.ttest_ind(a_arr, b_arr, equal_var=False)
    pvalue = float(result.pvalue)
    if not 0.0 <= pvalue <= 1.0:
        raise RuntimeError(f"Welch mengembalikan p-value tidak valid: {result}")
    return pvalue


def bh_fdr(pvals: dict) -> dict:
    """BH-FDR: q = p*m/rank, dimonotonkan dari p terbesar. Wajib karena readout
    menguji banyak arm sekaligus (5 arm = 5 hipotesis, alpha 0,05 mentah menipu)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, prev = {}, 1.0
    for i in range(m - 1, -1, -1):
        name, p = items[i]
        q = min(prev, p * m / (i + 1))
        out[name] = q
        prev = q
    return out


def verdict_for(n: int, mean_pp: float, ci, q: float | None = None,
                mean_ref_pp: float | None = None, min_n: int = MIN_N) -> str:
    """Verdict arm. Urutan prioritas: jumlah sampel dulu, lalu signifikansi vs
    referensi, lalu ambang roster uang nyata, lalu CI95 vs nol."""
    if n < min_n:
        return f"MONITOR (n<{min_n})"
    if mean_ref_pp is not None and q is not None and q < 0.05:
        arah = "LEBIH BAIK" if mean_pp > mean_ref_pp else "LEBIH BURUK"
        return f"{arah} dari referensi (BH q={q:.3f})"
    if ci and ci[0] > 0 and mean_pp >= 0.205:
        return "LOLOS ambang roster (CI95>0 dan >=0,205pp)"
    if ci and ci[1] < 0:
        return "EDGE NEGATIF (CI95<0)"
    return "BELUM SIGNIFIKAN"


def main() -> int:
    now = datetime.now(timezone.utc)
    lines = [f"\n## {now.isoformat(timespec='seconds')}", ""]
    arms_out = {}
    arms_out_flip = {}
    for label, unit, rel in ARMS:
        cut = unit_start(unit)
        rows = load_closed(ROOT / rel)
        if cut is None:
            lines.append(f"- {label} [{unit}]: cut time tidak terbaca — MONITOR")
            continue
        rows = [r for r in rows if r["_t"] >= cut]
        post = [float(r["pnl_pct"]) for r in rows]
        arms_out[label] = post
        arms_out_flip[label] = sum(1 for r in rows if "FLIP" in str(r.get("exit_reason")))
        if not post:
            continue
    ref = [k for k in arms_out if "REFERENSI" in k] or [k for k in arms_out if "KONTROL" in k]
    ref_name = ref[0] if ref else None
    ref_vals = arms_out.get(ref_name, []) if ref_name else []
    ref_mean = (sum(ref_vals) / len(ref_vals) * 100.0) if ref_vals else None
    pv = {}
    for k, v in arms_out.items():
        if k == ref_name or not v:
            continue
        p = welch_p(v, ref_vals)
        if p is not None:
            pv[k] = p
    qv = bh_fdr(pv) if pv else {}
    hist = []
    for label, unit, rel in ARMS:
        post = arms_out.get(label)
        if post is None:
            continue
        if not post:
            lines.append(f"- {label} [{unit}] n=0 — MONITOR")
            continue
        mean = sum(post) / len(post) * 100.0
        band = ci95(post)
        nflip = arms_out_flip.get(label, 0)
        q = qv.get(label)
        verdict = verdict_for(len(post), mean, band, q, ref_mean if label != ref_name else None,
                              min_n=MIN_N if len(post) >= MIN_N else MIN_N)
        band_txt = f" CI95[{band[0]:+.3f},{band[1]:+.3f}]pp" if band else ""
        q_txt = f" BH q={q:.4f}" if q is not None else ""
        lines.append(f"- {label} [{unit}]: n={len(post)} mean={mean:+.3f}pp{band_txt}{q_txt}"
                     f" (exit flip={nflip}) → **{verdict}**")
        hist.append({"ts": now.isoformat(timespec="seconds"), "arm": label, "unit": unit,
                     "n": len(post), "mean_pp": round(mean, 4),
                     "ci95": [round(band[0], 4), round(band[1], 4)] if band else None,
                     "q_bh": round(q, 5) if q is not None else None,
                     "ref": ref_name, "mean_ref_pp": round(ref_mean, 4) if ref_mean is not None else None,
                     "verdict": verdict})
    if ref_name and ref_mean is not None:
        for k, v in arms_out.items():
            if k != ref_name and v and "n=0" not in k:
                lines.append(f"  - DiD {k} − {ref_name}: "
                             f"{(sum(v) / len(v) * 100.0) - ref_mean:+.3f}pp "
                             f"(n={len(v)} vs {len(ref_vals)})")
    hist_path = ROOT / "data" / "sodex_ab_readout.jsonl"
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    with hist_path.open("a", encoding="utf-8") as fh:
        for h in hist:
            fh.write(json.dumps(h) + "\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
