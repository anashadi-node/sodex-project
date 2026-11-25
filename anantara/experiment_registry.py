"""
ANANTARA SAKTI — Experiment Registry v1.0

RS-8 (Audit Fable 5/6): Resmikan pabrik — eksperimen sebagai primitive platform.

Masalah tanpa registry:
  - 100 subkelompok bisa diuji (mudah, tidak ter-record)
  - Parameter berubah tanpa batas antar-eksperimen
  - Tidak ada power analysis ex-ante (n_target tidak didefinisikan)
  - FDR tidak dikontrol lintas hipotesis
  - Eksperimen "selesai" saat hasilnya bagus, bukan saat n_target tercapai

Registry ini menyediakan:
  1. Pre-registration: hipotesis + kriteria GO/NO-GO DITULIS sebelum data dikumpulkan
  2. Power tracking: progres n_current / n_target (Telegram setiap hari)
  3. FDR control: Benjamini-Hochberg lintas semua eksperimen aktif
  4. Auto-close: eksperimen ditutup otomatis saat n_target tercapai (bukan saat hasilnya bagus)
  5. Verdict permanen: hasil ditulis ke knowledge vault saat eksperimen selesai

Pure stdlib. Zero external deps.
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("anantara.experiments")

_PROJECT_DIR  = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
_REGISTRY_DIR = _PROJECT_DIR / "experiments"
_REGISTRY_FILE = _REGISTRY_DIR / "registry.json"
_KNOWLEDGE_DIR = _PROJECT_DIR / "knowledge" / "articles"


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Experiment:
    """Satu eksperimen yang terdaftar dalam registry."""
    exp_id:       str
    name:         str
    engine:       str           # "pregain" | "cex" | "sodex" | "hl_harvest" | "platform"
    hypothesis:   str           # H0 yang diuji (dirumuskan SEBELUM data)
    go_criteria:  dict          # {"min_wr": 0.65, "min_e": 0.3, ...}
    n_target:     int           # n yang dibutuhkan (dari power analysis ex-ante)
    alpha:        float         # α level (default 0.05)
    registered_at: str = field(default_factory=lambda: _utc_now())
    status:        str = "ACTIVE"   # "ACTIVE" | "CLOSED" | "EXPIRED"
    n_current:     int = 0
    verdict:       str = ""         # "GO" | "NO_GO" | "INCONCLUSIVE" | ""
    closed_at:     str = ""
    notes:         str = ""
    arm_control:   str = ""         # ID eksperimen kontrol (jika ada arm acak)
    p_value:       float = -1.0     # p-value akhir (-1 = belum dihitung)
    effect_size:   float = -1.0     # effect size (Cohen's h atau d)
    bh_adjusted_alpha: float = -1.0  # BH-adjusted α setelah FDR correction

    def power_pct(self) -> float:
        return min(100.0, self.n_current / max(1, self.n_target) * 100)

    def days_since_register(self) -> float:
        try:
            t = datetime.fromisoformat(self.registered_at).replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - t).total_seconds() / 86400
        except Exception:
            return 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Experiment":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.rename(path)
    except Exception as e:
        log.error(f"[REGISTRY] write {path.name}: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _read_registry() -> dict:
    try:
        return json.loads(_REGISTRY_FILE.read_text())
    except Exception:
        return {"version": "1.0", "experiments": []}


def _save_registry(data: dict) -> None:
    _write_atomic(_REGISTRY_FILE, data)


# ─────────────────────────────────────────────────────────────────────────────
# POWER ANALYSIS (ex-ante, stdlib-only)
# ─────────────────────────────────────────────────────────────────────────────

def compute_n_target(p0: float, p1: float, alpha: float = 0.05,
                     power: float = 0.80) -> int:
    """
    Hitung n minimal untuk mendeteksi perbedaan proporsi p0 vs p1.
    One-sided test (kita menguji p1 > p0).

    Menggunakan aproksimasi normal (stdlib-only, tanpa scipy).
    Formula: Fleiss, Levin, Paik (2003) dua-proporsi z-test.

    Args:
        p0: proporsi null (WR saat ini / baseline)
        p1: proporsi alternatif (WR yang ingin dideteksi)
        alpha: level signifikansi (default 0.05)
        power: 1 - β (default 0.80)

    Returns:
        n minimal per arm
    """
    if p0 <= 0 or p1 <= 0 or p0 >= 1 or p1 >= 1:
        return 100  # fallback konservatif

    # z-scores dari normal standar (approx stdlib)
    def _z_norm(p: float) -> float:
        # Rational approximation (Abramowitz & Stegun 26.2.17)
        t = math.sqrt(-2 * math.log(p))
        c0, c1, c2 = 2.515517, 0.802853, 0.010328
        d1, d2, d3 = 1.432788, 0.189269, 0.001308
        return t - (c0 + c1*t + c2*t**2) / (1 + d1*t + d2*t**2 + d3*t**3)

    z_alpha = _z_norm(alpha)    # ~1.645 untuk α=0.05 one-sided
    z_beta  = _z_norm(1 - power)  # ~0.842 untuk power=0.80

    # Effect size Cohen's h
    phi1 = 2 * math.asin(math.sqrt(p1))
    phi0 = 2 * math.asin(math.sqrt(p0))
    h    = abs(phi1 - phi0)

    if h < 1e-6:
        return 9999  # efek terlalu kecil untuk dideteksi

    n = ((z_alpha + z_beta) / h) ** 2
    return max(30, math.ceil(n))   # minimum 30 observasi


# ─────────────────────────────────────────────────────────────────────────────
# FDR CONTROL — Benjamini-Hochberg (G3 dari pregain_validation_gates)
# ─────────────────────────────────────────────────────────────────────────────

def apply_bh_correction(p_values: list[float], alpha: float = 0.05) -> list[float]:
    """
    Benjamini-Hochberg FDR correction untuk multiple hypothesis testing.
    Mengembalikan adjusted α per hipotesis (bukan adjusted p-value).

    Args:
        p_values: list p-value dari semua hipotesis aktif
        alpha: target FDR level

    Returns:
        list adjusted_alpha per hipotesis (urutan sama dengan input)
    """
    m = len(p_values)
    if m == 0:
        return []

    # BH: rank p-values ascending, threshold = (i/m) * α
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [0.0] * m

    for rank, (orig_idx, p) in enumerate(indexed, 1):
        adjusted[orig_idx] = (rank / m) * alpha

    return adjusted


# ─────────────────────────────────────────────────────────────────────────────
# CORE API
# ─────────────────────────────────────────────────────────────────────────────

def register(
    exp_id:     str,
    name:       str,
    engine:     str,
    hypothesis: str,
    go_criteria: dict,
    p0:         float,
    p1:         float,
    alpha:      float = 0.05,
    power:      float = 0.80,
    notes:      str   = "",
    arm_control: str  = "",
) -> Experiment:
    """
    Pre-register eksperimen baru.

    Hipotesis dan kriteria GO HARUS ditulis SEBELUM data dikumpulkan.
    n_target dihitung otomatis dari power analysis.

    Returns: Experiment yang baru terdaftar.
    """
    data = _read_registry()
    existing_ids = {e["exp_id"] for e in data.get("experiments", [])}
    if exp_id in existing_ids:
        raise ValueError(f"Eksperimen '{exp_id}' sudah terdaftar.")

    n_target = compute_n_target(p0, p1, alpha, power)

    exp = Experiment(
        exp_id=exp_id,
        name=name,
        engine=engine,
        hypothesis=hypothesis,
        go_criteria=go_criteria,
        n_target=n_target,
        alpha=alpha,
        notes=notes,
        arm_control=arm_control,
    )

    data.setdefault("experiments", []).append(exp.to_dict())
    data["updated_utc"] = _utc_now()
    _save_registry(data)

    log.info(
        f"[REGISTRY] Registered: {exp_id} | n_target={n_target} "
        f"(p0={p0:.0%}→p1={p1:.0%}, α={alpha}, power={power:.0%})"
    )
    return exp


def update_progress(exp_id: str, n_current: int,
                    p_value: float = -1.0,
                    effect_size: float = -1.0) -> Optional[Experiment]:
    """Update n_current dan p_value eksperimen. Kembalikan Experiment yang diperbarui."""
    data = _read_registry()
    for e in data.get("experiments", []):
        if e["exp_id"] == exp_id:
            e["n_current"]   = n_current
            e["p_value"]     = p_value
            e["effect_size"] = effect_size
            data["updated_utc"] = _utc_now()
            _save_registry(data)
            return Experiment.from_dict(e)
    log.warning(f"[REGISTRY] update_progress: '{exp_id}' tidak ditemukan")
    return None


def close_experiment(exp_id: str, verdict: str,
                     p_value: float = -1.0,
                     effect_size: float = -1.0,
                     notes: str = "") -> Optional[Experiment]:
    """
    Tutup eksperimen dengan verdict final.

    verdict: "GO" | "NO_GO" | "INCONCLUSIVE"
    Setelah closed, tulis verdict ke knowledge vault.
    """
    data = _read_registry()
    for e in data.get("experiments", []):
        if e["exp_id"] == exp_id:
            e["status"]      = "CLOSED"
            e["verdict"]     = verdict
            e["closed_at"]   = _utc_now()
            e["p_value"]     = p_value
            e["effect_size"] = effect_size
            if notes:
                e["notes"] = notes
            data["updated_utc"] = _utc_now()
            _save_registry(data)

            exp = Experiment.from_dict(e)
            _write_verdict_to_knowledge(exp)
            log.info(f"[REGISTRY] Closed: {exp_id} → {verdict}")
            return exp
    log.warning(f"[REGISTRY] close: '{exp_id}' tidak ditemukan")
    return None


def get_experiment(exp_id: str) -> Optional[Experiment]:
    data = _read_registry()
    for e in data.get("experiments", []):
        if e["exp_id"] == exp_id:
            return Experiment.from_dict(e)
    return None


def list_active() -> list[Experiment]:
    data = _read_registry()
    return [
        Experiment.from_dict(e)
        for e in data.get("experiments", [])
        if e.get("status") == "ACTIVE"
    ]


def list_all() -> list[Experiment]:
    data = _read_registry()
    return [Experiment.from_dict(e) for e in data.get("experiments", [])]


# ─────────────────────────────────────────────────────────────────────────────
# AUTO-CLOSE CHECK
# ─────────────────────────────────────────────────────────────────────────────

def check_auto_close(exp: Experiment) -> Optional[str]:
    """
    Periksa apakah eksperimen harus ditutup otomatis.

    Returns: verdict jika harus ditutup, None jika masih berjalan.
    """
    if exp.status != "ACTIVE":
        return None

    # n_target tercapai → auto-close
    if exp.n_current >= exp.n_target:
        # Evaluasi kriteria GO
        go_ok = True
        criteria = exp.go_criteria

        if "min_wr" in criteria and exp.p_value >= 0:
            # p_value di sini adalah WR terukur (diisi oleh update_progress)
            go_ok = go_ok and (exp.p_value >= criteria["min_wr"])

        if "max_p_value" in criteria and exp.p_value >= 0:
            go_ok = go_ok and (exp.p_value <= criteria["max_p_value"])

        if "min_e" in criteria and exp.effect_size >= 0:
            go_ok = go_ok and (exp.effect_size >= criteria["min_e"])

        return "GO" if go_ok else "NO_GO"

    # Eksperimen kadaluarsa (> 90 hari tanpa mencapai n_target)
    if exp.days_since_register() > 90:
        return "INCONCLUSIVE"

    return None


# ─────────────────────────────────────────────────────────────────────────────
# FDR LINTAS EKSPERIMEN
# ─────────────────────────────────────────────────────────────────────────────

def compute_fdr_corrections() -> list[dict]:
    """
    Hitung BH FDR correction untuk semua eksperimen aktif dengan p_value tersedia.
    Returns list dicts dengan exp_id + adjusted_alpha.
    """
    active = [e for e in list_active() if e.p_value >= 0]
    if not active:
        return []

    p_vals = [e.p_value for e in active]
    adj    = apply_bh_correction(p_vals, alpha=0.05)

    results = []
    data = _read_registry()
    for exp, adj_alpha in zip(active, adj):
        for e in data.get("experiments", []):
            if e["exp_id"] == exp.exp_id:
                e["bh_adjusted_alpha"] = adj_alpha
        results.append({"exp_id": exp.exp_id, "p_value": exp.p_value,
                         "bh_adjusted_alpha": adj_alpha})

    data["updated_utc"] = _utc_now()
    _save_registry(data)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# KNOWLEDGE VAULT INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────

def _write_verdict_to_knowledge(exp: Experiment) -> None:
    """Tulis verdict eksperimen ke knowledge vault sebagai artikel permanen."""
    try:
        _KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        slug   = exp.exp_id.lower().replace(" ", "_")
        fname  = _KNOWLEDGE_DIR / f"experiment-{slug}-verdict.md"
        closed_wib = ""
        try:
            t = datetime.fromisoformat(exp.closed_at).replace(tzinfo=timezone.utc)
            t_wib = t + timedelta(hours=7)
            closed_wib = t_wib.strftime("%Y-%m-%d %H:%M WIB")
        except Exception:
            pass

        content = f"""# Experiment: {exp.name}

