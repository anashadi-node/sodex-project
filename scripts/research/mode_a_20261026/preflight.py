#!/usr/bin/env python3
"""Preflight kesiapan LIVE 01-Des-2026 (read-only). Status: PASS | FAIL | WAIT (butuh tindakan user / waktu) | INFO.
  preflight.py            # tabel ringkas + exit code 0 bila tak ada FAIL
  preflight.py --json
"""
from __future__ import annotations
import datetime as dt, glob, json, os, subprocess, sys
import mode_a_live as L
import spot_exec as sx

HERE, FWD = L.HERE, L.FWD
R = []
def add(grp, name, st, msg=""): R.append({"grup": grp, "cek": name, "status": st, "info": msg})
def sh(cmd, timeout=120):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=HERE); return r.returncode, (r.stdout + r.stderr).strip()
def rd(p): return [json.loads(x) for x in open(p) if x.strip()] if os.path.exists(p) else []


def main():
    now = dt.datetime.now(dt.timezone.utc)
    # --- KODE
    rc, out = sh(".venv/bin/python -W ignore -m pytest -q -p no:warnings test_engine_v2.py test_paper_forward.py test_mode_a_live.py 2>&1 | tail -2")
    add("kode", "suite tes", "PASS" if "passed" in out and "failed" not in out and "error" not in out.lower() else "FAIL", out.splitlines()[-1] if out else "")
    rc, out = sh("git status --porcelain -- . | grep -v '^??' | grep -v 'forward/spot_book.jsonl' | head -5")
    add("kode", "file terlacak bersih (commit)", "PASS" if not out else "WAIT", out or "bersih")
    # --- DATA & PAPER
    led = [r for r in rd(os.path.join(FWD, "ledger.jsonl")) if r.get("kind") == "rec"]
    ev = [r for r in rd(os.path.join(FWD, "ledger.jsonl")) if r.get("kind") == "event"]
    exp = (now - dt.timedelta(days=1)).date() if now.hour * 60 + now.minute >= 45 else (now - dt.timedelta(days=2)).date()
    last = max((dt.date.fromisoformat(r["asof"]) for r in led), default=None)
    add("paper", "ledger target terbaru", "PASS" if last and last >= exp else "FAIL", f"asof terakhir={last} (min {exp}); n={len(led)}; GAGAL_DATA={len(ev)}")
    ex = [r for r in rd(os.path.join(FWD, "paper_exec.jsonl")) if r.get("kind") == "exec"]
    add("paper", "paper-eksekusi di buku nyata", "PASS" if ex and ex[-1]["asof"] == str(last) else "FAIL", f"n={len(ex)}; terakhir={ex[-1]['asof'] if ex else None}")
    bk = rd(os.path.join(FWD, "spot_book.jsonl"))
    age = (now - dt.datetime.fromisoformat(bk[-1]["utc"])).total_seconds() / 60 if bk else 9e9
    add("paper", "kolektor buku (<=70 mnt)", "PASS" if age <= 70 else "FAIL", f"snapshot={len(bk)}; umur={age:.0f} mnt")
    for t in ("sodex-prereg23b-record.timer", "sodex-spot-book-collector.timer"):
        rc, out = sh(f"systemctl --user is-active {t}"); add("paper", t, "PASS" if out == "active" else "FAIL", out)
    # --- VENUE (publik)
    try:
        mk = {m["displayName"]: m for m in sx.run_cli(["markets", "spot", "--format", "json"])}
        bad = []
        for a in L.ASSETS:
            m = mk.get(sx.NAME[a]); 
            if not m: bad.append(f"{a}: tak ada"); continue
            if m.get("status") != "TRADING" or Decimal_eq(m, "stepSize", sx.STEP[a]) or Decimal_eq(m, "tickSize", sx.TICK[a]) or Decimal_eq(m, "minNotional", sx.MIN_NOTIONAL):
                bad.append(f"{a}: spesifikasi berubah {({k: m.get(k) for k in ('status', 'stepSize', 'tickSize', 'minNotional')})}")
            if abs(float(m.get("takerFee", 0)) - sx.TAKER) > 1e-9: bad.append(f"{a}: fee taker {m.get('takerFee')}")
        add("venue", "spesifikasi pasar = asumsi engine", "PASS" if not bad else "FAIL", "; ".join(bad) or "step/tick/minNotional/fee cocok")
    except sx.ExecError as e: add("venue", "spesifikasi pasar", "FAIL", str(e)[:120])
    try:
        bs = {a: sx.fetch_book(a) for a in L.ASSETS}
        add("venue", "buku nyata sehat", "PASS", "; ".join(f"{a} spread {b['spread_bps']:.2f}bps biaya$60 {sx.depth_cost(b, 60)['buy']}bps" for a, b in bs.items()))
    except sx.ExecError as e: add("venue", "buku nyata sehat", "FAIL", str(e)[:120])
    # --- KREDENSIAL & DANA (user)
    ef = L.ENV_FILE
    if not os.path.exists(ef): add("user", "secrets/sodex.env", "WAIT", "belum dibuat (salin secrets/sodex.env.template, chmod 600, ISI SENDIRI)")
    else:
        try:
            e = L.load_env(); rc, ign = sh(f"git check-ignore -q {ef}; echo $?")
            add("user", "secrets/sodex.env valid & di-gitignore", "PASS" if ign.endswith("0") else "FAIL", "kunci ada (nilai tidak ditampilkan)")
            try:
                bal = L.parse_balances(sx.run_cli(["balance", "spot", e["SODEX_ADDRESS"], "--format", "json"], env={k: v for k, v in os.environ.items() if k not in sx.PUBLIC_ENV_DROP}))
                add("user", "saldo spot USDC terbaca", "PASS" if bal["usdc"] > 0 else "WAIT", f"USDC={bal['usdc']:.2f} btc={bal['btc']} eth={bal['eth']} xaut={bal['xaut']}")
            except sx.ExecError as ex_: add("user", "saldo spot terbaca", "FAIL", str(ex_)[:120])
        except L.Block as b: add("user", "secrets/sodex.env", "FAIL", str(b))
    st = os.path.join(FWD, "selftest_testnet_ok.json")
    add("user", "selftest TESTNET (place+cancel)", "PASS" if os.path.exists(st) else "WAIT", "bukti ada" if os.path.exists(st) else "belum: jalankan runbook langkah 3 (butuh kunci testnet)")
    try: L.check_arm(); add("user", "LIVE_ARMED.json (GO user)", "PASS", "armed")
    except L.Block as b: add("user", "LIVE_ARMED.json (GO user)", "WAIT", str(b))
    # --- VERDICT PAPER
    import paper_forward as pf
    ev_ = pf.evaluate(FWD); add("verdict", "PRAREG-23b", "INFO", f"{ev_.get('vonis')} (hari {ev_.get('n_hari_window', 0)}/{pf.N_WIN})")
    add("verdict", "tanggal", "INFO", f"sekarang {now.date()} | live paling cepat 2026-12-01 | sisa {(dt.date(2026, 12, 1) - now.date()).days} hari")
    try:
        d = L.run(False); add("dry-run", "perencana live (DRY) berjalan", "PASS", json.dumps({k: d[k] for k in d if k in ("mode", "status", "asof")}))
    except (L.Block, sx.ExecError) as b: add("dry-run", "perencana live (DRY)", "FAIL", str(b)[:140])
    return R


def Decimal_eq(m, k, exp):
    from decimal import Decimal
    return Decimal(str(m.get(k))) != exp


if __name__ == "__main__":
    res = main()
    if "--json" in sys.argv: print(json.dumps(res, indent=1))
    else:
        for r in res: print(f"{r['status']:5s} [{r['grup']:7s}] {r['cek']:40s} {r['info'][:110]}")
        n = {s: sum(1 for r in res if r["status"] == s) for s in ("PASS", "FAIL", "WAIT", "INFO")}
        print(f"\nRINGKAS: {n} -> " + ("TEKNIS SIAP; sisa = tindakan user" if n["FAIL"] == 0 else "ADA FAIL — perbaiki"))
    sys.exit(1 if any(r["status"] == "FAIL" for r in res) else 0)
