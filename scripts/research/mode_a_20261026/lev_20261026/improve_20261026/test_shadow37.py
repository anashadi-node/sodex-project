"""Tes PRAREG-37 shadow: sambungan funding forward + backfill celah ledger (offline, sintetis)."""
import json, os, sys
import pandas as pd, pytest
HERE = os.path.dirname(os.path.abspath(__file__)); LEV = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, LEV); sys.path.insert(0, os.path.dirname(LEV))
import shadow37 as sh
import lev_study as ls


def _frozen():
    """3 titik/hari 2026-10-23..25 (hari penuh) + 1 titik parsial 2026-10-26 (seperti CSV beku)."""
    t = pd.to_datetime(["2026-10-23 08:00", "2026-10-23 16:00", "2026-10-24 00:00",
                        "2026-10-24 08:00", "2026-10-24 16:00", "2026-10-25 00:00",
                        "2026-10-25 08:00", "2026-10-25 16:00", "2026-10-26 00:00",
                        "2026-10-26 00:00"][:9])
    s = pd.Series([1.0] * 9, index=t)
    return {"btc": s, "eth": s.copy()}


def _ledger(tmp_path, days):
    p = tmp_path / "ledger.jsonl"
    with open(p, "w") as fh:
        for d, v in days.items():
            fh.write(json.dumps({"kind": "rec", "asof": d, "funding_bps": v}) + "\n")
    return str(p)


def test_extend_ganti_hari_parsial_dan_sambung(tmp_path):
    f = _frozen()
    led = _ledger(tmp_path, {"2026-10-26": {"btc": 2.0, "eth": 3.0, "xaut": 2.0},
                             "2026-10-27": {"btc": 4.0, "eth": 5.0, "xaut": 4.0}})
    out = sh.extend_funding(f, led)
    b = out["btc"].groupby(out["btc"].index.normalize()).sum()
    assert float(b[pd.Timestamp("2026-10-26")]) == 2.0       # hari parsial diganti total harian ledger
    assert float(b[pd.Timestamp("2026-10-27")]) == 4.0       # hari baru tersambung
    assert float(b[pd.Timestamp("2026-10-25")]) == 3.0       # hari penuh beku TIDAK disentuh
    assert float(out["eth"].groupby(out["eth"].index.normalize()).sum()[pd.Timestamp("2026-10-27")]) == 5.0


def test_extend_tanpa_ledger_tidak_mengubah(tmp_path):
    f = _frozen()
    assert sh.extend_funding(f, str(tmp_path / "tidak_ada.jsonl")) is f


def test_extend_abaikan_nan_dan_null(tmp_path):
    f = _frozen()
    led = _ledger(tmp_path, {"2026-10-27": None, "2026-10-28": {"btc": float("nan"), "eth": 1.0, "xaut": 1.0}})
    out = sh.extend_funding(f, led)
    assert pd.Timestamp("2026-10-27") not in out["btc"].index.normalize()   # tidak mengarang nilai
    assert pd.Timestamp("2026-10-28") not in out["btc"].index.normalize()   # NaN btc ditolak
    assert pd.Timestamp("2026-10-28") in out["eth"].index.normalize()


def test_koreksi_funding_menang_atas_rec(tmp_path):
    f = _frozen(); p = tmp_path / "ledger.jsonl"
    with open(p, "w") as fh:
        fh.write(json.dumps({"kind": "rec", "asof": "2026-10-27", "funding_bps": None}) + "\n")
        fh.write(json.dumps({"kind": "event", "event": "KOREKSI_FUNDING", "asof": "2026-10-27",
                             "funding_bps": {"btc": 7.0, "eth": 8.0, "xaut": 7.0}}) + "\n")
    out = sh.extend_funding(f, str(p))
    assert float(out["btc"].groupby(out["btc"].index.normalize()).sum()[pd.Timestamp("2026-10-27")]) == 7.0


def test_aturan_cakupan_tetap_fail_closed():
    """Sambungan TIDAK melonggarkan build_fund: celah >1% hari tetap StudyError."""
    idx = pd.date_range("2020-01-01", "2020-04-30", freq="D")
    closes = {k: pd.Series(100.0, index=idx) for k in ("btc", "eth", "xaut")}
    t = pd.date_range("2020-03-01", "2020-04-30", freq="8h")          # funding hanya Mar-Apr => >1% kosong
    f = {"btc": pd.Series(1.0, index=t), "eth": pd.Series(1.0, index=t)}
    with pytest.raises(ls.StudyError):
        ls.build_fund(closes, sh.extend_funding(f, "/tidak/ada"))


def test_record_backfill_dan_idempoten(tmp_path, monkeypatch):
    idx = pd.date_range("2026-11-01", "2026-11-06", freq="D")
    s = pd.DataFrame({"L": 2.5, "net": 0.001, "gross": 0.001, "equity": 1.0, "mdd": 0.0}, index=idx)
    monkeypatch.setattr(sh, "series", lambda fdir: s)
    d = tmp_path / "shadow"; d.mkdir()
    (d / "shadow_ledger.jsonl").write_text("\n".join(json.dumps(
        {"kind": "shadow", "asof": a, "L": 2.5, "net": 0.001, "equity": 1.0, "mdd": 0.0})
        for a in ("2026-11-01", "2026-11-02", "2026-11-04")) + "\n")      # celah 11-03 + ketinggalan 11-05/06
    sh.record(str(d))
    rows = [json.loads(x) for x in open(d / "shadow_ledger.jsonl")]
    asof = [r["asof"] for r in rows]
    assert sorted(asof) == [f"2026-11-0{i}" for i in range(1, 7)] and len(set(asof)) == 6
    bf = {r["asof"]: r.get("backfill", False) for r in rows}
    assert bf["2026-11-03"] and bf["2026-11-05"] and not bf["2026-11-06"]   # hanya hari terakhir 'live'
    n = len(rows); sh.record(str(d))
    assert len(open(d / "shadow_ledger.jsonl").readlines()) == n            # idempoten


def test_status_urut_asof(tmp_path, capsys):
    d = tmp_path / "s"; d.mkdir()
    rows = [("2026-11-02", 1.2), ("2026-11-01", 1.1), ("2026-11-03", 1.3)]   # 11-01 ditulis belakangan (backfill)
    rows = [rows[0], rows[2], rows[1]]
    (d / "shadow_ledger.jsonl").write_text("\n".join(json.dumps(
        {"kind": "shadow", "asof": a, "L": 2.5, "net": 0.0, "equity": e, "mdd": 0.0}) for a, e in rows) + "\n")
    sh.status(str(d))
    out = json.loads(capsys.readouterr().out)
    assert out["dari"] == "2026-11-01" and out["sampai"] == "2026-11-03" and out["equity"] == 1.3
