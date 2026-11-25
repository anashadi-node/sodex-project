#!/usr/bin/env python3
"""Generate self-contained sodex_dashboard.html (data inline, no fetch)."""
import json, os, glob
from datetime import datetime, timezone, timedelta

PROJECT = os.path.expanduser('~/anantara-sakti')
DATA = os.path.join(PROJECT, 'data')
HTML = os.path.join(PROJECT, 'reports', 'sodex_dashboard.html')

tracks = {}
specs = {
 'REALWIDE': 'paper_test_realwide_state.json', 'SWING': 'paper_test_swing_state.json',
 'PARTIAL': 'paper_test_swing_state_partial.json', 'TWOWAY': 'paper_test_twoway_state.json',
 'DONCHIAN': 'paper_test_donchian_state.json', 'SPOT_V4': 'paper_test_spot_swing_v2_state.json',
 'SHORT_BEAR': 'paper_test_shortbear_state.json', 'PORTFOLIO': 'paper_test_portfolio_state.json',
 'ASTER': 'paper_test_aster_state.json',
}
for name, f in specs.items():
    p = os.path.join(DATA, f)
    if not os.path.exists(p):
        tracks[name] = {'n': 0, 'open': 0, 'pnl_usd': 0, 'wr': 0}; continue
    try:
        d = json.load(open(p))
        closed = d.get('closed', []) or d.get('closed_trades', [])
        op = d.get('open', {})
        opens = len(op) if isinstance(op, dict) else len(op)
        n = len(closed); total = 0.0; wins = 0
        for t in closed:
            pnl = t.get('pnl_usd', t.get('pnl', 0)) or 0
            if isinstance(pnl, str):
                try: pnl = float(pnl)
                except: pnl = 0
            total += float(pnl)
            if pnl > 0: wins += 1
        tracks[name] = {'n': n, 'open': opens, 'pnl_usd': round(total, 2),
                        'wr': round(wins / n * 100, 1) if n else 0}
    except Exception:
        tracks[name] = {'n': 0, 'open': 0, 'pnl_usd': 0, 'wr': 0}

gate = {}
try: gate = json.load(open(os.path.join(DATA, 'sodex_gate_monitor_state.json')))
except Exception: pass
# ── Pasar-Anantara paper test (SoDEX integration, 2026-09-08) ────────────────
pasar_h, pasar_ts, pasar_forward = {}, '', {}
_pasar_reports = sorted(glob.glob(os.path.join(PROJECT, 'reports', 'sodex',
                                               'paper_pasar_anantara_*.json')))
if _pasar_reports:
    try:
        _r = json.load(open(_pasar_reports[-1]))
        pasar_h = {k: dict(v) for k, v in _r.get('h', {}).items()}
        # Verdict jujur (zelfde logic als backtest main) — karena tidak di-persist in JSON
        MIN_N_CLAIM = 30
        for _hk, _hr in pasar_h.items():
            n_up = sum(d.get(_hk, {}).get('all', {}).get('n_up', 0)
                       for d in _r.get('symbols', {}).values())
            n_dn = sum(d.get(_hk, {}).get('all', {}).get('n_down', 0)
                       for d in _r.get('symbols', {}).values())
            if n_up == 0 and n_dn > 0:
                _hr['verdict'] = '⚠️ BIAS STRUKTURAL (UP mustahil)'
            elif _hr['n'] >= MIN_N_CLAIM and _hr['wr'] > _hr['base_up'] and _hr['p_binom'] < 0.05:
                _hr['verdict'] = 'SIGNAL OK'
            elif _hr['n'] >= MIN_N_CLAIM and _hr['wr'] < _hr['base_up'] - 0.03:
                _hr['verdict'] = '⚠️ ANTI-PREDICTIVE (WR < base)'
            elif _hr['n'] < MIN_N_CLAIM:
                _hr['verdict'] = 'TIDAK SIGNIFIKAN'
            else:
                _hr['verdict'] = 'BELUM TERBUKTI'
        pasar_ts = os.path.basename(_pasar_reports[-1]).replace(
            'paper_pasar_anantara_', '').replace('.json', '')
    except Exception:
        pasar_h = {}
try:
    pasar_forward = json.load(open(os.path.join(DATA,
                                                'paper_pasar_anantara_state.json')))
except Exception:
    pasar_forward = {}
