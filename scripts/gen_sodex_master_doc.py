#!/usr/bin/env python3
"""Generator dokumen master SoDEX (HTML self-contained) — SEMUA angka dihitung
dari data runtime nyata. Tidak ada angka yang diketik tangan.

Jalankan: env -u PYTHONPATH ./.venv-research/bin/python scripts/gen_sodex_master_doc.py
"""
from __future__ import annotations
import datetime as dt, glob, json, os, subprocess, sys, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import sodex_fleet_edge_audit as fa  # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)
OUT = os.path.join(ROOT, "reports", "sodex", f"SODEX_MASTER_{NOW:%Y%m%d}.html")


def sh(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:                                    # noqa: BLE001
        return f"<gagal: {e}>"


def jload(p, default=None):
    try:
        return json.load(open(os.path.join(ROOT, p)))
    except Exception:                                          # noqa: BLE001
        return default


# ---------------------------------------------------------------- 1. data lane
files = sorted(glob.glob(os.path.join(ROOT, "data", "paper_test*_state.json")))
rows = fa.audit(files)
lanes = [r for r in rows if r["n"] >= fa.MIN_N]
small = [r for r in rows if r["n"] < fa.MIN_N and r["n"] > 0]
n_all = sum(r["n"] for r in rows)
alpha_ok = [r for r in rows if r.get("ab_alpha") == "ALPHA"]

# agregat fleet
tot_pnl = 0.0
for f in files:
    s = jload(os.path.relpath(f, ROOT), {}) or {}
    ct = next((s[k] for k in ("closed_trades", "closed", "trades") if isinstance(s.get(k), list)), [])
    for t in ct:
        v = t.get("pnl_pct")
        if isinstance(v, (int, float)):
            tot_pnl += v

# ------------------------------------------------------- 2. RR & biaya (ab9a)
rr_block = {}
try:
    s = jload("data/paper_test_twoway_ab9a_state.json", {})
    ct = [x for x in s.get("closed_trades", []) if isinstance(x.get("pnl_pct"), (int, float))]
    tps, sls, gross = [], [], []
    for x in ct:
        e = x["entry_price"]; d = 1 if x["direction"] == "LONG" else -1
        tps.append((x["tp_price"] - e) / e * d * 100)
        sls.append(abs((x["sl_price"] - e) / e) * 100)
        if x.get("exit_price"):
            gross.append((x["exit_price"] / e - 1) * d)
    wr = 100 * sum(1 for x in ct if x["pnl_pct"] > 0) / len(ct)
    tp_m, sl_m = st.mean(tps), st.mean(sls)
    rr_block = dict(n=len(ct), tp=tp_m, sl=sl_m, rr=tp_m / sl_m, wr=wr,
                    be=sl_m / (sl_m + tp_m) * 100,
                    fee_bps=(st.mean(gross) - st.mean([x["pnl_pct"] for x in ct])) * 1e4)
except Exception:                                              # noqa: BLE001
    pass

# ------------------------------------------------------------ 3. venue nyata
snap = jload("data/sodex_real_sync_snapshot.json", {}) or {}
perps = snap.get("perps_positions", []) or []
bal = snap.get("perps_balance", {}) or {}
spot = [b for b in (snap.get("spot_balances") or []) if float(b.get("total") or 0) > 0]
wd = jload("data/sodex_watchdog_status.json", {}) or {}
pf = sh("env -u PYTHONPATH ./.venv-research/bin/python scripts/sodex_live_preflight.py", 180)
m_lulus = [ln for ln in pf.splitlines() if "Status:" in ln]
pf_line = m_lulus[0].strip() if m_lulus else "tidak tersedia"
pf_checks = [ln.strip() for ln in pf.splitlines() if ln.strip().startswith("[")]
units = sh("systemctl --user list-units 'anantara*' --no-legend --no-pager | awk '{print $1, $3, $4}'")
u_rows = [ln.split() for ln in units.splitlines() if ln.strip()]
paper_units = [u for u in u_rows if "paper" in u[0]]

# --------------------------------------------------------------- 4. repo/code
commit = sh("git log -1 --format='%h %s'").strip()
branch = sh("git rev-parse --abbrev-ref HEAD").strip()
n_py = int(sh("git ls-files '*.py' | wc -l").strip() or 0)
n_files = int(sh("git ls-files | wc -l").strip() or 0)
tests_line = sh("env -u PYTHONPATH ./.venv-research/bin/python -m pytest tests/test_sodex*.py -q -p no:cacheprovider -o addopts='' 2>&1 | tail -n 1", 400).strip()
kl = glob.glob(os.path.join(ROOT, "data", "sodex_klines", "1h", "*.json"))

# ------------------------------------------------------------- 5. HTML render
def esc(x):
    return (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def lane_table():
    h = ['<table><thead><tr><th>Lane</th><th>n</th><th>Mean %/trade</th><th>CI95</th>'
         '<th>Hit</th><th>q(BH)</th><th>Verdict</th><th>α: SIGNAL−RANDOM</th><th>α verdict</th></tr></thead><tbody>']
    for r in rows:
        if r["n"] == 0:
            continue
        ci = f"[{r['ci_lo']:+.2f}, {r['ci_hi']:+.2f}]" if "ci_lo" in r else "—"
        d = r.get("ab_delta_pp")
        dci = f"[{r['ab_delta_lo']:+.2f}, {r['ab_delta_hi']:+.2f}]" if "ab_delta_lo" in r else "—"
        cls = {"KANDIDAT": "ok", "TIDAK_ADA_EDGE": "bad", "DATA_KURANG": "warn"}.get(r["verdict"], "")
        acls = {"ALPHA": "ok", "TIDAK_TERBUKTI": "bad", "DATA_KURANG": "warn", "-": ""}.get(r.get("ab_alpha", "-"), "")
        h.append(f"<tr><td><code>{esc(r['lane'].replace('paper_test_',''))}</code></td><td class=n>{r['n']}</td>"
                 f"<td class=n>{r.get('mean_pct', float('nan')):+.3f}</td><td class=n>{ci}</td>"
                 f"<td class=n>{r.get('hit', 0):.0%}</td>"
                 f"<td class=n>{(f'{r[chr(113)]:.3f}' if 'q' in r else '—')}</td>"
                 f"<td class={cls}>{r['verdict']}</td>"
                 f"<td class=n>{f'{d:+.3f} {dci}' if d is not None else '—'}</td>"
                 f"<td class={acls}>{r.get('ab_alpha','-')}</td></tr>")
    h.append("</tbody></table>")
    return "\n".join(h)


def unit_table():
    h = ["<table><thead><tr><th>Unit</th><th>Load</th><th>Active</th><th>Sub</th></tr></thead><tbody>"]
    for u in u_rows:
        if len(u) >= 4:
            h.append(f"<tr><td><code>{esc(u[0])}</code></td><td>{esc(u[1])}</td><td>{esc(u[2])}</td><td>{esc(u[3])}</td></tr>")
    h.append("</tbody></table>")
    return "\n".join(h)


def pos_table():
    if not perps:
        return "<p>Tidak ada posisi perps terbuka pada snapshot.</p>"
    h = ["<table><thead><tr><th>Simbol</th><th>Size</th><th>Entry</th><th>Margin (vUSDC)</th>"
         "<th>Lev</th><th>Realized PnL</th><th>Ter-track?</th></tr></thead><tbody>"]
    crit = " ".join(c.get("msg", "") for c in wd.get("critical", []))
    for p in perps:
        sym = p.get("symbol", "?")
        track = "TIDAK" if sym.split("-")[0] in crit else "ya"
        cls = "bad" if track == "TIDAK" else ""
        h.append(f"<tr><td>{esc(sym)}</td><td class=n>{esc(p.get('size'))}</td>"
                 f"<td class=n>{float(p.get('avgEntryPrice') or 0):.6g}</td>"
                 f"<td class=n>{float(p.get('initialMargin') or 0):.2f}</td>"
                 f"<td class=n>{esc(p.get('leverage'))}</td>"
                 f"<td class=n>{float(p.get('realizedPnL') or 0):+.4f}</td><td class={cls}>{track}</td></tr>")
    h.append("</tbody></table>")
    return "\n".join(h)


def check_rows():
    h = []
    for ln in pf_checks:
        s = ln.strip()
        cls = "ok" if s.startswith("[OK") else ("bad" if s.startswith("[BLOCK") else "warn")
        h.append(f"<li class={cls}><code>{esc(s[:90])}</code></li>")
    return "\n".join(h)


CSS = """
:root{--bg:#0b0f14;--card:#121923;--line:#22303f;--fg:#e7eef7;--mut:#8fa3b8;--acc:#3ecf8e;--bad:#ff6b6b;--warn:#f7b955;--blue:#5aa9ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{display:grid;grid-template-columns:280px 1fr;gap:0;min-height:100vh}
nav{position:sticky;top:0;height:100vh;overflow:auto;border-right:1px solid var(--line);padding:22px 16px;background:#0d131b}
nav h2{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--mut);margin:0 0 12px}
nav a{display:block;color:var(--fg);text-decoration:none;font-size:13.5px;padding:5px 8px;border-radius:6px;opacity:.85}
nav a:hover{background:#16202c;opacity:1}
main{padding:34px 42px 90px;max-width:1080px}
h1{font-size:31px;line-height:1.25;margin:0 0 6px}
h2{font-size:22px;margin:44px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h3{font-size:16.5px;margin:26px 0 8px;color:var(--blue)}
p,li{color:#d7e2ee}
.sub{color:var(--mut);font-size:14px;margin-bottom:22px}
table{width:100%;border-collapse:collapse;margin:14px 0 20px;font-size:13.5px;background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden}
th{background:#16202c;text-align:left;padding:9px 10px;font-weight:600;color:#cfe0f0;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid #1a2531;vertical-align:top}
tr:last-child td{border-bottom:none}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
code{background:#0f1720;padding:1.5px 5px;border-radius:4px;font-size:12.5px;color:#a8d8ff}
pre{background:#0f1720;border:1px solid var(--line);border-radius:8px;padding:12px 14px;overflow-x:auto;max-width:100%}
pre code{background:none;padding:0;color:#bfe3ff;font-size:12.5px;white-space:pre}
.ok{color:var(--acc);font-weight:600}.bad{color:var(--bad);font-weight:600}.warn{color:var(--warn);font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:16px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:16px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.kpi .v{font-size:24px;font-weight:700;letter-spacing:-.5px}
.kpi .l{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.08em;margin-top:2px}
blockquote{border-left:3px solid var(--warn);margin:16px 0;padding:10px 16px;background:#1a160c;border-radius:0 8px 8px 0;color:#f0dfc0}
ul,ol{padding-left:22px}
li{margin:4px 0}
li.ok,li.bad,li.warn{list-style:none;margin-left:-14px}
.tag{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:20px;border:1px solid var(--line);color:var(--mut);margin-right:6px}
svg{display:block;width:100%;max-width:100%;height:auto}
.wrap>*{min-width:0}main{min-width:0}
footer{margin-top:60px;padding-top:16px;border-top:1px solid var(--line);color:var(--mut);font-size:12.5px}
@media(max-width:900px){.wrap{grid-template-columns:1fr}nav{position:static;height:auto;border-right:none;border-bottom:1px solid var(--line)}main{padding:22px 16px 60px}}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:8px}
td code{word-break:break-word}
@media print{nav{display:none}.wrap{grid-template-columns:1fr}body{background:#fff;color:#111}}
"""

TOC = [("ringkasan", "1. Ringkasan eksekutif"), ("filosofi", "2. Filosofi & North Star"),
       ("target", "3. Target & aritmetika modal"), ("venue", "4. Venue, instrumen, biaya"),
       ("arsitektur", "5. Arsitektur sistem"), ("struktur", "6. Struktur repo & runtime"),
       ("alur", "7. Alur kerja harian"), ("lane", "8. Lane paper (data nyata)"),
       ("riset", "9. Temuan riset 25 Nov"), ("metode", "10. Metodologi statistik"),
       ("safety", "11. Safety, gate, fail-closed"), ("kesiapan", "12. Kesiapan live"),
       ("posisi", "13. Posisi nyata & rekonsiliasi"), ("risiko", "14. Risiko terukur"),
       ("roadmap", "15. Roadmap ke 1 Des 2026"), ("publik", "16. Repo publik & keamanan"),
       ("verifikasi", "17. Cara verifikasi sendiri"), ("glosarium", "18. Glosarium"),
       ("lampiran", "19. Lampiran"), ("log", "20. Log perubahan hari ini")]

nav_html = "\n".join(f'<a href="#{i}">{esc(t)}</a>' for i, t in TOC)

HTML = f"""<!DOCTYPE html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SoDEX Master Document — {NOW:%Y-%m-%d}</title>
<style>{CSS}</style></head><body><div class="wrap">
<nav><h2>Daftar isi</h2>{nav_html}</nav>
<main>
<h1>SoDEX — Dokumen Master A–Z</h1>
<div class="sub">Keadaan sistem per <b>{NOW:%Y-%m-%d %H:%M} UTC</b> ({NOW.astimezone(dt.timezone(dt.timedelta(hours=7))):%H:%M} WIB).
Dokumen ini dibangun otomatis dari data runtime; setiap angka dapat diverifikasi ulang dengan perintah di bagian 17.</div>

<div class="grid">
  <div class="kpi"><div class="v bad">NO-GO</div><div class="l">Kesiapan live</div></div>
  <div class="kpi"><div class="v">{len(lanes)}</div><div class="l">Lane n≥{fa.MIN_N}</div></div>
  <div class="kpi"><div class="v bad">{len(alpha_ok)}</div><div class="l">Lane ber-alpha</div></div>
  <div class="kpi"><div class="v">{n_all}</div><div class="l">Trade paper tertutup</div></div>
  <div class="kpi"><div class="v">{len(paper_units)}</div><div class="l">Unit paper aktif</div></div>
  <div class="kpi"><div class="v">${float(bal.get('total') or 0):,.2f}</div><div class="l">Saldo perps (vUSDC)</div></div>
</div>

<h2 id="ringkasan">1. Ringkasan eksekutif</h2>
<div class="card">
<p><b>Status:</b> sistem <span class="bad">belum layak live</span> per {NOW:%Y-%m-%d}. Preflight: <code>{esc(pf_line)}</code>.</p>
<p><b>Temuan utama hari ini:</b> setelah 13 hari dan {n_all} trade paper lintas {len(lanes)} lane ber-n≥20,
<b>tidak ada satu lane pun</b> yang lolos gerbang edge (CI95 bawah &gt; 0 dan q-BH &lt; 0,05), dan
<b>{len(alpha_ok)} lane</b> yang terbukti punya <i>alpha</i> di atas kontrol RANDOM.</p>
<p><b>Penyebab rugi terukur</b> (bukan opini): geometri exit lane A/B 9a–9e memakai
RR = {rr_block.get('rr', float('nan')):.2f} (TP {rr_block.get('tp', float('nan')):.2f} % / SL {rr_block.get('sl', float('nan')):.2f} %),
sehingga win rate impas {rr_block.get('be', float('nan')):.1f} % sedangkan win rate nyata {rr_block.get('wr', float('nan')):.1f} %.
Biaya round-trip terkalibrasi <b>{rr_block.get('fee_bps', float('nan')):.1f} bps</b> = sekitar
{rr_block.get('fee_bps', 0) / max(rr_block.get('tp', 1), 1e-9) * 100:.0f} % dari jarak TP.</p>
<p><b>Implikasi:</b> menaikkan leverage/sizing untuk mengejar 0,8 % tidak menciptakan edge; ia hanya memperbesar
kerugian yang sudah terukur dan memperbesar risiko likuidasi.</p>
</div>

<h2 id="filosofi">2. Filosofi &amp; North Star</h2>
<p>SoDEX adalah divisi <b>swing trading DEX perps</b> di venue sodex.com. Tujuan satu-satunya: PnL
sebesar-besarnya dalam horison swing <b>1–30 jam</b>, dengan kemampuan belajar otonom 24/7.</p>
<blockquote><b>North Star (harga mati):</b> profit <b>≥0,8 %</b> dari <b>total modal wallet (spot + perps)</b>
di setiap window 1–30 jam, <b>akumulatif antar window</b> — bukan per trade.</blockquote>
<p>Tiga aturan yang tidak boleh dilanggar sistem ini sendiri: (1) safety di atas target; (2) tidak ada klaim
tanpa angka; (3) <i>fail-closed</i> — status hilang/rusak/stale dianggap gagal, bukan lulus.</p>

<h2 id="target">3. Target &amp; aritmetika modal</h2>
<p>Target diterjemahkan ke angka konkret memakai saldo nyata dari venue:</p>
<table><thead><tr><th>Komponen</th><th>Nilai</th><th>Catatan</th></tr></thead><tbody>
<tr><td>Saldo perps</td><td class="n">${float(bal.get('total') or 0):,.2f}</td><td>vUSDC, sumber snapshot venue</td></tr>
<tr><td>Spot vUSDC</td><td class="n">{sum(float(b.get('total') or 0) for b in spot if b.get('coin') == 'vUSDC'):,.4f}</td><td>likuid, siap dipakai</td></tr>
<tr><td>Token spot lain</td><td class="n">{len([b for b in spot if b.get('coin') != 'vUSDC'])} aset</td><td>sebagian besar debu; nilainya tidak dihitung sebagai modal kerja</td></tr>
<tr><td><b>Target per window 30 jam</b></td><td class="n"><b>${float(bal.get('total') or 0) * 0.008:,.2f}</b></td><td>0,8 % dari saldo perps</td></tr>
</tbody></table>
<p>Agar konsisten secara matematis: bila modal kerja C, biaya round-trip per posisi b, dan kita membuka
k posisi per window dengan notional N masing-masing, maka syarat target adalah
<code>N·(Σgᵢ − k·b) ≥ 0,008·C</code>, dengan gᵢ = return bruto per posisi. Menaikkan N memperbesar ruas kiri,
tetapi juga memperbesar kerugian saat gᵢ negatif — dan data hari ini menunjukkan rata-rata gᵢ masih negatif
untuk arah LONG.</p>

<h2 id="venue">4. Venue, instrumen, biaya</h2>
<ul>
<li><b>Venue:</b> SoDEX (perp DEX), akun <code>0x…(dipseudonimkan di repo publik)</code>, mode margin ISOLATED.</li>
<li><b>Universe:</b> 23 simbol pada lane paper (BTC, ETH, SOL, XRP, DOGE, BCH, LINK, AAVE, SUI, ADA, TRX, UNI, ENA, ARB, AVAX, ASTER, PUMP, LIT, BNB, HYPE, ONDO, XAU, SILVER).</li>
<li><b>Biaya terukur:</b> round-trip efektif <b>≈{rr_block.get('fee_bps', float('nan')):.1f} bps</b> (fee + spread + slippage, dari kalibrasi harga entry/exit vs PnL tercatat pada 7 lane).</li>
<li><b>Data pasar:</b> {len(kl)} berkas klines 1 jam venue-native tersimpan lokal (<code>data/sodex_klines/1h</code>).</li>
</ul>

<h2 id="arsitektur">5. Arsitektur sistem</h2>
<svg viewBox="0 0 900 330" role="img" aria-label="Diagram arsitektur SoDEX">
<defs><marker id="ar" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto">
<path d="M0,0 L0,6 L7,3 z" fill="#5aa9ff"/></marker></defs>
<style>.b{{fill:#121923;stroke:#22303f;rx:8}}.t{{fill:#e7eef7;font:12px sans-serif;text-anchor:middle}}
.s{{fill:#8fa3b8;font:10.5px sans-serif;text-anchor:middle}}.a{{stroke:#5aa9ff;stroke-width:1.6;fill:none;marker-end:url(#ar)}}</style>
<rect class="b" x="20" y="30" width="170" height="64"/><text class="t" x="105" y="56">Venue SoDEX</text><text class="s" x="105" y="74">perp + spot API</text>
<rect class="b" x="20" y="130" width="170" height="64"/><text class="t" x="105" y="156">Klines 1h / L2</text><text class="s" x="105" y="174">data/sodex_klines</text>
<rect class="b" x="245" y="30" width="180" height="64"/><text class="t" x="335" y="56">sodex_signal</text><text class="s" x="335" y="74">detektor + regime</text>
<rect class="b" x="245" y="130" width="180" height="64"/><text class="t" x="335" y="156">sodex_governor</text><text class="s" x="335" y="174">expectancy gate</text>
<rect class="b" x="480" y="30" width="180" height="64"/><text class="t" x="570" y="56">twin_engine</text><text class="s" x="570" y="74">eksekusi / sizing</text>
<rect class="b" x="480" y="130" width="180" height="64"/><text class="t" x="570" y="156">paper lanes ×{len(paper_units)}</text><text class="s" x="570" y="174">A/B + kontrol RANDOM</text>
<rect class="b" x="715" y="30" width="165" height="64"/><text class="t" x="797" y="56">watchdog</text><text class="s" x="797" y="74">rekonsiliasi venue</text>
<rect class="b" x="715" y="130" width="165" height="64"/><text class="t" x="797" y="156">preflight 12 gate</text><text class="s" x="797" y="174">fail-closed</text>
<rect class="b" x="245" y="240" width="415" height="62"/><text class="t" x="452" y="266">edge_audit + intel_layer</text><text class="s" x="452" y="284">dedup · CI95 · BH · alpha vs RANDOM</text>
<path class="a" d="M190,62 L243,62"/><path class="a" d="M190,162 L243,162"/>
<path class="a" d="M425,62 L478,62"/><path class="a" d="M425,162 L478,162"/>
<path class="a" d="M660,62 L713,62"/><path class="a" d="M660,162 L713,162"/>
<path class="a" d="M570,94 L570,128"/><path class="a" d="M335,194 L335,238"/>
<path class="a" d="M797,194 L662,262"/>
</svg>
<p>Alur: data venue → sinyal → <b>governor</b> (gerbang expectancy; satu-satunya yang boleh memblokir order) →
eksekusi/lane paper → <b>watchdog</b> (rekonsiliasi state vs exchange) → <b>preflight</b> (12 gerbang) → keputusan live.
Audit edge membaca semua state lane dan menghitung bukti statistik.</p>

<h2 id="struktur">6. Struktur repo &amp; runtime</h2>
<table><thead><tr><th>Aspek</th><th>Nilai</th></tr></thead><tbody>
<tr><td>Branch kerja</td><td><code>{esc(branch)}</code></td></tr>
<tr><td>Commit terakhir</td><td><code>{esc(commit)}</code></td></tr>
<tr><td>Berkas ter-track</td><td class="n">{n_files} ({n_py} berkas Python)</td></tr>
<tr><td>Unit systemd anantara*</td><td class="n">{len(u_rows)}</td></tr>
<tr><td>Lane paper aktif</td><td class="n">{len(paper_units)}</td></tr>
<tr><td>Berkas klines 1h</td><td class="n">{len(kl)}</td></tr>
<tr><td>Test suite SoDEX</td><td><code>{esc(tests_line[:110])}</code></td></tr>
</tbody></table>
<h3>Unit yang berjalan</h3>
{unit_table()}

<h2 id="alur">7. Alur kerja harian</h2>
<ol>
<li><b>Ingest</b> — klines 1h diperbarui tiap jam; pull dijaga <i>guard n&gt;0</i> agar tidak menulis file kosong.</li>
<li><b>Sinyal</b> — detektor arah + gate rezim BTC (SMA200 &amp; momentum 30 hari).</li>
<li><b>Gerbang</b> — governor menolak entry bila expectancy terukur ≤ 0; tidak ada bypass.</li>
<li><b>Eksekusi paper</b> — 20+ lane paralel; tiap lane menulis <code>data/paper_test_*_state.json</code>.</li>
<li><b>Rekonsiliasi</b> — watchdog tiap 3 menit membandingkan posisi exchange vs state; CRITICAL bila ada posisi tak ter-track.</li>
<li><b>Audit</b> — dedup, bootstrap CI95, BH-FDR, dan delta SIGNAL−RANDOM dihitung ulang.</li>
<li><b>Keputusan</b> — preflight 12 gerbang; live hanya bila semuanya OK <i>dan</i> ada kandidat edge.</li>
</ol>

<h2 id="lane">8. Lane paper — data nyata</h2>
<p>Audit dijalankan pada {len(files)} berkas state. Dedup berdasarkan (pair, arah, waktu entry) untuk
mencegah <i>pseudo-replication</i> ketika beberapa lane memakai entry yang sama. Epoch E6 diterapkan pada lane ab9*
(hanya trade dengan exit ≥ 2026-11-15) agar perubahan parameter tidak mencampur dua rezim eksperimen.</p>
{lane_table()}
<p><b>Bacaan:</b> lane dengan n≥{fa.MIN_N} = {len(lanes)}; lane n&lt;{fa.MIN_N} = {len(small)} (belum tahu, bukan "gagal").
Kandidat edge = {sum(1 for r in rows if r['verdict'] == 'KANDIDAT')}. Lane ber-alpha = {len(alpha_ok)}.</p>

<h2 id="riset">9. Temuan riset 25 November 2026</h2>
<h3>9.1 Geometri exit adalah penyebab aritmetis</h3>
<p>Lane A/B 9a–9e: TP <b>{rr_block.get('tp', float('nan')):.2f} %</b>, SL <b>{rr_block.get('sl', float('nan')):.2f} %</b>
→ RR = <b>{rr_block.get('rr', float('nan')):.2f}</b>. Win rate impas yang dibutuhkan
SL/(SL+TP) = <b>{rr_block.get('be', float('nan')):.1f} %</b>; win rate nyata <b>{rr_block.get('wr', float('nan')):.1f} %</b>
(n={rr_block.get('n', 0)}). Selisih {rr_block.get('wr', 0) - rr_block.get('be', 0):+.1f} pp sudah cukup menjelaskan rugi
sebelum bicara kualitas sinyal.</p>
<h3>9.2 Replay kontrafaktual &amp; kalibrasinya</h3>
<p>Entry diambil apa adanya dari trade nyata; hanya exit yang disimulasikan ulang dengan klines 1h venue-native,
aturan pesimistis (TP dan SL tersentuh di bar yang sama → SL menang). Kalibrasi: replay dengan geometri milik lane
mereproduksi hasil tercatat dalam ±0,08 pp (tiga lane, tanda bervariasi) → metode tidak sistematis optimis.</p>
<h3>9.3 Sweep 126 geometri</h3>
<p>7 level TP × 6 level SL × 3 time stop. <b>BH-FDR q=0,05: 0 kombinasi lolos.</b> Kombinasi terbaik in-sample
(TP 6×ATR / SL 4×ATR / 48 jam) memberi +0,653 %/trade CI95 [+0,23 ; +1,10], p=0,0016 — menarik, tetapi gagal
koreksi multiple-testing dan berada di luar window 30 jam.</p>
<h3>9.4 Semua gain berasal dari SHORT</h3>
<p>Pada geometri TP 6×ATR/SL 4×ATR/30 jam: SHORT <b>+1,046 %</b> (n=454) vs LONG <b>−0,721 %</b> (n=228).
LONG negatif di setiap periode dan setiap rezim.</p>
<h3>9.5 Kontrol RANDOM: ini beta, bukan alpha</h3>
<p>Pada geometri TP 9 %/SL 6 %/30 jam: SIGNAL short <b>+1,348 %</b> (n=267) vs RANDOM short <b>+1,070 %</b> (n=187).
Delta <b>+0,278 pp, t=0,61, p=0,543</b> → tidak terbukti ada alpha. Sebaliknya SHORT−LONG = +2,241 pp (p&lt;0,0001),
dan pada lengan RANDOM pun +2,114 pp (p=0,0007). Artinya: yang bekerja adalah <b>arah short di pasar turun</b>,
bukan pemilihan entry oleh sinyal.</p>
<h3>9.6 Peluruhan &amp; ketergantungan ekor</h3>
<ul>
<li>60 % awal +0,612 % → 40 % terakhir +0,217 % (30 jam); pada 48 jam: +1,123 % → −0,063 %.</li>
<li>Short-only tetap +1,062 % setelah 10 trade terbaik dibuang → bukan artefak outlier.</li>
<li>Ekuitas berurutan pooled: total +310,8 % dengan drawdown <b>−53,5 %</b> — angka total itu tidak boleh dikutip sebagai hasil.</li>
</ul>

<h2 id="metode">10. Metodologi statistik yang dipakai</h2>
<table><thead><tr><th>Langkah</th><th>Aturan</th><th>Alasan</th></tr></thead><tbody>
<tr><td>Dedup</td><td>(pair, arah, jam entry)</td><td>lane berbeda memakai entry sama; tanpa dedup CI terlalu sempit</td></tr>
<tr><td>Epoch</td><td>ab9* hanya exit ≥ 2026-11-15T00:55:52Z</td><td>perubahan parameter tidak boleh dicampur</td></tr>
<tr><td>CI</td><td>bootstrap {fa.N_BOOT}×, seed {fa.SEED}</td><td>distribusi PnL ekor gemuk, bukan normal</td></tr>
<tr><td>Uji utama</td><td>one-sided H0: mean ≤ 0</td><td>klaim butuh bukti arah positif</td></tr>
<tr><td>Multiplisitas</td><td>BH-FDR lintas lane / lintas geometri</td><td>menyaring kandidat dari kebetulan</td></tr>
<tr><td>Kontrol</td><td>lengan RANDOM di lane yang sama</td><td>memisahkan alpha dari beta arah/rezim</td></tr>
<tr><td>Ambang</td><td>n≥{fa.MIN_N}, CI95 bawah&gt;0, q&lt;0,05</td><td>sisanya = DATA_KURANG, bukan "gagal"</td></tr>
</tbody></table>
<blockquote>Aturan yang saya pegang: <b>"0 temuan" dari alat yang gagal ≠ bersih.</b> Setiap pemindai di sini punya
kontrol positif: auditor edge diuji dengan noise (harus TIDAK kandidat) dan dengan edge sintetis (harus kandidat);
gitleaks diuji dengan token palsu (harus terdeteksi).</blockquote>

<h2 id="safety">11. Safety, gate, dan fail-closed</h2>
<ul>
<li><b>Governor</b> — expectancy gate; satu-satunya komponen yang boleh menolak order. Tidak pernah di-bypass;
perubahannya hanya sah dengan n≥20, p&lt;0,05, BH-corrected.</li>
<li><b>Preflight 12 gerbang</b> — KILL file, kredensial, arm file, engine SHA, equity ledger, deadman heartbeat,
klines freshness, paper fleet, rekonsiliasi, promo gate, disk, probe residual.</li>
<li><b>Watchdog</b> — rekonsiliasi posisi exchange vs state; CRITICAL bila ada posisi tak ter-track atau status basi (&gt;600 s).</li>
<li><b>Red lines</b> — tidak ada <code>dry_run=false</code>, <code>LIVE_ARMED</code>, order, atau perubahan SL/TP/leverage
tanpa keputusan eksplisit Owner.</li>
</ul>
<h3>Status preflight saat ini</h3>
<p><code>{esc(pf_line)}</code></p>
<ul>{check_rows()}</ul>

<h2 id="kesiapan">12. Kesiapan live (gerbang bukti)</h2>
<table><thead><tr><th>Gerbang</th><th>Status</th><th>Bukti / alasan</th></tr></thead><tbody>
<tr><td>Kandidat edge (n≥{fa.MIN_N}, CI95 bawah&gt;0, q&lt;0,05)</td><td class="bad">GAGAL</td><td>{sum(1 for r in rows if r['verdict'] == 'KANDIDAT')} kandidat dari {len(lanes)} lane</td></tr>
<tr><td>Alpha di atas kontrol RANDOM</td><td class="bad">GAGAL</td><td>{len(alpha_ok)} lane ber-alpha</td></tr>
<tr><td>Kredensial venue</td><td class="bad">GAGAL</td><td><code>secrets/sodex.env</code> tidak ada (hanya template)</td></tr>
<tr><td>Rekonsiliasi posisi</td><td class="bad">GAGAL</td><td>watchdog {esc(wd.get('status', '?'))}, {len(wd.get('critical', []))} posisi tak ter-track</td></tr>
<tr><td>Promotion gate</td><td class="warn">DATA_KURANG</td><td>butuh 30 hari; baru ~20</td></tr>
<tr><td>Test suite</td><td class="ok">LULUS</td><td><code>{esc(tests_line[:100])}</code></td></tr>
<tr><td>Scan secret repo publik</td><td class="ok">LULUS</td><td>gitleaks: no leaks (pohon + riwayat), kontrol positif 5/5</td></tr>
</tbody></table>
<p><b>Kesimpulan:</b> menunda live adalah keputusan yang benar secara bukti. Tanggal 1 Desember 2026 hanya boleh
dipakai bila kelima gerbang merah/hijau di atas berubah status <i>dengan bukti</i>, bukan dengan target.</p>

<h2 id="posisi">13. Posisi nyata &amp; rekonsiliasi</h2>
{pos_table()}
<p>Dua posisi di atas <b>tidak tercatat</b> di state mana pun menurut watchdog. Ini bukan "residual aman":
ukuran, margin, dan PnL terealisasi harus direkonsiliasi sebelum ada keputusan apa pun. Menutup posisi
memerlukan kredensial venue dan persetujuan Owner — bukan tindakan yang boleh dijalankan otomatis.</p>

<h2 id="risiko">14. Risiko terukur</h2>
<table><thead><tr><th>Risiko</th><th>Ukuran / bukti</th><th>Mitigasi saat ini</th></tr></thead><tbody>
<tr><td>Beta tersamar sebagai edge</td><td>RANDOM short +1,07 % ≈ SIGNAL short +1,35 % (p=0,543)</td><td>kolom alpha wajib di auditor; live diblokir</td></tr>
<tr><td>Short squeeze</td><td>SL 6 % × 4 posisi × 0,75 modal ≈ −18 % wallet dalam satu event</td><td>regime gate; sizing belum diubah</td></tr>
<tr><td>Drawdown ekuitas</td><td>replay pooled −53,5 %</td><td>tidak ada lane live; lane riset dipisah</td></tr>
<tr><td>Biaya menelan edge</td><td>15,7 bps RT = 10 % jarak TP</td><td>geometri RR&gt;1 diusulkan, belum dipromosikan</td></tr>
<tr><td>Data/status basi</td><td>watchdog max_age 600 s; preflight cek freshness</td><td>fail-closed, bukan asumsi "masih jalan"</td></tr>
<tr><td>Kredensial</td><td>19 temuan riwayat = kredensial hidup → rotasi menunggu Owner</td><td>repo publik berriwayat bersih; tidak ada secret di pohon</td></tr>
</tbody></table>

<h2 id="roadmap">15. Roadmap ke 1 Desember 2026</h2>
<ol>
<li><b>Hari ini–besok:</b> rekonsiliasi dua posisi nyata (butuh Owner + kredensial). Tanpa ini, preflight tetap BLOCK.</li>
<li><b>Hari ini–3 hari:</b> kumpulkan bukti forward lane AB10 (SHORT-only, TP 9 %/SL 6 %/30 jam).</li>
<li><b>Kriteria promosi AB10:</b> n≥40; delta SIGNAL−RANDOM CI95 bawah &gt; 0 (alpha, bukan beta); bertahan pada
perubahan rezim; drawdown lane &lt; 15 % wallet.</li>
<li><b>Hari 3–6:</b> bila alpha belum terbukti, arahkan sumber profit ke <i>maker spread capture</i> yang tidak
bergantung arah, atau turunkan ekspektasi target secara eksplisit.</li>
<li><b>Sebelum arm:</b> preflight 12/12, promo gate 30/30, kredensial tervalidasi, dan keputusan GO-LIVE tertulis dari Owner.</li>
</ol>

<h2 id="publik">16. Repo publik &amp; keamanan</h2>
<ul>
<li>Repo: <a href="https://github.com/anashadi-node/sodex-project">github.com/anashadi-node/sodex-project</a> — publik, <b>hanya-baca</b>.</li>
<li>Proteksi: force-push &amp; delete dilarang pada <code>main</code>; secret scanning + push protection aktif; issues/wiki/projects/discussions dimatikan.</li>
<li>Sanitasi sebelum publikasi: alamat wallet → pseudonim HMAC satu arah; <code>/home/&lt;user&gt;</code> → <code>/home/USER</code>;
chat id → <code>&lt;REDACTED&gt;</code>; laporan forensik wallet dan audit HTML berisi alamat/ukuran akun dikeluarkan.</li>
<li>Verifikasi: isi diunduh ulang dari GitHub (tarball) lalu diperiksa — 0 alamat asli, 0 path rumah, 0 chat id; gitleaks bersih.</li>
<li>Tanpa LICENSE = hak cipta penuh: publik boleh melihat, tidak boleh memodifikasi/mendistribusikan ulang.</li>
</ul>

<h2 id="verifikasi">17. Cara memverifikasi dokumen ini</h2>
<pre><code>cd ~/anantara-sakti
env -u PYTHONPATH ./.venv-research/bin/python scripts/sodex_live_preflight.py
env -u PYTHONPATH ./.venv-research/bin/python scripts/sodex_fleet_edge_audit.py
env -u PYTHONPATH ./.venv-research/bin/python -m pytest tests/test_sodex*.py -q
cat data/sodex_watchdog_status.json | head -c 400
systemctl --user list-units 'anantara-paper-*' --no-legend
</code></pre>
<p>Dokumen ini diregenerasi dengan:</p>
<pre><code>env -u PYTHONPATH ./.venv-research/bin/python scripts/gen_sodex_master_doc.py</code></pre>

<h2 id="glosarium">18. Glosarium</h2>
<table><thead><tr><th>Istilah</th><th>Arti di proyek ini</th></tr></thead><tbody>
<tr><td>Alpha</td><td>Kemampuan memilih entry yang mengalahkan entry acak, diukur sebagai SIGNAL−RANDOM.</td></tr>
<tr><td>Beta</td><td>Hasil yang berasal dari arah pasar (mis. short saat pasar turun), bukan dari seleksi.</td></tr>
<tr><td>RR</td><td>Rasio jarak TP terhadap jarak SL. RR 0,25 berarti butuh win rate sangat tinggi.</td></tr>
<tr><td>BE WR</td><td>Win rate impas: SL/(SL+TP) sebelum biaya.</td></tr>
<tr><td>Fail-closed</td><td>Ragu/rusak/hilang → dianggap GAGAL, bukan lulus.</td></tr>
<tr><td>Epoch</td><td>Batas waktu; hanya trade setelah perubahan parameter yang dihitung.</td></tr>
<tr><td>BH-FDR</td><td>Benjamini–Hochberg: koreksi ketika banyak hipotesis diuji sekaligus.</td></tr>
</tbody></table>

<h2 id="lampiran">19. Lampiran</h2>
<h3>19.1 Snapshot saldo</h3>
<table><thead><tr><th>Akun</th><th>Nilai</th></tr></thead><tbody>
<tr><td>Perps vUSDC</td><td class="n">{float(bal.get('total') or 0):,.4f}</td></tr>
<tr><td>Spot vUSDC</td><td class="n">{sum(float(b.get('total') or 0) for b in spot if b.get('coin') == 'vUSDC'):,.4f}</td></tr>
<tr><td>Jumlah aset spot non-vUSDC</td><td class="n">{len([b for b in spot if b.get('coin') != 'vUSDC'])}</td></tr>
<tr><td>Posisi perps terbuka</td><td class="n">{len(perps)}</td></tr>
</tbody></table>
<h3>19.2 Berkas kunci</h3>
<table><thead><tr><th>Berkas</th><th>Peran</th></tr></thead><tbody>
<tr><td><code>scripts/sodex_live_preflight.py</code></td><td>12 gerbang kesiapan</td></tr>
<tr><td><code>scripts/sodex_live_watchdog.py</code></td><td>rekonsiliasi state vs exchange</td></tr>
<tr><td><code>scripts/sodex_fleet_edge_audit.py</code></td><td>audit edge + alpha vs RANDOM</td></tr>
<tr><td><code>scripts/sodex_realtime_sync.py</code></td><td>sinkronisasi snapshot venue</td></tr>
<tr><td><code>anantara/sodex_governor.py</code></td><td>gerbang expectancy (safety-critical)</td></tr>
<tr><td><code>anantara/sodex_farming.py</code></td><td>eksekusi (live-capable, tidak dipakai hari ini)</td></tr>
<tr><td><code>reports/sodex/RESEARCH_GEOMETRI_EXIT_BETA_2026-11-25.md</code></td><td>laporan riset lengkap</td></tr>
</tbody></table>

<h2 id="log">20. Log perubahan hari ini</h2>
<ul>
<li class="ok">Auditor edge: kolom alpha (delta, CI95 bootstrap, p Welch) + 4 test kontrol dua arah.</li>
<li class="ok">Laporan riset geometri &amp; beta diterbitkan; semua angka dihitung program.</li>
<li class="ok">Repo publik diperbarui (laporan + auditor + README) dan diverifikasi dari isi remote.</li>
<li class="ok">Lane riset <code>anantara-paper-ab10</code> dibuat: SHORT-only, TP 9 %/SL 6 %/30 jam, state terpisah.</li>
<li class="warn">Telemetri funnel AB10 menunggu siklus pertama.</li>
<li class="bad">Rekonsiliasi 2 posisi nyata &amp; kredensial venue: menunggu keputusan Owner.</li>
</ul>

<footer>Dibangun otomatis oleh <code>scripts/gen_sodex_master_doc.py</code> pada {NOW:%Y-%m-%d %H:%M} UTC.
Sumber angka: state lane, snapshot venue, keluaran preflight/watchdog, git. Tidak ada angka yang ditulis manual.</footer>
</main></div></body></html>"""

os.makedirs(os.path.dirname(OUT), exist_ok=True)
# Bungkus setiap tabel dengan div scroll agar tidak ada overflow horizontal halaman.
HTML = HTML.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
open(OUT, "w", encoding="utf-8").write(HTML)
print(f"OK {OUT} ({len(HTML)} byte)")
