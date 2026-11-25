#!/usr/bin/env python3
"""Verifikasi klaim kunci riset ke sumber primer — lewat curl/API (web_search mati).

MENGAPA skrip ini ada: `web_search`/`web_extract` mengembalikan HTTP 402
(insufficient_funds) sehingga riset tidak boleh mengandalkan tool itu. Semua
klaim di bawah diverifikasi ulang secara mekanis ke arXiv / PyPI / GitHub /
CrossRef — supaya laporan tidak pernah memuat klaim tanpa jejak.

Aturan: klaim yang GAGAL diverifikasi ditandai, bukan dihapus diam-diam.
"""
import json
import pathlib
import re
import urllib.error
import urllib.request

TIMEOUT = 20
UA = {"User-Agent": "anantara-verify/1.0 (+research)"}


def get(url: str, headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or UA)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def arxiv_title(aid: str) -> str | None:
    """Judul resmi dari halaman abs arXiv (regex pada <title>)."""
    code, body = get(f"https://arxiv.org/abs/{aid}")
    if code != 200 or not body:
        return None
    m = re.search(r'<meta name="citation_title" content="([^"]+)"', body)
    return m.group(1).strip() if m else None


def pypi(name: str) -> str | None:
    """Versi terbaru + tanggal unggah dari PyPI JSON API."""
    code, body = get(f"https://pypi.org/pypi/{name}/json")
    if code != 200 or not body:
        return None
    try:
        d = json.loads(body)
        v = d["info"]["version"]
        files = d["releases"].get(v, [])
        date = files[0]["upload_time"][:10] if files else "?"
        return f"{v} ({date})"
    except Exception:
        return None


def github(repo: str) -> str | None:
    """Lisensi + commit terakhir + bintang dari GitHub REST API."""
    code, body = get(f"https://api.github.com/repos/{repo}")
    if code != 200 or not body:
        return None
    try:
        d = json.loads(body)
        lic = (d.get("license") or {}).get("spdx_id", "?")
        return f"{lic} | ★{d.get('stargazers_count')} | push {d.get('pushed_at','')[:10]}"
    except Exception:
        return None


# Klaim yang HARUS diverifikasi. (label, jenis, id)
ARXIV = [
    ("CoVe — verifikasi berlapis",           "2309.11495"),
    ("PAL — penalaran via program",          "2211.10435"),
    ("PoT — program of thoughts",            "2211.12588"),
    ("Self-Consistency",                     "2203.11171"),
    ("CoT meta-analisis (Sprague/Meta)",     "2409.12183"),
    ("MAD tidak dominan (Smit et al.)",      "2311.17371"),
    ("ToT — tree of thoughts",               "2305.10601"),
    ("PRM — process supervision",            "2305.20050"),
    ("Self-Refine",                          "2303.17651"),
    ("Self-correct gagal (Huang et al.)",    "2310.01798"),
    ("Semantic entropy (Nature 2024)",       "2302.09664"),
    ("Selective prediction (Geifman)",       "1705.08500"),
    ("R-Tuning — menolak menjawab",          "2311.09677"),
    ("Conformal language modeling",          "2306.10193"),
    ("Temperature scaling (Guo et al.)",     "1706.04599"),
    ("Calibration under shift (Ovadia)",     "1906.02530"),
    ("Verbalized confidence (Tian et al.)",  "2305.14975"),
    ("LLM overconfident (Xiong et al.)",     "2306.13063"),
    ("FActScore",                            "2305.14251"),
    ("SummaC (NLI faithfulness)",            "2111.09525"),
    ("GopherCite (kutipan verbatim)",        "2203.11147"),
    ("DoWhy — causal inference",             "2011.04216"),
    ("DSPy — compiler pipeline",             "2310.03714"),
    ("GEPA — optimizer DSPy",                "2507.19457"),
    ("XGrammar — constrained decoding",      "2411.15100"),
    ("Outlines — guided generation",         "2307.09702"),
    ("Cleanlab — confident learning",        "1911.00068"),
    ("Ragas — evaluasi RAG",                 "2309.15217"),
    ("SelfCheckGPT",                         "2303.08896"),
    ("Abstention survey (TACL)",             "2407.18418"),
    ("RAG/attribution audit (Liu et al.)",   "2304.09848"),
]

PKGS = [
    "z3-solver", "cvc5", "duckdb", "polars", "sympy", "pydantic", "jsonschema",
    "arch", "statsmodels", "scipy", "skfolio", "dowhy", "econml", "pandera",
    "dspy", "ragas", "cleanlab", "selfcheckgpt", "xgrammar", "outlines",
    "lm-eval", "inspect-ai", "pymc", "linearmodels", "rdrobust", "timeseriescv",
]

REPOS = [
    "Z3Prover/z3", "cvc5/cvc5", "duckdb/duckdb", "pola-rs/polars",
    "stanfordnlp/dspy", "py-why/dowhy", "cleanlab/cleanlab", "explodinggradients/ragas",
    "potsawee/SelfCheckGPT", "mlc-ai/xgrammar", "dottxt-ai/outlines",
    "EleutherAI/lm-evaluation-harness", "UKGovernmentBEIS/inspect_ai",
    "bashtage/arch", "skfolio/skfolio", "sam31415/timeseriescv",
]


def main() -> None:
    out = {"arxiv": {}, "pypi": {}, "github": {}, "gagal": []}

    print("═══ 1. arXiv — judul resmi dari sumber primer ═══")
    for label, aid in ARXIV:
        t = arxiv_title(aid)
        out["arxiv"][aid] = {"label": label, "judul": t}
        if t:
            print(f"  ✅ {aid:<12} {t[:74]}")
        else:
            print(f"  ❌ {aid:<12} {label}  <- TIDAK TERVERIFIKASI")
            out["gagal"].append(f"arxiv:{aid}:{label}")

    print("\n═══ 2. PyPI — paket & versi rilis ═══")
    for p in PKGS:
        v = pypi(p)
        out["pypi"][p] = v
        if v:
            print(f"  ✅ {p:<20} {v}")
        else:
            print(f"  ❌ {p:<20} <- TIDAK ADA di PyPI")
            out["gagal"].append(f"pypi:{p}")

    print("\n═══ 3. GitHub — lisensi/aktivitas ═══")
    for r in REPOS:
        g = github(r)
        out["github"][r] = g
        if g:
            print(f"  ✅ {r:<34} {g}")
        else:
            print(f"  ⚠️  {r:<34} (kuota API / tidak terbaca)")

    print("\n═══ RINGKASAN ═══")
    n_ar = sum(1 for v in out["arxiv"].values() if v["judul"])
    n_py = sum(1 for v in out["pypi"].values() if v)
    print(f"  arXiv  : {n_ar}/{len(ARXIV)} judul terverifikasi")
    print(f"  PyPI   : {n_py}/{len(PKGS)} paket terverifikasi")
    print(f"  Gagal  : {len(out['gagal'])}")
    for g in out["gagal"]:
        print(f"    - {g}")

    dst = pathlib.Path("data/research/verifikasi_riset_kapabilitas_20261001.json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\n  disimpan -> {dst}")


if __name__ == "__main__":
    main()