matur = {}
try: matur = json.load(open(os.path.join(DATA, 'sodex_maturation_status.json')))
except Exception: pass
wallet_perps = wallet_spot = pos = 0
wallet_source = 'snapshot'
spot_unpriced = []
try:
    d = json.load(open(os.path.join(DATA, 'sodex_real_sync_snapshot.json')))
    wallet_perps = float(d.get('perps_balance', {}).get('total', 0))
    # Use mark-to-market spot equity, not vUSDC cash only. vUSDC-only made
    # dashboard understate wallet and target whenever spot holdings existed.
    wallet_spot = float(d.get('spot_equity_usd') or d.get('spot_vusdc', {}).get('total', 0))
    wallet_source = 'perps_balance + spot_equity_usd'
    spot_unpriced = d.get('spot_unpriced', []) or []
    pos = len(d.get('perps_positions', []))
except Exception: pass
try:
    regime_cf = json.load(open(os.path.join(PROJECT, 'reports', 'SODEX_REGIME_COUNTERFACTUAL_2026-09-15.json')))
except Exception:
    regime_cf = {}
now = datetime.now(timezone.utc) + timedelta(hours=7)
ts = now.strftime('%d %b %Y %H:%M WIB')

data_json = json.dumps({
    'ts': ts, 'wallet': round(wallet_perps + wallet_spot, 2),
    'perps': round(wallet_perps, 2), 'spot': round(wallet_spot, 2),
    'wallet_source': wallet_source, 'spot_unpriced': spot_unpriced,
    'target_usd': round((wallet_perps + wallet_spot) * 0.008, 3),
    'pos': pos, 'regime_cf': regime_cf,
    'gate': gate, 'matur': matur, 'track': tracks,
    'pasar': {'h': pasar_h, 'ts': pasar_ts,
              'forward': {'pred': len((pasar_forward.get('predictions') or {})),
                          'done': sum(1 for v in (pasar_forward.get('predictions') or {}).values()
                                      if v.get('done')),
                          'hits': sum(1 for v in (pasar_forward.get('predictions') or {}).values()
                                      if v.get('hit'))}},
})

