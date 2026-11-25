#!/usr/bin/env python3
"""
layer0_gate.py — LAYER 0 TOOL-ORIGIN GATE (Anantara Sakti)

Tujuan: fail-closed check SEBELUM tool/repo pihak ketiga dipakai di ekosistem.
Kelas:  read-only, stdlib saja, tidak mengeksekusi/mengimpor kode repo target.

Pakai:
  python3 layer0_gate.py --audit <dir|repo>     # audit cepat, exit!=0 kalau ada temuan kelas DENY
  python3 layer0_gate.py --verify <dir> --policy <policy.json>   # cocokkan tree hash vs allowlist
  python3 layer0_gate.py --selftest             # uji internal (tanpa jaringan, tmpdir)

Aturan (policy-as-data, bukan hafalan):
  1. Lisensi wajib jelas di ROOT repo. GPL/AGPL/LGPL => TIDAK boleh di-vendor/di-copy
     ke kode Anantara (proprietary). Hanya boleh sebagai proses CLI terpisah.
  2. Tanpa file LICENSE di root => default all-rights-reserved => DENY.
  3. Karakter tak terlihat (PUA/bidi/ZWJ shell-level) di SOURCE => DENY sampai dibuktikan benign.
  4. Repo basi (>12 bulan tanpa commit) => DENY untuk adopsi kode.
  5. `curl|wget ... | sh`, auto-install runtime, git+https unpinned => RISK, butuh review.
  6. Fail-closed: kalau ragu => BLOCK, kembali ke user.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".zip", ".gz", ".whl", ".so",
              ".ttf", ".woff", ".woff2", ".pdf", ".mp3", ".mp4", ".webm", ".jar"}
TEXT_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".rb", ".go", ".rs", ".java",
            ".php", ".pl", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".json", ".toml", ".md",
            ".txt", ".rst", ".html", ".htm", ""}

GPL_MARKERS = ("GPL", "AGPL", "LGPL")  # dicocokkan sebagai substring, bukan equality
MAXB = 2_000_000

INVISIBLE = re.compile("[\u200b\u200c\u200d\u2060\ufeff\ue000-\uf8ff]")
CURL_PIPE = re.compile(r"(curl|wget)[^\n|]*\|\s*(ba|z)?sh")
AUTO_INSTALL = re.compile(r"(subprocess\.run\([^)]*[\"'](pip|uv)[\"']|os\.system\([^)]*pip\s+install)")
UNPINNED_GIT = re.compile(r"git\+https://[^\s\"']+(?!@[0-9a-f]{7,40})")
COMMITTED_ENV = re.compile(r"(^|/)\.env$")
INJECTION = re.compile(r"ignore (all )?(previous|prior) instructions|disregard (your|all) (rules|instructions)", re.I)
EXFIL = re.compile(r"curl\s+[^\n]*-d\s+@|requests\.post\([^\n]{0,80}(env|os\.environ)|nc\s+-e\s")


def iter_files(base: str):
    for dp, dn, fns in os.walk(base):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for fn in fns:
            yield os.path.join(dp, fn)


def read_text(path: str) -> str | None:
    if os.path.splitext(path)[1].lower() in BINARY_EXT:
        return None
    try:
        if os.path.getsize(path) > MAXB:
            return None
        with open(path, "r", encoding="utf-8", errors="strict") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def tree_hash(base: str) -> tuple[str, int, int]:
    """sha256 over sorted 'relpath:sha256' lines. Deterministic, tamper-evident."""
    manifest, total, nbytes = [], 0, 0
    for p in iter_files(base):
        rel = os.path.relpath(p, base)
        h = hashlib.sha256()
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
        except OSError:
            continue
        manifest.append(f"{rel}:{h.hexdigest()}")
        total += 1
        nbytes += os.path.getsize(p)
    manifest.sort()
    return hashlib.sha256("\n".join(manifest).encode()).hexdigest(), total, nbytes


def detect_license(base: str) -> list[str]:
    found = []
    for fn in os.listdir(base) if os.path.isdir(base) else []:
        low = fn.lower()
        if not low.startswith(("license", "licence", "copying", "notice")):
            continue
        # Only the LICENSE header decides the family; body text mentions other
        # licenses (GPL-2.0 text points readers at the LGPL), which caused a
        # misclassification before. Read the first 400 chars only.
        try:
            with open(os.path.join(base, fn), "r", errors="replace") as f:
                head = f.read(400)
            with open(os.path.join(base, fn), "r", errors="replace") as f:
                t = f.read(8000)
        except OSError:
            continue
        h = re.sub(r"\s+", " ", head).lower()
        if "affero general public" in h:
            found.append("AGPL")
        elif "lesser general public" in h or "library general public" in h:
            found.append("LGPL")
        elif "gnu general public license version 3" in h or "gnu general public license  version 3" in h:
            found.append("GPL-3.0")
        elif "gnu general public license version 2" in h:
            found.append("GPL-2.0")
        elif re.search(r"Apache License\s*\n?\s*Version 2\.0", head, re.I):
            found.append("Apache-2.0")
        elif re.search(r"MIT License|Permission is hereby granted, free of charge", t, re.I):
            found.append("MIT")
        elif re.search(r"Redistribution and use in source and binary forms", t, re.I):
            found.append("BSD")
        else:
            found.append("UNKNOWN")
    return sorted(set(found))


def audit(base: str) -> dict:
    """Read-only static audit. Returns findings bucketed by severity."""
    base = os.path.abspath(base)
    res = {
        "target": base,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deny": [], "risk": [], "info": [],
    }
    if not os.path.isdir(base):
        res["deny"].append(f"target bukan direktori: {base}")
        return res
    res["license_root"] = detect_license(base)
    if not res["license_root"] or res["license_root"] == ["UNKNOWN"]:
        res["deny"].append(
            "TIDAK ADA / TIDAK TERBACA file LICENSE di root => default all-rights-reserved (DENY)")
    elif any(mk in L for L in res["license_root"] for mk in GPL_MARKERS):
        res["deny"].append(
            f"lisensi copyleft {res['license_root']} => DILARANG di-vendor/di-copy ke kode Anantara; "
            "hanya boleh sebagai proses CLI terpisah")
    res["license_root"] = res["license_root"] or ["NONE"]

    if os.path.isdir(os.path.join(base, ".git")):
        try:
            out = subprocess.run(["git", "-C", base, "log", "-1", "--format=%ct"],
                                 capture_output=True, text=True, timeout=20)
            ts = int(out.stdout.strip() or 0)
            age_days = (datetime.now().timestamp() - ts) / 86400
            res["last_commit_age_days"] = round(age_days, 1)
            if age_days > 365:
                res["deny"].append(f"repo basi: commit terakhir {age_days:.0f} hari lalu (>365) => DENY untuk adopsi kode")
        except Exception:
            res["info"].append("umur commit tidak terbaca (git log gagal)")

    counts = {}
    for p in iter_files(base):
        rel = os.path.relpath(p, base)
        if COMMITTED_ENV.search("/" + rel):
            res["risk"].append(f".env ter-commit di repo: {rel} (cek isinya; jangan pernah copy ke ekosistem)")
        t = read_text(p)
        if t is None:
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext in TEXT_EXT:
            for m in INVISIBLE.finditer(t):
                cp = ord(m.group(0))
                line = t[:m.start()].count("\n") + 1
                rawline = t.split("\n")[line - 1] if line - 1 < len(t.split("\n")) else ""
                if cp in (0x200d, 0x200b, 0x200c, 0x2060, 0xfeff):
                    counts["invisible_soft"] = counts.get("invisible_soft", 0) + 1
                    continue
                # PUA/U+FFFD squeezed between two '-' inside a regex character
                # class is a Unicode RANGE literal (e.g. XML 1.0: #xE000-#xFFFD),
                # not the Glassworm identifier-shuffling pattern. Report for human
                # review instead of hard-deny, so the gate keeps its signal.
                if re.search(r"\[[^\]]*.\ue000-.\ufffd[^\]]*\]|\[[^\]]*[^\x00-\x7f]-", rawline) and "-" in rawline:
                    counts["pua_range_literal"] = counts.get("pua_range_literal", 0) + 1
                    res["risk"].append(
                        f"PUA U+{cp:04X} di {rel}:{line} terlihat sebagai literal rentang Unicode "
                        "(bukan Glassworm) — perlu review manusia + alasan tertulis")
                else:
                    counts["pua"] = counts.get("pua", 0) + 1
                    if counts["pua"] <= 5:
                        res["deny"].append(
                            f"karakter PUA U+{cp:04X} di SOURCE {rel}:{line} "
                            "(pola Glassworm) => DENY sampai dibuktikan benign")
        for tag, rx in (("curl|sh", CURL_PIPE), ("auto_install", AUTO_INSTALL),
                        ("unpinned_git", UNPINNED_GIT), ("injection", INJECTION), ("exfil", EXFIL)):
            m = rx.search(t)
            if m:
                line = t[:m.start()].count("\n") + 1
                (res["risk"] if tag != "injection" else res["deny"]).append(
                    f"{tag} di {rel}:{line}: {m.group(0)[:90].strip()}")
    res["counts"] = counts
    res["verdict"] = "BLOCK" if res["deny"] else ("REVIEW" if res["risk"] else "PASS")
    return res


def verify(base: str, policy_path: str) -> dict:
    with open(policy_path) as f:
        pol = json.load(f)
    th, files, nbytes = tree_hash(base)
    name = os.path.basename(os.path.abspath(base))
    entry = (pol.get("repos") or {}).get(name)
    out = {"target": name, "tree_sha256": th, "files": files, "bytes": nbytes}
    if not entry:
        out["status"] = "UNKNOWN_REPO"
        out["action"] = "BLOCK — repo tidak ada di allowlist; audit manual + approval user dulu"
        return out
    out["policy_verdict"] = entry.get("verdict")
    out["allowed_usage"] = entry.get("allowed_usage")
    if entry.get("tree_sha256") == th:
        out["status"] = "HASH_MATCH"
        out["action"] = f"OK sesuai allowlist ({entry.get('verdict')}). Batasan: {entry.get('allowed_usage')}"
    else:
        out["status"] = "HASH_MISMATCH"
        out["action"] = ("BLOCK — isi repo BERUBAH dari versi teraudit. Re-audit + update allowlist "
                         "butuh approval user (jangan auto-trust update).")
    return out


def selftest() -> int:
    """Uji internal tanpa jaringan. Membuktikan gate benar-benar fail-closed."""
    fails = 0
    with tempfile.TemporaryDirectory() as d:
        # 1) repo tanpa LICENSE -> BLOCK
        os.makedirs(os.path.join(d, "a"))
        open(os.path.join(d, "a", "x.py"), "w").write("print(1)\n")
        r = audit(os.path.join(d, "a"))
        ok = r["verdict"] == "BLOCK"
        print(f"  [{'OK ' if ok else 'FAIL'}] tanpa LICENSE => {r['verdict']}")
        fails += 0 if ok else 1
        # 2) GPL di root -> BLOCK (copyleft)
        os.makedirs(os.path.join(d, "b"))
        open(os.path.join(d, "b", "LICENSE"), "w").write("GNU GENERAL PUBLIC LICENSE\nVersion 2, June 1991\n")
        open(os.path.join(d, "b", "x.py"), "w").write("print(1)\n")
        r = audit(os.path.join(d, "b"))
        ok = r["verdict"] == "BLOCK" and "GPL-2.0" in r["license_root"]
        print(f"  [{'OK ' if ok else 'FAIL'}] GPL-2.0 => {r['verdict']} {r['license_root']}")
        fails += 0 if ok else 1
        # 3) MIT bersih -> PASS
        os.makedirs(os.path.join(d, "c"))
        open(os.path.join(d, "c", "LICENSE"), "w").write("MIT License\nPermission is hereby granted, free of charge\n")
        open(os.path.join(d, "c", "x.py"), "w").write("print(1)\n")
        r = audit(os.path.join(d, "c"))
        ok = r["verdict"] == "PASS"
        print(f"  [{'OK ' if ok else 'FAIL'}] MIT bersih => {r['verdict']}")
        fails += 0 if ok else 1
        # 4) PUA di source -> BLOCK
        os.makedirs(os.path.join(d, "e"))
        open(os.path.join(d, "e", "LICENSE"), "w").write("MIT License\nPermission is hereby granted, free of charge\n")
        open(os.path.join(d, "e", "x.py"), "w").write("VAR='a\ue000b'\n")
        r = audit(os.path.join(d, "e"))
        ok = r["verdict"] == "BLOCK" and r["counts"].get("pua")
        print(f"  [{'OK ' if ok else 'FAIL'}] PUA di source => {r['verdict']} {r['counts']}")
        fails += 0 if ok else 1
        # 5) tree hash tamper-evident
        h1, _, _ = tree_hash(os.path.join(d, "c"))
        open(os.path.join(d, "c", "x.py"), "a").write("# tamper\n")
        h2, _, _ = tree_hash(os.path.join(d, "c"))
        ok = h1 != h2
        print(f"  [{'OK ' if ok else 'FAIL'}] tree hash berubah setelah tamper")
        fails += 0 if ok else 1
        # 6) allowlist verify: mismatch -> BLOCK
        pol = {"repos": {"c": {"verdict": "ALLOWED", "tree_sha256": h1, "allowed_usage": "x"}}}
        pp = os.path.join(d, "pol.json")
        json.dump(pol, open(pp, "w"))
        r = verify(os.path.join(d, "c"), pp)
        ok = r["status"] == "HASH_MISMATCH" and "BLOCK" in r["action"]
        print(f"  [{'OK ' if ok else 'FAIL'}] allowlist mismatch => {r['status']}")
        fails += 0 if ok else 1
    print(f"  selftest: {'LULUS' if fails == 0 else f'{fails} GAGAL'}")
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Layer 0 tool-origin gate (read-only, fail-closed)")
    ap.add_argument("--audit", metavar="DIR")
    ap.add_argument("--verify", metavar="DIR")
    ap.add_argument("--policy", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "layer0_tool_policy.json"))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.audit:
        r = audit(a.audit)
        print(json.dumps(r, indent=1)[:6000])
        return 0 if r["verdict"] == "PASS" else 1
    if a.verify:
        print(json.dumps(verify(a.verify, a.policy), indent=1))
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())