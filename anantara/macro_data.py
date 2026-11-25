"""
macro_data.py — US Macroeconomic Factor Integration (audit 2026-09-08)

Menambahkan kesadaran event FOMC/CPI/NFP/GDP + data pasar DXY/Treasury-yield/VIX
ke pipeline Pre-Sentimen & Intelijen Anantara Sakti.

PRINSIP DESAIN (evidence-based, anti-bias, sesuai §10.2 metodologi repo):
- Semua time-series (VIX, DXY, yield) diambil LIVE dari FRED (Federal Reserve
  Bank of St. Louis) via endpoint CSV publik — TANPA API KEY, tanpa rate-limit
  masalah untuk polling low-frequency (cache 4 jam; data ini tidak bergerak
  intraday seperti crypto).
- KALENDER event (tanggal FOMC/CPI/NFP/GDP) di-HARDCODE per tahun dari sumber
  RESMI (federalreserve.gov, bls.gov, bea.gov) — diverifikasi manual via
  web_search pada 2026-09-08, BUKAN scraping HTML live (scraping halaman .gov
  rapuh; tanggal salah lebih berbahaya daripada tidak ada data).
- macro_tilt (komposit DXY + VIX + yield-curve) DIEKSPOS tapi TIDAK dibobotkan
  ke intelligence composite_score secara default — sesuai aturan repo sendiri
  "no deploy without OOS evidence, n>=20". Sinyal baru butuh bukti backtest
  empiris dulu sebelum memengaruhi trade_eligible. Sampai saat itu, statusnya
  INFORMASIONAL SAJA (tampil di laporan + API, TIDAK mengubah skor).
- event_guard menandai window volatilitas tinggi (defensive-only, BUKAN
  taruhan arah) — ini TIDAK butuh backtest karena murni risk-avoidance
  (analog dengan melebarkan SL / menahan entry saat news berdampak tinggi,
  praktik risk management standar tanpa risiko overfitting).

SUMBER DATA TERVERIFIKASI (2026-09-08, via web_search langsung ke situs resmi):
- FOMC 2026: federalreserve.gov/monetarypolicy/fomccalendars.htm
- CPI 2026:  bls.gov/schedule/news_release/cpi.htm
- NFP 2026:  bls.gov/schedule/news_release/empsit.htm
- GDP 2026:  bea.gov/news/schedule/full
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# FRED series IDs — semua gratis, tanpa API key, update harian/mingguan/bulanan.
SERIES_VIX          = "VIXCLS"     # CBOE Volatility Index (fear gauge, harian)
SERIES_DXY_BROAD     = "DTWEXBGS"  # Nominal Broad US Dollar Index (Fed, harian)
SERIES_UST10Y        = "DGS10"     # 10-Year Treasury Yield (harian)
SERIES_UST2Y         = "DGS2"      # 2-Year Treasury Yield (harian)
SERIES_YIELD_CURVE   = "T10Y2Y"    # 10Y-2Y spread; negatif = inversi (resesi warning)
SERIES_FEDFUNDS      = "DFF"       # Effective Federal Funds Rate (harian)

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL_S = 4 * 3600  # 4 jam — macro data tidak bergerak intraday

# ─────────────────────────────────────────────────────────────────────────
# KALENDER EVENT MAKRO 2026 — hardcoded, sumber resmi terverifikasi manual
# ─────────────────────────────────────────────────────────────────────────

# FOMC rate decision — semua jam 14:00 waktu Eastern (ET). UTC offset berubah
# sesuai DST AS (EDT=UTC-4 Mar 8–Nov 1 2026; EST=UTC-5 di luar itu).
FOMC_2026_UTC = [
    dt.datetime(2026, 1, 28, 19, 0, tzinfo=dt.timezone.utc),   # EST (UTC-5)
    dt.datetime(2026, 3, 18, 18, 0, tzinfo=dt.timezone.utc),   # EDT (UTC-4)
    dt.datetime(2026, 4, 29, 18, 0, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 6, 17, 18, 0, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 7, 29, 18, 0, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 9, 16, 18, 0, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 10, 28, 18, 0, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 12, 9, 19, 0, tzinfo=dt.timezone.utc),   # EST (UTC-5)
]

# CPI (Consumer Price Index) — 08:30 ET. Sumber: bls.gov/schedule/news_release/cpi.htm
CPI_2026_UTC = [
    dt.datetime(2026, 1, 13, 13, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 2, 13, 13, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 3, 11, 12, 30, tzinfo=dt.timezone.utc),  # EDT mulai
    dt.datetime(2026, 4, 10, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 5, 12, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 6, 10, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 7, 14, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 8, 12, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 9, 11, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 10, 14, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 11, 10, 13, 30, tzinfo=dt.timezone.utc),  # EST mulai
    dt.datetime(2026, 12, 10, 13, 30, tzinfo=dt.timezone.utc),
]

# NFP / Employment Situation — 08:30 ET. Sumber: bls.gov/schedule/news_release/empsit.htm
NFP_2026_UTC = [
    dt.datetime(2026, 1, 9, 13, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 2, 11, 13, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 3, 6, 13, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 4, 3, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 5, 8, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 6, 5, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 7, 2, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 8, 7, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 9, 4, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 10, 2, 12, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 11, 6, 13, 30, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 12, 4, 13, 30, tzinfo=dt.timezone.utc),
]

# GDP Advance Estimate (BEA) — 08:30 ET. Sumber: bea.gov/news/schedule/full
GDP_2026_UTC = [
    dt.datetime(2026, 2, 20, 13, 30, tzinfo=dt.timezone.utc),  # Q4'25 (rescheduled)
    dt.datetime(2026, 4, 30, 12, 30, tzinfo=dt.timezone.utc),  # Q1'26
    dt.datetime(2026, 7, 30, 12, 30, tzinfo=dt.timezone.utc),  # Q2'26
    dt.datetime(2026, 10, 29, 12, 30, tzinfo=dt.timezone.utc), # Q3'26
]

_EVENTS = (
    [("FOMC", t) for t in FOMC_2026_UTC]
    + [("CPI", t) for t in CPI_2026_UTC]
    + [("NFP", t) for t in NFP_2026_UTC]
    + [("GDP", t) for t in GDP_2026_UTC]
)

# Window peringatan: berapa jam sebelum/sesudah event dianggap "high volatility zone"
EVENT_GUARD_BEFORE_H = 2.0   # 2 jam sebelum rilis: mulai waspada
EVENT_GUARD_AFTER_H = 1.0    # 1 jam setelah rilis: masih volatile


# ─────────────────────────────────────────────────────────────────────────
# FETCHER — FRED CSV publik, tanpa API key
# ─────────────────────────────────────────────────────────────────────────

async def _fetch_fred_series(series_id: str, client: httpx.AsyncClient) -> list[tuple[str, float]] | None:
    """Ambil deret waktu FRED via endpoint CSV publik. Return None jika gagal."""
    cache_key = f"fred:{series_id}"
    now = time.time()
    if cache_key in _CACHE:
        ts, val = _CACHE[cache_key]
        if now - ts < _CACHE_TTL_S:
            return val
    try:
        resp = await client.get(FRED_CSV_URL.format(series_id=series_id), timeout=15.0)
        resp.raise_for_status()
        lines = resp.text.strip().splitlines()
        rows: list[tuple[str, float]] = []
        for ln in lines[1:]:  # skip header "DATE,VALUE"
            parts = ln.split(",")
            if len(parts) != 2:
                continue
            date_s, val_s = parts
            if val_s.strip() in ("", "."):  # FRED pakai "." untuk missing data
                continue
            try:
                rows.append((date_s, float(val_s)))
            except ValueError:
                continue
        if not rows:
            return None
        _CACHE[cache_key] = (now, rows)
        return rows
    except Exception:
        return None


def _pct_change(rows: list[tuple[str, float]], lookback: int) -> float | None:
    """Persen perubahan dari `lookback` observasi terakhir ke observasi terkini."""
    if len(rows) < lookback + 1:
        return None
    latest = rows[-1][1]
    prior = rows[-1 - lookback][1]
    if prior == 0:
        return None
    return round((latest - prior) / prior * 100.0, 4)


async def fetch_macro_snapshot() -> dict[str, Any]:
    """Ambil snapshot lengkap makro AS: VIX, DXY, yield curve, Fed funds rate.

    Semua live dari FRED. Graceful degradation: field individual None kalau
    fetch gagal, TIDAK exception (data makro adalah signal tambahan, bukan
    dependency kritis — sistem harus tetap jalan kalau FRED down).
    """
    async with httpx.AsyncClient() as client:
        vix_rows   = await _fetch_fred_series(SERIES_VIX, client)
        dxy_rows   = await _fetch_fred_series(SERIES_DXY_BROAD, client)
        y10_rows   = await _fetch_fred_series(SERIES_UST10Y, client)
        y2_rows    = await _fetch_fred_series(SERIES_UST2Y, client)
        curve_rows = await _fetch_fred_series(SERIES_YIELD_CURVE, client)
        ffr_rows   = await _fetch_fred_series(SERIES_FEDFUNDS, client)

    vix_level  = vix_rows[-1][1] if vix_rows else None
    vix_chg_5d = _pct_change(vix_rows, 5) if vix_rows else None
    dxy_level  = dxy_rows[-1][1] if dxy_rows else None
    dxy_chg_5d = _pct_change(dxy_rows, 5) if dxy_rows else None
    y10        = y10_rows[-1][1] if y10_rows else None
    y2         = y2_rows[-1][1] if y2_rows else None
    curve      = curve_rows[-1][1] if curve_rows else None
    ffr        = ffr_rows[-1][1] if ffr_rows else None

    return {
        "vix_level": vix_level,
        "vix_chg_5d_pct": vix_chg_5d,
        "dxy_level": dxy_level,
        "dxy_chg_5d_pct": dxy_chg_5d,
        "ust10y_pct": y10,
        "ust2y_pct": y2,
        "yield_curve_10y2y": curve,
        "yield_curve_inverted": (curve is not None and curve < 0),
        "fed_funds_rate_pct": ffr,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "FRED (fred.stlouisfed.org), no API key required",
    }


def fetch_macro_snapshot_sync() -> dict[str, Any]:
    """Sync wrapper for sync engines (Freqtrade/SoDEX)."""
    return asyncio.run(fetch_macro_snapshot())


# ─────────────────────────────────────────────────────────────────────────
# EVENT GUARD — deteksi window high-impact event
# ─────────────────────────────────────────────────────────────────────────

def next_macro_events(now: dt.datetime | None = None, limit: int = 3) -> list[dict[str, Any]]:
    """Daftar N event makro berikutnya (FOMC/CPI/NFP/GDP), terurut waktu."""
    now = now or dt.datetime.now(dt.timezone.utc)
    upcoming = sorted((t, name) for name, t in _EVENTS if t >= now)
    out = []
    for t, name in upcoming[:limit]:
        delta_h = (t - now).total_seconds() / 3600.0
        out.append({
            "event": name,
            "datetime_utc": t.isoformat(),
            "hours_until": round(delta_h, 1),
        })
    return out


def event_guard_status(now: dt.datetime | None = None) -> dict[str, Any]:
    """Cek apakah sekarang berada di window volatilitas tinggi (event makro dekat).

    Return dict dengan `active` (bool), `event` (nama event kalau aktif),
    dan `reason` (penjelasan human-readable). Ini SINYAL DEFENSIF — dipakai
    untuk menahan/mengurangi ukuran entry baru, BUKAN untuk memilih arah.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    for name, t in _EVENTS:
        hours_diff = (now - t).total_seconds() / 3600.0
        if -EVENT_GUARD_BEFORE_H <= hours_diff <= EVENT_GUARD_AFTER_H:
            phase = "before" if hours_diff < 0 else "after"
            return {
                "active": True,
                "event": name,
                "phase": phase,
                "event_time_utc": t.isoformat(),
                "reason": (
                    f"{name} window aktif ({phase} rilis) — volatilitas makro tinggi, "
                    f"pertimbangkan kurangi ukuran entry baru / lebarkan SL"
                ),
            }
    nxt = next_macro_events(now, limit=1)
    return {
        "active": False,
        "event": None,
        "next_event": nxt[0] if nxt else None,
    }


