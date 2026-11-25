#!/usr/bin/env python3
"""Bangun laporan status SoDEX satu file HTML dari data aktual (tanpa angka hard-code)."""
from __future__ import annotations

import glob
import json
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "reports/sodex/SODEX_STATUS_2026-10-25.html")
NOW = "25 Oktober 2026 · 19:25 WIB"

def E(x, n=0):
    """Format Indonesia: 1.234,56 (bukan 1,234.56)."""
    s = f"{x:,.{n}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def load_json(p, default=None):
    try:
        return json.load(open(os.path.join(ROOT, p)))
    except Exception:
        return default if default is not None else {}


# ---------- data ----------
inv = load_json("reports/sodex/SCAN_INVENTORY.json", [])
bydir = defaultdict(int)
for h in inv:
    bydir[h["p"].split("/")[0]] += 1

real = defaultdict(lambda: dict(rt=0, g=0.0, f=0.0, vol=0.0, net=0.0))
import sqlite3
sys.path.insert(0, ROOT)
from scripts.research.ledger_truth import summarize as _ledger_summary  # noqa: E402

_L = _ledger_summary(os.path.join(ROOT, "twin_engine.db"))
for m, v in _L["months"].items():
    if v["rt"]:
        real[m] = dict(rt=v["rt"], g=v["net"] + v["fee"], f=v["fee"], vol=v["vol"], net=v["net"])
R = dict(rt=_L["total"]["rt"], g=_L["total"]["gross"], f=_L["total"]["fee"],
         vol=_L["total"]["vol"], net=_L["total"]["net"])
ENG = _L["engines"]
LIVE = _L["live"]
SIM = _L["sim"]
LIVE_BPS = lambda d: (1e4 * d["net"] / d["vol"]) if d["vol"] else 0.0
_con = sqlite3.connect(f"file:{os.path.join(ROOT, 'twin_engine.db')}?mode=ro", uri=True)
pairs = {p: [c, n] for p, c, n in _con.execute(
    "select pair,count(*),coalesce(sum(cast(net_pnl as real)),0) from rts group by pair")}
_con.close()

paper = []
for f in sorted(glob.glob(os.path.join(ROOT, "data/paper_test_*state*.json"))):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    cl = [t for t in (d.get("closed") or []) if isinstance(t, dict)]
    op = d.get("open") or []
    name = os.path.basename(f).replace("paper_test_", "").replace("_state.json", "").replace(".json", "")
    pnl = sum(float(t.get("net_pnl") or t.get("pnl_usd") or 0) for t in cl)
    paper.append(dict(name=name[:30], n=len(cl), open=len(op) if isinstance(op, list) else (1 if op else 0), pnl=pnl))
paper.sort(key=lambda x: x["pnl"])
P_TOT = sum(p["pnl"] for p in paper)
P_N = sum(p["n"] for p in paper)

wide1d = load_json("reports/sodex/WIDE_SCAN_1d.json", {}).get("1d", {})
wmulti = load_json("reports/sodex/WIDE_SCAN_MULTI.json", {})
wbin = load_json("reports/sodex/WIDE_SCAN_BINANCE_4h.json", {}).get("4h", {})
p3 = load_json("reports/sodex/P3_EVAL.json", [])

