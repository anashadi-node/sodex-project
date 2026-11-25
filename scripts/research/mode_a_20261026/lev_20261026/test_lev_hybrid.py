"""Tes PRAREG-35 (offline). Kontrol utama: hybrid L=1 == bt_indep.simulate (spot murni, tanpa funding)."""
import os, sys
import numpy as np, pandas as pd, pytest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import lev_hybrid as lh
import lev_study as ls
import mode_a_engine as eng
from bt_indep import simulate


@pytest.fixture(scope="module")
def real():
    closes, ohlc, f = ls.load_all(); return closes, ohlc, f


def test_hybrid_L1_identik_spot(real):
    closes, _, _ = real; T = eng.target_history(closes, mode="A", today=pd.Timestamp("2026-10-25"))
    a = simulate(closes, T, start="2022-01-01", cost=0.0010)[0]
    b = lh.hybrid_sim(closes, T, 1.0, "2022-01-01", 0.0010, 0.0010)["net"]
    assert np.allclose(a.values, b.values, atol=1e-12)                   # L=1 => lapisan perp nol, drag funding nol


def test_drag_funding_hanya_lapisan_perp():
    idx = pd.date_range("2023-01-01", periods=300, freq="D"); c = {k: pd.Series(100.0, index=idx) for k in ls.COLS}
    T = pd.DataFrame(0.0, index=idx, columns=ls.COLS); T["btc"] = 0.5
    f = pd.DataFrame(4.0, index=idx, columns=ls.COLS)                     # 4 bps/hari
    r1 = lh.hybrid_sim(c, T, 1.0, "2023-03-01", 0.0, 0.0, f)["net"]; assert r1.iloc[10:].mean() == pytest.approx(0.0, abs=1e-15)
    r2 = lh.hybrid_sim(c, T, 2.0, "2023-03-01", 0.0, 0.0, f)["net"]; assert r2.iloc[10:].mean() == pytest.approx(-0.5 * 4 / 1e4, rel=1e-9)   # (L-1)*w*F
    r3 = lh.hybrid_sim(c, T, 3.0, "2023-03-01", 0.0, 0.0, f)["net"]; assert r3.iloc[10:].mean() == pytest.approx(-1.0 * 4 / 1e4, rel=1e-9)


def test_fee_terpisah_per_lapisan():
    idx = pd.date_range("2023-01-01", periods=80, freq="D"); c = {k: pd.Series(100.0, index=idx) for k in ls.COLS}
    r = pd.Series(0.0, index=idx); r.iloc[40] = 0.10; c["btc"] = (1 + r).cumprod() * 100
    T = pd.DataFrame(0.0, index=idx, columns=ls.COLS); T["btc"] = 0.4
    res = lh.hybrid_sim(c, T, 2.0, "2023-01-01", 0.0010, 0.0020)          # spot 10 bps, perp 20 bps
    assert res["turn_p"].sum() == pytest.approx(res["turn_s"].sum() * 1.0)   # L-1 = 1
    # biaya total = turn_s*10bps + turn_p*20bps  -> dicek lewat hari tanpa return: net = -(cost)
    d0 = res["net"].iloc[5]; assert d0 == pytest.approx(-(res["turn_s"].iloc[5] * 0.0010 + res["turn_p"].iloc[5] * 0.0020), rel=1e-9)


def test_ambang_likuidasi_analitis():
    """Ambang analitis (satu aset, w=1): 1 + L*a = MMR*(L-1)*(1+a) untuk hybrid; MMR*L*(1+a) untuk perp penuh."""
    mmr = ls.MMR["btc"]
    for L in (2.0, 3.0, 4.0):
        a_h = (mmr * (L - 1) - 1) / (L - mmr * (L - 1)); a_p = (mmr * L - 1) / (L - mmr * L)
        assert a_h < a_p < 0                                   # ambang hybrid lebih dalam (lebih aman)
        assert a_h == pytest.approx(-1 / L, abs=0.03)           # praktis ~ -1/L karena MMR kecil
        idx = pd.date_range("2023-01-01", periods=120, freq="D"); c = {k: pd.Series(100.0, index=idx) for k in ls.COLS}
        T = pd.DataFrame(0.0, index=idx, columns=ls.COLS); T["btc"] = 1.0
        adv = pd.DataFrame(0.0, index=idx, columns=ls.COLS); adv.loc[idx[60], "btc"] = a_h + 0.01   # sedikit lebih ringan dari ambang
        assert not lh.hybrid_sim(c, T, L, "2023-01-01", 0.0, 0.0, None, adv)["liq"].any()
        adv2 = pd.DataFrame(0.0, index=idx, columns=ls.COLS); adv2.loc[idx[60], "btc"] = a_h - 0.01  # melewati ambang
        assert lh.hybrid_sim(c, T, L, "2023-01-01", 0.0, 0.0, None, adv2)["liq"].any()


def test_verdict_dan_plan_beku():
    ok = {"M_2022+": 0.015, "M_OOS26": 0.002, "M_2024+": 0.004, "hari_likuidasi_stres": 0, "MDD_2022+": -30.0, "p_M_le_0": 0.3}
    assert lh.verdict(ok, 0.4)[0] == "LAYAK_PAPER_BUKAN_BUKTI"
    assert lh.verdict({**ok, "p_M_le_0": 0.01}, 0.01)[0] == "TERBUKTI"
    assert lh.verdict({**ok, "MDD_2022+": -36.0}, None)[0] == "TIDAK_LAYAK"
    assert lh.verdict({**ok, "hari_likuidasi_stres": 1}, None)[0] == "TIDAK_LAYAK"
    P = lh.PLAN35
    assert (P["cost_primary"], P["mdd_cap"], P["target_M"]) == (0.0010, -35.0, 0.010)
    assert P["cost_perp_real"] < P["cost_spot_real"] < P["cost_primary"]     # fee taker perp < spot, keduanya < asumsi 10 bps
