#!/usr/bin/env python3
"""Divisi RISET — literature harvester. Kanal: arXiv API + Crossref API (gratis).
Usage:
  python3 litsearch.py arxiv "query" [max]
  python3 litsearch.py crossref "query" [rows]
  python3 litsearch.py abs "arxiv_id"        # ambil abstract dari arxiv
  python3 litsearch.py jsonl                 # cetak semua hasil tersimpan
"""
import sys, json, re, time, urllib.request, urllib.parse, pathlib, html

OUT = pathlib.Path.home() / "anantara-sakti/docs/research/masterplan/riset_metode_sodex_cex_20260914/hits.jsonl"
UA = {"User-Agent": "AnantaraResearch/1.0 (research; contact: local)"}


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def _save(rec):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def arxiv(q, mx=6):
    url = ("http://export.arxiv.org/api/query?search_query=" + urllib.parse.quote(q)
           + f"&start=0&max_results={mx}&sortBy=relevance")
    x = _get(url)
    ents = re.findall(r"<entry>([\s\S]*?)</entry>", x)
    for e in ents:
        mt = re.search(r"<title>([\s\S]*?)</title>", e)
        ma = re.search(r"<summary>([\s\S]*?)</summary>", e)
        mi = re.search(r"<id>(.*?)</id>", e)
        mp = re.search(r"<published>(.*?)</published>", e)
        if not (mt and ma and mi and mp):
            continue
        t = _clean(mt.group(1))
        a = _clean(ma.group(1))
        idu = mi.group(1).strip()
        pub = mp.group(1)[:10]
        rec = {"src": "arxiv", "q": q, "title": t, "url": idu, "date": pub, "abstract": a[:1500]}
        _save(rec)
        print(f"[arXiv {pub}] {t}\n   {idu}\n   {a[:340]}\n")


def crossref(q, rows=4):
    url = ("https://api.crossref.org/works?query.bibliographic=" + urllib.parse.quote(q)
           + f"&rows={rows}&select=title,DOI,container-title,issued,is-referenced-by-count,type")
    d = json.loads(_get(url))
    for it in d["message"]["items"]:
        ti = (it.get("title") or [""])[0]
        ven = (it.get("container-title") or [""])[0]
        yr = (it.get("issued", {}).get("date-parts") or [[None]])[0][0]
        cit = it.get("is-referenced-by-count", 0)
        doi = it.get("DOI", "")
        rec = {"src": "crossref", "q": q, "title": ti, "doi": doi, "venue": ven,
               "year": yr, "cites": cit, "type": it.get("type", "")}
        _save(rec)
        print(f"[CR {yr} c={cit}] {ti[:120]}\n   {ven[:60]} | {doi}\n")


def absx(aid):
    x = _get("https://arxiv.org/abs/" + aid)
    m = re.search(r'<blockquote class="abstract[^>]*">([\s\S]*?)</blockquote>', x)
    t = re.search(r'<h1 class="title[^>]*">([\s\S]*?)</h1>', x)
    print(_clean(t.group(1)) if t else "")
    print(_clean(m.group(1)) if m else "NO ABSTRACT")
    return _clean(m.group(1)) if m else ""


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "arxiv":
        arxiv(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 6)
    elif cmd == "crossref":
        crossref(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
    elif cmd == "abs":
        absx(sys.argv[2])
    elif cmd == "jsonl":
        for l in OUT.read_text().splitlines():
            print(l[:300])
