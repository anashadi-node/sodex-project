"""Tes paper_forward (PRAREG-23b). Offline: update=False, jendela historis lewat monkeypatch."""
import json, shutil, warnings
import numpy as np
import pandas as pd
import pytest
import mode_a_engine as eng
import paper_forward as pf
from bt_indep import load, simulate

warnings.filterwarnings("ignore")
TODAY = pd.Timestamp("2026-10-25")
FIRST = pd.Timestamp("2024-03-01")


@pytest.fixture()
def fdir(tmp_path, monkeypatch):
    for k, src in (("btc", "btc.csv"), ("eth", "eth.csv"), ("xaut", "xaut_spliced.csv")):
        shutil.copy(f"data/{src}", tmp_path / f"{k}.csv")
    monkeypatch.setattr(pf, "FIRST_ASOF", FIRST)
    monkeypatch.setattr(pf, "WIN_FIRST", FIRST + pd.Timedelta(days=1))
    monkeypatch.setattr(pf, "WIN_LAST", FIRST + pd.Timedelta(days=31))
    return str(tmp_path)


def test_record_idempoten_dan_backfill_terbendera(fdir):
    r1 = pf.record(fdir, TODAY, update=False)
    assert r1["status"] == "OK" and r1["ditulis"][0] == "2024-03-01" and len(r1["ditulis"]) == 32
    rows = [json.loads(x) for x in open(f"{fdir}/ledger.jsonl")]
    assert all(r["backfill"] for r in rows)                      # semua di masa lalu = backfill (terbendera)
    r2 = pf.record(fdir, TODAY, update=False)
    assert r2["ditulis"] == [] and len(open(f"{fdir}/ledger.jsonl").readlines()) == 32


def test_record_tanggal_hari_ini_bukan_backfill(fdir, monkeypatch):
    monkeypatch.setattr(pf, "FIRST_ASOF", pd.Timestamp("2026-10-24"))
    monkeypatch.setattr(pf, "WIN_LAST", pd.Timestamp("2026-12-31"))
    pf.record(fdir, TODAY, update=False)
    rows = [json.loads(x) for x in open(f"{fdir}/ledger.jsonl")]
    assert [r["asof"] for r in rows] == ["2026-10-24"] and rows[0]["backfill"] is False


def test_data_buruk_gagal_tertutup_tanpa_target(fdir):
    s = pd.read_csv(f"{fdir}/btc.csv", index_col=0, parse_dates=True)["close"]
    s.iloc[-1] = np.nan
    s.rename("close").to_csv(f"{fdir}/btc.csv", index_label="date")
    r = pf.record(fdir, TODAY, update=False)
    assert r["status"] == "GAGAL_DATA"
    rows = [json.loads(x) for x in open(f"{fdir}/ledger.jsonl")]
    assert len(rows) == 1 and rows[0]["event"] == "GAGAL_DATA" and not [x for x in rows if x["kind"] == "rec"]


def test_eval_sama_dengan_simulasi_langsung(fdir):
    pf.record(fdir, TODAY, update=False)
    out = pf.evaluate(fdir)
    assert out["n_hari_window"] == 31 and out["gerbang"]["G2_target_cocok_engine"] is True and out["g2_selisih"] == 0
    closes = {k: eng.load_csv(f"{fdir}/{k}.csv") for k in pf.SYMS}
    tg = eng.target_history(closes, mode="A", validate=False)
    r, _ = simulate(closes, tg, start=str((FIRST + pd.Timedelta(days=1)).date()), cost=pf.COST)
    r = r.loc[pf.WIN_FIRST:pf.WIN_LAST]
    assert out["hasil"]["A_c010"]["cum_pct"] == pytest.approx(((1 + r).prod() - 1) * 100, abs=1e-3)
    assert out["vonis"] in ("NO-GO",) or out["vonis"].startswith("LAYAK")
    assert out["hasil"]["A_c025"]["cum_pct"] <= out["hasil"]["A_c010"]["cum_pct"] + 1e-9    # biaya lebih tinggi tak bisa lebih baik


def test_eval_berjalan_bila_belum_lengkap(fdir, monkeypatch):
    monkeypatch.setattr(pf, "WIN_LAST", FIRST + pd.Timedelta(days=10))
    pf.record(fdir, TODAY, update=False)
    out = pf.evaluate(fdir)
    assert out["vonis"].startswith("BERJALAN") and "gerbang" not in out


def test_eval_tandai_ledger_bolong_dan_tampar_NOGO(fdir):
    pf.record(fdir, TODAY, update=False)
    L = open(f"{fdir}/ledger.jsonl").readlines()
    del L[10]
    open(f"{fdir}/ledger.jsonl", "w").writelines(L)
    out = pf.evaluate(fdir)
    assert out["gap_tanggal"] == ["2024-03-11"]


def test_eval_deteksi_target_ledger_dirusak(fdir):
    pf.record(fdir, TODAY, update=False)
    L = [json.loads(x) for x in open(f"{fdir}/ledger.jsonl")]
    L[5]["targets"]["A"]["btc"] += 0.05
    open(f"{fdir}/ledger.jsonl", "w").writelines(json.dumps(x) + "\n" for x in L)
    out = pf.evaluate(fdir)
    assert out["gerbang"]["G2_target_cocok_engine"] is False and out["vonis"] == "NO-GO"


def test_gerbang_mdd_dan_cum_menolak(fdir, monkeypatch):
    pf.record(fdir, TODAY, update=False)
    monkeypatch.setitem(pf.GATE, "G3_mdd_min", 100.0)             # mustahil terpenuhi
    out = pf.evaluate(fdir)
    assert out["gerbang"]["G3_mdd_A"] is False and out["vonis"] == "NO-GO"
