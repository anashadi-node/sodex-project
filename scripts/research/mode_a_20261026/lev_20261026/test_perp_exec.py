"""Tes eksekutor perp PRAREG-38 — tanpa jaringan, tanpa kunci."""
import json, os, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perp_exec as pe

SPEC = lambda: {"BTC-USD": {"id": 1, "stepSize": "0.00001", "minNotional": "10"},
                "ETH-USD": {"id": 2, "stepSize": "0.0001", "minNotional": "10"},
                "XAUT-USD": {"id": 11, "stepSize": "0.0001", "minNotional": "10"}}
MARK = {"BTC-USD": 80000.0, "ETH-USD": 2300.0, "XAUT-USD": 4000.0}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "SPECS", None, raising=False)
    monkeypatch.setattr(pe, "specs", SPEC)
    monkeypatch.setattr(pe, "marks", lambda s: {k: v for k, v in MARK.items() if k in s})
    monkeypatch.setattr(pe, "SEC", str(tmp_path / "secrets")); os.makedirs(tmp_path / "secrets")
    monkeypatch.setattr(pe, "LEDGER", str(tmp_path / "perp_ledger.jsonl"))
    return tmp_path


def test_plan_mematuhi_step_dan_min_notional(env):
    p = pe.plan(60.0, lp=3.0)
    assert p["gross_cap"] == 180.0 and p["used"] <= 180.0
    for o in p["orders"]:
        step = float(o["step"])
        assert abs(o["qty"] / step - round(o["qty"] / step)) < 1e-9
        assert o["notional"] >= 10.0


def test_plan_tidak_melampaui_gross_cap(env):
    p = pe.plan(1000.0, lp=3.0)
    assert p["used"] <= p["gross_cap"] + 1e-6
    assert p["margin"] <= 1000.0 + 1e-6      # ekuitas arg = akun perp (25% dari total E)


def test_ekuitas_kecil_tidak_memaksa_order_di_bawah_min_notional(env):
    p = pe.plan(5.0, lp=3.0)                      # gross 15 -> per aset 5 < 10
    assert p["orders"] == [] and p["used"] == 0


def test_live_ditolak_tanpa_live_armed(env):
    with pytest.raises(pe.Block, match="LIVE_ARMED"):
        pe.apply(pe.plan(60.0), live=True)


def test_live_ditolak_tanpa_confirm(env):
    (env / "secrets" / "LIVE_ARMED.json").write_text(json.dumps({"armed": True, "not_before": "2026-12-01"}))
    with pytest.raises(pe.Block, match="CONFIRM_LIVE|not_before"):
        pe.apply(pe.plan(60.0), live=True)


def test_live_ditolak_tanpa_selftest(env):
    (env / "secrets" / "LIVE_ARMED.json").write_text(json.dumps({"armed": True, "not_before": "2020-01-01"}))
    os.environ["CONFIRM_LIVE"] = "YES"
    try:
        with pytest.raises(pe.Block, match="selftest"):
            pe.apply(pe.plan(60.0), live=True)
    finally:
        os.environ.pop("CONFIRM_LIVE", None)


HIST = {
    123: {"orderID": 123, "status": "NEW", "executedQty": "0"},
    124: {"orderID": 124, "status": "CANCELED", "executedQty": "0"},
    987: {"orderID": 987, "status": "FILLED", "executedQty": "0.002"},
}


def look(oid):
    return HIST.get(int(oid))


@pytest.mark.parametrize("resp", [
    {"orderID": 0, "status": "FILLED", "filledQuantity": "0.001"},
    {"orderID": None, "status": "FILLED", "filledQuantity": "1"},
    {"orderID": 123, "status": "FILLED", "filledQuantity": "0.001"},   # place bilang FILLED, history NEW
    {"orderID": 124, "status": "FILLED", "filledQuantity": "0.001"},   # CANCELED di history
    {"orderID": 999, "status": "FILLED", "filledQuantity": "0.001"},   # tidak ada di history
    [],
])
def test_fill_phantom_selalu_ditolak(resp):
    with pytest.raises(pe.AmbiguousFill):
        pe.verify_fill(resp, lookup=look)


def test_fill_sah_diterima():
    # Bentuk respons venue nyata: hanya orderID, status kosong.
    r = pe.verify_fill({"orderID": 987, "status": ""}, lookup=look)
    assert r[0]["orderID"] == 987 and float(r[0]["executedQty"]) == 0.002


def test_paper_idempoten(env):
    p = pe.plan(60.0, lp=3.0)
    a = pe.apply(p); b = pe.apply(p)
    assert a["n"] == len(p["orders"]) and b["n"] == 0
    rows = [json.loads(x) for x in open(pe.LEDGER)]
    assert all(r["mode"] == "PAPER" for r in rows)
    assert len({(r["symbol"], r["qty"]) for r in rows}) == len(rows) == len(p["orders"])


def test_live_plus_testnet_ditolak(env):
    with pytest.raises(pe.Block, match="tidak sah"):
        pe.apply(pe.plan(60.0), live=True, testnet=True)


def test_live_ditolak_saat_env_testnet(env, monkeypatch):
    (env / "secrets" / "LIVE_ARMED.json").write_text(json.dumps({"armed": True, "not_before": "2020-01-01"}))
    monkeypatch.setenv("SODEX_TESTNET", "1")
    with pytest.raises(pe.Block, match="SODEX_TESTNET=1"):
        pe.apply(pe.plan(60.0), live=True)
