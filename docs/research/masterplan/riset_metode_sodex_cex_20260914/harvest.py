#!/usr/bin/env python3
"""Divisi RISET — literature harvester v2.
Kanal hidup (terverifikasi 14 Sep 2026):
  - arxiv.org/search (HTML)      -> 200 OK
  - arxiv.org/abs/<id>           -> 200 OK (abstract)
  - api.crossref.org             -> 200 OK
  - api.openalex.org (mailto)    -> polite pool
Mati: export.arxiv.org API (timeout), api.semanticscholar.org (429), web_search/web_extract (billing 402)

Usage:
  python3 harvest.py arxiv "query terms" [n]      # cari via arxiv.org/search
  python3 harvest.py abs 2411.12753               # abstract satu paper
  python3 harvest.py crossref "query" [n]
  python3 harvest.py openalex "query" [n]
  python3 harvest.py stats
"""
import sys, json, re, html, time, pathlib, urllib.parse, urllib.request, subprocess

OUT = pathlib.Path(__file__).parent / "hits.jsonl"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/120.0 Safari/537.36")


def _get(url, timeout=30):
    """curl-first + retry: arxiv.org 406 tanpa UA browser, 400/000 saat flaky."""
    args = ["curl", "-sS", "-m", str(timeout), "--retry", "4", "--retry-delay", "2",
            "--retry-all-errors", "--compressed", "-L", "-A", UA,
            "-H", "Accept: text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            url]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout * 3 + 20)
        if r.returncode == 0 and r.stdout:
            return r.stdout
    except Exception:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def save(rec):
    with OUT.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def arxiv(q, n=10):
    # arXiv hanya menerima size ∈ {25,50,100,200}; nilai lain -> HTTP 400. Ambil 50, potong lokal.
    url = "https://arxiv.org/search/?searchtype=all&query=" + urllib.parse.quote(q) + "&size=50"
    h = _get(url, timeout=30)
    blocks = re.split(r'<li class="arxiv-result">', h)[1:]
    got = 0
    for b in blocks:
        if got >= n:
            break
        mi = re.search(r'<a href="https://arxiv.org/abs/([^"]+)"', b)
        mt = re.search(r'<p class="title is-5 mathjax">([\s\S]*?)</p>', b)
        ma = re.search(r'<span class="abstract-full[^"]*"[^>]*>([\s\S]*?)</span>', b)
        md = re.search(r'Submitted</span>\s*([^;<]+)', b)
        if not (mi and mt):
            continue
        rec = {"src": "arxiv", "q": q, "id": mi.group(1), "title": clean(mt.group(1)),
               "abstract": clean(ma.group(1))[:1200] if ma else "",
               "date": (md.group(1).strip() if md else ""),
               "url": "https://arxiv.org/abs/" + mi.group(1)}
        save(rec); got += 1
        print(f"[{rec['date'][:12]:12s}] {rec['title'][:110]}\n    https://arxiv.org/abs/{rec['id']}\n    {(rec['abstract'] or '')[:300]}\n")
    if not got:
        print("no result parsed; page bytes:", len(h))


def absx(aid):
    h = _get("https://arxiv.org/abs/" + aid)
    mt = re.search(r'<h1 class="title mathjax">([\s\S]*?)</h1>', h)
    ma = re.search(r'<blockquote class="abstract mathjax">([\s\S]*?)</blockquote>', h)
    t = clean(mt.group(1)) if mt else ""
    a = clean(ma.group(1)) if ma else "NO ABSTRACT"
    print(t, "\n\n", a)
    save({"src": "arxiv_abs", "id": aid, "title": t, "abstract": a[:2500]})


def crossref(q, n=5):
    url = ("https://api.crossref.org/works?query.bibliographic=" + urllib.parse.quote(q)
           + f"&rows={n}&select=title,DOI,container-title,issued,is-referenced-by-count,type,abstract")
    d = json.loads(_get(url))
    for it in d["message"]["items"]:
        rec = {"src": "crossref", "q": q, "title": (it.get("title") or [""])[0],
               "doi": it.get("DOI", ""), "venue": (it.get("container-title") or [""])[0],
               "year": (it.get("issued", {}).get("date-parts") or [[None]])[0][0],
               "cites": it.get("is-referenced-by-count", 0), "type": it.get("type", ""),
               "abstract": clean(it.get("abstract", ""))[:900]}
        save(rec)
        print(f"[CR {rec['year']} c={rec['cites']}] {rec['title'][:115]}\n    {rec['venue'][:55]} | {rec['doi']}")
        if rec["abstract"]:
            print("    abs:", rec["abstract"][:260])


def openalex(q, n=5):
    url = ("https://api.openalex.org/works?search=" + urllib.parse.quote(q)
           + f"&per-page={n}&mailto=research@anantara.local")
    d = json.loads(_get(url))
    for w in d.get("results", []):
        rec = {"src": "openalex", "q": q, "title": w.get("title") or "",
               "doi": w.get("doi") or "", "year": w.get("publication_year"),
               "cites": w.get("cited_by_count"), "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or "",
               "abstract": ""}
        save(rec)
        print(f"[OA {rec['year']} c={rec['cites']}] {rec['title'][:115]}\n    {rec['venue'][:50]} | {rec['doi']}")


def stats():
    if not OUT.exists():
        print("no hits"); return
    rows = [json.loads(l) for l in OUT.read_text().splitlines() if l.strip()]
    from collections import Counter
    print("total", len(rows), Counter(r["src"] for r in rows))


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "arxiv":    arxiv(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 10)
    elif c == "abs":    absx(sys.argv[2])
    elif c == "crossref": crossref(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 5)
    elif c == "openalex": openalex(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 5)
    elif c == "stats":  stats()