**ID:** `{exp.exp_id}`
**Engine:** {exp.engine}
**Verdict:** {exp.verdict}
**Closed:** {closed_wib}
**n_reached:** {exp.n_current} / {exp.n_target} (target)

## Hipotesis
{exp.hypothesis}

## Kriteria GO
```json
{json.dumps(exp.go_criteria, indent=2)}
```

## Hasil
- p-value: {exp.p_value:.4f if exp.p_value >= 0 else 'N/A'}
- Effect size: {exp.effect_size:.4f if exp.effect_size >= 0 else 'N/A'}
- BH-adjusted α: {exp.bh_adjusted_alpha:.4f if exp.bh_adjusted_alpha >= 0 else 'N/A'}
- Days active: {exp.days_since_register():.1f}

## Catatan
{exp.notes or '(tidak ada)'}

---
*Generated oleh experiment_registry.py — RS-8 Audit Fable 5/6*
"""
        fname.write_text(content)
        log.info(f"[REGISTRY] Verdict ditulis ke knowledge: {fname.name}")
    except Exception as e:
        log.warning(f"[REGISTRY] write_verdict_to_knowledge: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# PROGRESS REPORT (untuk Telegram)
# ─────────────────────────────────────────────────────────────────────────────

def progress_report() -> str:
    """Format ringkasan progres semua eksperimen aktif untuk Telegram."""
    active = list_active()
    if not active:
        return "📋 *Experiment Registry*: Tidak ada eksperimen aktif."

    lines = [f"📋 *Experiment Progress* ({len(active)} aktif)"]
    for exp in active:
        bar_filled = int(exp.power_pct() / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        p_str = f"p={exp.p_value:.3f}" if exp.p_value >= 0 else "p=?"
        lines.append(
            f"\n*{exp.name}* ({exp.engine})\n"
            f"  `{bar}` {exp.power_pct():.0f}% "
            f"({exp.n_current}/{exp.n_target}) {p_str}\n"
            f"  {exp.hypothesis[:80]}..."
        )

    # FDR corrections
    fdr = compute_fdr_corrections()
    if fdr:
        lines.append(f"\n*FDR (BH @ α=0.05):* {len(fdr)} eksperimen")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "list":
        exps = list_all()
        for e in exps:
            print(f"{e.exp_id:20} {e.status:8} {e.engine:12} "
                  f"{e.n_current}/{e.n_target:>4} ({e.power_pct():.0f}%) "
                  f"verdict={e.verdict or '-'}")
        if not exps:
            print("(registry kosong)")

    elif cmd == "report":
        print(progress_report())

    elif cmd == "fdr":
        results = compute_fdr_corrections()
        for r in results:
            print(r)
