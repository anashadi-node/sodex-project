#!/usr/bin/env python3
"""SODEX Scan Audit -- READ-ONLY. Tidak ada jalur order/sign/withdraw, tidak mencetak nilai kredensial.

Subperintah: security | live | data | tracks | all
Semua temuan dicetak sebagai baris 'FINDING [SEV] ...' agar bisa di-grep/diaudit ulang.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
UNITS = Path.home() / ".config/systemd/user"


def sh(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return f"ERR {e}"


def finding(sev, msg):
    print(f"FINDING [{sev}] {msg}")


def sodex_files():
    pats = ["scripts/sodex_*.py", "anantara/sodex_*.py", "scripts/paper_test_*.py", "anantara/*liquidat*.py"]
    out = []
    for p in pats:
        out += glob.glob(p)
    return sorted(set(out))


def security():
    print("== SECURITY ==")
    # 1 provenance proses sodex/paper
    ps = sh("ps -eo pid,etimes,args | grep -E 'sodex|paper_test|obi|orderflow' | grep -v grep")
    bad = [l for l in ps.splitlines() if re.search(r"/tmp/|/dev/shm/|\.cache/", l)]
    print(f"proses terkait: {len(ps.splitlines())}; dari /tmp|/dev/shm: {len(bad)}")
    for l in bad:
        finding("HIGH", f"proses dari lokasi tak lazim: {l[:140]}")
    # 2 egress
    pids = re.findall(r"^\s*(\d+)\s", ps, re.M)
    ss = sh("ss -tnp state established 2>/dev/null")
    hosts = {}
    for l in ss.splitlines():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+):(\d+)\s.*pid=(\d+)", l)
        if m and m.group(3) in pids:
            hosts.setdefault(m.group(1) + ":" + m.group(2), 0)
            hosts[m.group(1) + ":" + m.group(2)] += 1
    print(f"egress unik dari proses sodex/paper: {len(hosts)}")
    for h, n in sorted(hosts.items(), key=lambda x: -x[1])[:12]:
        print(f"  {h} x{n}")
    # 3 persistensi
    cron = sh("crontab -l 2>&1").strip()
    print("crontab:", cron[:200] if "no crontab" not in cron else "kosong")
    pre = Path("/etc/ld.so.preload")
    if pre.exists() and pre.read_text().strip():
        finding("HIGH", "/etc/ld.so.preload berisi entri")
    rc = sh("tail -n 5 ~/.bashrc ~/.profile 2>/dev/null | grep -iE 'curl|wget|base64|eval|nc ' ")
    if rc.strip():
        finding("MED", f"rc shell mengandung perintah jaringan/eval: {rc.strip()[:160]}")
    # unit systemd: yang tidak ada di git
    tracked = set(Path(p).name for p in glob.glob("systemd/*"))
    live = [Path(p).name for p in glob.glob(str(UNITS / "*sodex*")) + glob.glob(str(UNITS / "anantara-obi*"))]
    unt = [u for u in live if u not in tracked]
    print(f"unit sodex di systemd: {len(live)}; tidak ada salinan di git/systemd/: {len(unt)}")
    # 4 unicode tersembunyi
    hits = 0
    pua = re.compile("[\ue000-\uf8ff\U000e0100-\U000e01ef\u200b\u200e\u2060\u00ad\u202a-\u202e]")
    for f in sodex_files():
        try:
            t = Path(f).read_text(errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        m = pua.findall(t)
        if m:
            hits += 1
            finding("MED", f"karakter tak terlihat di {f}: {len(m)} (cek: bisa artefak patch, bisa payload)")
    print(f"unicode tersembunyi: {hits} berkas dari {len(sodex_files())}")
    # 5 pola berbahaya di kode sodex
    danger = re.compile(r"\beval\(|\bexec\(|base64\.b64decode|subprocess\..*shell=True|os\.system\(|__import__\(|pickle\.loads")
    cnt = {}
    for f in sodex_files():
        for i, l in enumerate(Path(f).read_text(errors="ignore").splitlines(), 1):
            if danger.search(l) and not l.strip().startswith("#"):
                cnt.setdefault(f, []).append(i)
    for f, ls in cnt.items():
        finding("LOW", f"pola eksekusi dinamis {f} baris {ls[:6]}")
    # 6 git integrity + remote + kredensial di history
    print("git remote:", sh("git remote -v").strip().replace("\n", " | ")[:200] or "TIDAK ADA remote")
    print("author unik 40 commit terakhir:", sh("git log -40 --format=%an|%ae | sort -u").strip().replace("\n", "; ")[:200])
    tracked_env = sh("git ls-files | grep -E '(^|/)\\.env' ").split()
    print("berkas .env* ter-track:", tracked_env)
    pat = re.compile(r"0x[a-fA-F0-9]{64}\b")
    leaked = []
    for f in sh("git ls-files 'docs/*.md' 'reports/*.md' 'scripts/*.py' 'anantara/*.py' 'systemd/*'").split():
        try:
            if pat.search(Path(f).read_text(errors="ignore")):
                leaked.append(f)
        except Exception:  # noqa: BLE001
            pass
    for f in leaked:
        finding("HIGH", f"pola kunci privat 0x+64hex di berkas ter-track: {f} (nilai TIDAK dicetak)")
    # izin berkas rahasia
    for f in glob.glob(".env*") + glob.glob("secrets/*"):
        try:
            mode = oct(os.stat(f).st_mode & 0o777)
            if os.stat(f).st_mode & 0o077:
                finding("MED", f"izin longgar {f} mode {mode} (harus 600)")
        except Exception:  # noqa: BLE001
            pass
    pushed = sh("git branch -r 2>&1").strip()
    print("branch remote:", pushed[:120] or "tidak ada")
    cl = sh("which clamscan")
    print("clamscan:", cl.strip() or "TIDAK terpasang")


def live():
    print("== JALUR UANG NYATA ==")
    order = re.compile(r"place_order|create_order|submit_order|/exchange\b|/order\b|api/v1/(perps|spot)/trade|\.post\(.*(order|exchange)|eth_account|sign_typed|private_key|Account\.from_key|withdraw")
    rows = []
    for f in sodex_files():
        t = Path(f).read_text(errors="ignore")
        n = len(order.findall(t))
        if n:
            rows.append((n, f))
    rows.sort(reverse=True)
    print(f"berkas dengan kemampuan order/sign: {len(rows)}")
    # apakah ada yang berjalan sebagai service
    active = sh("systemctl --user list-units --state=running --no-pager --plain | awk '{print $1}'").split()
    cap = []
    for n, f in rows:
        base = Path(f).name
        for u in active:
            p = UNITS / u
            if p.exists() and base in p.read_text(errors="ignore"):
                cap.append((u, f, n))
    for u, f, n in cap:
        finding("HIGH", f"service BERJALAN memuat skrip berkemampuan order: {u} -> {f} ({n} pola)")
    if not cap:
        print("OK: tidak ada service RUNNING yang memuat skrip berkemampuan order/sign")
    # default live-by-default
    dflt = re.compile(r"(\w*(LIVE|DRY)\w*)\s*=\s*os\.environ\.get\(\s*['\"]\w+['\"]\s*,\s*['\"]?(0|1|true|false)", re.I)
    for f in sodex_files():
        for i, l in enumerate(Path(f).read_text(errors="ignore").splitlines(), 1):
            m = dflt.search(l)
            if m:
                name, val = m.group(1), m.group(3).lower()
                live_default = ("LIVE" in name.upper() and val in ("1", "true")) or ("DRY" in name.upper() and val in ("0", "false"))
                if live_default:
                    finding("HIGH", f"default LIVE-by-default {f}:{i} {name} default={val}")
    # fail-open: fungsi baca venue return [] saat except
    fo = re.compile(r"except[^\n]*:\s*\n\s*return\s*(\[\]|\{\}|None|0)\b")
    for f in sodex_files():
        t = Path(f).read_text(errors="ignore")
        n = len(fo.findall(t))
        if n >= 3:
            finding("LOW", f"{f}: {n} blok 'except -> return kosong' (kandidat fail-open, periksa pemakainya)")
    kill = sorted(glob.glob("data/*KILL*") + glob.glob("data/*kill*"))
    print("berkas kill-switch:", kill or "tidak ada (state normal = tidak terkunci)")
    for k in glob.glob("data/sodex_go_live_resume_*.json"):
        try:
            d = json.loads(Path(k).read_text())
            print("resume-approval", k, "approved=", d.get("live_resume_approved"))
        except Exception:  # noqa: BLE001
            pass


def data():
    print("== INTEGRITAS DATA FORWARD ==")
    base = Path("freqtrade_user_data/data/sodex")
    for kind in ("trades", "obi"):
        files = sorted(base.glob(f"{kind}/{kind}_*.jsonl"))
        days = [f.stem.split("_")[1] for f in files]
        print(f"{kind}: {len(files)} berkas {days[0]}..{days[-1]}")
        # celah hari
        from datetime import date, timedelta
        d0 = date(int(days[0][:4]), int(days[0][4:6]), int(days[0][6:]))
        d1 = date(int(days[-1][:4]), int(days[-1][4:6]), int(days[-1][6:]))
        have = set(days)
        miss, d = [], d0
        while d <= d1:
            if d.strftime("%Y%m%d") not in have:
                miss.append(d.strftime("%m-%d"))
            d += timedelta(days=1)
        print(f"  hari hilang: {len(miss)} {miss[:12]}")
        sizes = [f.stat().st_size for f in files]
        small = [(f.name, s) for f, s in zip(files, sizes) if s < 0.1 * (sum(sizes) / len(sizes))]
        print(f"  berkas <10% ukuran rata-rata (kandidat bolong): {len(small)} {[x[0][-14:-6] for x in small][:8]}")
        newest = files[-1]
        age = (time.time() - newest.stat().st_mtime) / 60
        print(f"  berkas terbaru ditulis {age:.1f} menit lalu")
        if age > 15:
            finding("HIGH", f"collector {kind} basi {age:.0f} menit")
    # cek struktur 1 berkas trade + duplikat + monotonik
    f = sorted(base.glob("trades/trades_*.jsonl"))[-2]
    n = 0
    seen = set()
    dup = 0
    nonmono = 0
    last = -1
    syms = {}
    keys = None
    with open(f) as fh:
        for l in fh:
            try:
                r = json.loads(l)
            except Exception:  # noqa: BLE001
                continue
            n += 1
            keys = keys or list(r.keys())
            tid = (r.get("sym") or r.get("s"), r.get("id") or r.get("tid") or r.get("i"))
            if tid in seen:
                dup += 1
            seen.add(tid)
            ts = r.get("ts") or r.get("t") or r.get("T") or 0
            if ts < last:
                nonmono += 1
            last = max(last, ts)
            syms[r.get("sym") or r.get("s")] = syms.get(r.get("sym") or r.get("s"), 0) + 1
    print(f"sampel {f.name}: {n} baris, duplikat id={dup}, non-monoton={nonmono}, simbol={len(syms)}, kunci={keys}")
    if dup:
        finding("MED", f"duplikat trade id di {f.name}: {dup}")
    # data historis venue lain
    for p in ("binance/futures", "hl/candles", "hl/funding", "okx/futures", "bybit/futures", "bitget/futures"):
        d = Path("freqtrade_user_data/data") / p
        fs = list(d.glob("*"))
        print(f"{p}: {len(fs)} berkas, {sum(x.stat().st_size for x in fs if x.is_file()) / 1e6:.0f} MB, contoh {[x.name for x in fs[:3]]}")
    print(sh("df -h /home | tail -1").strip())


def tracks():
    print("== STATUS TRACK PAPER ==")
    wallet = float(os.environ.get("SODEX_TOTAL_WALLET", "262.77"))
    for f in sorted(glob.glob("data/paper_test_*_state.json")):
        try:
            d = json.loads(Path(f).read_text())
        except Exception as e:  # noqa: BLE001
            finding("MED", f"{f} tidak terbaca: {e}")
            continue
        age = (time.time() - os.stat(f).st_mtime) / 3600
        tr = d.get("trades") or d.get("closed") or []
        print(f"{Path(f).name:55s} umur={age:5.1f}j  trade_tersimpan={len(tr):4d}  kunci={list(d.keys())[:6]}")
        if age > 24:
            finding("MED", f"state basi {age:.0f} jam: {f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    for name, fn in (("security", security), ("live", live), ("data", data), ("tracks", tracks)):
        if cmd in (name, "all"):
            fn()
            print()
