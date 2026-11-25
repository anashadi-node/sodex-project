#!/usr/bin/env python3
"""
ASTRONACCI v1.0 — Ephemeris Engine (Layer 1: Valid Astronomy Data)

Sumber data astronomi deterministik yang menjadi fondasi seluruh sistem
Astronacci. Semua perhitungan berbasis Skyfield + JPL DE440/DE441 ephemeris
— data observasi NASA yang direplikasi secara independen.

DOKTRIN SAINTIFIK:
  Layer 1 adalah FAKTA (data posisi benda langit). Validitas data ini tidak
  otomatis memvalidasi interpretasi pasar. Posisi planet adalah input fitur,
  BUKAN prediktor otomatis.

WHAT THIS MODULE PROVIDES:
  • Planet positions (longitude, latitude, declination, RA, distance) for all
    major bodies at any timestamp
  • Lunar phase, illumination, distance, declination — continuous sin/cos form
  • Aspect computation: proximity score to 0°/60°/90°/120°/180° for any pair
  • Retrograde detection (apparent backward motion in ecliptic longitude)
  • Planetary cluster density score
  • Sun-Moon separation angle
  • All outputs in UTC, timezone-aware

Skyfield caches JPL ephemeris files locally (~13 MB DE440). Falls back to
built-in DE421 (~1 MB) if DE440 not yet downloaded. All deterministic.

DEPENDENCIES: skyfield (pip install skyfield)
  — stdlib-only for feature computation; skyfield only for raw position data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Skyfield imports (lazy-loaded for testing without the dep) ──
_SKYFIELD_AVAILABLE = False
try:
    from skyfield.api import load, Loader
    from skyfield.framelib import ecliptic_frame
    from skyfield.almanac import moon_phase as _sf_moon_phase
    _SKYFIELD_AVAILABLE = True
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# Major celestial bodies tracked (Skyfield DE440 keys)
PLANETS = [
    "Sun", "Moon", "Mercury", "Venus", "Mars",
    "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto",
]

# DE440 uses barycenter names for most planets; DE421 uses simple names.
# Keys are tried in order — first match wins.
_PLANET_KEYS = {
    "Sun":     ["sun"],
    "Moon":    ["moon"],
    "Mercury": ["mercury"],
    "Venus":   ["venus"],
    "Mars":    ["mars barycenter", "mars"],
    "Jupiter": ["jupiter barycenter", "jupiter"],
    "Saturn":  ["saturn barycenter", "saturn"],
    "Uranus":  ["uranus barycenter", "uranus"],
    "Neptune": ["neptune barycenter", "neptune"],
    "Pluto":   ["pluto barycenter", "pluto"],
}

# Classical astrological aspects (degrees)
ASPECTS = {
    "conjunction":    0,
    "sextile":       60,
    "square":        90,
    "trine":        120,
    "opposition":   180,
}

ASPECT_ORB = 8.0  # max orb in degrees for aspect proximity scoring

# Lunar cycle in days (synodic month)
SYNODIC_MONTH = 29.53058867

# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CelestialBody:
    """Position data for a single celestial body at one timestamp."""
    name: str
    lon_ecl: float          # ecliptic longitude (0–360°)
    lat_ecl: float          # ecliptic latitude
    ra_deg: float           # right ascension (degrees)
    dec_deg: float          # declination (degrees)
    distance_au: float      # distance from Earth in AU
    is_retrograde: bool     # apparent retrograde motion


@dataclass
class LunarState:
    """Comprehensive lunar state at one timestamp."""
    phase_angle: float      # 0–360°, continuous (0=new, 180=full)
    illumination: float     # 0.0–1.0 fraction illuminated
    distance_km: float      # Earth-Moon distance
    declination: float      # Moon declination
    sun_moon_sep: float     # Sun-Moon angular separation
    phase_sin: float = 0.0  # sin(phase_angle) — continuous feature
    phase_cos: float = 0.0  # cos(phase_angle) — continuous feature
    days_to_new: float = 0.0   # days UNTIL next new moon (forward arc, see note)
    days_to_full: float = 0.0  # days UNTIL next full moon (forward arc)
    days_since_new: float = 0.0    # days SINCE last new moon (elapsed)
    days_since_full: float = 0.0   # days SINCE last full moon (elapsed)
    days_to_nearest_new: float = 0.0   # min(days_to_new, days_since_new) — symmetric distance
    days_to_nearest_full: float = 0.0  # min(days_to_full, days_since_full)

    def __post_init__(self):
        self.phase_sin = math.sin(math.radians(self.phase_angle))
        self.phase_cos = math.cos(math.radians(self.phase_angle))

        # DAYS-TO-EVENT — CORRECTED SEMANTICS (root-cause fix).
        #
        # PREVIOUS IMPLEMENTATION (BUG):
        #   days_to_new = phase_angle / 360 * SYNODIC_MONTH
        # For phase_angle=131° this yielded 10.75, which is actually "days
        # SINCE the last new moon" (elapsed time), NOT "days UNTIL the next
        # new moon" (which would be 29.53 - 10.75 = 18.78). The field name
        # "days_to_new" therefore lied, and behavioural modules consumed it
        # as a distance-to-event, producing wrong risk-premium geometry.
        #
        # FIX: provide BOTH directional quantities unambiguously:
        #   days_to_X      = forward arc to the NEXT X   (in [0, SYNODIC_MONTH))
        #   days_since_X   = backward arc since the LAST X (= SYNODIC_MONTH - days_to_X)
        #   days_to_nearest_X = min(forward, backward) — the symmetric distance
        #     used by behavioural decay models (effect peaks AT event, decays
        #     both before and after; absolute distance is what matters).
        #
        # Note on linearity: this converts phase angle to time via the mean
        # synodic rate (360° / 29.53d). True lunar motion is slightly
        # eccentric, so ±a few hours of error is expected — acceptable for a
        # behavioural-distance feature.
        half_cycle = SYNODIC_MONTH / 2.0
        forward_to_new = (360.0 - self.phase_angle) % 360.0
        forward_to_full = (180.0 - self.phase_angle) % 360.0
        self.days_to_new = forward_to_new / 360.0 * SYNODIC_MONTH
        self.days_to_full = forward_to_full / 360.0 * SYNODIC_MONTH
        self.days_since_new = SYNODIC_MONTH - self.days_to_new
        self.days_since_full = SYNODIC_MONTH - self.days_to_full
        # Symmetric distance to nearest event (capped at half a cycle)
        self.days_to_nearest_new = min(self.days_to_new, self.days_since_new)
        self.days_to_nearest_full = min(self.days_to_full, self.days_since_full)
        # Sanity: nearest distance cannot exceed half a synodic cycle
        assert self.days_to_nearest_new <= half_cycle + 1e-9
        assert self.days_to_nearest_full <= half_cycle + 1e-9


@dataclass
class AspectScore:
    """Proximity score for a specific aspect between two bodies."""
    body_a: str
    body_b: str
    aspect_name: str        # conjunction/sextile/square/trine/opposition
    target_angle: float     # 0/60/90/120/180
    actual_angle: float     # actual angular separation
    proximity: float        # 0.0–1.0 (1.0 = exact aspect, 0.0 = outside orb)
    orb_degrees: float      # absolute deviation from exact


@dataclass
class PlanetCluster:
    """Planetary clustering density score."""
    density_score: float    # 0.0–1.0, higher = more planets clustered
    cluster_center: float   # approximate center longitude of densest cluster
    participating: list[str]  # bodies in the densest cluster


@dataclass
class EphemerisSnapshot:
    """Complete ephemeris data for one timestamp."""
    ts: datetime
    bodies: dict[str, CelestialBody]
    lunar: LunarState
    aspects: list[AspectScore]
    cluster: PlanetCluster


# ─────────────────────────────────────────────────────────────────────────────
# CORE ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class EphemerisEngine:
    """Deterministic astronomical computation engine.

    Caches Skyfield objects after first load. All methods are pure functions
    over time — same input → same output, always.

    Usage:
        engine = EphemerisEngine()
        snap = engine.compute(datetime.now(timezone.utc))
        print(snap.lunar.illumination)  # 0.0–1.0
        print(snap.bodies["Mars"].lon_ecl)  # ecliptic longitude
    """

    def __init__(self, ephemeris_dir: str = "/tmp/skyfield"):
        self._eph_dir = ephemeris_dir
        self._ts = None
        self._eph = None
        self._earth = None
        self._loaded = False

    def _ensure_loaded(self):
        """Lazy-load the JPL ephemeris (Skyfield Loader).

        Selection logic (preferred → fallback):
          1. DE440 if already cached locally  (most accurate: ±13000 yr span)
          2. DE421 if already cached locally  (smaller: 1900–2050 span)
          3. Otherwise download DE440         (one-time ~13 MB fetch)

        ROOT-CAUSE NOTES (why this was rewritten):
          1. The previous code tried DE421 FIRST and DE440 only as a fallback.
             That contradicted the module docstring ("DE440 primary, DE421
             fallback"), so documentation and behaviour disagreed.
          2. More importantly, `loader("de421.bsp")` NEVER raises when the
             file is missing — Skyfield's Loader silently downloads it. So the
             `except Exception` fallback to DE440 was DEAD CODE: it could
             never execute, meaning the "DE440" path existed only on paper.
          3. Skyfield's auto-download also breaks the fallback intent: calling
             loader("de440.bsp") when only de421.bsp is cached would BLOCK to
             download de440 instead of falling back to the present de421. We
             therefore check the local cache FIRST and only trigger a download
             when no candidate is cached at all.
        """
        if self._loaded:
            return
        if not _SKYFIELD_AVAILABLE:
            raise ImportError(
                "skyfield required for ephemeris. Install: pip install skyfield"
            )
        import os
        loader = Loader(self._eph_dir)
        eph_dir = Path(self._eph_dir)

        # Priority 1+2: use whatever is already cached, DE440 first then DE421.
        cached_candidates = [
            "de440.bsp",  # highest accuracy if present
            "de421.bsp",  # smaller fallback if present
        ]
        for filename in cached_candidates:
            local_path = eph_dir / filename
            if local_path.exists() and local_path.stat().st_size > 0:
                try:
                    self._eph = loader(filename)
                    _ = self._eph["earth"]  # detect corrupt/truncated .bsp
                    break
                except Exception:
                    self._eph = None
                    continue
        else:
            # Priority 3: nothing usable cached → download DE440 (preferred).
            # If DE440 download fails, try downloading DE421 as final fallback.
            for filename in cached_candidates:
                try:
                    self._eph = loader(filename)  # triggers download
                    _ = self._eph["earth"]
                    break
                except Exception as e:
                    last_error = e
                    self._eph = None
                    continue
            else:
                raise RuntimeError(
                    "Cannot load or download any JPL ephemeris file "
                    f"({cached_candidates}). Last error: {last_error!r}"
                )

        self._ts = load.timescale()
        self._earth = self._eph["earth"]
        self._loaded = True

    def _body_position(self, name: str, t) -> CelestialBody:
        """Compute position of a single body at Skyfield time t."""
        # Try barycenter key first (DE440), fall back to simple name (DE421)
        keys = _PLANET_KEYS.get(name, [name.lower().replace(" ", "_")])
        body = None
        for key in keys:
            try:
                body = self._eph[key]
                break
            except KeyError:
                continue
        if body is None:
            raise KeyError(f"Cannot find body '{name}' in ephemeris (tried {keys})")

        # Geocentric apparent position
        astrometric = self._earth.at(t).observe(body).apparent()

        # Ecliptic coordinates
        ecliptic_pos = astrometric.frame_latlon(ecliptic_frame)
        lon = ecliptic_pos[1].degrees % 360.0
        lat = ecliptic_pos[0].degrees

        # Equatorial coordinates
        ra, dec, dist = astrometric.radec()
        ra_deg = ra.hours * 15.0
        dec_deg = dec.degrees

        # Distance in AU
        distance_au = dist.au if hasattr(dist, 'au') else float(dist.km) / 149_597_870.7

        # Retrograde detection: compute at t and t+1 day, check longitude direction
        t2 = self._ts.tt_jd(t.tt + 1.0)
        ecl2 = self._earth.at(t2).observe(body).apparent().frame_latlon(ecliptic_frame)
        lon2 = ecl2[1].degrees % 360.0
        # Retrograde if apparent longitude moves backward
        delta_lon = (lon2 - lon + 180.0) % 360.0 - 180.0  # signed diff
        is_retro = delta_lon < -0.01  # moving backward > 0.01°/day

        return CelestialBody(
            name=name,
            lon_ecl=round(lon, 6),
            lat_ecl=round(lat, 6),
            ra_deg=round(ra_deg, 6),
            dec_deg=round(dec_deg, 6),
            distance_au=round(distance_au, 8),
            is_retrograde=is_retro,
        )

    def _lunar_state(self, t, sun: CelestialBody, moon: CelestialBody) -> LunarState:
        """Compute comprehensive lunar state."""
        # Phase angle from Sun-Moon separation
        sun_moon_sep = _angular_separation(
            sun.lon_ecl, sun.lat_ecl, moon.lon_ecl, moon.lat_ecl
        )
        phase_angle = sun_moon_sep  # 0°=new, 180°=full
        illumination = (1.0 - math.cos(math.radians(phase_angle))) / 2.0

        # Distance
        distance_km = moon.distance_au * 149_597_870.7

        return LunarState(
            phase_angle=round(phase_angle, 4),
            illumination=round(illumination, 6),
            distance_km=round(distance_km, 1),
            declination=moon.dec_deg,
            sun_moon_sep=round(sun_moon_sep, 4),
        )

    def _compute_aspects(
        self, bodies: dict[str, CelestialBody]
    ) -> list[AspectScore]:
        """Compute aspect proximity scores for all body pairs."""
        result = []
        names = list(bodies.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = bodies[names[i]], bodies[names[j]]
                angle = _angular_separation(
                    a.lon_ecl, a.lat_ecl, b.lon_ecl, b.lat_ecl
                )
                for asp_name, asp_target in ASPECTS.items():
                    orb = min(
                        abs(angle - asp_target),
                        360.0 - abs(angle - asp_target),
                    )
                    if orb <= ASPECT_ORB:
                        proximity = 1.0 - (orb / ASPECT_ORB)
                        result.append(AspectScore(
                            body_a=a.name,
                            body_b=b.name,
                            aspect_name=asp_name,
                            target_angle=asp_target,
                            actual_angle=round(angle, 4),
                            proximity=round(proximity, 4),
                            orb_degrees=round(orb, 4),
                        ))
        return result

    def _cluster_density(
        self, bodies: dict[str, CelestialBody]
    ) -> PlanetCluster:
        """Compute planetary clustering density score.

        Algorithm: sliding window of 60° across the ecliptic, count bodies
        within. Density = max count / total bodies. Higher = more clustered.
        """
        lons = sorted(
            (b.lon_ecl, b.name) for b in bodies.values()
            if b.name not in ("Sun", "Moon")
        )
        n = len(lons)
        if n < 2:
            return PlanetCluster(0.0, 0.0, [])

        best_count = 2
        best_center = 0.0
        best_members: list[str] = []

        window = 60.0  # degrees
        for i, (center_lon, _) in enumerate(lons):
            count = 0
            members = []
            for lon, name in lons:
                dist = min(abs(lon - center_lon), 360.0 - abs(lon - center_lon))
                if dist <= window / 2:
                    count += 1
                    members.append(name)
            if count > best_count:
                best_count = count
                best_center = center_lon
                best_members = members

        density = best_count / n
        return PlanetCluster(
            density_score=round(density, 4),
            cluster_center=round(best_center, 4),
            participating=best_members,
        )

    def compute(self, dt: datetime) -> EphemerisSnapshot:
        """Compute full ephemeris snapshot for a given UTC datetime."""
        self._ensure_loaded()

        # Convert to Skyfield time — must use skyfield's UTC-aware wrapper
        # Ensure dt is UTC-aware first
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        # Skyfield requires its own utc object
        from skyfield.api import utc as sf_utc
        t = self._ts.from_datetime(dt.astimezone(sf_utc))

        # All bodies
        bodies = {}
        for name in PLANETS:
            bodies[name] = self._body_position(name, t)

        # Lunar state
        lunar = self._lunar_state(t, bodies["Sun"], bodies["Moon"])

        # Aspects
        aspects = self._compute_aspects(bodies)

        # Cluster
        cluster = self._cluster_density(bodies)

        return EphemerisSnapshot(
            ts=dt,
            bodies=bodies,
            lunar=lunar,
            aspects=aspects,
            cluster=cluster,
        )

    def compute_range(
        self,
        start: datetime,
        end: datetime,
        interval_hours: float = 24.0,
    ) -> list[EphemerisSnapshot]:
        """Compute snapshots over a time range."""
        snapshots = []
        current = start
        while current <= end:
            snapshots.append(self.compute(current))
            current += timedelta(hours=interval_hours)
        return snapshots

    def find_aspect_events(
        self,
        start: datetime,
        end: datetime,
        body_a: str,
        body_b: str,
        aspect: str,
        interval_hours: float = 1.0,
        orb_threshold: float = 1.0,
    ) -> list[datetime]:
        """Find exact times when two bodies form a specific aspect within orb."""
        target = ASPECTS.get(aspect)
        if target is None:
            raise ValueError(f"Unknown aspect: {aspect}. Use: {list(ASPECTS.keys())}")

        events = []
        current = start
        prev_angle = None
        while current <= end:
            snap = self.compute(current)
            a_body = snap.bodies[body_a]
            b_body = snap.bodies[body_b]
            angle = _angular_separation(
                a_body.lon_ecl, a_body.lat_ecl, b_body.lon_ecl, b_body.lat_ecl
            )
            orb = min(abs(angle - target), 360.0 - abs(angle - target))

            if orb <= orb_threshold and prev_angle is not None:
                # Check if we crossed the exact aspect
                prev_orb = min(abs(prev_angle - target), 360.0 - abs(prev_angle - target))
                if orb < prev_orb and orb <= 0.5:  # close to exact
                    events.append(current)

            prev_angle = angle
            current += timedelta(hours=interval_hours)

        return events

    def find_lunar_events(
        self,
        start: datetime,
        end: datetime,
        interval_hours: float = 1.0,
    ) -> dict[str, list[datetime]]:
        """Find new moon, full moon, first quarter, last quarter dates."""
        events: dict[str, list[datetime]] = {
            "new_moon": [],
            "full_moon": [],
            "first_quarter": [],
            "last_quarter": [],
        }
        current = start
        while current <= end:
            snap = self.compute(current)
            pa = snap.lunar.phase_angle

            # Detect phase crossings
            for target, name in [(0, "new_moon"), (90, "first_quarter"),
                                  (180, "full_moon"), (270, "last_quarter")]:
                orb = min(abs(pa - target), 360.0 - abs(pa - target))
                if orb <= 0.5:
                    events[name].append(current)
                    break  # one phase per timestamp

            current += timedelta(hours=interval_hours)

        return events


# ─────────────────────────────────────────────────────────────────────────────
# PURE MATH HELPERS (stdlib-only, testable without skyfield)
# ─────────────────────────────────────────────────────────────────────────────

def _angular_separation(
    lon1: float, lat1: float, lon2: float, lat2: float
) -> float:
    """Great-circle angular separation between two ecliptic positions.

    All inputs in degrees. Returns degrees [0, 180].
    """
    dlon = math.radians(lon2 - lon1)
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    a = (
        math.sin(lat1_r) * math.sin(lat2_r)
        + math.cos(lat1_r) * math.cos(lat2_r) * math.cos(dlon)
    )
    a = max(-1.0, min(1.0, a))
    return math.degrees(math.acos(a))


def continuous_lunar_phase(illumination: float, phase_angle: float) -> tuple[float, float]:
    """Convert lunar data to continuous ML-friendly features.

    Returns (sin_component, cos_component) for a circular feature representation
    that avoids the 0°/360° discontinuity in phase angle.
    """
    return (
        math.sin(math.radians(phase_angle)),
        math.cos(math.radians(phase_angle)),
    )


def aspect_proximity(actual_angle: float, target_angle: float, orb: float = 8.0) -> float:
    """Score how close actual_angle is to target_angle, 0.0–1.0."""
    diff = min(abs(actual_angle - target_angle), 360.0 - abs(actual_angle - target_angle))
    if diff > orb:
        return 0.0
    return 1.0 - (diff / orb)


def retrograde_score(speed_deg_per_day: float) -> float:
    """Convert retrograde speed to a feature: positive = direct, negative = retrograde."""
    return max(-3.0, min(3.0, speed_deg_per_day)) / 3.0  # normalize to [-1, 1]


def is_turning_point_window(
    dt: datetime,
    lunar_events: dict[str, list[datetime]],
    window_days: int = 1,
) -> dict[str, bool]:
    """Check if dt is within window_days of any lunar event.

    Returns dict with boolean flags for each event type.
    """
    result = {}
    window = timedelta(days=window_days)
    for event_name, dates in lunar_events.items():
        result[event_name] = any(
            abs(dt - ed) <= window for ed in dates
        )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: degree normalization
# ─────────────────────────────────────────────────────────────────────────────

def normalize_angle(deg: float, to_range: float = 360.0) -> float:
    """Normalize angle to [0, to_range)."""
    return deg % to_range


def angular_distance_to(angle_a: float, angle_b: float) -> float:
    """Symmetric great-circle distance on a 360° circle (shortest arc).

    Returns a value in [0, 180]. This is the correct way to measure how close
    a phase angle is to a target event (e.g. 0° new moon, 180° full moon).

    BUG CONTEXT: several modules previously used asymmetric comparisons like
    `pa < 15 or pa > 345` to detect proximity to 0°, which treated pa=340 as
    "near new moon" but pa=20 as "far" — despite both being 20° away. Using
    this helper makes proximity symmetric and avoids the wrap-around trap.
    """
    d = abs(angle_a - angle_b) % 360.0
    return min(d, 360.0 - d)


def lunar_phase_name(phase_angle: float) -> str:
    """Human-readable name for a lunar phase angle (0–360°).

    Single source of truth shared by daemon/dashboard so the phase label is
    always computed the same way (symmetric, wrap-around-safe).

    Phases (orb ±15° around each cardinal phase):
      0°   🌑 New Moon
      90°  🌓 First Quarter
      180° 🌕 Full Moon
      270° 🌗 Last Quarter
    Intermediate octants are labelled Waxing/Waning Crescent/Gibbous.
    """
    pa = phase_angle % 360.0
    # Cardinal phases first (symmetric distance check)
    if angular_distance_to(pa, 0.0) < 15.0:
        return "🌑 New Moon"
    if angular_distance_to(pa, 90.0) < 15.0:
        return "🌓 First Quarter"
    if angular_distance_to(pa, 180.0) < 15.0:
        return "🌕 Full Moon"
    if angular_distance_to(pa, 270.0) < 15.0:
        return "🌗 Last Quarter"
    # Intermediate octants
    if pa < 90:
        return "🌒 Waxing Crescent"
    if pa < 180:
        return "🌔 Waxing Gibbous"
    if pa < 270:
        return "🌖 Waning Gibbous"
    return "🌘 Waning Crescent"


# ─────────────────────────────────────────────────────────────────────────────
# BATCH COMPUTATION (for feature engineering pipelines)
# ─────────────────────────────────────────────────────────────────────────────

def compute_astro_features(
    snap: EphemerisSnapshot,
) -> dict[str, float]:
    """Extract a flat dictionary of numerical astro features from a snapshot.

    Designed as input to ML models. Continuous, normalized, no ordinal encoding.
    """
    f: dict[str, float] = {}

    # ── Lunar features ──
    f["lunar_phase_sin"] = snap.lunar.phase_sin
    f["lunar_phase_cos"] = snap.lunar.phase_cos
    f["lunar_illumination"] = snap.lunar.illumination
    f["lunar_distance_km"] = snap.lunar.distance_km
    f["lunar_declination"] = snap.lunar.declination
    f["lunar_sun_moon_sep"] = snap.lunar.sun_moon_sep
    f["lunar_days_to_new"] = snap.lunar.days_to_new
    f["lunar_days_to_full"] = snap.lunar.days_to_full

    # ── Planetary longitude (sin/cos for circular encoding) ──
    for name in ["Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune"]:
        body = snap.bodies.get(name)
        if body:
            rad = math.radians(body.lon_ecl)
            f[f"{name}_lon_sin"] = math.sin(rad)
            f[f"{name}_lon_cos"] = math.cos(rad)
            f[f"{name}_retrograde"] = 1.0 if body.is_retrograde else 0.0
            f[f"{name}_distance_au"] = body.distance_au
            f[f"{name}_declination"] = body.dec_deg

    # Sun
    sun = snap.bodies.get("Sun")
    if sun:
        f["sun_lon_sin"] = math.sin(math.radians(sun.lon_ecl))
        f["sun_lon_cos"] = math.cos(math.radians(sun.lon_ecl))
        f["sun_declination"] = sun.dec_deg

    # ── Aspect proximity scores (top aspects) ──
    for asp_name in ASPECTS:
        # Max proximity for each aspect type
        scores = [a.proximity for a in snap.aspects if a.aspect_name == asp_name]
        f[f"aspect_{asp_name}_max"] = max(scores) if scores else 0.0
        f[f"aspect_{asp_name}_count"] = float(len(scores))

    # ── Cluster density ──
    f["planet_cluster_density"] = snap.cluster.density_score
    f["planet_cluster_center_sin"] = math.sin(math.radians(snap.cluster.cluster_center))
    f["planet_cluster_center_cos"] = math.cos(math.radians(snap.cluster.cluster_center))

    # ── Retrograde count ──
    f["retrograde_count"] = float(
        sum(1 for b in snap.bodies.values() if b.is_retrograde)
    )

    return f


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    engine = EphemerisEngine()
    now = datetime.now(timezone.utc)
    snap = engine.compute(now)

    print(f"=== Astronacci Ephemeris Snapshot @ {snap.ts.isoformat()} ===")
    print(f"Lunar: phase={snap.lunar.phase_angle:.1f}° illum={snap.lunar.illumination:.3f}")
    print(f"Sun-Moon separation: {snap.lunar.sun_moon_sep:.1f}°")
    print(f"Moon distance: {snap.lunar.distance_km:.0f} km")
    print(f"Moon declination: {snap.lunar.declination:.2f}°")
    print(f"Retrograde: {[b.name for b in snap.bodies.values() if b.is_retrograde]}")
    print(f"Aspects (top 5):")
    for a in sorted(snap.aspects, key=lambda x: -x.proximity)[:5]:
        print(f"  {a.body_a}-{a.body_b} {a.aspect_name} "
              f"({a.actual_angle:.1f}°, orb={a.orb_degrees:.2f}°, "
              f"prox={a.proximity:.3f})")
    print(f"Cluster: density={snap.cluster.density_score:.3f} "
          f"members={snap.cluster.participating}")

    features = compute_astro_features(snap)
    print(f"\nFeatures: {len(features)} computed")
    for k, v in sorted(features.items())[:10]:
        print(f"  {k}: {v:.4f}")
