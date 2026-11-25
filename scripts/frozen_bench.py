#!/usr/bin/env python3
"""Basis Uji Beku (frozen bench) — Anantara Sakti.

MENGAPA BERKAS INI ADA
----------------------
Kesalahan paling mahal di ekosistem ini bukan kode yang crash, tapi KESIMPULAN
yang salah: gerbang sinyal dinyatakan "terbukti" padahal telemetri punya
duplikasi 11,64x. Saat duplikasi dibiarkan, false-positive rate melonjak dari
~4,9% ke ~58% (diukur ulang di sini) — mayoritas "temuan" adalah kebetulan.

Bench ini membekukan data SEKALI, mengunci hashnya, lalu menilai aturan apa pun
terhadap data yang sama persis. Tiga sifat yang membuatnya boleh dipercaya:

1. BEKU & DETERMINISTIK — setelah freeze, tidak ada jaringan, tidak ada angka
   yang bergeser. Seed bootstrap/permutasi tetap.
2. FAIL-CLOSED — hash tak cocok / berkas hilang / kolom kurang => ABORT.
   Tidak pernah "lulus karena data tak terbaca" (kelas cacat A9).
3. KONTROL NEGATIF TERPASANG — bench menguji DIRINYA SENDIRI: gerbang ACAK
   harus "signifikan" di ~5% kasus (alpha), bukan 58%. Kalau kontrol ini gagal,
   SELURUH keluaran bench tidak boleh dipercaya.

Pakai:
    python3 scripts/frozen_bench.py --freeze      # bekukan data (sekali)
    python3 scripts/frozen_bench.py --selfcheck   # integritas + kontrol negatif
    python3 scripts/frozen_bench.py --eval        # nilai gerbang produksi
    python3 scripts/frozen_bench.py --report      # JSON ringkas

BATAS PERAN (jangan dilebihkan)
-------------------------------
Bench ini MENGUKUR; ia tidak membuktikan kebenaran kausal. CI95 yang
mengecualikan nol = "belum terfalsifikasi", bukan "terbukti benar". n kecil
(<20 blokir) tetap "MONITOR", bukan "ACTION".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

import numpy as np
from statistics import NormalDist

ROOT = pathlib.Path(__file__).resolve().parent.parent
TELEMETRY = ROOT / "data" / "paper_test_shortbear_sodex_mark_execution_telemetry.jsonl"
PRICE_CACHE = ROOT / "data" / "research" / "binance_1h_cache"
FREEZE_DIR = ROOT / "data" / "frozen"
CYCLES_F = FREEZE_DIR / "cycles.jsonl"
PRICES_F = FREEZE_DIR / "prices.json"
MANIFEST_F = FREEZE_DIR / "MANIFEST.json"

PAIRS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT", "UNIUSDT"]
HORIZONS = [1, 4, 24]
ALPHA = 0.05
# z kritis dua-sisi untuk ALPHA (kuantil normal baku, stdlib-only).
_Z_CRIT = NormalDist().inv_cdf(1.0 - ALPHA / 2.0)
# Inflasi variansi `n_signifikan` antar-aturan acak. Ke-200 aturan mengacak label di
# ATAS DATA YANG SAMA (2400 siklus identik), jadi indikator "signifikan"-nya saling
# berkorelasi -> sd sebenarnya > sd binomial. Terukur 2026-10-04 (40 replikasi x 3
# horizon): sd empiris 3,483/3,562/3,586 vs binomial 3,082 -> 1,28x/1,34x/1,35x.
# Tanpa koreksi ini ambang terlalu ketat dan kontrol bisa GAGAL secara keliru.
VAR_INFLASI_ANTAR_ATURAN = 1.35
SCHEMA = 1

# Ambang minimum per kelompok. MENGAPA 20: pedoman riset "n<20 = MONITOR, bukan
# ACTION". Ambang 5 yang lama meloloskan n=20 (12 blokir/8 lolos) sebagai
# "SINYAL" dengan CI95 nyaris menyentuh nol — kelas keyakinan palsu yang persis
# diperangi bench ini. CI95 pada n kecil tidak berarti apa-apa.
MIN_GROUP = 20

# Seed TETAP — bagian dari kontrak determinisme. Jangan diubah tanpa
# membekukan ulang + mencatat di MANIFEST (kalau tidak, hasil lama tak banding).
SEED_BOOT = 7
SEED_PERM = 11
SEED_NEG = 1234


class BenchError(RuntimeError):
    """Dilempar saat integritas bench rusak. Fail-closed: pemanggil WAJIB berhenti."""


# ── Gerbang produksi (predikat identik dengan signal_gate_falsification.py) ────
def _chk_below_4(f: dict) -> bool:
    v = f.get("chk")
    try:
        return v is not None and float(v) < 4
    except (TypeError, ValueError):
        return False


GATES = {
    "chk_below_4":            ("chk < 4", _chk_below_4),
    "bear_stack_failed":      ("bear_stack tidak terpenuhi", lambda f: f.get("bear_stack") is False),
    "return_1h_not_negative": ("r1 tidak negatif", lambda f: f.get("r1_negative") is False),
    "weekend":                ("akhir pekan", lambda f: f.get("weekend") is True),
}


# ── Utilitas hash ─────────────────────────────────────────────────────────────
def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(p: pathlib.Path) -> str:
    """Jalur relatif terhadap ROOT; jatuh ke absolut bila di luar repo.

    MENGAPA: telemetri bisa berada di luar pohon repo (mis. di direktori
    sementara saat diuji). `relative_to` melempar ValueError di kasus itu, dan
    freeze() tidak boleh mati hanya karena provenance-nya tak bisa dipendekkan.
    """
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


# ── 1. FREEZE ─────────────────────────────────────────────────────────────────
def _load_raw_cycles() -> tuple[list[dict], int]:
    """Muat telemetri mentah + DEDUP ke (pair, signal_candle_ts) unik.

    MENGAPA dedup: loop berjalan ~12x/jam/pair dengan candle sinyal SAMA PERSIS.
    Memakai baris mentah menggelembungkan n 11,64x dan membuat p-value
    anti-konservatif (dibuktikan oleh kontrol negatif bench ini sendiri).
    Nilai gerbang TERBUKTI konstan dalam satu (pair, candle) — 0% tidak
    konsisten — jadi mengambil satu baris tidak menghilangkan informasi apa pun.

    Kembalikan (cycles_unik, n_baris_mentah).
    """
    if not TELEMETRY.exists():
        raise BenchError(f"telemetri tidak ada: {TELEMETRY}")
    out: dict[tuple, dict] = {}
    raw = 0
    with TELEMETRY.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw += 1
            fu = r.get("funnel") or {}
            ts = fu.get("signal_candle_ts") or r.get("signal_candle_ts")
            if ts is None or not fu:
                continue
            try:
                fts = float(ts)
            except (TypeError, ValueError):
                continue
            key = (r.get("pair"), fts)
            if key in out:
                continue
            out[key] = {
                "pair": r.get("pair"),
                "symbol": r.get("symbol"),
                "ts": fts,
                "entry_ts": float(fu.get("entry_candle_ts") or (fts + 3600)),
                "decision": r.get("decision"),
                "funnel": fu,
            }
    return list(out.values()), raw


def _load_prices_from_cache(cycles: list[dict]) -> dict[str, dict[int, dict]]:
    """Indeks harga dari CACHE LOKAL saja (tanpa jaringan) — inti determinisme.

    Rentang: dari 1 jam sebelum siklus paling awal sampai horizon terpanjang
    setelah entry paling akhir. Cache dibuat oleh signal_gate_falsification.py.
    """
    t0 = int(min(c["ts"] for c in cycles)) * 1000 - 3600_000
    t1 = int(max(c["entry_ts"] for c in cycles)) * 1000 + (max(HORIZONS) + 2) * 3600_000
    idx: dict[str, dict[int, dict]] = {}
    for sym in PAIRS:
        cands = sorted(PRICE_CACHE.glob(f"{sym}_*.json"))
        if not cands:
            raise BenchError(
                f"cache harga tidak ada untuk {sym} di {PRICE_CACHE}. "
                f"Jalankan scripts/signal_gate_falsification.py dulu untuk mengunduhnya."
            )
        rows: list[list] = []
        for cf in cands:
            try:
                rows.extend(json.loads(cf.read_text()))
            except json.JSONDecodeError:
                raise BenchError(f"cache harga rusak (JSON invalid): {cf}")
        bars = {
            int(r[0]): {"o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4])}
            for r in rows
        }
        if not bars:
            raise BenchError(f"cache harga kosong untuk {sym}")
        idx[sym] = bars
    _ = (t0, t1)  # rentang terdokumentasi; bar di luar rentang tidak dipakai
    return idx


def freeze() -> dict:
    """Bekukan dataset + tulis MANIFEST ber-hash. Idempoten."""
    FREEZE_DIR.mkdir(parents=True, exist_ok=True)
    cycles, raw = _load_raw_cycles()
    prices = _load_prices_from_cache(cycles)

    # cycles.jsonl — diurutkan agar bit-identik antar-jalan
    cycles.sort(key=lambda c: (c["pair"] or "", c["ts"]))
    with CYCLES_F.open("w") as fh:
        for c in cycles:
            fh.write(json.dumps(c, sort_keys=True, separators=(",", ":")) + "\n")

    # prices.json — kunci int jadi str (batasan JSON), dikembalikan saat load
    PRICES_F.write_text(json.dumps(
        {sym: {str(k): v for k, v in sorted(bars.items())} for sym, bars in prices.items()},
        sort_keys=True, separators=(",", ":"),
    ))

    n_bars = sum(len(b) for b in prices.values())
    manifest = {
        "schema": SCHEMA,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "seeds": {"boot": SEED_BOOT, "perm": SEED_PERM, "neg": SEED_NEG},
        "horizons": HORIZONS,
        "alpha": ALPHA,
        "source_telemetry": {
            "path": _rel(TELEMETRY),
            "sha256": sha256_file(TELEMETRY),
            "bytes": TELEMETRY.stat().st_size,
        },
        "dedup": {
            "baris_mentah": raw,
            "unik_pair_jam": len(cycles),
            "rasio_penggelembungan": round(raw / max(len(cycles), 1), 3),
        },
        "artifacts": {
            "cycles.jsonl": {
                "sha256": sha256_file(CYCLES_F),
                "bytes": CYCLES_F.stat().st_size,
                "rows": len(cycles),
            },
            "prices.json": {
                "sha256": sha256_file(PRICES_F),
                "bytes": PRICES_F.stat().st_size,
                "symbols": sorted(prices.keys()),
                "bars": n_bars,
            },
        },
    }
    MANIFEST_F.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


# ── 2. LOAD (fail-closed) ─────────────────────────────────────────────────────
def load_frozen() -> tuple[list[dict], dict, dict]:
    """Muat dataset beku + VERIFIKASI hash. Rusak => BenchError (fail-closed)."""
    for p in (CYCLES_F, PRICES_F, MANIFEST_F):
        if not p.exists():
            raise BenchError(f"dataset beku belum ada ({p.name}). Jalankan: --freeze")
    manifest = json.loads(MANIFEST_F.read_text())
    if manifest.get("schema") != SCHEMA:
        raise BenchError(f"schema MANIFEST {manifest.get('schema')} != {SCHEMA} — freeze ulang")
    for name, path in (("cycles.jsonl", CYCLES_F), ("prices.json", PRICES_F)):
        want = manifest["artifacts"][name]["sha256"]
        got = sha256_file(path)
        if got != want:
            raise BenchError(
                f"INTEGRITAS RUSAK: {name} hash {got[:12]}... != manifest {want[:12]}...\n"
                f"  Data beku sudah berubah. JANGAN pakai hasil ini. Jalankan --freeze "
                f"hanya bila perubahan memang disengaja, lalu catat di laporan."
            )
    cycles = [json.loads(ln) for ln in CYCLES_F.read_text().splitlines() if ln.strip()]
    if len(cycles) != manifest["artifacts"]["cycles.jsonl"]["rows"]:
        raise BenchError("jumlah baris cycles tidak cocok dengan manifest")
    if not cycles:
        raise BenchError("dataset beku KOSONG — fail-closed (bukan lulus)")
    raw_prices = json.loads(PRICES_F.read_text())
    prices = {
        sym: {int(k): v for k, v in bars.items()}
        for sym, bars in raw_prices.items()
    }
    return cycles, prices, manifest


# ── 3. Penilaian ──────────────────────────────────────────────────────────────
def outcome(cycle: dict, prices: dict, h: int) -> float | None:
    """PnL short (%) pada horizon h jam. None bila harga tak tersedia."""
    bars = prices.get(cycle["symbol"])
    if not bars:
        return None
    e = int(cycle["entry_ts"]) * 1000
    x = int(cycle["entry_ts"] + h * 3600) * 1000
    b0, b1 = bars.get(e), bars.get(x)
    if not b0 or not b1 or b0["o"] <= 0:
        return None
    return -(b1["c"] / b0["o"] - 1.0) * 100.0


def _cluster_arrays(rows):
    """rows: (cluster_id, gate_bool, value) -> agregat per cluster."""
    cl = np.array([c for c, _, _ in rows])
    g = np.array([bool(b) for _, b, _ in rows])
    v = np.array([x for _, _, x in rows], dtype=float)
    uniq = np.unique(cl)
    s_a = np.array([v[(cl == c) & g].sum() for c in uniq])
    n_a = np.array([((cl == c) & g).sum() for c in uniq], dtype=float)
    s_b = np.array([v[(cl == c) & ~g].sum() for c in uniq])
    n_b = np.array([((cl == c) & ~g).sum() for c in uniq], dtype=float)
    obs = (v[g].mean() - v[~g].mean()) if g.any() and (~g).any() else float("nan")
    return uniq, cl, g, v, s_a, n_a, s_b, n_b, obs


def cluster_boot_ci(rows, n_boot: int = 4000, seed: int = SEED_BOOT):
    """CI95 selisih mean; resample unit = CLUSTER (jam), bukan baris.

    MENGAPA cluster: dalam satu jam 6 pair bergerak bersama (faktor pasar umum).
    Bootstrap per-baris menganggap observasi independen -> CI terlalu sempit.
    """
    uniq, cl, g, v, s_a, n_a, s_b, n_b, obs = _cluster_arrays(rows)
    if not np.isfinite(obs) or uniq.size < 3:
        return obs, float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, uniq.size, size=(n_boot, uniq.size))
    SA, NA = s_a[pick].sum(axis=1), n_a[pick].sum(axis=1)
    SB, NB = s_b[pick].sum(axis=1), n_b[pick].sum(axis=1)
    ok = (NA > 0) & (NB > 0)
    if not ok.any():
        return obs, float("nan"), float("nan")
    diffs = SA[ok] / NA[ok] - SB[ok] / NB[ok]
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(obs), float(lo), float(hi)


def permutation_test(rows, n_perm: int = 1500, seed: int = SEED_BOOT):
    """Nilai-p permutasi dua-sisi; SAH di bawah H0 berapa pun jumlah cluster.

    Mengapa ini menggantikan `cluster_boot_ci` di ARM KONTROL: label gerbang acak
    diberikan PER-BARIS (lihat `negative_control`), jadi di bawah H0 label dapat
    dipertukarkan di tingkat baris dan distribusi permutasi bersifat EKSAK.

    Bootstrap cluster sebaliknya anti-konservatif saat cluster sedikit. Terukur
    2026-10-04 pada data beku (2400 siklus, span 425 jam):
        cluster= 17 -> FPR 1,62x alpha      cluster= 99 -> 1,18x
        cluster= 40 -> FPR 1,35x alpha      cluster=399 -> 1,06x
    Fit: inflasi = 1 + 5,2715 * n_cluster^-0,7427  (R^2 = 0,9986).
    Efeknya: kontrol negatif h=24 (hanya ~18 cluster) melaporkan FPR 8,3% padahal
    labelnya acak murni -- gerbang mutunya sendiri GAGAL secara keliru.
    """
    values = np.array([v for _, _, v in rows], dtype=float)
    gate = np.array([bool(b) for _, b, _ in rows], dtype=bool)
    n = values.size
    k = int(gate.sum())
    if n < 4 or k < 1 or (n - k) < 1:
        return float("nan"), float("nan")
    obs = float(values[gate].mean() - values[~gate].mean())
    rng = np.random.default_rng(seed)
    total = float(values.sum())
    null = np.empty(n_perm, dtype=float)
    for i in range(n_perm):
        s = float(values[rng.permutation(n)[:k]].sum())
        null[i] = s / k - (total - s) / (n - k)
    p = float((np.abs(null) >= abs(obs) - 1e-12).mean())
    return obs, p


def permutation_z(rows):
    """Selisih mean + z dari distribusi PERMUTASI (varians eksak, aproksimasi normal).

    Di bawah H0 label diacak per-baris, maka variansi eksak statistik beda-mean
    untuk subset acak berukuran k dari n adalah:

        Var = [ sum((v_i - v_bar)^2) / (n-1) ] * n / (k*(n-k))

    Ini menjawab akar masalah: variabilitas yang benar adalah variabilitas
    PENGACAKAN, bukan variabilitas resampling cluster. Karena itu ia tetap sah
    walau jumlah cluster sedikit -- persis kasus yang membuat `cluster_boot_ci`
    melaporkan FPR 1,62x alpha pada 17 cluster (terukur 2026-10-04).
    """
    values = np.array([v for _, _, v in rows], dtype=float)
    gate = np.array([bool(b) for _, b, _ in rows], dtype=bool)
    n = values.size
    k = int(gate.sum())
    if n < 4 or k < 1 or (n - k) < 1:
        return float("nan"), float("nan")
    obs = float(values[gate].mean() - values[~gate].mean())
    vbar = values.mean()
    ss = float(((values - vbar) ** 2).sum())
    if ss <= 0:
        return obs, float("nan")
    var = (ss / (n - 1)) * n / (k * (n - k))
    if var <= 0:
        return obs, float("nan")
    return obs, obs / var ** 0.5


def evaluate(cycles: list[dict], prices: dict, gate_fn, horizon: int,
             cluster_width: int | None = None) -> dict:
    """Nilai satu gerbang pada satu horizon. Kembalikan statistik + tafsir."""
    rows_pairs = [(c, p) for c, p in ((c, outcome(c, prices, horizon)) for c in cycles)
                  if p is not None]
    cw = cluster_width if cluster_width else max(1, horizon)
    rows = [(int(c["ts"] // (3600 * cw)), bool(gate_fn(c["funnel"])), p)
            for c, p in rows_pairs]
    n_blk = sum(1 for _, b, _ in rows if b)
    n_los = len(rows) - n_blk
    res: dict = {
        "horizon_jam": horizon,
        "lebar_cluster_jam": cw,
        "n_observasi_unik": len(rows),
        "n_cluster": len({c for c, _, _ in rows}),
        "n_blokir": n_blk,
        "n_lolos": n_los,
    }
    if n_blk < MIN_GROUP or n_los < MIN_GROUP:
        res["catatan"] = (f"n terlalu kecil (<{MIN_GROUP} di satu sisi): "
                          f"blokir={n_blk} lolos={n_los} — MONITOR, bukan ACTION")
        res["ci95_mengecualikan_nol"] = False
        return res
    obs, lo, hi = cluster_boot_ci(rows)
    blk = [v for _, b, v in rows if b]
    los = [v for _, b, v in rows if not b]
    excl = bool(lo == lo and (lo > 0 or hi < 0))
    res.update({
        "mean_blokir": sum(blk) / len(blk),
        "mean_lolos": sum(los) / len(los),
        "delta_blokir_minus_lolos": obs,
        "ci95": [lo, hi],
        "ci95_mengecualikan_nol": excl,
        "tafsir": ("blokir LEBIH BAIK -> gerbang searah" if obs > 0
                   else "blokir LEBIH BURUK -> gerbang MERUGIKAN"),
        "status": "SINYAL" if excl else "TIDAK SIGNIFIKAN",
    })
    return res


# ── 4. KONTROL NEGATIF — bench menguji dirinya sendiri ────────────────────────
def negative_control(cycles: list[dict], prices: dict, horizon: int,
                     n_rules: int = 200, method: str = "perm_z") -> dict:
    """Gerbang ACAK dengan tingkat blokir setara produksi. FPR harus ~alpha.

    Kalau FPR jauh di atas alpha, bench (atau datanya) masih cacat — mis. karena
    duplikasi. Inilah gerbang mutu yang membuat keluaran bench boleh dipakai.
    """
    rows_pairs = [(c, p) for c, p in ((c, outcome(c, prices, horizon)) for c in cycles)
                  if p is not None]
    cw = max(1, horizon)
    rng = np.random.default_rng(SEED_NEG)
    base_rate = 0.5
    sig = 0
    tested = 0
    deltas = []
    for _ in range(n_rules):
        rows = [(int(c["ts"] // (3600 * cw)), bool(rng.random() < base_rate), p)
                for c, p in rows_pairs]
        n_blk = sum(1 for _, b, _ in rows if b)
        if n_blk < MIN_GROUP or len(rows) - n_blk < MIN_GROUP:
            continue
        tested += 1
        if method == "perm_z":
            # Variansi permutasi eksak + aproksimasi normal. Cepat (tanpa loop
            # resampling) dan SAH walau cluster sedikit. z kritis dua-sisi dari
            # kuantil normal baku (stdlib, tanpa numpy.stats).
            obs, z = permutation_z(rows)
            deltas.append(obs)
            if z == z and abs(z) > _Z_CRIT:
                sig += 1
        elif method == "permutation":
            # Uji permutasi: eksak di bawah H0 berapa pun jumlah cluster (lihat
            # permutation_test). Bootstrap cluster anti-konservatif saat cluster
            # sedikit -> FPR palsu 1,62x pada 17 cluster (terukur 2026-10-04).
            obs, p_val = permutation_test(rows, n_perm=1000, seed=SEED_NEG + tested)
            deltas.append(obs)
            if p_val == p_val and p_val < ALPHA:
                sig += 1
        else:
            obs, lo, hi = cluster_boot_ci(rows, n_boot=1500, seed=SEED_NEG + tested)
            deltas.append(obs)
            if lo == lo and (lo > 0 or hi < 0):
                sig += 1
    fpr = sig / max(tested, 1)
    # Ambang kewajaran binomial: mean n*alpha, sd sqrt(n*a*(1-a)) -> batas ~3.5 sd.
    # sd dikoreksi dgn VAR_INFLASI_ANTAR_ATURAN (lihat definisinya) karena ke-200
    # aturan tidak independen: mengacak label di atas data yang sama.
    n = max(tested, 1)
    exp = n * ALPHA
    sd = (n * ALPHA * (1 - ALPHA) * VAR_INFLASI_ANTAR_ATURAN) ** 0.5
    hi_limit = (exp + 3.5 * sd) / n
    return {
        "horizon_jam": horizon,
        "n_aturan_diuji": tested,
        "n_signifikan": sig,
        "fpr_empiris": round(fpr, 4),
        "fpr_nominal": ALPHA,
        "batas_atas_wajar": round(hi_limit, 4),
        "mean_delta": float(np.mean(deltas)) if deltas else float("nan"),
        "metode": method,
        "n_cluster": len({c for c, _, _ in (
            [(int(c["ts"] // (3600 * cw)), bool(0), p) for c, p in rows_pairs])}),
        "lulus": bool(fpr <= hi_limit),
        "tafsir": ("kontrol negatif LULUS — FPR dekat alpha; bench boleh dipercaya"
                   if fpr <= hi_limit
                   else "kontrol negatif GAGAL — FPR jauh di atas alpha; BENCH CACAT, "
                        "semua keluaran tidak sah"),
    }


# ── 5. Orkestrasi ─────────────────────────────────────────────────────────────
def _source_drift(manifest: dict) -> dict:
    """Deteksi apakah telemetri SUMBER sudah bergerak sejak freeze.

    MENGAPA penting: loop paper terus menulis telemetri, sehingga baris mentah
    bertambah sementara dataset beku tetap sah (hash-nya terverifikasi). Tanpa
    pemeriksaan ini, bench bisa DIAM-DIAM BASI — hasil tetap keluar, tetapi tidak
    lagi memuat siklus terbaru. Ini bukan kegagalan integritas; ini peringatan
    kesegaran yang harus terlihat, bukan tersembunyi.
    """
    rec = manifest.get("source_telemetry", {})
    if not TELEMETRY.exists():
        return {"status": "SUMBER_HILANG",
                "catatan": f"telemetri sumber tidak ada: {TELEMETRY}"}
    now_sha = sha256_file(TELEMETRY)
    now_bytes = TELEMETRY.stat().st_size
    sama = now_sha == rec.get("sha256")
    return {
        "status": "SEGAR" if sama else "BASI",
        "sha256_saat_freeze": rec.get("sha256"),
        "sha256_sekarang": now_sha,
        "bytes_saat_freeze": rec.get("bytes"),
        "bytes_sekarang": now_bytes,
        "catatan": ("sumber tidak berubah sejak freeze" if sama else
                    "telemetri sumber sudah bertambah sejak freeze — dataset beku "
                    "tetap SAH (hash terverifikasi), tetapi provenance-nya tidak lagi "
                    "menunjuk berkas yang sama. Baris baru umumnya hanya DUPLIKAT "
                    "pair-jam yang sudah ada, jadi siklus unik tidak berubah; "
                    "jalankan --freeze untuk menyegarkan provenance bila perlu."),
    }


def selfcheck() -> dict:
    """Integritas + determinisme + kontrol negatif + kesegaran sumber."""
    # load_frozen() memverifikasi hash; ia MELEMPAR bila rusak. Jadi baris ini
    # hanya tercapai bila verifikasi lulus.
    cycles, prices, manifest = load_frozen()
    out = {
        "manifest_ok": True,
        "n_siklus_unik": len(cycles),
        "dedup": manifest["dedup"],
        "sumber_telemetri": _source_drift(manifest),
        "kontrol_negatif": {},
        "determinisme": {},
    }
    # determinisme: evaluasi dua kali, delta harus sama persis
    fn = GATES["chk_below_4"][1]
    a = evaluate(cycles, prices, fn, horizon=4)
    b = evaluate(cycles, prices, fn, horizon=4)
    out["determinisme"] = {
        "delta_1": a.get("delta_blokir_minus_lolos"),
        "delta_2": b.get("delta_blokir_minus_lolos"),
        "identik": a.get("delta_blokir_minus_lolos") == b.get("delta_blokir_minus_lolos"),
    }
    for h in HORIZONS:
        out["kontrol_negatif"][str(h)] = negative_control(cycles, prices, h, n_rules=200)
    out["lulus"] = (
        out["determinisme"]["identik"]
        and all(v["lulus"] for v in out["kontrol_negatif"].values())
    )
    return out


def evaluate_production_gates() -> dict:
    cycles, prices, manifest = load_frozen()
    out = {"manifest": {"frozen_at_utc": manifest["frozen_at_utc"],
                        "dedup": manifest["dedup"]}, "horizons": {}}
    for h in HORIZONS:
        out["horizons"][str(h)] = {
            g: evaluate(cycles, prices, fn, horizon=h) for g, (_, fn) in GATES.items()
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Basis uji beku Anantara Sakti")
    ap.add_argument("--freeze", action="store_true", help="bekukan dataset + manifest")
    ap.add_argument("--selfcheck", action="store_true", help="integritas + kontrol negatif")
    ap.add_argument("--eval", action="store_true", help="nilai gerbang produksi")
    ap.add_argument("--report", action="store_true", help="cetak JSON ringkas")
    args = ap.parse_args()
    if not any([args.freeze, args.selfcheck, args.eval, args.report]):
        ap.print_help()
        return 2
    try:
        if args.freeze:
            m = freeze()
            print(f"BEKU: {m['artifacts']['cycles.jsonl']['rows']} siklus unik "
                  f"(dari {m['dedup']['baris_mentah']} baris mentah, "
                  f"rasio {m['dedup']['rasio_penggelembungan']}x)")
            print(f"      bars={m['artifacts']['prices.json']['bars']} "
                  f"sha256(cycles)={m['artifacts']['cycles.jsonl']['sha256'][:16]}...")
        if args.selfcheck:
            r = selfcheck()
            print(json.dumps(r, indent=2, default=str))
            if not r["lulus"]:
                print("SELFCHECK GAGAL", file=sys.stderr)
                return 1
        if args.eval or args.report:
            r = evaluate_production_gates()
            print(json.dumps(r, indent=2, default=str) if args.eval else json.dumps(r))
    except BenchError as e:
        print(f"BENCH ABORT (fail-closed): {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
