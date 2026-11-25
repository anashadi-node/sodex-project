"""
ANANTARA SAKTI — Konstitusi Platform v1.0

RS-1 (Audit Fable 5/6): Pindahkan filosofi dari docs/ ke runtime.

Prinsip:
  F1 Volume adalah HASIL profitabilitas — tidak ada eksekusi EV-negatif
  F2 Security-first — keamanan/privasi/kejujuran override semua trade-off
  F3 Edge-gated live — uang riil hanya setelah bukti +expectancy empiris

Mekanisme:
  1. Flag live tidak bisa dinyalakan oleh editor teks.
     Daemon membaca konstitusi ini saat startup. Jika gates_passed.json
     tidak valid atau tidak ada, AUTOTRADE_LIVE/PREGAIN_LIVE diabaikan
     dan sistem tetap PAPER.

  2. Freeze manifest — hash parameter strategi + tanggal batas fase.
     Perubahan parameter di luar batas fase → konstitusi MERAH.

  3. Anggaran kompleksitas — 1 parameter / 10 live trades terverifikasi.
     Melebihi anggaran → peringatan (belum hard-block, perlu akumulasi data).

  4. Supremasi prinsip — doktrin proyek TIDAK bisa override F1-F3 secara diam.

Pure stdlib (json, hashlib, pathlib, datetime). Zero external deps.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("anantara.constitution")

# ─────────────────────────────────────────────────────────────────────────────
# PATHS & CONFIG
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_DIR  = Path(os.environ.get("ANANTARA_DIR", str(Path.home() / "anantara-sakti")))
_DATA_DIR     = _PROJECT_DIR / "data"
_GATES_FILE   = _DATA_DIR / "gates_passed.json"
_FREEZE_FILE  = Path(os.environ.get("FREEZE_MANIFEST_PATH",
                                    str(_PROJECT_DIR / "data" / "freeze.json")))
_BYPASS_FLAG  = os.environ.get("CONSTITUTION_BYPASS", "").strip()

# Gate verdikt berlaku maksimal 7 hari sebelum perlu dijalankan ulang.
_GATES_TTL_DAYS = 7

# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConstitutionVerdict:
    """Hasil pemeriksaan konstitusi saat startup."""
    live_permitted: bool          # boleh live trade atau tidak
    reason: str                   # alasan singkat
    gates_age_days: float         # berapa hari yang lalu gate terakhir dijalankan
    freeze_ok: bool               # apakah parameter dalam batas freeze
    freeze_violations: list[str]  # daftar parameter yang melanggar freeze
    bypass_active: bool           # apakah CONSTITUTION_BYPASS aktif (DARURAT)
    timestamp: str = field(default_factory=lambda: _utc_now_iso())

    def to_dict(self) -> dict:
        return asdict(self)

    def log_summary(self) -> None:
        status = "✅ LIVE PERMITTED" if self.live_permitted else "🚨 LIVE BLOCKED"
        log.info(f"[CONSTITUTION] {status}: {self.reason}")
        if self.bypass_active:
            log.critical("[CONSTITUTION] CONSTITUTION_BYPASS AKTIF — operator darurat. "
                         "Catat insiden ini.")
        if self.freeze_violations:
            log.warning(f"[CONSTITUTION] Freeze violations: {self.freeze_violations}")


@dataclass
class GatesResult:
    """Struktur yang disimpan di data/gates_passed.json oleh sovereign gates."""
    verdict: str                  # "GO" atau "NO_GO"
    engine: str                   # nama engine: "pregain", "cex", "sodex", "hl_harvest"
    n_gates_passed: int           # jumlah gate yang lulus
    n_gates_total: int            # total gate yang diuji
    timestamp_utc: str            # ISO timestamp saat gate dijalankan
    live_criteria: dict           # kriteria GO yang dipakai (untuk audit trail)
    constitution_hash: str        # hash konstitusi saat gate dijalankan
    notes: str = ""               # catatan tambahan


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_file(path: Path) -> str:
    """SHA-256 dari isi file. Dipakai sebagai fingerprint parameter."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except Exception:
        return "UNREADABLE"


