#!/usr/bin/env python3
"""Verifikasi DOI dari dokumen ANANTARA V1+V2 via Crossref API (kanal terverifikasi hidup)."""
import json, subprocess, time

DOIS = {
 'S1  Order flow (Anastasopoulos 2026 JFM)': '10.1016/j.finmar.2026.101047',
 'S2  Deprez-Frömmel 2024 IREF': '10.1016/j.iref.2024.05.003',
 'S3  Gerritsen 2020 FRL': '10.1016/j.frl.2019.08.011',
 'S4  TA crypto 2022 JIFM': '10.1016/j.intfin.2022.101601',
 'S5  Guo 2024 JEDC': '10.1016/j.jedc.2024.104863',
 'S6  Yang 2025 FRL momentum': '10.1016/j.frl.2025.107879',
 'S7  Hsieh 2025 FRL states': '10.1016/j.frl.2025.108356',
 'S8  Zhang 2026 Physica A ProSP': '10.1016/j.physa.2026.131911',
 'S9  Chi 2023 JFM basis': '10.1002/fut.22425',
 'S11 Bailey-LdP 2014 DSR': '10.3905/jpm.2014.40.5.094',
 'S12 Bailey PBO JCF': '10.21314/jcf.2016.322',
 'S13 Arian 2024 KBS CPCV': '10.1016/j.knosys.2024.112477',
 'E1  Fieberg 2025 JFQA CTREND': '10.1017/S0022109024000747',
 'E2  Fieberg 2024 IRFA size/vol': '10.1016/j.irfa.2024.103218',
 'E3  Fieberg 2023 QuantFin': '10.1080/14697688.2023.2269999',
 'E4  Mercik 2025 IRFA liquidity': '10.1016/j.irfa.2024.103809',
 'E5  Liu-Tsyvinski-Wu 2022 JF': '10.1111/jofi.13119',
}

def get(doi):
    try:
        r = subprocess.run(['curl','-sS','-m','20','-L',
            '-A','Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0',
            f'https://api.crossref.org/works/{doi}'],
            capture_output=True, text=True, timeout=30)
        if r.returncode != 0 or not r.stdout.strip():
            return {'err': 'no response'}
        d = json.loads(r.stdout)['message']
        return {
            'title': (d.get('title') or ['?'])[0][:110],
            'journal': (d.get('container-title') or ['?'])[0][:55],
            'year': (d.get('issued', {}).get('date-parts', [[None]])[0][0]),
            'type': d.get('type'),
            'cites': d.get('is-referenced-by-count'),
        }
    except Exception as e:
        return {'err': f'{type(e).__name__}: {e}'}

out = {}
for k, doi in DOIS.items():
    r = get(doi)
    out[k] = {'doi': doi, **r}
    if 'err' in r:
        print(f"❌ {k}\n     {doi} -> {r['err']}")
    else:
        print(f"✅ {k}\n     {doi}\n     \"{r['title']}\" | {r['journal']} | {r['year']} | cites={r['cites']}")
    time.sleep(0.4)

json.dump(out, open('/home/USER/anantara-sakti/docs/research/masterplan/riset_metode_sodex_cex_20260914/DOI_VERIFY.json','w'), indent=1)
print('\ntersimpan: DOI_VERIFY.json')
