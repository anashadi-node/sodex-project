"""Tes PRAREG-34 (offline, sintetis + kontrol ekuivalensi terhadap bt_indep.simulate)."""
import os, sys
import numpy as np, pandas as pd, pytest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import lev_study as ls
import mode_a_engine as eng
from bt_indep import simulate


@pytest.fixture(scope="module")
def real():
    closes, ohlc, f = ls.load_all(); return closes, ohlc, f


def test_kontrol_ekuivalen_simulate(real):
    closes, _, _ = real; T = eng.target_history(closes, mode="A", today=pd.Timestamp("2026-10-25"))
    a = simulate(closes, T, start="2022-01-01", cost=0.0010)[0]
    b = ls.lev_sim(closes, T, 1.0, "2022-01-01", 0.0010)["net"]
    assert np.allclose(a.values, b.values, atol=1e-12)                     # L=1, tanpa funding == engine riset terverifikasi


def test_L0_nol_dan_turnover_skala(real):
    closes, _, _ = real; T = eng.target_history(closes, mode="A", today=pd.Timestamp("2026-10-25"))
    z = ls.lev_sim(closes, T, 0.0, "2022-01-01", 0.0010); assert (z["net"] == 0).all()
    t1 = ls.lev_sim(closes, T, 1.0, "2022-01-01", 0.0010)["turn"].sum(); t2 = ls.lev_sim(closes, T, 2.0, "2022-01-01", 0.0010)["turn"].sum()
    assert t2 / t1 == pytest.approx(2.0, rel=0.05)


def _synth(n=400):
    idx = pd.date_range("2023-01-01", periods=n, freq="D"); c = {k: pd.Series(100.0, index=idx) for k in ls.COLS}
    return idx, c


def test_funding_positif_membebani_long_dan_negatif_menambah():
    idx, c = _synth(); T = pd.DataFrame(0.0, index=idx, columns=ls.COLS); T["btc"] = 0.5
    f = pd.DataFrame(2.0, index=idx, columns=ls.COLS)
    r = ls.lev_sim(c, T, 1.0, "2023-03-01", 0.0, f)["net"]; assert r.iloc[10:].mean() == pytest.approx(-0.5 * 2.0 / 1e4, rel=1e-6)
    r2 = ls.lev_sim(c, T, 2.0, "2023-03-01", 0.0, f)["net"]; assert r2.iloc[10:].mean() == pytest.approx(-1.0 * 2.0 / 1e4, rel=1e-6)   # L skala drag
    r3 = ls.lev_sim(c, T, 1.0, "2023-03-01", 0.0, -f)["net"]; assert r3.iloc[10:].mean() > 0


def test_likuidasi_sintetis():
    idx, c = _synth(); T = pd.DataFrame(0.0, index=idx, columns=ls.COLS); T["btc"] = 1.0
    adv = pd.DataFrame(0.0, index=idx, columns=ls.COLS); adv.loc[idx[200], "btc"] = -0.40
    for L, expect in ((1.0, False), (2.0, False), (2.6, True), (3.0, True)):         # 1/(0,4+0,0125*(1-0,4)) ~ batas 2,45x
        res = ls.lev_sim(c, T, L, "2023-03-01", 0.0, None, adv); assert bool(res["liq"].any()) == expect, L


def test_stres_lebih_ketat_dari_dasar():
    idx, c = _synth(); T = pd.DataFrame(0.0, index=idx, columns=ls.COLS); T["btc"] = 1.0
    adv = pd.DataFrame(0.0, index=idx, columns=ls.COLS); adv.loc[idx[200], "btc"] = -0.30
    res = ls.lev_sim(c, T, 2.3, "2023-03-01", 0.0, None, adv); assert (not res["liq"].any()) and res["liq_stress"].any()   # 30% aman, 45% (x1,5) likuidasi


def test_funding_cakupan_kurang_fail_closed(real):
    closes, _, f = real; f2 = {k: v.loc["2024-01-01":] for k, v in f.items()}
    with pytest.raises(ls.StudyError):
        ls.build_fund(closes, f2)


def test_verdict_gerbang():
    ok = {"M_2022+": 0.011, "M_OOS26": 0.002, "M_2024+": 0.003, "hari_likuidasi_stres": 0, "MDD_2022+": -20.0, "p_M_le_0": 0.3}
    assert ls.verdict(ok, {"p_kontrol": 0.5})[0] == "LAYAK_PAPER_BUKAN_BUKTI"
    assert ls.verdict({**ok, "p_M_le_0": 0.01}, {"p_kontrol": 0.01})[0] == "TERBUKTI"
    assert ls.verdict({**ok, "M_2022+": 0.009}, None)[0] == "TIDAK_LAYAK"
    assert ls.verdict({**ok, "hari_likuidasi_stres": 1}, None)[0] == "TIDAK_LAYAK"
    assert ls.verdict({**ok, "MDD_2022+": -40.0}, None)[0] == "TIDAK_LAYAK"
    assert ls.verdict({**ok, "M_OOS26": -0.001}, None)[0] == "TIDAK_LAYAK"
    assert ls.verdict({"M_2022+": 0, "M_OOS26": 0, "M_2024+": 0, "hari_likuidasi_stres": 0, "MDD_2022+": 0}, None)[0] == "TIDAK_LAYAK"   # kontrol nol


def test_plan_beku():
    P = ls.PLAN
    assert (P["target_M"], P["mdd_cap"], P["stress_mult"], P["cost_primary"], P["p_alpha"]) == (0.010, -35.0, 1.5, 0.0010, 0.05)
    assert P["arms"] == ("A", "B2") and P["L_grid"] == (1.0, 1.5, 2.0, 3.0) and ls.MMR == {"btc": 0.0125, "eth": 0.02, "xaut": 0.02}
