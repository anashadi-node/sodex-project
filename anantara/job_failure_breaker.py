"""Repeated-failure fuse (sekring) for scheduled daemon jobs.

Closes one failure class: a *deterministic* job error repeats every cycle
(e.g. every 3600 s) and floods the log / Telegram while burning CPU, and
nobody notices which single job is stuck. Adapted from the failure-loop
breaker pattern reviewed in hermes-jev (fingerprint -> dedupe -> local
control), rebuilt stdlib-only with no third-party dependency.

Behaviour:
  * fingerprint the error by exception type + normalized message
  * count repeats of the SAME fingerprint per job
  * at `threshold` repeats -> pause that job + alert once
  * after `cooldown_minutes` -> auto-resume, so a transient outage heals
    without human action
  * a different error resets the counter (new bug != same bug)

Fail-open by design. This is ops monitoring, NOT a trading safety gate:
every path is defensive, it never raises into the scheduler, and it never
touches order/execution code. A broken fuse must not stop trading.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

# Tokens that vary between otherwise-identical failures. Normalizing them is
# what makes "3 repeats of the same bug" detectable at all (long-lived
# schedulers do not have conversation context to compare against).
_VOLATILE = (
    re.compile(r"0x[0-9a-fA-F]{6,}"),                    # hashes / addresses
    re.compile(r"\d{4}-\d{2}-\d{2}[T ][\d:.+Z-]+"),      # timestamps
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}\b"),  # uuid
    re.compile(r"(/[\w.\-]+){2,}"),                      # file paths
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:ms|s|us|µs)\b"),   # durations
    re.compile(r"\b\d+(?:\.\d+)?\b"),                    # bare numbers
)


def fingerprint(exc: BaseException | str, max_len: int = 200) -> str:
    """Stable identity for one failure mode: type + normalized message.

    Deliberately keeps the message text (not just the type) so two distinct
    bugs sharing an exception class stay distinct.
    """
    if isinstance(exc, BaseException):
        # str(exc) can itself raise (broken __str__ / lazy __getattr__), and a
        # fusing fuse must never become the outage it was meant to report.
        try:
            head = f"{type(exc).__name__}: {exc}"
        except Exception:
            head = type(exc).__name__
    else:
        head = str(exc)
    text = " ".join(head.split())[: max_len * 2]
    for rx in _VOLATILE:
        text = rx.sub("<v>", text)
    # An empty fingerprint would make every message-less failure compare equal
    # (and never reset a streak). Give it a stable, non-empty identity.
    return " ".join(text.split())[:max_len].lower() or "<no-message>"


def should_alert(count: int, threshold: int, every: int) -> bool:
    """First alert at `threshold`, then every `every` repeats (no per-cycle spam)."""
    if count < threshold:
        return False
    if count == threshold:
        return True
    return every > 0 and (count - threshold) % every == 0


class RepeatedFailureBreaker:
    """Counts identical recurring job failures; pauses the job past a threshold.

    Side effects are injected (`pause`, `resume`, `alert`) so the logic is
    testable without a scheduler and without Telegram.
    """

    def __init__(
        self,
        jobs: tuple[str, ...] | list[str],
        threshold: int = 3,
        cooldown_minutes: int = 30,
        alert_every: int = 5,
        pause: Callable[[str], Any] | None = None,
        resume: Callable[[str], Any] | None = None,
        alert: Callable[[str], Any] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.jobs = tuple(jobs)
        self.threshold = max(2, int(threshold))
        self.cooldown_s = max(60, int(cooldown_minutes) * 60)
        self.alert_every = int(alert_every)
        self._pause = pause
        self._resume = resume
        self._alert = alert
        self._clock = clock
        # job_id -> {"fp", "count", "last", "paused_at","paused_fp","alerts"}
        self._state: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []

    # ── observation paths (called from the scheduler listener) ──────────
    def note_failure(self, job_id: str, exc: BaseException | str) -> dict[str, Any]:
        """Record one failure. Returns the action taken (never raises)."""
        try:
            return self._note_failure(job_id, exc)
        except Exception as e:  # a broken fuse must not break the daemon
            log.warning("failure-breaker internal error: %s", e)
            return {"action": "error", "job_id": job_id}

    def _note_failure(self, job_id: str, exc: BaseException | str) -> dict[str, Any]:
        fp = fingerprint(exc)
        st = self._state.setdefault(
            job_id, {"fp": fp, "count": 0, "alerts": 0, "paused_fp": None, "paused_at": 0.0}
        )
        if st["fp"] != fp:
            # A different error is a different bug: restart the streak.
            st.update(fp=fp, count=0, alerts=0, paused_fp=None, paused_at=0.0)
        st["count"] += 1
        st["last"] = self._clock()

        if st["count"] < self.threshold:
            return {"action": "count", "job_id": job_id, "count": st["count"], "fp": fp}

        if st["paused_fp"] is None:
            self._pause_job(job_id)
            st["paused_fp"] = fp
            st["paused_at"] = self._clock()

        alerted = False
        if should_alert(st["count"], self.threshold, self.alert_every):
            st["alerts"] += 1
            self._alert_msg(
                f"[SEKRING] job `{job_id}` dihentikan sementara: "
                f"{st['count']}x gagal identik ({fp[:120]}). "
                f"Dijeda {self.cooldown_s // 60} menit, lalu dicoba lagi otomatis."
            )
            alerted = True
        ev = {
            "action": "pause",
            "job_id": job_id,
            "count": st["count"],
            "fp": fp,
            "alerted": alerted,
        }
        self.events.append(ev)
        return ev

    def note_success(self, job_id: str) -> dict[str, Any]:
        """Clear a streak; resume the job if the fuse had paused it."""
        try:
            st = self._state.get(job_id)
            if not st:
                return {"action": "noop", "job_id": job_id}
            was_paused = st["paused_fp"] is not None
            st.update(count=0, alerts=0, paused_fp=None, paused_at=0.0)
            if was_paused:
                self._resume_job(job_id)
                self._alert_msg(f"[SEKRING] job `{job_id}` pulih — dijalankan kembali.")
                ev = {"action": "resume", "job_id": job_id, "reason": "success"}
                self.events.append(ev)
                return ev
            return {"action": "reset", "job_id": job_id}
        except Exception as e:
            log.warning("failure-breaker resume error: %s", e)
            return {"action": "error", "job_id": job_id}

    def check_cooldowns(self) -> list[dict[str, Any]]:
        """Resume paused jobs whose cooldown expired (called periodically)."""
        out: list[dict[str, Any]] = []
        try:
            now = self._clock()
            for job_id, st in self._state.items():
                if st["paused_fp"] is None:
                    continue
                if now - st["paused_at"] < self.cooldown_s:
                    continue
                st.update(paused_fp=None, paused_at=0.0, count=0, alerts=0)
                self._resume_job(job_id)
                ev = {"action": "resume", "job_id": job_id, "reason": "cooldown"}
                self.events.append(ev)
                out.append(ev)
        except Exception as e:
            log.warning("failure-breaker cooldown error: %s", e)
        return out

    def state(self) -> dict[str, dict[str, Any]]:
        """Snapshot for logging/diagnostics (counts + fingerprints only)."""
        return {k: dict(v) for k, v in self._state.items()}

    # ── injected side effects ───────────────────────────────────────────
    def _pause_job(self, job_id: str) -> None:
        if not self._pause:
            return
        try:
            self._pause(job_id)
        except Exception as e:
            log.warning("pause_job(%s) failed: %s", job_id, e)

    def _resume_job(self, job_id: str) -> None:
        if not self._resume:
            return
        try:
            self._resume(job_id)
        except Exception as e:
            log.warning("resume_job(%s) failed: %s", job_id, e)

    def _alert_msg(self, text: str) -> None:
        if not self._alert:
            return
        try:
            self._alert(text)
        except Exception as e:
            log.warning("failure-breaker alert failed: %s", e)