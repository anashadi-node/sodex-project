"""Guard dataset: pull klines TIDAK boleh menimpa data valid dengan hasil n=0.

Latar: 2026-11-04 20:56:52, 2026-11-09 07:13:32, 2026-11-11 09:15:33 (masing-masing
4-6 detik setelah boot) seluruh 98/98 file 1d ter-zero karena fetch mengembalikan
respons kosong dan main() menulis apa pun hasilnya. Test ini mengunci perbaikan.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "scripts" / "research" / "sodex_pull_klines_paged.py"


def _load():
    spec = importlib.util.spec_from_file_location("sodex_pull_klines_paged_guard", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _empty(symbol, interval):
    return {"symbol": symbol, "interval": interval, "n": 0, "oldest": None,
            "newest": None, "pulled_utc": "2026-11-12T00:00:00+00:00", "bars": []}


def _setup(monkeypatch, tmp_path, pull_fn):
    m = _load()
    monkeypatch.setattr(m, "OUTBASE", str(tmp_path))
    monkeypatch.setattr(m, "trading_symbols", lambda: ["AAA-USD"])
    monkeypatch.setattr(m, "pull", pull_fn)
    monkeypatch.setattr(sys, "argv", ["prog", "1d", "all"])
    return m


def test_n0_tidak_menimpa_file_valid(monkeypatch, tmp_path):
    m = _setup(monkeypatch, tmp_path, _empty)
    d = tmp_path / "1d"
    d.mkdir(parents=True)
    good = {"symbol": "AAA-USD", "interval": "1d", "n": 200, "bars": [{}] * 200}
    (d / "AAA-USD.json").write_text(json.dumps(good))

    rc = m.main()

    assert rc == 2, "main() harus melaporkan kegagalan (exit 2) saat 0 simbol dapat bar"
    assert json.loads((d / "AAA-USD.json").read_text())["n"] == 200, "file valid tertimpa n=0"


def test_n0_tidak_membuat_file_baru(monkeypatch, tmp_path):
    m = _setup(monkeypatch, tmp_path, _empty)
    rc = m.main()
    assert rc == 2
    files = [f.name for f in (tmp_path / "1d").glob("*.json")]
    assert files == ["MANIFEST.json"], f"tidak boleh membuat file simbol kosong (ada: {files})"


def test_n_positif_tetap_ditulis(monkeypatch, tmp_path):
    bars = [{"t": i, "o": 1.0, "h": 1.1, "l": 0.9, "c": 1.0, "v": 1.0} for i in range(5)]

    def _pull(symbol, interval):
        return {"symbol": symbol, "interval": interval, "n": len(bars),
                "oldest": "o", "newest": "n", "pulled_utc": "u", "bars": bars}

    m = _setup(monkeypatch, tmp_path, _pull)
    rc = m.main()
    assert rc == 0
    out = json.loads((tmp_path / "1d" / "AAA-USD.json").read_text())
    assert out["n"] == 5