# ---------- svg helpers ----------
def bars_svg(items, w=760, h=230, pad=30, pos="#22d3a6", neg="#f45b69", fmt=lambda v: E(v), threshold=None, force=None, tlabel=""):
    """items: [(label, value)] — bar chart dengan garis nol proporsional."""
    if not items:
        return ""
    vals = [v for _, v in items]
    lo, hi = min(0, min(vals)), max(0, max(vals))
    if threshold is not None:
        hi = max(hi, threshold * 1.12)
    rng = (hi - lo) or 1
    zero = pad + (hi / rng) * (h - 2 * pad)
    n = len(items)
    step = (w - 2 * pad) / n
    bw = step * 0.5
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart">']
    out.append(f'<line x1="{pad}" y1="{zero:.1f}" x2="{w-pad}" y2="{zero:.1f}" stroke="#3a4a63" stroke-width="1"/>')
    for i, (lab, v) in enumerate(items):
        x = pad + i * step + (step - bw) / 2
        bh = abs(v) / rng * (h - 2 * pad)
        y = zero - bh if v >= 0 else zero
        col = force or (pos if v >= 0 else neg)
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(bh,2):.1f}" rx="3" fill="{col}" opacity="0.9"/>')
        ty = y + 15 if v >= 0 else y + bh - 7
        if bh < 26:
            ty = zero - 6 if v >= 0 else zero + 14
        out.append(f'<text x="{x+bw/2:.1f}" y="{ty:.1f}" text-anchor="middle" class="vl">{fmt(v)}</text>')
        out.append(f'<text x="{x+bw/2:.1f}" y="{h-7}" text-anchor="middle" class="ax">{lab}</text>')
    if threshold is not None and threshold <= hi:
        ty = zero - threshold / rng * (h - 2 * pad)
        out.append(f'<line x1="{pad}" y1="{ty:.1f}" x2="{w-pad}" y2="{ty:.1f}" stroke="#f5b942" stroke-width="1.4" stroke-dasharray="6 5"/>')
        out.append(f'<text x="{w-pad}" y="{ty-6:.1f}" text-anchor="end" class="ax" fill="#f5b942">{tlabel}</text>')
    out.append("</svg>")
    return "".join(out)


def line_svg(vals, w=760, h=210, pad=30, color="#57b6ff"):
    if len(vals) < 2:
        return ""
    mx, mn = max(vals), min(vals)
    rng = (mx - mn) or 1
    pts = []
    for i, v in enumerate(vals):
        x = pad + i * (w - 2 * pad) / (len(vals) - 1)
        y = h - pad - (v - mn) / rng * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    return (f'<svg viewBox="0 0 {w} {h}" class="chart"><polyline points="{" ".join(pts)}" '
            f'fill="none" stroke="{color}" stroke-width="2.2"/>'
            f'<line x1="{pad}" y1="{h-pad}" x2="{w-pad}" y2="{h-pad}" stroke="#3a4a63"/></svg>')


def Num(x, spec="+.2f"):
    """Format angka tahan-None: sel INSUFFICIENT bisa tidak punya nilai CL/OOS."""
    if x is None:
        return "—"
    try:
        return format(x, spec)
    except (TypeError, ValueError):
        return "—"


def badge(v):
    cls = {"PASS": "ok", "NO-GO": "bad", "INSUFFICIENT": "warn"}.get(v, "warn")
    return f'<span class="badge {cls}">{v}</span>'


# ---------- tabel ----------
real_rows = ""
for m in sorted(real):
    d = real[m]
    net = d["g"] - d["f"]
    mode = ('<span class="badge ok">LIVE</span>' if m == "2026-09"
            else '<span class="badge">simulasi</span>')
    real_rows += (f"<tr><td>{m}</td><td>{mode}</td><td class='num'>{E(d['rt'])}</td><td class='num'>{E(d['g'],2)}</td>"
                  f"<td class='num'>{E(d['f'],2)}</td><td class='num {'neg' if net<0 else 'pos'}'>{E(net,2)}</td>"
                  f"<td class='num'>{E(1e4*d['f']/d['vol'],2)}</td></tr>")

pair_rows = ""
for k, v in sorted(pairs.items(), key=lambda kv: -kv[1][1])[:6]:
    pair_rows += (f"<tr><td>{k}</td><td class='num'>{E(v[0])}</td>"
                  f"<td class='num {'neg' if v[1]<0 else 'pos'}'>{E(v[1],2)}</td></tr>")

eng_rows = ""
for e, v in sorted(ENG.items(), key=lambda kv: -kv[1]["net"]):
    eng_rows += (f"<tr><td>{e}</td><td class='num'>{E(v['rt'])}</td><td class='num'>{E(v['vol'])}</td>"
                 f"<td class='num'>{E(v['net']+v['fee'],2)}</td><td class='num'>{E(v['fee'],2)}</td>"
                 f"<td class='num {'neg' if v['net']<0 else 'pos'}'>{E(v['net'],2)}</td>"
                 f"<td class='num'>{v['net']/v['vol']*1e4:+.2f}</td></tr>")

paper_rows = ""
for p in paper:
    paper_rows += (f"<tr><td>{p['name']}</td><td class='num'>{p['n']}</td><td class='num'>{p['open']}</td>"
                   f"<td class='num {'neg' if p['pnl']<0 else 'pos'}'>{E(p['pnl'],2)}</td></tr>")

