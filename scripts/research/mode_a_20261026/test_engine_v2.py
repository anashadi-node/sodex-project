"""Suite tes engine v2. Jalankan: .venv/bin/python -m pytest -q test_engine_v2.py
Tidak butuh jaringan (update_history diuji dengan fetch palsu). Data: data/*.csv hasil fetch_data.py + step2_oos.py."""
import math
import warnings

import numpy as np
import pandas as pd
import pytest

import mode_a_engine as eng
import mode_a_engine_orig as orig
from bt_indep import load, signal_indep, simulate, stats

warnings.filterwarnings("ignore")
TODAY = pd.Timestamp("2026-10-25")
BN = {"btc": load("data/btc.csv"), "eth": load("data/eth.csv"), "xaut": load("data/xaut_spliced.csv")}
END = "2026-05-23"
CM = {k: load(f"data/cm_{k}.csv").loc[:END] for k in ("btc", "eth", "xaut")}
CM_TODAY = pd.Timestamp("2026-05-24")


@pytest.fixture(scope="module")
def tgtA():
    return eng.target_history(BN, today=TODAY)


# ---------------------------------------------------------------- kesetaraan & kebenaran
def test_v2_identik_dengan_v1(tgtA):
    ref = orig.target_history(BN)
    assert float((tgtA - ref).abs().max().max()) < 1e-15


def test_sinyal_sama_dengan_implementasi_independen():
    for k, c in BN.items():
        assert float((eng.donchian_signal(c) - signal_indep(c)).abs().max()) == 0.0


def test_replikasi_angka_dokumen_26okt():
    t = eng.target_history(CM, today=CM_TODAY)
    r, _ = simulate(CM, t, end=END)
    a, b = stats(r), stats(r.loc["2022-01-01":])
    assert abs(a["per5h"] - 0.0157) <= 0.00006 and abs(b["per5h"] - 0.0055) <= 0.00006
    assert abs(a["sharpe"] - 1.33) <= 0.011 and abs(b["sharpe"] - 0.65) <= 0.011
    assert abs(a["mdd"] - (-21.1)) <= 0.11 and abs(b["mdd"] - (-13.0)) <= 0.11


@pytest.mark.parametrize("mode", ["B1", "B2"])
def test_mode_B_sama_dengan_hasil_varian(mode):
    d = pd.read_csv("data/variants_daily.csv", index_col=0, parse_dates=True)[f"{mode}_0.001"]
    t = eng.target_history(BN, mode=mode, today=TODAY)
    r, _ = simulate(BN, t, start="2021-02-01", cost=0.001)
    assert float((r - d).abs().max()) < 1e-12


def test_tanpa_kebocoran_masa_depan(tgtA):
    rng = np.random.default_rng(11)
    for d in rng.choice(tgtA.loc["2021-06-01":].index, 15, replace=False):
        d = pd.Timestamp(d)
        tr = {k: v.loc[:d] for k, v in BN.items()}
        lt = eng.latest_targets(tr, today=d + pd.Timedelta(days=1))
        assert lt["asof_close"] == str(d.date())
        assert max(abs(lt["weights"][k] - float(tgtA.loc[d, k])) for k in BN) == 0.0


@pytest.mark.parametrize("mode", ["A", "B1", "B2"])
def test_invarian_bobot(mode):
    t = eng.target_history(BN, mode=mode, today=TODAY)
    assert (t >= -1e-12).all().all()                       # tanpa short
    assert (t.sum(axis=1) <= 1 + 1e-9).all()              # tanpa leverage
    assert np.isfinite(t.values).all()


def test_mode_B_aturan_sisa_kas():
    a = eng.target_history(BN, today=TODAY)
    b1 = eng.target_history(BN, mode="B1", today=TODAY)
    el = BN["xaut"].notna().cumsum() >= 360
    el = el.reindex(a.index).fillna(False).astype(bool)
    rem = (1 - a["btc"] - a["eth"]).clip(lower=0)
    assert float((b1["xaut"] - rem.where(el, 0)).abs().max()) < 1e-15
    assert (b1.loc[~el, "xaut"] == 0).all()                # XAUT belum layak (<360 bar) => tidak dibeli
    assert float((b1[["btc", "eth"]] - a[["btc", "eth"]]).abs().max().max()) == 0.0


def test_deterministik(tgtA):
    assert eng.target_history(BN, today=TODAY).equals(tgtA)