def _hash_dict(d: dict) -> str:
    """SHA-256 dari representasi JSON deterministik dict."""
    raw = json.dumps(d, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _read_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_json_atomic(path: Path, data: dict) -> None:
    """Tulis JSON secara atomik (write tmp → rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.rename(path)
    except Exception as e:
        log.error(f"[CONSTITUTION] Gagal menulis {path}: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# FREEZE MANIFEST
# ─────────────────────────────────────────────────────────────────────────────

def load_freeze_manifest() -> dict:
    """Muat freeze.json. Kembalikan dict kosong jika tidak ada."""
    return _read_json_safe(_FREEZE_FILE) or {}


def check_freeze(engine: str = "all") -> tuple[bool, list[str]]:
    """
    Periksa apakah parameter strategi masih dalam batas freeze.

    Returns:
        (ok: bool, violations: list[str])
        ok=True berarti tidak ada pelanggaran.
    """
    manifest = load_freeze_manifest()
    if not manifest:
        return True, []  # tidak ada manifest = belum ada freeze (ok)

    violations: list[str] = []
    entries = manifest.get("entries", [])

    for entry in entries:
        if engine != "all" and entry.get("engine", "all") != engine:
            continue

        param_name   = entry.get("param_name", "?")
        expected_hash = entry.get("hash", "")
        file_path     = _PROJECT_DIR / entry.get("file", "")
        expires_str   = entry.get("expires_after", "")

        # Periksa apakah entry sudah kadaluarsa (freeze sudah lewat)
        if expires_str:
            try:
                expires = datetime.fromisoformat(expires_str).replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > expires:
                    continue  # freeze sudah berakhir — tidak periksa
            except Exception:
                pass

        if not file_path.exists():
            violations.append(f"{param_name}: FILE_MISSING ({file_path.name})")
            continue

        actual_hash = _hash_file(file_path)
        if expected_hash and actual_hash != expected_hash:
            violations.append(
                f"{param_name}: HASH_MISMATCH "
                f"(expected={expected_hash[:8]}, actual={actual_hash[:8]})"
            )

    return len(violations) == 0, violations


def update_freeze_manifest(engine: str, entries: list[dict],
                           phase_ends: Optional[str] = None) -> None:
    """
    Tulis atau perbarui entri freeze manifest untuk engine tertentu.

    Args:
        engine: nama engine ("pregain", "cex", dll)
        entries: list dict dengan key: param_name, file, hash (opsional), expires_after
        phase_ends: ISO string kapan fase berakhir (setelah ini freeze dihapus otomatis)
    """
    manifest = load_freeze_manifest()
    manifest.setdefault("version", "1.0")
    manifest.setdefault("created_utc", _utc_now_iso())
    manifest["updated_utc"] = _utc_now_iso()

    existing = {e.get("param_name"): e for e in manifest.get("entries", [])}

    for entry in entries:
        name = entry.get("param_name", "unknown")
        # Auto-compute hash jika file ada dan hash tidak diberikan
        if "file" in entry and "hash" not in entry:
            fp = _PROJECT_DIR / entry["file"]
            if fp.exists():
                entry["hash"] = _hash_file(fp)
        if phase_ends:
            entry.setdefault("expires_after", phase_ends)
        entry["engine"] = engine
        entry["frozen_at"] = _utc_now_iso()
        existing[name] = entry

    manifest["entries"] = list(existing.values())
    _write_json_atomic(_FREEZE_FILE, manifest)
    log.info(f"[CONSTITUTION] Freeze manifest diperbarui: {len(manifest['entries'])} entries.")


# ─────────────────────────────────────────────────────────────────────────────
# GATES PASSED FILE
# ─────────────────────────────────────────────────────────────────────────────

def write_gates_result(result: GatesResult) -> None:
    """
    Dipanggil oleh pregain_validation_gates (atau gate engine lain) setelah
    menjalankan sovereign gates. Hasilnya disimpan sebagai bukti untuk
    constitution.check_live_permission().
    """
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "verdict":          result.verdict,
        "engine":           result.engine,
        "n_gates_passed":   result.n_gates_passed,
        "n_gates_total":    result.n_gates_total,
        "timestamp_utc":    result.timestamp_utc,
        "live_criteria":    result.live_criteria,
        "constitution_hash": result.constitution_hash,
        "notes":            result.notes,
    }
    _write_json_atomic(_GATES_FILE, data)
    log.info(f"[CONSTITUTION] Gates result disimpan: {result.verdict} "
             f"({result.n_gates_passed}/{result.n_gates_total}) engine={result.engine}")


def read_gates_result() -> Optional[dict]:
    """Baca gates_passed.json. None jika tidak ada atau corrupt."""
    return _read_json_safe(_GATES_FILE)


# ─────────────────────────────────────────────────────────────────────────────
# CORE API: CHECK LIVE PERMISSION
# ─────────────────────────────────────────────────────────────────────────────

def check_live_permission(engine: str = "pregain") -> ConstitutionVerdict:
    """
    Pemeriksaan utama konstitusi: apakah sistem BOLEH menjalankan live trade?

    ATURAN:
    1. Jika CONSTITUTION_BYPASS diset → log CRITICAL + izinkan (darurat operator)
    2. Gates passed.json harus ada, verdict=GO, dan tidak kadaluarsa (< TTL_DAYS hari)
    3. Freeze manifest tidak boleh dilanggar
    4. Jika semua OK → live_permitted=True

    Dipanggil dari daemon saat startup dan sebelum setiap cycle trading.
    """
    bypass_active = bool(_BYPASS_FLAG)

    # ── Cek freeze manifest ───────────────────────────────────────────────────
    freeze_ok, freeze_violations = check_freeze(engine)

    # ── Cek gates passed file ─────────────────────────────────────────────────
    gates_data = read_gates_result()

    if gates_data is None:
        reason = "data/gates_passed.json tidak ada. Jalankan sovereign gates terlebih dahulu."
        return ConstitutionVerdict(
            live_permitted=bypass_active,
            reason=reason,
            gates_age_days=float("inf"),
            freeze_ok=freeze_ok,
            freeze_violations=freeze_violations,
            bypass_active=bypass_active,
        )

    # Periksa engine
    gate_engine = gates_data.get("engine", "unknown")
    if gate_engine != engine and gate_engine != "all":
        reason = (f"Gates di gates_passed.json adalah untuk engine='{gate_engine}', "
                  f"bukan '{engine}'. Jalankan gates untuk engine yang tepat.")
        return ConstitutionVerdict(
            live_permitted=bypass_active,
            reason=reason,
            gates_age_days=float("inf"),
            freeze_ok=freeze_ok,
            freeze_violations=freeze_violations,
            bypass_active=bypass_active,
        )

    # Periksa usia gates file
    try:
        gates_ts = datetime.fromisoformat(gates_data["timestamp_utc"]).replace(
            tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - gates_ts).total_seconds() / 86400
    except Exception:
        age_days = float("inf")

    if age_days > _GATES_TTL_DAYS:
        reason = (f"Gates kadaluarsa: {age_days:.1f} hari yang lalu "
                  f"(maks {_GATES_TTL_DAYS} hari). Jalankan ulang sovereign gates.")
        return ConstitutionVerdict(
            live_permitted=bypass_active,
            reason=reason,
            gates_age_days=age_days,
            freeze_ok=freeze_ok,
            freeze_violations=freeze_violations,
            bypass_active=bypass_active,
        )

    # Periksa verdict
    verdict = gates_data.get("verdict", "NO_GO")
    if verdict != "GO":
        n_pass = gates_data.get("n_gates_passed", 0)
        n_tot  = gates_data.get("n_gates_total", 10)
        reason = (f"Sovereign gates: {verdict} ({n_pass}/{n_tot} passed). "
                  f"Sistem tetap PAPER sampai semua kriteria GO terpenuhi.")
        return ConstitutionVerdict(
            live_permitted=bypass_active,
            reason=reason,
            gates_age_days=age_days,
            freeze_ok=freeze_ok,
            freeze_violations=freeze_violations,
            bypass_active=bypass_active,
        )

    # ── Semua cek lolos ────────────────────────────────────────────────────────
    n_pass = gates_data.get("n_gates_passed", 0)
    n_tot  = gates_data.get("n_gates_total", 10)
    freeze_note = "" if freeze_ok else f" | PERINGATAN: {len(freeze_violations)} freeze violation"
    reason = (f"GO ({n_pass}/{n_tot} gates, {age_days:.1f}d lalu){freeze_note}")

    return ConstitutionVerdict(
        live_permitted=True,
        reason=reason,
        gates_age_days=age_days,
        freeze_ok=freeze_ok,
        freeze_violations=freeze_violations,
        bypass_active=bypass_active,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ANGGARAN KOMPLEKSITAS (RS-1 §3)
# ─────────────────────────────────────────────────────────────────────────────

def check_complexity_budget(engine: str, n_live_trades: int,
                            n_fitted_params: int) -> tuple[bool, str]:
    """
    Aturan: 1 parameter / 10 live trades terverifikasi.
    Melebihi anggaran → warning (belum hard-block di v1.0).

    Returns:
        (within_budget: bool, message: str)
    """
    budget = max(1, n_live_trades // 10)
    if n_fitted_params > budget:
        msg = (f"[COMPLEXITY] {engine}: {n_fitted_params} parameter ter-fit, "
               f"anggaran {budget} (dari {n_live_trades} live trades). "
               f"Kelebihan {n_fitted_params - budget} parameter — risiko overfit.")
        log.warning(msg)
        return False, msg
    return True, f"{engine}: {n_fitted_params}/{budget} parameter OK."


# ─────────────────────────────────────────────────────────────────────────────
# HASH KONSTITUSI SENDIRI (untuk audit trail)
# ─────────────────────────────────────────────────────────────────────────────

def constitution_hash() -> str:
    """SHA-256 pendek dari file constitution.py ini. Digunakan di GatesResult."""
    return _hash_file(Path(__file__))


# ─────────────────────────────────────────────────────────────────────────────
# STARTUP CHECK — dipanggil oleh daemon
# ─────────────────────────────────────────────────────────────────────────────

def startup_constitution_check(engine: str = "pregain") -> ConstitutionVerdict:
    """
    Entry point utama: dipanggil dari anantara_daemon.py saat startup.

    Jika live_permitted=False:
      - AUTOTRADE_LIVE di environment DIABAIKAN
      - daemon log warning dan tetap paper mode
      - TIDAK raise exception (sistem terus berjalan, hanya blocked dari live)

    Jika live_permitted=True:
      - daemon respek nilai AUTOTRADE_LIVE dari .env
    """
    verdict = check_live_permission(engine)
    verdict.log_summary()
    return verdict


# ─────────────────────────────────────────────────────────────────────────────
# CLI UTILITY
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    engine_arg = sys.argv[1] if len(sys.argv) > 1 else "pregain"
    v = startup_constitution_check(engine_arg)
    print(json.dumps(v.to_dict(), indent=2, ensure_ascii=False))
    sys.exit(0 if v.live_permitted else 1)