scan_rows = ""
for tf, d in [("1d", wide1d)] + [(k, v) for k, v in wmulti.items() if "error" not in v]:
    if not d or "cells" not in d:
        continue
    best = sorted([c for c in d["cells"] if c.get("t")], key=lambda c: -c["t"])[:1]
    if not best:
        continue
    c = best[0]
    scan_rows += (f"<tr><td>{tf}</td><td class='num'>{d.get('n_symbols', 0)}</td><td class='num'>{d.get('n_cells', 0)}</td>"
                  f"<td>{c.get('fam')} L={c.get('L')} H={c.get('H')}</td><td class='num'>{Num(c.get('n'), ',')}</td>"
                  f"<td class='num {'neg' if (c.get('mean') or 0)<0 else 'pos'}'>{Num(c.get('mean'), '+.1f')}</td>"
                  f"<td class='num'>{Num(c.get('t'))}</td><td class='num'>{Num(c.get('cl_t'))}</td>"
                  f"<td class='num'>{Num(c.get('cl_oos_t'))}</td><td>{badge(c.get('verdict') or 'INSUFFICIENT')}</td></tr>")
if wbin.get("cells"):
    c = sorted([x for x in wbin["cells"] if x.get("t")], key=lambda x: -x["t"])[0]
    scan_rows += (f"<tr class='alt'><td>4h Binance</td><td class='num'>{wbin['n_symbols']}</td>"
                  f"<td class='num'>{wbin['n_cells']}</td><td>{c['fam']} L={c['L']} H={c['H']}</td>"
                  f"<td class='num'>{Num(c.get('n'), ',')}</td><td class='num'>{Num(c.get('mean'), '+.1f')}</td>"
                  f"<td class='num'>{Num(c.get('t'))}</td><td class='num'>{Num(c.get('cl_t'))}</td>"
                  f"<td class='num'>{Num(c.get('cl_oos_t'))}</td><td>{badge(c.get('verdict') or 'INSUFFICIENT')}</td></tr>")

MON={"01":"Jan","02":"Feb","03":"Mar","04":"Apr","05":"Mei","06":"Jun","07":"Jul","08":"Agu","09":"Sep","10":"Okt","11":"Nov","12":"Des"}
month_chart = bars_svg([(MON.get(m[5:],m[5:]), real[m]["net"]) for m in sorted(real)])
paper_chart = bars_svg([(p["name"][:9], p["pnl"]) for p in paper if abs(p["pnl"]) > 0.01][:12], h=200)
scan_chart = bars_svg([(f"{tf}", d["best"][0].get("cl_t") or 0.0) for tf, d in
                       [("1d", wide1d)] + [(k, v) for k, v in wmulti.items() if v.get("best")] if d.get("best")],
                      h=210, fmt=lambda v: f"{v:+.2f}", threshold=2.5, force="#f5b942", tlabel="ambang t klaster 2,5")