# ---------------------------------------------------------------- regresi bug (v1 salah diam-diam, v2 harus menolak)
def _mut(key, fn):
    c = {k: v.copy() for k, v in BN.items()}
    c[key] = fn(c[key])
    return c


def test_F1_bar_terakhir_telat():
    with pytest.raises(eng.DataError, match="tidak sama"):
        eng.latest_targets(_mut("xaut", lambda s: s.iloc[:-1]), today=TODAY)


def test_F1_nan_bar_terakhir():
    def f(s):
        s.iloc[-1] = np.nan
        return s
    with pytest.raises(eng.DataError, match="NaN"):
        eng.latest_targets(_mut("xaut", f), today=TODAY)


def test_F1_v1_memang_salah_diam_diam():
    """Bukti bug nyata di v1: bobot BTC naik 50% tanpa error."""
    base = orig.latest_targets(BN)["weights"]["btc"]
    bad = orig.latest_targets(_mut("xaut", lambda s: s.iloc[:-1]))["weights"]["btc"]
    assert bad > base * 1.4


def test_F2_hari_hilang():
    with pytest.raises(eng.DataError, match="hari hilang"):
        eng.latest_targets(_mut("btc", lambda s: s.drop(s.index[-40:-35])), today=TODAY)


def test_F3_bar_parsial_hari_ini():
    def f(s):
        s.loc[s.index[-1] + pd.Timedelta(days=1)] = s.iloc[-1] * 0.9
        return s
    with pytest.raises(eng.DataError, match="belum ditutup"):
        eng.latest_targets(_mut("btc", f), today=pd.Timestamp("2026-10-25"))


def test_F4_harga_nol_negatif_inf_lonjakan():
    for val, pat in ((0.0, "<= 0"), (-5.0, "<= 0"), (np.inf, "NaN/inf")):
        def f(s, v=val):
            s.iloc[-3] = v
            return s
        with pytest.raises(eng.DataError, match=pat):
            eng.latest_targets(_mut("eth", f), today=TODAY)


def test_F4_lonjakan_harian():
    def f(s):
        s.iloc[-1] = s.iloc[-2] * 1.8
        return s
    with pytest.raises(eng.DataError, match="lonjakan"):
        eng.latest_targets(_mut("btc", f), today=TODAY)


def test_data_valid_lolos_validasi():
    eng.validate_closes(BN, today=TODAY)
    eng.validate_closes(CM, today=CM_TODAY)


def test_indeks_tz_dan_waktu():
    c = {k: v.copy() for k, v in BN.items()}
    c["btc"].index = c["btc"].index.tz_localize("UTC")
    with pytest.raises(eng.DataError, match="tz-naive"):
        eng.validate_closes(c, today=TODAY)
    c = {k: v.copy() for k, v in BN.items()}
    c["btc"].index = c["btc"].index + pd.Timedelta(hours=3)
    with pytest.raises(eng.DataError):
        eng.validate_closes(c, today=TODAY)


# ---------------------------------------------------------------- band & perencana order
def test_band():
    r = eng.rebalance_orders
    assert r({"btc": 0.10}, {"btc": 0.11}) == {}
    assert r({"btc": 0.10}, {"btc": 0.0}) == {"btc": -0.10}
    assert r({"btc": 0.10}, {"btc": 0.14}) == {"btc": pytest.approx(0.04)}
    assert r({}, {"btc": 0.009}) == {}                    # target terlalu kecil: abaikan
    assert r({}, {"btc": 0.011}) == {"btc": 0.011}


PX = {"btc": 80000.0, "eth": 2300.0, "xaut": 4000.0}


def test_planner_beli_awal_dan_batas():
    p = eng.plan_orders({"btc": 0.074, "eth": 0.069, "xaut": 0.0}, {}, PX, 243.0)
    assert p["dry_run"] is True
    buys = [o for o in p["orders"] if o["side"] == "BUY"]
    assert {o["asset"] for o in buys} == {"btc", "eth"}
    assert all(o["notional"] >= 5.0 for o in p["orders"])
    assert sum(o["notional"] for o in buys) <= 243.0 * (1 - 0.005)
    assert p["cash_after"] >= 0
    for o in buys:                                        # qty kelipatan step
        step = eng.DEFAULT_META[o["asset"]]["step"]
        assert abs(o["qty"] / step - round(o["qty"] / step)) < 1e-6


