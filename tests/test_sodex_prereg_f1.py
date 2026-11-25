"""Tes evaluator F1 (data sintetis; TIDAK menyentuh tape nyata)."""
import json
import random
import statistics as st
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sodex_prereg_f1 as f1  # noqa: E402
import sodex_forward_momentum as fm  # noqa: E402

S = f1.F_START_MIN


def flat(n=3000, px=100.0):
    return {S + i: (float((S + i) * 60), px) for i in range(n)}


def with_jump(d, at, pct=0.025):
    """naik pct dalam 10 menit sebelum `at`, lalu bertahan"""
    for i in range(10):
        m = at - 10 + i
        d[m] = (float(m * 60), 100.0 * (1 + pct * (i + 1) / 10))
    for m in range(at, max(d) + 1):
        d[m] = (float(m * 60), 100.0 * (1 + pct))
    return d


def test_event_detected_and_clustered():
    d = with_jump(flat(), S + 100)
    ev = f1.find_events(d)
    assert len(ev) == 1 and ev[0][1] == 1


def test_event_survives_missing_p0_minute_via_ffill():
    d = with_jump(flat(), S + 100)
    for m in (S + 85, S + 84):  # p0 menit t-15 hilang -> ffill <=5 menit
        d.pop(m, None)
    assert len(f1.find_events(d)) >= 1


def test_no_event_below_theta():
    assert f1.find_events(with_jump(flat(), S + 100, 0.012)) == []


def test_day_signflip_detects_real_edge_and_not_noise():
    """REGRESI bug day_cluster_p lama: data jelas positif WAJIB berp kecil."""
    rng = random.Random(1)
    pos = {f"d{i}": [rng.gauss(0.05, 0.005) for _ in range(3)] for i in range(40)}
    nul = {f"d{i}": [rng.gauss(0.0, 0.05) for _ in range(3)] for i in range(40)}
    assert f1.day_signflip_p(pos, n=3000) < 0.01
    # kalibrasi: pada data NOL, penolakan palsu @0,05 harus <=~5% (diukur 3,7% pada 300 dataset); satu seed bisa kebetulan
    rej = 0
    for s in range(120):
        r = random.Random(1000 + s)
        d = {f"d{i}": [r.gauss(0, 0.05) for _ in range(3)] for i in range(40)}
        rej += f1.day_signflip_p(d, n=600, seed=s) < 0.05
    assert rej / 120 <= 0.12
    assert fm.day_cluster_p(pos, n=2000) > 0.4  # bukti bug lama (didokumentasikan, tidak diperbaiki: protokol beku)


def test_gate_closed_before_trigger_and_open_at_hard_stop():
    ok, _ = f1.gate_open({"n": 100, "days": 5, "symbols": 3}, date(2026, 10, 10))
    assert not ok
    ok, why = f1.gate_open({"n": 100, "days": 5, "symbols": 3}, f1.HARD_STOP)
    assert ok and "HARD_STOP" in why
    ok, _ = f1.gate_open({"n": 150, "days": 14, "symbols": 10}, date(2026, 10, 20))
    assert ok


def test_inconclusive_when_sample_small_never_pass():
    eps = [{"sym": "A", "t_in": S + i * 100, "t_out": S + i * 100 + 1440, "day": "20261008", "net": 0.05,
            "fade": -0.05, "net_d2": 0.05} for i in range(10)]
    res = f1.judge(eps, 10, S + 20000)
    assert res["verdict"] == "INCONCLUSIVE"


def test_window_gross_cap_enforced():
    eps = [{"sym": s, "t_in": S + 10 + i, "t_out": S + 10 + i + 1440, "net": 0.10, "day": "x"} for i, s in enumerate("ABCDEFGHIJ")]
    w, taken = f1.window_pnls(eps, S + 5760, f=0.15, cap=1.0)
    assert taken == 6  # 6 x 0,15 = 0,90; ke-7 = 1,05 > 1,0 ditolak
    assert abs(sum(w) - 6 * 0.15 * 0.10) < 1e-9


def test_loader_dedupes_and_takes_latest_ts_per_minute(tmp_path):
    day = f1.F_START.strftime("%Y%m%d")
    rows = [{"id": 1, "ts": (S * 60 + 50) * 1000, "sym": "X", "price": 11.0},
            {"id": 2, "ts": (S * 60 + 10) * 1000, "sym": "X", "price": 10.0},  # lebih lama, muncul belakangan
            {"id": 1, "ts": (S * 60 + 50) * 1000, "sym": "X", "price": 11.0}]  # duplikat
    (tmp_path / f"trades_{day}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    out = f1.load_minutes(tmp_path)
    assert out["X"][S][1] == 11.0  # harga dengan ts TERBESAR, bukan yang terakhir tertulis


def test_count_only_does_not_need_exit_price():
    d = with_jump(flat(2000), S + 100)
    assert f1.count_complete({"A": d})["n"] == 1
    d2 = with_jump(flat(1200), S + 100)  # belum 24 jam -> belum lengkap
    assert f1.count_complete({"A": d2})["n"] == 0


def test_amendment_fee_is_official_4bp_and_funding_charged():
    """AMENDEMEN 07-Okt-2026: taker resmi 4 bp/leg (dulu salah 2 bp) + funding 24 jam 2,4 bp.
    Regresi: cost = 2*(setengah-spread + 4bp) + 10bp slip + 2,4bp funding."""
    assert f1.FEE_TAKER == 0.0004
    assert f1.FUNDING_BP_24H == 2.4
    eps, n = f1.build_episodes({"A": with_jump(flat(), S + 100)}, {}, 1.0)  # fallback half-spread 1 bp
    assert n == 1 and len(eps) == 1
    expected_cost = 2 * (1.0 / 1e4 + 0.0004) + 10.0 / 1e4 + 2.4 / 1e4
    # fade = -g - cost ; net = g - cost  =>  fade + net = -2*cost
    assert abs((eps[0]["fade"] + eps[0]["net"]) + 2 * expected_cost) < 1e-9
