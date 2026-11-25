"""Tes PRAREG-36 (offline): recorder idempoten, evaluator deterministik, gerbang, dan guard live pada eksekutor."""
import json, os, shutil, sys
import pandas as pd, pytest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(HERE))
import hybrid36 as h36
import hybrid_exec as hx
import mode_a_engine as eng

FWD = os.path.join(os.path.dirname(HERE), "forward")


@pytest.fixture(scope="module")
def tmpdir_real(tmp_path_factory):
    d = tmp_path_factory.mktemp("hyb36")
    for k in ("btc", "eth", "xaut"):
        shutil.copy(os.path.join(FWD, f"{k}.csv"), os.path.join(d, f"{k}.csv"))
    return str(d)


def test_record_idempoten(tmpdir_real):
    a = h36.record(tmpdir_real, today=pd.Timestamp("2026-10-26"), update=False, fetch_funding=False)
    b = h36.record(tmpdir_real, today=pd.Timestamp("2026-10-26"), update=False, fetch_funding=False)
    assert a["status"] == "OK" and b["ditulis"] == []                         # tanggal sama tidak ditulis dua kali
    rows = [json.loads(x) for x in open(os.path.join(tmpdir_real, "ledger.jsonl"))]
    assert len([r for r in rows if r["kind"] == "rec"]) == 1
    assert set(rows[0]["targets"]) == {"A", "B2"}


def test_record_tidak_mengarang_bar_hilang(tmpdir_real):
    h36.record(tmpdir_real, today=pd.Timestamp("2026-10-27"), update=False, fetch_funding=False)
    rows = [json.loads(x) for x in open(os.path.join(tmpdir_real, "ledger.jsonl")) if '"rec"' in x]
    asof = sorted(r["asof"] for r in rows)
    assert asof == ["2026-10-25"]                     # data berakhir 25-Okt: tidak ada bar 26/27 yang dikarang
    assert all(r["funding_bps"] is None for r in rows)                        # tanpa jaringan -> None, bukan angka karangan


def _synth_dir(path, n=35, start="2025-03-01"):
    px = {k: eng.load_csv(os.path.join(FWD, f"{k}.csv")) for k in h36.SYMS}   # riwayat penuh utk lookback
    th = {a: eng.target_history(px, mode=a, validate=False) for a in h36.PLAN36["cells"]}
    idx = pd.date_range(start, periods=n, freq="D"); rows = []
    for d in idx:
        rows.append({"kind": "rec", "asof": str(d.date()), "backfill": False,
                     "closes": {k: float(px[k].loc[d]) for k in h36.SYMS},
                     "targets": {a: {k: float(th[a].loc[d, k]) for k in h36.SYMS} for a in h36.PLAN36["cells"]},
                     "funding_bps": {"btc": 1.7, "eth": 1.7, "xaut": 1.7}})
    os.makedirs(path, exist_ok=True)
    for k in h36.SYMS:                                            # CSV penuh: sumber recompute G2 (lookback cukup)
        shutil.copy(os.path.join(FWD, f"{k}.csv"), os.path.join(path, f"{k}.csv"))
    with open(os.path.join(path, "ledger.jsonl"), "w") as f:
        for r in rows: f.write(json.dumps(r, sort_keys=True) + "\n")
    return path


def test_eval_jendela_belum_cukup(tmp_path):
    d = _synth_dir(str(tmp_path / "a"), n=10)                    # data baru 10 hari, jendela 30 hari belum lewat
    out = h36.evaluate(d, "2025-03-01", "2025-03-30")
    assert out["vonis"].startswith("BERJALAN") and "gerbang" not in out


def test_eval_satu_baris_tetap_melaporkan_progres(tmp_path):
    d = _synth_dir(str(tmp_path / "a3"), n=1)
    out = h36.evaluate(d, "2025-03-01", "2025-03-30")
    assert out["vonis"].startswith("BERJALAN") and out["n_hari_window"] == 1


def test_eval_data_invalid_bila_jendela_lewat_tapi_bolong(tmp_path):
    d = _synth_dir(str(tmp_path / "a2"), n=10)
    out = h36.evaluate(d, "2025-03-01", "2025-03-09")            # jendela sudah lewat, hari kurang
    assert out["vonis"] == "DATA_INVALID" and out["gerbang"]["G1_data_lengkap"] is False


