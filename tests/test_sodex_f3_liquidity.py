"""Tes stratifikasi likuiditas F3 (NON-GATING) + snapshot tickers.

Kontrak yang diuji:
1. `liquidity_view` TIDAK boleh masuk `criteria` -> verdict C0-C8 tetap dapat
   direproduksi tanpa data likuiditas (bukti: judge() tak punya kunci "liquidity").
2. FAIL-CLOSED: tanpa snapshot -> status UNKNOWN + peringatan, bukan diam-diam "likuid".
3. Ambang bucket objektif & deterministik.
4. Pasar tipis (<$10k) dihitung terpisah; `tradable_only_secondary` hanya info.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sodex_prereg_f3 as f3  # noqa: E402
import sodex_tickers_snapshot as snap  # noqa: E402

T0 = 1_000_000


def _ep(sym, t_in, net, day):
    return {"sym": sym, "t_in": t_in, "net": net, "day": day, "side": "buy"}


def _eps_mixed():
    """24 episode: 8 tipis (+, menipu), 8 sedang (-), 8 dalam (+)."""
    eps = []
    for i in range(8):
        eps.append(_ep(f"THIN{i}", T0 + i * 100, +0.01, f"2026100{i % 9 + 1}"))
    for i in range(8):
        eps.append(_ep(f"MID{i}", T0 + i * 100 + 9, -0.01, f"2026100{i % 9 + 1}"))
    for i in range(8):
        eps.append(_ep(f"DEEP{i}", T0 + i * 100 + 18, +0.01, f"2026100{i % 9 + 1}"))
    return eps


def _liq_map(thin=5_000.0, mid=20_000.0, deep=200_000.0):
    m = {}
    for i in range(8):
        m[f"THIN{i}"] = thin
        m[f"MID{i}"] = mid
        m[f"DEEP{i}"] = deep
    return m


def test_bucket_boundaries_are_objective_and_deterministic():
    assert f3.bucket_of(None) == "unknown"
    assert f3.bucket_of(0.0) == "thin_<10k"
    assert f3.bucket_of(9_999.99) == "thin_<10k"
    assert f3.bucket_of(10_000.0) == "mid_10k-50k"
    assert f3.bucket_of(49_999.99) == "mid_10k-50k"
    assert f3.bucket_of(50_000.0) == "deep_50k-1M"
    assert f3.bucket_of(999_999.99) == "deep_50k-1M"
    assert f3.bucket_of(1_000_000.0) == "verydeep_>=1M"


def test_fail_closed_when_snapshot_missing():
    """Tanpa snapshot: UNKNOWN + peringatan. Bukan default optimistis."""
    v = f3.liquidity_view(_eps_mixed(), {})
    assert v["status"] == "UNKNOWN"
    assert "warning" in v and v["warning"]
    assert "by_bucket" not in v  # tidak ada klaim likuiditas palsu


def test_load_liquidity_missing_or_broken_file_returns_empty(tmp_path):
    assert f3.load_liquidity(tmp_path / "tidak-ada.json") == {}
    bad = tmp_path / "rusak.json"
    bad.write_text("{bukan json")
    assert f3.load_liquidity(bad) == {}


def test_load_liquidity_reads_snapshot_shape(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"volumes": {"AAA-USD": "12345.5", "BBB-USD": 7, "CCC-USD": None}}))
    got = f3.load_liquidity(p)
    assert got == {"AAA-USD": 12345.5, "BBB-USD": 7.0}  # CCC invalid -> dibuang


def test_liquidity_view_does_not_touch_criteria():
    """KONTRAK KUNCI: verdict C0-C8 tidak boleh bergantung pada data likuiditas."""
    eps = _eps_mixed()
    res = f3.judge(eps, T0, T0 + 2880 * 10)
    assert "liquidity" not in res, "judge() tidak boleh menyertakan likuiditas"
    criteria_before = dict(res["criteria"])
    # Melampirkan view likuiditas tidak boleh mengubah criteria/verdict sedikit pun.
    res["liquidity"] = f3.liquidity_view(eps, _liq_map())
    assert res["criteria"] == criteria_before
    # Determinisisme: judge() dua kali -> identik.
    assert f3.judge(eps, T0, T0 + 2880 * 10)["criteria"] == criteria_before


def test_stratification_separates_thin_edge_from_deep_edge():
    """Edge yang hanya hidup di pasar tipis harus TERLIHAT, bukan tersembunyi."""
    eps = _eps_mixed()
    v = f3.liquidity_view(eps, _liq_map())
    assert v["status"] == "OK"
    b = v["by_bucket"]
    assert b["thin_<10k"]["n"] == 8 and b["thin_<10k"]["mean_net_bp"] == 100.0
    assert b["mid_10k-50k"]["n"] == 8 and b["mid_10k-50k"]["mean_net_bp"] == -100.0
    assert b["deep_50k-1M"]["n"] == 8 and b["deep_50k-1M"]["mean_net_bp"] == 100.0
    assert v["n_thin_episodes"] == 8
    assert v["thin_share"] == round(8 / 24, 4)
    # Secondary (NON-GATING): pasar >= $10k saja -> thin dibuang.
    sec = v["tradable_only_secondary"]
    assert sec["n"] == 16 and sec["mean_net_bp"] == 0.0


def test_unknown_volume_symbols_are_not_silently_treated_as_liquid():
    eps = [_ep("GHOST-USD", T0, 0.01, "20261001")]
    v = f3.liquidity_view(eps, {"LAIN-USD": 5_000_000.0})
    assert v["by_bucket"].get("unknown", {}).get("n") == 1
    assert v["n_thin_episodes"] == 1  # volume tak diketahui TIDAK dianggap likuid


def test_snapshot_normalize_handles_shapes():
    assert snap.normalize({"data": [{"symbol": "A-USD", "quoteVolume": 10}]}) == {"A-USD": 10.0}
    # camel / snake / tanpa symbol / nilai tak valid
    got = snap.normalize([{"symbol": "B-USD", "quote_volume": 5}, {"quoteVolume": 9}, "x"])
    assert got == {"B-USD": 5.0}
    assert snap.normalize({"data": "aneh"}) == {}
    assert snap.normalize("bukan-dict") == {}
