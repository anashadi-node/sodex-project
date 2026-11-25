"""Tes auditor edge lintas-lane: kontrol negatif (noise tidak boleh jadi kandidat) + kontrol positif + dedup + epoch."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import sodex_fleet_edge_audit as fa


def _state(tmp, name, pnls, start="2026-11-01T00:00:00+00:00", dup=0):
    import datetime as dt
    t0 = dt.datetime.fromisoformat(start); tr = []
    for i, p in enumerate(pnls):
        tr.append({"pair": f"P{i}", "side": "SHORT", "entry_time": (t0 + dt.timedelta(hours=i)).isoformat(),
                   "exit_time": (t0 + dt.timedelta(hours=i + 1)).isoformat(), "pnl_pct": float(p)})
    tr += tr[:dup]
    p = tmp / f"{name}_state.json"; p.write_text(json.dumps({"closed_trades": tr})); return str(p)


def test_noise_zero_mean_bukan_kandidat(tmp_path):                       # KONTROL NEGATIF
    rng = np.random.default_rng(1)
    f = _state(tmp_path, "noise", rng.normal(0, 0.02, 200))
    r = fa.audit([f])[0]
    assert r["n"] == 200 and r["verdict"] != "KANDIDAT"


def test_edge_positif_nyata_kandidat(tmp_path):                          # KONTROL POSITIF
    rng = np.random.default_rng(2)
    f = _state(tmp_path, "edge", rng.normal(0.01, 0.01, 80))
    r = fa.audit([f])[0]
    assert r["verdict"] == "KANDIDAT" and r["ci_lo"] > 0 and r["q"] < 0.05


def test_mean_positif_n_kecil_data_kurang(tmp_path):
    f = _state(tmp_path, "kecil", [0.05] * 10)
    assert fa.audit([f])[0]["verdict"] == "DATA_KURANG"                   # n<20 tak pernah 'kandidat'


def test_dedup_dan_epoch(tmp_path):
    f = _state(tmp_path, "paper_test_twoway_ab9a", [0.01] * 30, start="2026-11-14T00:00:00+00:00", dup=30)
    r = fa.audit([f])[0]
    # 30 trade unik (dup dibuang); epoch 2026-11-15T00:55:52 membuang yang exit-nya lebih awal
    assert 0 < r["n"] < 30 and r["epoch_dari"].startswith("2026-11-15T00:55:52")
    g = _state(tmp_path, "dupe", [0.01] * 25, dup=25)
    assert fa.audit([g])[0]["n"] == 25


def test_skema_tak_dikenal_tidak_diam(tmp_path):
    p = tmp_path / "x_state.json"; p.write_text(json.dumps({"foo": 1}))
    r = fa.audit([str(p)])[0]
    assert r["status"] == "TANPA_DAFTAR_TRADE" and r["n"] == 0
    q = tmp_path / "y_state.json"; q.write_text("{rusak")
    assert fa.audit([str(q)])[0]["status"] == "TAK_TERBACA"


def test_bh_monoton_dan_terbatas():
    q = fa.bh([0.001, 0.02, 0.5, 0.04])
    assert all(0 <= x <= 1 for x in q) and q[0] <= q[1] <= q[3] <= q[2] + 1e-12


def test_gross_tanpa_fee_tidak_jadi_kandidat(tmp_path):
    import datetime as dt
    t0 = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc); rng = np.random.default_rng(3)
    tr = [{"pair": f"P{i}", "direction": "LONG", "entry_time": (t0 + dt.timedelta(hours=i)).isoformat(),
           "exit_time": (t0 + dt.timedelta(hours=i + 1)).isoformat(), "gross_pct": float(v)}
          for i, v in enumerate(rng.normal(0.01, 0.01, 80))]
    p = tmp_path / "g_state.json"; p.write_text(json.dumps({"closed": tr}))
    r = fa.audit([str(p)])[0]
    assert r["basis"] == "gross_pct" and r["n"] == 80 and r["verdict"] == "GROSS_SAJA_PERLU_NET"


def test_net_pct_dibaca_sebelum_gross(tmp_path):
    import datetime as dt
    t0 = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
    tr = [{"pair": f"P{i}", "entry_time": (t0 + dt.timedelta(hours=i)).isoformat(),
           "exit_time": (t0 + dt.timedelta(hours=i + 1)).isoformat(), "gross_pct": 0.05, "net_pct": -0.01} for i in range(30)]
    p = tmp_path / "n_state.json"; p.write_text(json.dumps({"closed": tr}))
    r = fa.audit([str(p)])[0]
    assert r["basis"] == "net_pct" and r["mean_pct"] < 0