HTML_TMPL = """<!DOCTYPE html>
<html lang="id"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anantara SoDEX — Dashboard</title>
<style>
:root{--bg:#0b1020;--card:#151b30;--border:#232b45;--fg:#e8ecf8;--muted:#8b93b0;--green:#22c55e;--red:#ef4444;--yellow:#eab308;--accent:#6366f1}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;padding:24px;line-height:1.5}
h1{font-size:22px;margin-bottom:4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:16px}
.grid{display:grid;gap:14px;margin-bottom:16px}
.cols-3{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.cols-2{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px}
.card h3{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;font-weight:600}
.big{font-size:26px;font-weight:700}
.pill{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600}
.green{background:rgba(34,197,94,.15);color:var(--green)}
.red{background:rgba(239,68,68,.15);color:var(--red)}
.yellow{background:rgba(234,179,8,.15);color:var(--yellow)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--muted);text-align:left;padding:8px 6px;border-bottom:1px solid var(--border)}
td{padding:8px 6px;border-bottom:1px solid #1c2440}
.pos{color:var(--green);font-weight:600}.neg{color:var(--red);font-weight:600}
.progress{height:8px;background:#1c2440;border-radius:6px;overflow:hidden;margin-top:6px}
.progress>div{height:100%;background:linear-gradient(90deg,var(--accent),#06b6d4)}
.mt-10{margin-top:10px}
.meta{font-size:12px;color:var(--muted);margin-top:6px}
</style></head><body>
<h1>📊 Anantara SoDEX — Dashboard Status</h1>
<div class="sub" id="ts"></div>
<div class="grid cols-3">
<div class="card"><h3>Wallet Real</h3><div class="big">$<span id="wallet"></span></div><div class="meta">Perps $<span id="perps"></span> · Spot $<span id="spot"></span> · Target/trade $<span id="target-usd"></span></div><div class="meta" id="wallet-source"></div></div>
<div class="card"><h3>Posisi Perps</h3><div class="big" id="pos"></div><div class="meta">dari exchange sync</div></div>
<div class="card"><h3>Market Regime</h3><div class="big" id="regime"></div><div class="meta" id="regime-detail"></div></div></div>
<div class="grid cols-2">
<div class="card"><h3>Gate LONG Live</h3><div class="big" id="gate"></div><div class="meta" id="gate-reason"></div></div>
<div class="card"><h3>Maturasi TP6/SL1.5</h3><div class="big"><span id="matur"></span></div>
<div class="progress"><div id="matur-bar" style="width:0%"></div></div>
<div class="meta" id="matur-meta"></div></div></div>
<div class="card"><h3>📈 Laporan Pasar (Paper Test Akurasi)</h3>
<table><thead><tr><th>Horizont</th><th>n</th><th>WR</th><th>Base</th><th>ΔWR</th><th>OOS WR</th><th>Verdict</th></tr></thead>
<tbody id="pasar-rows"></tbody></table>
<div class="meta" id="pasar-meta"></div></div>
<div class="card"><h3>Track Paper — Progres & Target (ROI/trade vs 0.7%)</h3>
<table><thead><tr><th>Track</th><th>n</th><th>WR</th><th>PnL ($)</th><th>ROI/trade</th><th>Open</th><th>Status</th></tr></thead>
<tbody id="rows"></tbody></table></div>
<script>
const D=__DATA__;
const TARGET=0.7;
const fmt=(x)=>x==null?'--':Number(x).toLocaleString('id-ID',{maximumFractionDigits:2});
function load(){
document.getElementById('ts').textContent='Update: '+D.ts;
document.getElementById('wallet').textContent=fmt(D.wallet);
document.getElementById('perps').textContent=fmt(D.perps);
document.getElementById('spot').textContent=fmt(D.spot);
document.getElementById('target-usd').textContent=fmt(D.target_usd);
document.getElementById('wallet-source').textContent=D.wallet_source+(D.spot_unpriced?.length?' · unpriced dust: '+D.spot_unpriced.map(x=>x.coin).join(', '):'');
document.getElementById('pos').textContent=D.pos;
const g=D.gate||{};
document.getElementById('regime').textContent=g.regime||'--';
document.getElementById('regime-detail').textContent='score '+(g.regime_score??'--')+' · '+(g.reason||'');
document.getElementById('gate').textContent=g.long_blocked?'🔒 TUTUP':'🟢 TERBUKA';
document.getElementById('gate-reason').textContent=g.reason||'';
const m=D.matur||{};const nf=m.n_forward||0;
document.getElementById('matur').textContent=nf+'/'+m.target_n;
document.getElementById('matur-bar').style.width=Math.min(100,nf/(m.target_n||30)*100)+'%';
document.getElementById('matur-meta').textContent='WR '+(m.wr?((m.wr*100).toFixed(0)+'%'):'--')+' · avg '+(m.avg_net_pct?('+'+(m.avg_net_pct).toFixed(2)+'%'):'--')+' · ROI wall '+(m.wallet_roi_pct?('+'+(m.wallet_roi_pct).toFixed(2)+'%'):'--');
const pr=D.pasar||{};const ph=pr.h||{};
const prows=document.getElementById('pasar-rows');
for(const[h,hr]of Object.entries(ph)){
const d=(hr.wr||0)-(hr.base_up||0);const delta=(d*100).toFixed(1)+'pp';
const vc=String(hr.verdict||'').includes('ANTI')||String(hr.verdict||'').includes('BIAS')?'<span class="pill red">'+String(hr.verdict||'').replace('⚠️ ','')+'</span>':(String(hr.verdict||'').includes('OK')?'<span class="pill green">OK</span>':'<span class="pill yellow">'+String(hr.verdict||'').replace('⚠️ ','').replace('BELUM TERBUKTI','COLLECT')+'</span>');
const tr=document.createElement('tr');
tr.innerHTML='<td>T+'+h+'h</td><td>'+(hr.n||0)+'</td><td>'+(hr.wr?((hr.wr*100).toFixed(1)+'%'):'--')+'</td><td>'+(hr.base_up?((hr.base_up*100).toFixed(1)+'%'):'--')+'</td><td class="'+(d>=0?'pos':'neg')+'">'+delta+'</td><td>'+(hr.oos_wr?((hr.oos_wr*100).toFixed(1)+'%'):'--')+'</td><td>'+vc+'</td>';
prows.appendChild(tr);}
document.getElementById('pasar-meta').textContent='Backtest '+(pr.ts||'').slice(0,8)+' · Forward: '+(pr.forward?.pred||0)+' pred, '+(pr.forward?.done||0)+' verified, '+(pr.forward?.hits||0)+' hits';
const rows=document.getElementById('rows');
for(const[name,t]of Object.entries(D.track||{})){
const roi=t.n?t.pnl_usd/D.wallet/t.n*100:0;
const st=roi>=TARGET?'<span class="pill green">✅ Target</span>':(roi>0?'<span class="pill yellow">Positif</span>':'<span class="pill red">Negatif</span>');
const tr=document.createElement('tr');
tr.innerHTML='<td>'+name+'</td><td>'+(t.n||0)+'</td><td>'+(t.wr||0)+'%</td><td class="'+(t.pnl_usd>=0?'pos':'neg')+'">'+fmt(t.pnl_usd)+'</td><td>'+(roi?roi.toFixed(2)+'%':'--')+'</td><td>'+(t.open||0)+'</td><td>'+st+'</td>';
rows.appendChild(tr);}
}
load();
</script>
</body></html>"""

html = HTML_TMPL.replace('__DATA__', data_json)
open(HTML, 'w').write(html)
print('Written', HTML, len(html), 'bytes')