def test_planner_jual_dulu_dan_tak_jual_lebih_dari_saldo():
    hold = {"btc": 0.0005, "eth": 0.0, "xaut": 0.05}      # btc $40, xaut $200
    p = eng.plan_orders({"btc": 0.0, "eth": 0.10, "xaut": 0.0}, hold, PX, 3.0)
    sides = [o["side"] for o in p["orders"]]
    assert sides == sorted(sides, key=lambda s: 0 if s == "SELL" else 1)      # jual dulu
    for o in p["orders"]:
        if o["side"] == "SELL":
            assert o["qty"] <= hold[o["asset"]] + 1e-12
    assert {o["asset"] for o in p["orders"] if o["side"] == "SELL"} == {"btc", "xaut"}


def test_planner_debu_di_bawah_min_notional_dilewati():
    p = eng.plan_orders({"btc": 0.0, "eth": 0.0, "xaut": 0.0}, {"btc": 0.00003}, PX, 200.0)   # $2.4 debu
    assert p["orders"] == [] and p["skipped"] and p["skipped"][0]["asset"] == "btc"


def test_planner_kas_kurang_tidak_membeli_melebihi_kas():
    p = eng.plan_orders({"btc": 0.5, "eth": 0.5, "xaut": 0.0}, {}, PX, 20.0)
    assert sum(o["notional"] * (1 + 0.00065) for o in p["orders"]) <= 20.0
    assert p["cash_after"] >= -1e-9


def test_planner_harga_buruk_ditolak():
    with pytest.raises(eng.DataError):
        eng.plan_orders({"btc": 0.1}, {}, {"btc": 0.0}, 100.0)
    with pytest.raises(eng.DataError):
        eng.plan_orders({"btc": 0.1}, {"btc": -1.0}, {"btc": 1.0}, 100.0)


def test_planner_tanpa_posisi_pendek():
    p = eng.plan_orders({"btc": 0.0, "eth": 0.0, "xaut": 0.0}, {"btc": 0.001}, PX, 0.0)
    assert all(o["qty"] > 0 for o in p["orders"]) and all(o["side"] == "SELL" for o in p["orders"])


# ---------------------------------------------------------------- update_history (offline)
def test_update_history_rantai_return_dan_tolak_sumber_rusak(tmp_path, monkeypatch):
    s = BN["btc"].loc[:"2026-10-20"]
    path = tmp_path / "btc.csv"
    s.rename("close").to_csv(path, index_label="date")
    full = BN["btc"] * 1.05                                # sumber baru beda skala 5%: harus tetap konsisten (rantai return)
    monkeypatch.setattr(eng, "fetch_binance_daily", lambda sym, start, today=None: full.loc[pd.Timestamp(start, unit="ms").normalize():])
    out = eng.update_history(str(path), "BTCUSDT", today=TODAY)
    assert out.index[-1] == pd.Timestamp("2026-10-24") and len(out) == len(BN["btc"])
    assert float((out.pct_change().dropna() - BN["btc"].pct_change().dropna()).abs().max()) < 1e-9
    bad = full.copy()
    bad.loc[bad.index[-6:]] = bad.loc[bad.index[-6:]] * np.linspace(1, 1.5, 6)
    monkeypatch.setattr(eng, "fetch_binance_daily", lambda sym, start, today=None: bad.loc[pd.Timestamp(start, unit="ms").normalize():])
    with pytest.raises(eng.DataError, match="tidak konsisten"):
        eng.update_history(str(path), "BTCUSDT", today=TODAY)


def test_utc_today_tanpa_api_usang():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert isinstance(eng.today_utc(), pd.Timestamp)


def test_planner_pembulatan_tidak_pernah_melebihi_saldo():
    """Regresi AMENDMENT_1: _floor_step lama (+1e-9) bisa membulatkan ke atas -> jual > saldo."""
    rng = np.random.default_rng(5)
    for _ in range(3000):
        step = float(rng.choice([0.00001, 0.0001]))
        q = float(rng.integers(1, 10**6)) * step * (1 - float(rng.random()) * 1e-12)
        assert eng._floor_step(q, step) <= q
    assert eng._floor_step(0.0013, 0.0001) == 0.0013 and eng._floor_step(0.00129999, 0.0001) == 0.0012
    p = eng.plan_orders({"btc": 0.0, "eth": 0.0, "xaut": 0.0}, {"btc": 0.00123456789}, PX, 0.0)
    assert all(o["qty"] <= 0.00123456789 for o in p["orders"])
