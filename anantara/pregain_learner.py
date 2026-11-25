#!/usr/bin/env python3
"""
ANANTARA SAKTI — Pre-Gain/Loser Learning System

Self-improving feedback loop untuk Pre-Gain/Loser Scan & Trading System.
Membaca outcome empiris dari signal_tracker DB dan mengadaptasi multiplier
scoring — menjembatani gap antara "mengukur" dan "membaik".

Arsitektur mengikuti mode8_learner.py (pola Anantara yang sudah proven):
  signal_tracker DB (outcomes) → PregainLearner.refresh()
    → PatternWeights      (pola sinyal mana yang benar-benar menang)
    → RegimeMultipliers   (TRENDING / RANGING / CHAOS: kualitas empiris)
    → SessionMultipliers  (Asia / EU / US / US_Asia: win-rate empiris)
    → ScoreCalibration    (raw score → win-probability via isotonic PAVA)
  → diterapkan di pregain_scan.run_scan() sebelum ranking final

Disiplin learning (jujur, data-driven):
  MIN_SAMPLES = 15 per bucket sebelum adaptasi (cegah noise-fitting)
  Multiplier dikunci [0.70, 1.30] — cautious ±30% max
  Kalibrasi via calibration.py isotonic PAVA (stdlib, tested)
  Persistent: JSON state file, atomic write, crash-safe
  Thread-safe: RLock protects semua shared state

Apa yang DIUBAH vs apa yang TIDAK:
  DIUBAH  : composite regime×session multiplier diterapkan sebagai faktor akhir
  DIUBAH  : per-pattern weight rata-rata dari sinyal yang fired
  TIDAK   : logika scoring di pregain_signals.py tetap utuh (research-validated)

Pure functions (yang bisa unit-tested) dipisah dari IO di refresh().
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import errno
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import logging as _log

log = _log.getLogger("pregain_learner")

# ── Persistence ────────────────────────────────────────────────────────────────
LEARNER_PATH = Path(os.environ.get(
    "PREGAIN_LEARNER_PATH",
    str(Path.home() / ".local/share/anantara/pregain_learner.json")
))

# ── Learning config ────────────────────────────────────────────────────────────
MIN_SAMPLES       = 15     # resolved signals per bucket sebelum adaptasi aktif
COIN_MIN_SAMPLES  = 5      # min per coin+direction sebelum coin gate aktif
MULT_MIN          = 0.70   # minimum multiplier (max penalti -30%)
MULT_MAX          = 1.30   # maximum multiplier (max boost +30%)
COIN_BLOCK_THRESH = 0.25   # win-rate < 25% + n≥COIN_MIN → coin BLOCKED (multiplier=0)
COIN_BOOST_THRESH = 0.70   # win-rate > 70% + n≥COIN_MIN → coin BOOSTED (mult=MULT_MAX)
BASE_WIN_RATE     = 0.50   # referensi: coin-flip baseline
REFRESH_INTERVAL  = 3600   # re-read DB max 1x per jam
SAVE_INTERVAL     = 600    # auto-save max 1x per 10 menit


# ── Pure core: _Bucket ─────────────────────────────────────────────────────────

@dataclass
class _Bucket:
    """Rolling win/loss stats untuk satu kelompok (pattern, regime, session)."""
    n:           int   = 0
    wins:        int   = 0
    avg_outcome: float = 0.0

    def win_rate(self) -> Optional[float]:
        """Win-rate float 0-1, atau None jika belum cukup sampel (< MIN_SAMPLES)."""
        return self.wins / self.n if self.n >= MIN_SAMPLES else None

    def multiplier(self, base: float = BASE_WIN_RATE) -> float:
        """Multiplier relatif terhadap base_rate. Returns 1.0 (neutral) jika belum trained.

        Rumus: clip(win_rate / base, MULT_MIN, MULT_MAX)
        Contoh: win_rate=0.70, base=0.50 → 1.40x boost
                win_rate=0.35, base=0.50 → 0.70x penalti
        """
        wr = self.win_rate()
        if wr is None:
            return 1.0
        raw = wr / max(base, 0.01)
        return max(MULT_MIN, min(MULT_MAX, raw))


# ── Pure: composite multiplier ─────────────────────────────────────────────────

def compose_multipliers(regime_mult: float, session_mult: float) -> float:
    """Geometric mean dari dua multiplier, dikunci [MULT_MIN, MULT_MAX].

    Menggunakan geometric mean (bukan produk) agar dua dimensi yang sama-sama
    bullish tidak saling compounding secara agresif:
      regime=1.2 × session=1.2 → prod=1.44 (terlalu tinggi) vs sqrt=1.20 (controlled)
    """
    composed = (regime_mult * session_mult) ** 0.5
    return max(MULT_MIN, min(MULT_MAX, composed))


def average_pattern_weight(weights: list[float]) -> float:
    """Rata-rata bobot dari semua pattern yang fired, dikunci [MULT_MIN, MULT_MAX]."""
    if not weights:
        return 1.0
    avg = sum(weights) / len(weights)
    return max(MULT_MIN, min(MULT_MAX, avg))


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN LEARNER CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class PregainLearner:
    """Self-improving weight adapter untuk Pre-Gain/Loser signals.

    Baca outcome dari signal_tracker DB → adaptasi per-pattern, per-regime,
    per-session multiplier → diterapkan sebagai faktor akhir di run_scan().

    Thread-safe singleton. Persistent JSON state. Graceful degradation:
    jika belum cukup data, semua multiplier = 1.0 (tanpa efek).
    """

    def __init__(self) -> None:
        self._lock         = threading.RLock()
        self._last_refresh : float = 0.0
        self._last_save    : float = 0.0
        self._persist_disabled_reason: Optional[str] = None
        self._global       : _Bucket = _Bucket()
        self._patterns     : dict[str, _Bucket] = {}
        self._regimes      : dict[str, _Bucket] = {}
        self._sessions     : dict[str, _Bucket] = {}
        # Coin-level tracking: key = "DIRECTION:COIN" e.g. "SHORT:XMR"
        # Blocked coins (0-25% win with enough data) get score→0.
        # Boosted coins (70%+ win with enough data) get score boost.
        self._coins        : dict[str, _Bucket] = {}
        # Isotonic calibration knots (dari calibration.py)
        self._calib_x      : list[float] = []
        self._calib_y      : list[float] = []
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load state dari JSON file (crash-safe: missing file = fresh start)."""
        try:
            if LEARNER_PATH.exists():
                data = json.loads(LEARNER_PATH.read_text())

                def _bk(d: dict) -> _Bucket:
                    return _Bucket(d.get("n", 0), d.get("wins", 0),
                                   d.get("avg_outcome", 0.0))

                self._global   = _bk(data.get("global", {}))
                self._patterns = {k: _bk(v) for k, v in data.get("patterns", {}).items()}
                self._regimes  = {k: _bk(v) for k, v in data.get("regimes", {}).items()}
                self._sessions = {k: _bk(v) for k, v in data.get("sessions", {}).items()}
                self._coins    = {k: _bk(v) for k, v in data.get("coins", {}).items()}
                self._calib_x  = data.get("calib_x", [])
                self._calib_y  = data.get("calib_y", [])
                log.info("PregainLearner loaded: global_n=%d patterns=%d coins=%d",
                         self._global.n, len(self._patterns), len(self._coins))
        except Exception as e:
            log.warning("PregainLearner load failed: %s — starting fresh", e)

    def _save(self) -> None:
        """Atomic write state ke disk (tmp → replace, crash-safe)."""
        if self._persist_disabled_reason:
            return

        def _bk_dict(b: _Bucket) -> dict:
            return {"n": b.n, "wins": b.wins, "avg_outcome": round(b.avg_outcome, 4)}
        try:
            LEARNER_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "updated":  datetime.now(timezone.utc).isoformat(),
                "global":   _bk_dict(self._global),
                "patterns": {k: _bk_dict(v) for k, v in self._patterns.items()},
                "regimes":  {k: _bk_dict(v) for k, v in self._regimes.items()},
                "sessions": {k: _bk_dict(v) for k, v in self._sessions.items()},
                "coins":    {k: _bk_dict(v) for k, v in self._coins.items()},
                "calib_x":  self._calib_x,
                "calib_y":  self._calib_y,
            }
            tmp = str(LEARNER_PATH) + ".tmp"
            Path(tmp).write_text(json.dumps(data, indent=2))
            os.replace(tmp, str(LEARNER_PATH))
            self._last_save = time.time()
        except Exception as e:
            if isinstance(e, PermissionError) or (
                isinstance(e, OSError) and e.errno in {errno.EROFS, errno.EACCES, errno.EPERM}
            ):
                self._persist_disabled_reason = f"{type(e).__name__}: {e}"
                log.info("PregainLearner persistence disabled for this process: %s",
                         self._persist_disabled_reason)
                return
            log.warning("PregainLearner save failed: %s", e)

    # ── DB reader ──────────────────────────────────────────────────────────────

    def refresh(self, db_path: str | Path, force: bool = False) -> None:
        """Re-read signal_tracker DB dan update semua weight bucket.

        Dipanggil setelah backfill_outcomes() di validate() agar sinyal baru
        yang resolved langsung masuk ke learning loop.
        Throttled ke REFRESH_INTERVAL (1 jam) kecuali force=True.
        """
        with self._lock:
            if not force and time.time() - self._last_refresh < REFRESH_INTERVAL:
                return
            try:
                self._refresh_from_db(str(db_path))
                self._last_refresh = time.time()
                # Auto-save hanya jika sudah cukup trained (hindari spam write saat test)
                if self._global.n >= MIN_SAMPLES:
                    if time.time() - self._last_save > SAVE_INTERVAL:
                        self._save()
            except Exception as e:
                log.warning("PregainLearner.refresh failed: %s", e)

    def _refresh_from_db(self, db_path: str) -> None:
        """Rebuild semua bucket dari resolved signals di DB (aggregation murni).

        Defensive terhadap schema lama: cek keberadaan setiap kolom opsional
        (session, patterns) sebelum query agar kompatibel dengan DB lama.
        """
        conn = sqlite3.connect(db_path)
        try:
            # Pastikan table exists (graceful: DB mungkin baru)
            if not conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='signal_log'"
            ).fetchone():
                return

            # Cek kolom opsional — fallback ke NULL jika belum ada (schema lama)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(signal_log)")}
            session_col  = "session"  if "session"  in cols else "NULL"
            patterns_col = "patterns" if "patterns" in cols else "NULL"

            rows = conn.execute(
                f"SELECT grade, regime, {session_col}, outcome_pct, correct, "
                f"{patterns_col}, coin, direction "
                "FROM signal_log WHERE outcome_pct IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()

        g_new  = _Bucket()
        pat    : dict[str, _Bucket] = {}
        reg    : dict[str, _Bucket] = {}
        coin_d : dict[str, _Bucket] = {}   # key = "DIRECTION:COIN"
        sess   : dict[str, _Bucket] = {}
        probs  : list[tuple[float, int]] = []  # (score_proxy, correct) untuk kalibrasi

        for grade, regime, session, outcome_pct, correct, patterns, coin, direction in rows:
            c  = int(correct or 0)
            op = float(outcome_pct or 0.0)

            # ── global
            g_new.n    += 1
            g_new.wins += c
            # Running mean untuk avg_outcome (numerically stable)
            g_new.avg_outcome += (op - g_new.avg_outcome) / g_new.n

            # ── regime bucket
            rk = (regime or "RANGING").split("(")[0]
            if rk not in reg:
                reg[rk] = _Bucket()
            b = reg[rk]
            b.n    += 1; b.wins += c
            b.avg_outcome += (op - b.avg_outcome) / b.n

            # ── session bucket
            sk = session or "US"
            if sk not in sess:
                sess[sk] = _Bucket()
            b = sess[sk]
            b.n    += 1; b.wins += c
            b.avg_outcome += (op - b.avg_outcome) / b.n

            # ── pattern bucket (patterns = comma-separated string, bisa NULL)
            if patterns:
                for pname in str(patterns).split(","):
                    pname = pname.strip()
                    if not pname:
                        continue
                    if pname not in pat:
                        pat[pname] = _Bucket()
                    b = pat[pname]
                    b.n    += 1; b.wins += c
                    b.avg_outcome += (op - b.avg_outcome) / b.n

            # ── coin+direction bucket
            if coin and direction:
                ck = f"{direction}:{coin}"
                if ck not in coin_d:
                    coin_d[ck] = _Bucket()
                b = coin_d[ck]
                b.n    += 1; b.wins += c
                b.avg_outcome += (op - b.avg_outcome) / b.n

            # ── calibration data: gunakan grade sebagai proxy raw-score
            # Grade S≈92, A≈85, B≈72, C≈57 (midpoints dari grade() thresholds)
            grade_score = {"S": 0.92, "A": 0.85, "B": 0.72, "C": 0.57}.get(grade or "C", 0.60)
            probs.append((grade_score, c))

        self._global   = g_new
        self._patterns = pat
        self._regimes  = reg
        self._sessions = sess
        self._coins    = coin_d

        # ── Rebuild isotonic calibration (isotonic_fit dari calibration.py)
        if len(probs) >= MIN_SAMPLES:
            try:
                try:
                    from anantara.calibration import isotonic_fit
                except ImportError:
                    from calibration import isotonic_fit  # type: ignore
                xs  = [p[0] for p in probs]
                ys  = [p[1] for p in probs]
                fit = isotonic_fit(xs, ys)
                self._calib_x = fit.get("x", [])
                self._calib_y = fit.get("y", [])
            except Exception as e:
                log.debug("calibration isotonic_fit failed: %s", e)

    # ── Query interface (pure, no IO) ──────────────────────────────────────────

    def get_pattern_weight(self, pattern_name: str) -> float:
        """Multiplier untuk satu pattern berdasarkan empirical win-rate.

        Returns 1.0 (neutral) sampai MIN_SAMPLES tercapai.
        Range: [MULT_MIN, MULT_MAX] = [0.70, 1.30].
        """
        with self._lock:
            b = self._patterns.get(pattern_name)
            if b is None:
                return 1.0
            base = self._global.win_rate() or BASE_WIN_RATE
            return b.multiplier(base)

    def get_regime_mult(self, regime: str) -> float:
        """Multiplier untuk BTC regime saat ini (TRENDING/RANGING/CHAOS)."""
        with self._lock:
            rk = regime.split("(")[0] if "(" in regime else regime
            b  = self._regimes.get(rk)
            if b is None:
                return 1.0
            base = self._global.win_rate() or BASE_WIN_RATE
            return b.multiplier(base)

    def get_session_mult(self, session: str) -> float:
        """Multiplier untuk trading session (Asia/EU/US/US_Asia)."""
        with self._lock:
            b = self._sessions.get(session)
            if b is None:
                return 1.0
            base = self._global.win_rate() or BASE_WIN_RATE
            return b.multiplier(base)

    def get_coin_mult(self, coin: str, direction: str) -> float:
        """Coin+direction multiplier berdasarkan empirical win-rate.

        Ini adalah filter paling kuat:
          - Win-rate < 25% + n ≥ COIN_MIN_SAMPLES → 0.0 (BLOCKED: signal tidak dipercaya)
          - Win-rate > 70% + n ≥ COIN_MIN_SAMPLES → MULT_MAX (BOOSTED)
          - Lainnya → interpolasi atau 1.0 (neutral/insufficient data)

        Contoh (2026-06-02 data):
          SHORT:WLD   win=0%  n=4  → 0.0  (WLD adalah structural bull, SHORT selalu gagal)
          SHORT:XMR   win=100% n=7 → 1.30 (XMR short sangat reliable)
        """
        with self._lock:
            key = f"{direction}:{coin}"
            b = self._coins.get(key)
            if b is None or b.n < COIN_MIN_SAMPLES:
                return 1.0   # insufficient data → neutral

            # Use coin-specific min samples (not global MIN_SAMPLES=15)
            wr = b.wins / b.n   # raw ratio (0.0 to 1.0)
            # Block: win-rate below threshold → score = 0 (coin blocked)
            if wr < COIN_BLOCK_THRESH:
                return 0.0
            # Boost: win-rate above threshold → max multiplier
            if wr > COIN_BOOST_THRESH:
                return MULT_MAX
            # Between thresholds → interpolate relative to global win-rate
            base = self._global.win_rate() or BASE_WIN_RATE
            raw  = wr / max(base, 0.01)
            return max(MULT_MIN, min(MULT_MAX, raw))

    def get_composite_mult(self, regime: str, session: str) -> float:
        """Composite regime×session multiplier via geometric mean.

        Hanya aktif jika trained (is_trained() = True). Kalau belum: 1.0.
        Berguna untuk run_scan() agar diterapkan sekali per scan.
        """
        if not self.is_trained():
            return 1.0
        rm = self.get_regime_mult(regime)
        sm = self.get_session_mult(session)
        return compose_multipliers(rm, sm)

    def get_pattern_composite_mult(self, patterns_csv: str) -> float:
        """Rata-rata weight dari semua pattern yang fired (comma-separated string).

        Returns 1.0 jika learner belum trained atau patterns kosong.
        Contoh: "SHORT_SQUEEZE,COIL" → avg weight dari kedua pattern.
        """
        if not self.is_trained() or not patterns_csv:
            return 1.0
        with self._lock:
            base = self._global.win_rate() or BASE_WIN_RATE
            weights = []
            for pname in patterns_csv.split(","):
                pname = pname.strip()
                if not pname:
                    continue
                b = self._patterns.get(pname)
                if b is not None:
                    weights.append(b.multiplier(base))
        return average_pattern_weight(weights)  # 1.0 if empty

    def calibrate_score(self, raw_score: float) -> float:
        """Map raw attention score (0–100) ke calibrated win-probability (0.0–1.0).

        Menggunakan isotonic fit yang dilatih dari outcome empiris.
        Fallback ke linear mapping jika belum cukup data.
        """
        with self._lock:
            if not self._calib_x:
                return max(0.0, min(1.0, raw_score / 100.0))
            try:
                try:
                    from anantara.calibration import apply_isotonic
                except ImportError:
                    from calibration import apply_isotonic  # type: ignore
                return apply_isotonic(
                    {"x": self._calib_x, "y": self._calib_y},
                    raw_score / 100.0
                )
            except Exception:
                return max(0.0, min(1.0, raw_score / 100.0))

    def is_trained(self) -> bool:
        """True jika cukup data untuk adaptasi (≥ MIN_SAMPLES resolved signals)."""
        with self._lock:
            return self._global.n >= MIN_SAMPLES

    # ── Reporting ──────────────────────────────────────────────────────────────

    def get_report(self) -> dict:
        """Summary stats dict untuk monitoring/Telegram."""
        with self._lock:
            base = self._global.win_rate() or BASE_WIN_RATE
            out: dict = {
                "total_resolved": self._global.n,
                "global_win_rate": self._global.win_rate(),
                "trained": self.is_trained(),
                "patterns": {},
                "regimes":  {},
                "sessions": {},
            }
            for k, b in self._patterns.items():
                out["patterns"][k] = {
                    "n":        b.n,
                    "win_rate": b.win_rate(),
                    "weight":   b.multiplier(base),
                }
            for k, b in self._regimes.items():
                out["regimes"][k] = {
                    "n":        b.n,
                    "win_rate": b.win_rate(),
                    "mult":     b.multiplier(base),
                }
            for k, b in self._sessions.items():
                out["sessions"][k] = {
                    "n":        b.n,
                    "win_rate": b.win_rate(),
                    "mult":     b.multiplier(base),
                }
            return out

    def format_report(self) -> str:
        """Human-readable learning report (Telegram/terminal friendly)."""
        rep     = self.get_report()
        n       = rep["total_resolved"]
        wr      = rep["global_win_rate"]
        trained = rep["trained"]
        wr_str  = f"{wr*100:.1f}%" if wr is not None else "?"

        lines = [
            f"🧠 *PRE-GAIN LEARNER* (n={n} resolved, global win={wr_str})",
            f"   Status: {'✅ TRAINED — bobot adaptif aktif' if trained else f'📊 Akumulasi ({n}/{MIN_SAMPLES} sinyal resolved untuk aktivasi)'}",
        ]
        if not trained:
            lines.append(f"   Perlu {MIN_SAMPLES - n} sinyal resolved lagi.")
            return "\n".join(lines)

        if rep["patterns"]:
            lines.append("   Per pattern (weight ×):")
            for k, v in sorted(rep["patterns"].items(),
                                key=lambda x: -(x[1]["n"])):
                if v["n"] >= 5:
                    wr_s = f"{v['win_rate']*100:.0f}%" if v["win_rate"] else "?"
                    lines.append(
                        f"     {k:<22} n={v['n']:>3}  win={wr_s:<6} ×{v['weight']:.2f}")

        if rep["regimes"]:
            lines.append("   Per regime:")
            for k, v in rep["regimes"].items():
                if v["n"]:
                    wr_s = f"{v['win_rate']*100:.0f}%" if v["win_rate"] else "?"
                    lines.append(
                        f"     {k:<12} n={v['n']:>3}  win={wr_s:<6} ×{v['mult']:.2f}")

        if rep["sessions"]:
            _icons = {"Asia": "🌏", "EU": "🇪🇺", "US": "🇺🇸", "US_Asia": "🌙"}
            lines.append("   Per sesi:")
            for k in ("Asia", "EU", "US", "US_Asia"):
                v = rep["sessions"].get(k)
                if v and v["n"]:
                    wr_s = f"{v['win_rate']*100:.0f}%" if v["win_rate"] else "?"
                    icon = _icons.get(k, "📡")
                    lines.append(
                        f"   {icon} {k:<8} n={v['n']:>3}  win={wr_s:<6} ×{v['mult']:.2f}")

        calib_status = (f"aktif ({len(self._calib_x)} knot)"
                        if self._calib_x else "belum cukup data")
        lines.append(f"   Kalibrasi: {calib_status}")
        lines.append("   Catatan: adaptasi aktif setelah ≥15 resolved/bucket. "
                     "Multiplier dikunci [0.70–1.30].")
        return "\n".join(lines)

    def force_save(self) -> None:
        """Force immediate state persistence ke disk."""
        with self._lock:
            self._save()


# ── Global singleton ──────────────────────────────────────────────────────────
_learner      : Optional[PregainLearner] = None
_learner_lock : threading.Lock           = threading.Lock()


def get_learner() -> PregainLearner:
    """Get atau create global PregainLearner singleton."""
    global _learner
    with _learner_lock:
        if _learner is None:
            _learner = PregainLearner()
        return _learner


if __name__ == "__main__":
    import os
    db = os.environ.get("ANANTARA_SIGNAL_DB",
                        str(Path.home() / ".local/share/anantara/signals.db"))
    learner = get_learner()
    learner.refresh(db, force=True)
    print(learner.format_report())