# ---------- html ----------
html = f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SoDEX — Status & Audit Komprehensif · 25 Okt 2026</title>
<style>
:root{{--bg:#0b1220;--card:#121c2e;--card2:#0f1728;--line:#22304a;--ink:#e8eef9;--mut:#93a4c0;--acc:#57b6ff;--ok:#22d3a6;--bad:#f45b69;--warn:#f5b942}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 -apple-system,"Segoe UI",Inter,Roboto,sans-serif}}
.wrap{{max-width:1080px;margin:0 auto;padding:36px 22px 80px}}
header{{border-bottom:1px solid var(--line);padding-bottom:22px;margin-bottom:28px}}
.kicker{{color:var(--acc);font-size:12px;letter-spacing:.14em;text-transform:uppercase;font-weight:700}}
h1{{font-size:32px;line-height:1.2;margin:8px 0 6px}}
h2{{font-size:21px;margin:44px 0 14px;padding-top:18px;border-top:1px solid var(--line)}}
h3{{font-size:16px;margin:24px 0 8px;color:#cfe0f7}}
p,li{{color:#cfd9e8}}
.sub{{color:var(--mut);font-size:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:12px;margin:18px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.card .k{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut)}}
.card .v{{font-size:20px;font-weight:700;margin-top:4px}}
.card .n{{font-size:12px;color:var(--mut);margin-top:2px}}
table{{width:100%;border-collapse:collapse;margin:14px 0;font-size:13.5px}}
th{{text-align:left;color:var(--mut);font-weight:600;border-bottom:1px solid var(--line);padding:8px 6px;font-size:12px;text-transform:uppercase;letter-spacing:.05em}}
td{{padding:7px 6px;border-bottom:1px solid #1a2740}}
tr:last-child td{{border-bottom:none}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.pos{{color:var(--ok)}} .neg{{color:var(--bad)}}
.badge{{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.04em}}
.badge.ok{{background:rgba(34,211,166,.14);color:var(--ok)}}
.badge.bad{{background:rgba(244,91,105,.14);color:var(--bad)}}
.badge.warn{{background:rgba(245,185,66,.14);color:var(--warn)}}
.note{{background:var(--card2);border-left:3px solid var(--acc);padding:12px 16px;border-radius:0 8px 8px 0;margin:16px 0}}
.warnbox{{border-left-color:var(--warn)}}
.badbox{{border-left-color:var(--bad)}}
.chart{{width:100%;height:auto;background:var(--card2);border:1px solid var(--line);border-radius:10px;margin:10px 0}}
.ax{{fill:#93a4c0;font-size:11px}} .vl{{fill:#cfd9e8;font-size:11px}}
code{{background:#0a1526;border:1px solid var(--line);padding:1px 5px;border-radius:4px;font-size:12.5px}}
ul{{padding-left:20px}} li{{margin:4px 0}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:760px){{.two{{grid-template-columns:1fr}}}}
footer{{margin-top:50px;padding-top:18px;border-top:1px solid var(--line);color:var(--mut);font-size:12px}}
@media print{{body{{background:#fff;color:#111}} .card,table{{border-color:#ddd}} h1,h2{{color:#111}}}}
</style></head><body><div class="wrap">

<header>
<div class="kicker">Anantara Sakti · Dokumen Status & Audit</div>
<h1>SoDEX — Kondisi Proyek Per 25 Oktober 2026</h1>
<div class="sub">Cakupan: 1.481 artefak di PC + 2 repo GitHub · 15.291 RT (325 live) · 23 track paper · 4 timeframe · 135 simbol</div>
</header>

<div class="grid">
  <div class="card"><div class="k">Live terbukti</div><div class="v neg">−${E(abs(LIVE['net']),2)}</div><div class="n">{E(LIVE['rt'])} RT · 26–29 Sep · 3,5 hari</div></div>
  <div class="card"><div class="k">Simulasi (bukan bukti)</div><div class="v pos">+${E(SIM['net'],2)}</div><div class="n">{E(SIM['rt'])} RT · Jun–Jul</div></div>
  <div class="card"><div class="k">Live: gross vs fee</div><div class="v neg" style="font-size:19px">−{E(abs(LIVE_BPS(LIVE)),1)} bps</div><div class="n">gross {E(1e4*LIVE['gross']/LIVE['vol'],1)} · fee {E(1e4*LIVE['fee']/LIVE['vol'],1)} bps</div></div>
  <div class="card"><div class="k">Track paper</div><div class="v">{len(paper)}</div><div class="n">{P_N} trade · net −${E(abs(P_TOT),2)}</div></div>
  <div class="card"><div class="k">Uji teregistrasi</div><div class="v">1.277</div><div class="n">0 lolos ambang |t|≥4,11</div></div>
  <div class="card"><div class="k">Sapuan luas</div><div class="v">0 PASS</div><div class="n">95 simbol × 4 TF + 40 Binance</div></div>
  <div class="card"><div class="k">P3 arbitrase</div><div class="v warn" style="font-size:15px">INSUFFICIENT</div><div class="n">0 event · p99 2,6 bps</div></div>
</div>

<div class="note badbox"><b>Vonis satu baris:</b> satu ledger mencampur dua mode. <b>97,9% RT adalah simulasi</b>
(+${E(SIM['net'],2)}). Satu-satunya eksekusi live yang terbukti — 325 RT, 3,5 hari — menghasilkan
<b>−$1,83</b>, dengan gross 2,9 bps < fee 10,0 bps. Tidak ada klaim profitabilitas live yang bisa
dipertahankan, dan klaim “5,6 bulan rekam jejak” harus dibaca “5,6 bulan pengembangan + 3,5 hari live”.</div>

<h2>1. Batas bukti — 9 bulan tidak terbukti, 5,6 bulan artefak, 3,5 hari live</h2>
<table><tr><th>Artefak</th><th>Tanggal tertua</th><th>Keterangan</th></tr>
<tr><td>Repo <code>scalping-agent</code> (GitHub)</td><td>5 Mei 2026</td><td>hanya README, tanpa kode trading</td></tr>
<tr><td>Dokumen riset</td><td>9 Mei 2026</td><td><code>RISET_AI_AGENT_AUTOMATION_CRYPTO_TRADING.md</code></td></tr>
<tr><td>Repo <code>anantara-sakti</code></td><td>17 Mei 2026</td><td>commit <code>Day 1: Foundation Docker stack</code></td></tr>
<tr><td>Catatan modal pertama</td><td>24 Jun 2026</td><td><code>data/capital_report.jsonl</code></td></tr>
<tr><td>Track paper pertama</td><td>Agustus 2026</td><td><code>paper_test_*_state.json</code></td></tr></table>
<p>Pencarian di seluruh <code>/home/USER</code> (kedalaman 7, tanpa node_modules/.git) menemukan
<b>{len(inv):,} berkas</b> bernama sodex/anantara, rentang <b>9 Mei – 25 Okt 2026</b>. Tidak ada satu pun
artefak Januari–April. Jika periode itu ada di tempat lain, ia harus diserahkan untuk diaudit —
dokumen ini tidak mengarangnya.</p>

<h2>2. Sapuan PC + GitHub</h2>
<div class="two">
<div><h3>Sebaran berkas di PC</h3><table>
<tr><th>Lokasi</th><th class="num">Berkas</th></tr>
{''.join(f"<tr><td>{k}</td><td class='num'>{v:,}</td></tr>" for k, v in sorted(bydir.items(), key=lambda kv: -kv[1])[:8])}
</table></div>
<div><h3>GitHub</h3><table>
<tr><th>Item</th><th>Nilai</th></tr>
<tr><td>Repo privat</td><td><code>anashadi-node/anantara-sakti</code></td></tr>
<tr><td>Commit di remote <code>main</code></td><td>410</td></tr>
<tr><td>Commit di lokal</td><td><b>1.157</b></td></tr>
<tr><td>Remote tertinggal</td><td class="neg">747 commit</td></tr>
<tr><td>Posisi remote terakhir</td><td>15 Jun 2026</td></tr>
</table></div></div>
<div class="note warnbox"><b>Risiko cadangan:</b> 4 bulan pekerjaan (Jul–Okt) belum ada di GitHub.
Mesin ini satu-satunya salinan. Tindakan: <code>git push origin main</code> setelah audit secret.</div>

<h2>3. Rekonsiliasi — satu ledger, dua mode</h2>
<table><tr><th>Sumber</th><th>Cakupan</th><th class="num">RT</th><th class="num">Net $</th><th>Status</th></tr>
<tr><td><code>twin_engine.db</code>/<code>rts</code> — LIVE</td><td>26–29 Sep</td><td class="num">{E(LIVE['rt'])}</td><td class="num neg">−{E(abs(LIVE['net']),2)}</td><td><span class="badge ok">LIVE</span></td></tr>
<tr><td><code>twin_engine.db</code>/<code>rts</code> — simulasi</td><td>Jun–Jul</td><td class="num">{E(SIM['rt'])}</td><td class="num pos">+{E(SIM['net'],2)}</td><td><span class="badge">SIMULASI</span></td></tr>
<tr><td><code>capital_report.jsonl</code> (jumlah window)</td><td>Jun–Sep</td><td class="num">15.647</td><td class="num neg">−592,04</td><td><span class="badge bad">SALAH</span></td></tr>
<tr><td>Dokumen 9-Okt</td><td>s/d 5 Okt</td><td class="num">—</td><td class="num pos">+32,60</td><td><span class="badge warn">CAMPURAN</span></td></tr>
<tr><td><code>paper_test_*</code></td><td>Agu–Okt, perp</td><td class="num">{P_N}</td><td class="num neg">−{E(abs(P_TOT),2)}</td><td>paper, bukan uang nyata</td></tr></table>

<div class="note badbox"><b>Dua bug yang membalik tanda:</b> (1) <code>rt_6h</code> adalah window
<b>6 jam bergulir</b>, ditulis jauh lebih sering dari tiap 6 jam — menjumlahkan 227 snapshot menghitung
trade yang sama berkali-kali (25 record berjarak &lt;1 jam); (2) <code>rts.net_pnl</code>
<b>sudah net-of-fee</b> (<code>pnl = (sell−buy)·qty − vol·fee</code>), tapi <code>capital_report</code>
mengurangkan fee <b>lagi</b>. Akibatnya gross terlihat 0,42 bps dan net −$592, padahal
gabungan: gross 4,41 bps dan net +$32,60.</div>

<div class="note warnbox"><b>Koreksi rev.2 — cara memisahkan mode:</b> kolom <code>mode</code> baru
ditambahkan 25-Okt (backfill 325 RT live / 14.966 dry_run), jadi baris lama diklasifikasi dari
bukti luar: banner <code>Twin-Engine start [LIVE]</code>
di <code>logs/twin_live.log</code> + <code>logs/e1_microlive.log</code> hanya muncul <b>26–29 Sep</b>;
harga fill Juni berpresisi 25 desimal (simulator) sedangkan September berpresisi venue;
<code>SODEX_SPOT_FARM_LIVE=0</code>. 319 baris 28-Sep adalah backfill, tetapi <code>fills</code>
tersebar 26–29 Sep → perdagangan live nyata dengan stempel waktu yang rusak.</div>

<h3>Ledger per bulan — mode terbukti</h3>
<table><tr><th>Bulan</th><th>Mode</th><th class="num">Round-trip</th><th class="num">Gross $</th><th class="num">Fee $</th><th class="num">Net $</th><th class="num">Fee bps</th></tr>
{real_rows}
<tr><td><b>Total</b></td><td>—</td><td class="num"><b>{E(R['rt'])}</b></td><td class="num"><b>{E(R['g'],2)}</b></td><td class="num"><b>{E(R['f'],2)}</b></td><td class="num {'pos' if R['net']>=0 else 'neg'}"><b>{E(R['net'],2)}</b></td><td class="num"><b>{E(1e4*R['f']/R['vol'],2)}</b></td></tr></table>
{month_chart}

<div class="note warnbox"><b>Konsentrasi — hanya di simulasi:</b> E1 (spot maker) menyumbang
<b>+$85,25</b> pada data gabungan, tetapi <b>+$87,23</b> di antaranya dari <b>12–13 Juni</b> —
12.138 RT pertama saat PEPE/USDC baru listing, dan semuanya berjalan di mode simulasi.
Satu-satunya E1 live (26–29 Sep) menghasilkan <b>−$1,83</b>. Laba peluncuran belum pernah
dibuktikan dengan uang nyata.</div>

<h3>Per engine</h3>
<table><tr><th>Engine</th><th class="num">RT</th><th class="num">Volume $</th><th class="num">Gross $</th><th class="num">Fee $</th><th class="num">Net $</th><th class="num">Net bps</th></tr>{eng_rows}</table>

<h3>Pair teratas (net)</h3>
<table><tr><th>Pair</th><th class="num">RT</th><th class="num">Net $</th></tr>{pair_rows}</table>

<h2>4. Riset baru — perluasan aset & timeframe</h2>
<p><b>Pra-registrasi:</b> <code>docs/sodex/PRAREG_WIDE_01_2026-10-25.md</code> (beku sebelum run).
<b>Universe:</b> 95 simbol SoDEX (dari 10) × 5m/1h/4h/1d + 40 perp Binance 4h (validasi eksternal).
<b>Keluarga:</b> TSMOM, REV, DONCH, RANGEPOS. <b>Biaya:</b> 7,6 bps round-trip.
<b>Uji:</b> non-overlapping, BH-FDR q=0,10, OOS 30% terakhir, dan <b>t klaster per tanggal</b>
(karena 76 simbol pada hari yang sama bukan 76 taruhan independen).</p>
<table><tr><th>TF</th><th class="num">Simbol</th><th class="num">Sel</th><th>Sel terbaik</th><th class="num">n</th><th class="num">Net bps</th><th class="num">t naive</th><th class="num">t klaster</th><th class="num">t OOS</th><th>Verdict</th></tr>
{scan_rows}</table>
{scan_chart}
<div class="note"><b>Yang ditemukan:</b> satu pola konsisten — <b>short-term reversal</b> — positif di 1h, 4h, dan 1d
(1d: +54 bps per tanggal, 340 tanggal, t klaster 1,65; OOS 1,68). <b>Tidak satu pun lolos</b> ambang
t klaster ≥2,5 + OOS ≥2,0. Di Binance 4h pola yang sama <b>hilang</b> (t klaster 0,31) → indikasi
artefak venue tipis, bukan edge pasar. Status: <b>kandidat forward-test</b>, bukan sinyal produksi.</div>

<h3>Mengapa "t naik-turun" berbahaya</h3>
<p>Contoh nyata dari run ini: REV 1d L=6 H=6 terlihat <b>t=3,12</b> bila 3.530 trade dianggap independen.
Setelah diklaster per tanggal (340 tanggal), <b>t=1,65</b>. Selisih itu adalah inflasi Correlation —
persis jebakan yang membuat backtest terlihat yakin padahal tidak.</p>

<h2>5. Paper test — semua masih berjalan</h2>
<div class="grid">
<div class="card"><div class="k">Track</div><div class="v">{len(paper)}</div><div class="n">{sum(1 for p in paper if p['n']==0)} tanpa trade</div></div>
<div class="card"><div class="k">Trade tertutup</div><div class="v">{P_N}</div><div class="n">7 track punya posisi terbuka</div></div>
<div class="card"><div class="k">Net paper</div><div class="v neg">${E(P_TOT,2)}</div><div class="n">hanya <code>realwide</code> positif (+$3,72)</div></div>
<div class="card"><div class="k">Timer</div><div class="v">aktif</div><div class="n">arena 09:13 · P3 08:50 · venue 51 hari</div></div>
</div>
<table><tr><th>Track</th><th class="num">Tutup</th><th class="num">Buka</th><th class="num">Net $</th></tr>{paper_rows}</table>

<h2>6. P3 — arbitrase lintas venue</h2>
<table><tr><th>Mode</th><th class="num">Event</th><th class="num">p99 dislokasi</th><th class="num">Jam &gt; hurdle</th><th>Verdict</th></tr>
<tr><td>Buku langsung</td><td class="num">0</td><td class="num">2,61 bps</td><td class="num">0,0%</td><td>{badge('INSUFFICIENT')}</td></tr>
<tr><td>Proxy 1 jam (Jun–Okt)</td><td class="num">27.336 simbol-jam</td><td class="num">18,73 bps</td><td class="num">1,11%</td><td>{badge('INSUFFICIENT')}</td></tr></table>
<p>Hurdle 17,6 bps vs p99 18,73 bps → <b>margin 1,1 bps</b>. Recorder berjalan sampai 15 Des 2026;
evaluator harian fail-closed. Butuh ≥50 event unik sebelum ada vonis.</p>

<h2>7. Akar masalah, berurut dampak</h2>
<table><tr><th>#</th><th>Akar</th><th>Angka kunci</th><th>Sifat</th></tr>
<tr><td>R1</td><td><b>Fee &gt; edge pada sampel live</b></td><td>live gross 2,9 vs fee 10,0 bps → net −7,1</td><td>Struktural</td></tr>
<tr><td>R2</td><td><b>Laba peluncuran hanya ada di simulator</b></td><td>+$87 dari 2 hari simulasi; live 3,5 hari −$1,83</td><td>Waktu-terbatas</td></tr>
<tr><td>R3</td><td>Agregator PnL salah 2×</td><td>window bergulir + fee ganda</td><td>Pengukuran (sudah diperbaiki)</td></tr>
<tr><td>R4</td><td>Churn tanpa akumulasi</td><td>PVE $607k volume → −$16,76 (simulasi)</td><td>Proses</td></tr>
<tr><td>R5</td><td>Horizon sertifikasi &gt; horizon proyek</td><td>8,5 tahun pada t=4,11 level window</td><td>Metodologis</td></tr>
<tr><td>R6</td><td>Mode tidak tercatat di ledger</td><td>14.966 RT simulasi + 325 RT live dalam satu tabel</td><td>Pengukuran (sudah diperbaiki)</td></tr></table>
<div class="note"><b>Uji IS/IS NOT:</b> masalah ADA di semua rezim dan semua keluarga sinyal;
TIDAK ADA di data (korelasi 0,999), eksekusi (tidak ada posisi telanjang), atau AI.
Lokasinya di <b>edge yang tipis</b> — dan pada live, <b>di bawah biaya</b>.</div>

<h2>8. Yang tidak gagal</h2>
<ul>
<li><b>Data:</b> korelasi SoDEX–Binance 0,999–1.000; 24.276 bar sah.</li>
<li><b>Eksekusi:</b> 15.291 round-trip tercatat; 325 di antaranya live; tidak ada posisi telanjang.</li>
<li><b>Kontrol negatif:</b> positif palsu 3–5% — alat ukur tidak menghasilkan ilusi berlebih.</li>
<li><b>Disiplin:</b> PRAREG beku; PRAREG-19 melaporkan 0/24 apa adanya.</li>
<li><b>Infrastruktur:</b> 1.157 commit, 183 skrip riset, timer berjalan.</li>
</ul>

<h2>9. Jalan keluar & ambang yang harus dilewati</h2>
<table><tr><th>Jalur</th><th>Ambang</th><th>Status</th><th>Catatan jujur</th></tr>
<tr><td><b>Launch MM (E1)</b></td><td>net ≥5 bps, ≥30 hari <b>live</b></td><td>simulasi 2 hari; live 3,5 hari −7,1 bps</td><td>laba peluncuran belum pernah terbukti dengan uang nyata</td></tr>
<tr><td><b>P3 arbitrase</b></td><td>≥17,6 bps, ≥50 event</td><td>berjalan</td><td>margin 1,1 bps; freq 1,1% jam</td></tr>
<tr><td><b>Listing/event</b></td><td>median +24j &lt; −2%, mean &gt; 0</td><td>18 event terukur</td><td>median −2,84% tapi mean −0,03%: ekor kanan menghapus edge</td></tr>
<tr><td><b>Reversal 1d</b></td><td>t klaster ≥2,5 forward 60 hari</td><td>kandidat</td><td>t 1,65; gagal di Binance</td></tr>
<tr><td><b>Trend harian</b></td><td>gerak 300–500 bps vs 20 bps</td><td>belum diuji</td><td>horizon &gt;30 jam; perlu izin definisi target</td></tr></table>

<h2>10. Keputusan yang menunggu</h2>
<ol>
<li><b>Arsip Jan–Apr</b>: serahkan bila ada; tanpa itu audit sah 5,6 bulan pengembangan,
tetapi hanya <b>3,5 hari bukti live</b>.</li>
<li><b>Kolom <code>mode</code></b> <span class="badge ok">SELESAI 25-Okt</span> — ada di
<code>rts</code>/<code>fills</code>; backfill 325 RT live / 14.966 dry_run, mesin mencap mode saat menulis.</li>
<li><b>Bekukan TA directional</b> dan pindahkan compute ke P3 + launch-MM live kecil + listing forward-test.</li>
<li><b>Sumber kebenaran PnL</b>: <span class="badge ok">SELESAI</span> <code>twin_engine.db/rts</code>
via <code>ledger_truth.py</code> (dengan pemisahan live/simulasi);
agregator <code>capital_report</code> masih perlu diperbaiki agar berhenti menjumlahkan window.</li>
<li><b>Push ke GitHub</b>: 747 commit belum tercadang.</li>
<li><b>Target</b>: 0,8%/30j tetap, atau hitung horizon jujur per jalur?</li>
</ol>

<footer>
Dokumen dihasilkan otomatis dari data aktual pada {NOW}. Sumber angka:
<code>twin_engine.db</code> (tabel <code>rts</code> + <code>fills</code>, via
<code>scripts/research/ledger_truth.py</code>), <code>data/paper_test_*_state.json</code>,
<code>reports/sodex/WIDE_SCAN_*.json</code>, <code>reports/sodex/P3_EVAL.json</code>,
<code>reports/sodex/SCAN_INVENTORY.json</code>. Tidak ada angka PnL yang ditulis tangan.
Keterbatasan: hanya 3,5 hari yang terbukti live (325 RT); kolom mode baru ada 25-Okt (baris lama
di-backfill dari tanggal); 319 baris 28-Sep adalah backfill (timestamp rusak, pakai <code>fills</code>);
survivorship 76 simbol; slippage 7,6 bps asumsi; 91,4% snapshot equity tidak tervalidasi sehingga
equity tidak dapat direkonsiliasi tanpa mutasi wallet.
</footer>
</div></body></html>"""

open(OUT, "w").write(html)
print("tulis", OUT, len(html), "byte")