def test_eval_gerbang_lengkap_dan_deterministik(tmp_path):
    d = _synth_dir(str(tmp_path / "b"), n=35); out = h36.evaluate(d, "2025-03-01", "2025-03-30")
    assert out["n_hari_window"] >= h36.PLAN36["n_win"]
    g = out["gerbang"]
    assert set(g) == {"G1_data_lengkap", "G2_target_deterministik", "G3_M_utama", "G4_mdd", "G5_likuidasi_stres", "G6_bh_signifikan", "G7_pembanding_positif"}
    assert g["G2_target_deterministik"] and g["G1_data_lengkap"] and out["g2_selisih"] == 0
    assert out["vonis"] in ("NO-GO", "LANJUT_EKSEKUTOR_DRY_RUN", "LANJUT_EKSEKUTOR_DRY_RUN_TERBUKTI", "TIDAK_KONSISTEN")
    assert out["hasil"]["B2"]["L"] == 1.5 and out["hasil"]["A"]["L"] == 2.0
    assert h36.evaluate(d, "2025-03-01", "2025-03-30")["hasil"]["B2"]["M_per5h_pct"] == out["hasil"]["B2"]["M_per5h_pct"]   # deterministik


def test_gerbang_no_go_bila_mdd_jeblok(tmp_path):
    d = _synth_dir(str(tmp_path / "c"), n=35)
    rows = [json.loads(x) for x in open(os.path.join(d, "ledger.jsonl"))]
    for i, r in enumerate(rows):                                   # semua aset -2%/hari -> MDD tembus
        for k in h36.SYMS: r["closes"][k] = r["closes"][k] * (0.98 ** i)
    full = {k: eng.load_csv(os.path.join(d, f"{k}.csv")) for k in h36.SYMS}
    for r in rows:                                                 # CSV ikut diubah
        for k in h36.SYMS: full[k].loc[pd.Timestamp(r["asof"])] = r["closes"][k]
    for k in h36.SYMS: full[k].rename("close").sort_index().to_csv(os.path.join(d, f"{k}.csv"), index_label="date")
    th = {a: eng.target_history(full, mode=a, validate=False) for a in h36.PLAN36["cells"]}
    for r in rows:                                                 # target dihitung ulang dari seri penuh
        r["targets"] = {a: {k: float(th[a].loc[pd.Timestamp(r["asof"]), k]) for k in h36.SYMS} for a in h36.PLAN36["cells"]}
    with open(os.path.join(d, "ledger.jsonl"), "w") as f:
        for r in rows: f.write(json.dumps(r, sort_keys=True) + "\n")
    out = h36.evaluate(d, "2025-03-01", "2025-03-30")
    assert out["gerbang"]["G2_target_deterministik"] and out["vonis"] == "NO-GO", out.get("gerbang")


def test_executor_menolak_live(tmp_path):
    with pytest.raises(hx.LiveRefused):
        hx.guard_live({"LIVE_ARMED": "1"})
    with pytest.raises(hx.LiveRefused):
        hx.guard_live({"HL_API_SECRET": "x" * 66})
    hx.guard_live({"LIVE_ARMED": "0", "PREGAIN_LIVE": ""})                     # aman kalau kosong/0


def test_executor_intent_dua_lapis(tmp_path):
    d = _synth_dir(str(tmp_path / "e")); rec = hx.latest_target(d)
    st = {"spot": {}, "perp": {}, "equity_usdc": 1000.0}
    os_ = hx.intents(rec, st, "B2")
    spot = [o for o in os_ if o["layer"] == "spot"]; perp = [o for o in os_ if o["layer"] == "perp"]
    assert spot and perp
    for o in spot: assert o["to_w"] == pytest.approx(rec["targets"]["B2"][o["asset"]], abs=1e-6)
    for o in perp: assert o["to_w"] == pytest.approx(rec["targets"]["B2"][o["asset"]] * 0.5, abs=1e-6)
    assert all(o["dry_run"] for o in os_)
    # notional kecil dibuang
    tiny = hx.intents(rec, {"spot": {}, "perp": {}, "equity_usdc": 1.0}, "B2")
    assert tiny == []
