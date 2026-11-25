"""Regresi struktur dokumen master SoDEX (HTML hasil generator).

Tidak menjalankan generator (butuh network + suite penuh); yang diuji adalah
artefak terakhir: anchor daftar isi harus menunjuk id yang ada, tidak boleh ada
placeholder angka gagal (nan/None/undefined), dan jumlah bagian harus utuh.
"""
import glob
import os
import re
from html.parser import HTMLParser

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _P(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.hrefs, self.text = set(), [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and (a.get("href") or "").startswith("#"):
            self.hrefs.append((a.get("href") or "")[1:])

    def handle_data(self, data):
        self.text.append(data)


def _docs():
    return sorted(glob.glob(os.path.join(ROOT, "reports", "sodex", "SODEX_MASTER_*.html")))


@pytest.fixture
def doc():
    d = _docs()
    if not d:
        pytest.skip("dokumen master belum digenerate (artefak, tidak dibundel)")
    return d[-1]


def test_semua_anchor_daftar_isi_tertuju(doc):
    p = _P()
    p.feed(open(doc, encoding="utf-8").read())
    assert p.hrefs, "daftar isi kosong"
    hilang = [h for h in p.hrefs if h not in p.ids]
    assert not hilang, f"anchor tanpa target: {hilang}"


def test_tidak_ada_placeholder_gagal(doc):
    p = _P()
    p.feed(open(doc, encoding="utf-8").read())
    txt = " ".join(p.text)
    for bad in ("nan", "NaN", "None", "undefined"):
        assert not re.search(rf"\b{bad}\b", txt), f"placeholder gagal muncul: {bad}"


def test_bagian_utama_lengkap(doc):
    p = _P()
    p.feed(open(doc, encoding="utf-8").read())
    txt = " ".join(p.text)
    for wajib in ("Ringkasan eksekutif", "North Star", "Arsitektur sistem",
                  "Lane paper", "Metodologi statistik", "Kesiapan live",
                  "Roadmap", "Glosarium"):
        assert wajib in txt, f"bagian hilang: {wajib}"