# ─────────────────────────────────────────────────────────────────────────
# macro_tilt — sinyal komposit INFORMASIONAL (belum dibobot ke composite_score)
# ─────────────────────────────────────────────────────────────────────────

def compute_macro_tilt(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Hitung macro_tilt [-1, 1]: risk-on (+) vs risk-off (-) dari DXY+VIX.

    Logika (berbasis korelasi makro yang mapan di literatur — BUKAN backtested
    khusus untuk crypto oleh kami):
    - DXY naik (dollar strengthening) → historically risk-off untuk aset
      berisiko termasuk crypto (korelasi negatif BTC-DXY terdokumentasi luas).
    - VIX naik tajam (fear gauge) → risk-off, crypto cenderung ikut turun
      saat VIX spike (correlation regime-dependent, lebih kuat saat VIX>25).
    - Yield curve inversi (10Y-2Y<0) → sinyal resesi jangka menengah, bukan
      sinyal jangka pendek untuk swing 1-30 jam — TIDAK dimasukkan ke tilt
      jangka pendek ini, hanya ditampilkan sebagai konteks makro.

    STATUS: informational. TIDAK di-backtest empiris terhadap crypto returns
    oleh sistem ini (n=0 evidence). Weight di bawah adalah estimasi literatur
    umum, bukan hasil kalibrasi OOS — JANGAN dipakai untuk trading decision
    otomatis sampai divalidasi dengan data historis (lihat catatan roadmap).
    """
    dxy_chg = snapshot.get("dxy_chg_5d_pct")
    vix_level = snapshot.get("vix_level")
    vix_chg = snapshot.get("vix_chg_5d_pct")

    parts = []
    if dxy_chg is not None:
        # DXY +1% dalam 5 hari → -0.3 tilt (risk-off); skala linear, cap ±0.5
        parts.append(max(-0.5, min(0.5, -dxy_chg * 0.3)))
    if vix_chg is not None and vix_level is not None:
        # VIX naik >15% dalam 5 hari DAN level >20 → risk-off signifikan
        if vix_chg > 15.0 and vix_level > 20.0:
            parts.append(-0.5)
        elif vix_chg > 8.0:
            parts.append(-0.25)
        elif vix_chg < -15.0:
            parts.append(0.25)  # VIX crush = risk-on

    if not parts:
        return {"macro_tilt": 0.0, "confidence": "no_data", "components_used": 0}

    tilt = max(-1.0, min(1.0, sum(parts) / len(parts)))
    return {
        "macro_tilt": round(tilt, 3),
        "confidence": "low_n0_backtest" if len(parts) < 2 else "medium_n0_backtest",
        "components_used": len(parts),
        "note": "Literature-based heuristic, NOT empirically backtested for crypto. Informational only.",
    }
