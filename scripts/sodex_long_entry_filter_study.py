#!/usr/bin/env python3
"""Studi filter ENTRY kaki LONG `twoway` — apakah ada subset ber-edge >= 2x fee?

MENGAPA
-------
Constraint T1 SoDEX adalah BIAYA, bukan sinyal. Kaki LONG `twoway` (n=325, satu-
satunya ber-n besar) ber-edge +8,05 bps sementara fee RT = 8,00 bps: cost 1x
praktis nol, cost 2x gagal. Kaki SHORT ber-edge +60,9 bps (7,6x fee) tetapi
digerbangi death-cross dan nol trade sejak 2026-09-01, jadi tak dapat
dijadwalkan. Jalur maker (fee 2,28 bps) sudah terbukti 0 fill dan E1 dibekukan.

Satu-satunya jalur tersisa yang TERJADWAL dan TIDAK BEKU adalah mempersempit
masuknya: kalau ada subset trade LONG dengan edge >= 2x fee (16 bps), subset itu
lolos cost 2x tanpa menyentuh fee, tanpa maker, tanpa leverage.

INI PENGUKURAN, BUKAN STRATEGI BARU
-----------------------------------
Semua kandidat berasal dari KOMPONEN LOGIKA YANG SUDAH ADA (field `entry_reasons`
yang ditulis mesin itu sendiri) plus satu dimensi rezim (`btc_regime`). Tidak ada
indikator baru, tidak ada model baru, tidak ada parameter yang diubah.

ANTI-P-HACKING (WAJIB)
----------------------
1. Daftar kandidat DIDEKLARASIKAN DI MUKA (lihat kandidat()).
2. Penalti multiple-testing memakai mekanisme harness sendiri: `n_trials` yang
   diberikan ke evaluate() = jumlah trial registry + jumlah kandidat diuji.
   DSR di dalam harness yang menghukumnya -- bukan koreksi buatan di luar.
3. VALIDASI TIGA-SEGMEN: `entry_time` membagi 325 trade jadi TIGA periode
   waktu. Filter hanya LAYAK jika cost 2x positif di KETIGA segmen.

   KENAPA TIGA, BUKAN DUA (pelajaran 2026-10-05): pada percobaan pertama,
   validasi belah-dua MELOLOSKAN filter palsu `strong_24h_trend` -- edge
   +24,28 bps yang seluruhnya berasal dari SATU jendela 15 hari (04-19 Sep,
   edge +93,6 bps) sementara dua periode lain NEGATIF (-7,7 dan -9,1 bps).
   Median `entry_time` (12-Sep) kebetulan jatuh DI DALAM jendela mujur itu,
   sehingga kedua paruh ikut memuatnya dan keduanya tampak lulus.

   Pelajaran umum: memotong dua bagian data yang berdekatan TIDAK menguji
   ketahanan terhadap rezim. Tiga segmen membuat konsentrasi semacam ini
   langsung terlihat. Jangan turunkan kembali ke dua.
4. Semua kandidat masuk registry, lulus maupun gagal.

Pemakaian:
    python3 scripts/sodex_long_entry_filter_study.py --dry-run   # tak tulis registry
    python3 scripts/sodex_long_entry_filter_study.py             # tulis registry
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "docs/handover/RISET_TO_DIVISI_2026-10-01/harness"))

import sodex_harness_reeval as H  # noqa: E402
from anantara_harness import TrialRegistry  # noqa: E402

MIN_N = 30           # dokumen riset 10.1: n>=30 = evidence minimum
MIN_N_HALF = 15      # paruh lebih kecil; <15 -> tak dinilai
TARGET_EDGE_BPS = 2 * H.SODEX_FEE_BPS   # 16 bps = syarat lolos cost 2x


def kandidat(rows: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """Daftar filter yang DIDEKLARASIKAN DI MUKA. Tidak boleh tumbuh setelah
    melihat hasil -- itu p-hacking."""
    out: list[tuple[str, str, list[dict]]] = []

    # (a) flag komponen: setiap alasan yang cukup sering muncul
    alasan = sorted({str(x) for r in rows for x in (r.get("entry_reasons") or [])})
    for a in alasan:
        sub = [r for r in rows if a in (r.get("entry_reasons") or [])]
        if len(sub) < MIN_N or len(sub) == len(rows):
            continue          # terlalu kecil, atau selalu benar (tak memfilter)
        out.append((f"flag:{a}", f"punya {a}", sub))

    # (b) kombinasi persis
    combos: dict[tuple, list[dict]] = {}
    for r in rows:
        combos.setdefault(tuple(sorted(map(str, r.get("entry_reasons") or []))), []).append(r)
    for c, sub in sorted(combos.items(), key=lambda kv: -len(kv[1])):
        if len(sub) < MIN_N:
            continue
        out.append(("combo:" + "+".join(c), "kombinasi persis", sub))

    # (c) rezim BTC (satu-satunya dimensi rezim yang terisi di set ini)
    for reg in sorted({str(r.get("btc_regime")) for r in rows if r.get("btc_regime")}):
        sub = [r for r in rows if str(r.get("btc_regime")) == reg]
        if len(sub) >= MIN_N:
            out.append((f"btc_regime:{reg}", f"rezim BTC {reg}", sub))
    return out


def ukur(sub: list[dict], candles, n_trials: int) -> dict | None:
    """Metrik sama persis dengan harness T1 (beta-netral, cost 1x & 2x)."""
    if len(sub) < MIN_N:
        return None
    returns = [H.trade_return(r) for r in sub]
    _grade, res = H.evaluate(
        returns=returns,
        market=H.btc_market_returns(sub, candles),
        sides=[H.side_sign(r) for r in sub],
        fee_bps=H.SODEX_FEE_BPS,
        n_trials=n_trials,
        groups=[H.trade_symbol(r) for r in sub],
        periods_per_year=365,
        min_n=MIN_N,
    )
    cs = res.get("cost_stress", {})
    ck = res.get("checks", {}) or {}
    ci = res.get("ci95") or [math.nan, math.nan]
    return {
        "n": len(sub),
        "wr": res.get("wr"),
        "excess_bps": res.get("excess_mean", math.nan) * 10_000.0,
        "cost1x_bps": cs.get("1.0", {}).get("mean", math.nan) * 10_000.0,
        "cost2x_bps": cs.get("2.0", {}).get("mean", math.nan) * 10_000.0,
        "ci95_lo_bps": ci[0] * 10_000.0,
        "sharpe": res.get("sharpe_ann", math.nan),
        "net2x": bool(ck.get("net_pos_2x")),
        "net1x": bool(ck.get("net_pos_1x")),
        "ci_lo_pos": bool(ck.get("ci95_lower_positive")),
        "dsr_ok": bool(ck.get("dsr_passed")),
        "beta_neutral": bool(res.get("beta_neutral")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="jangan tulis registry")
    args = ap.parse_args()

    reg = TrialRegistry(ROOT / "reports/sodex/sodex_trial_registry.json")
    rows_all = [r for r in H.closed_rows(H.TRACKS["twoway"]) if H.arm_of(r) == H.ARM_SIGNAL]
    longs = [r for r in rows_all if H.side_sign(r) == 1]

    candles = H.fetch_btc_1h(dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc),
                             dt.datetime.now(dt.timezone.utc))

    kands = kandidat(longs)
    base = reg.count() + 1
    n_trials = base + len(kands)   # penalti multiple-testing jujur

    print(f"LONG twoway    : {len(longs)} trade")
    print(f"fee RT         : {H.SODEX_FEE_BPS:.1f} bps  -> target edge >= {TARGET_EDGE_BPS:.1f} bps")
    print(f"kandidat       : {len(kands)} (dideklarasikan di muka)")
    print(f"n_trials       : {n_trials} (registry {base} + kandidat {len(kands)})\n")

    # tiga segmen waktu (bukan dua -- lihat docstring, pelajaran 2026-10-05)
    srt = sorted(longs, key=lambda r: str(r.get("entry_time") or ""))
    n3 = len(srt) // 3
    blok = [("S1", srt[:n3]), ("S2", srt[n3:2 * n3]), ("S3", srt[2 * n3:])]
    batas = [(lbl, str(seg[0].get("entry_time") or ""), str(seg[-1].get("entry_time") or ""))
             for lbl, seg in blok]
    print("tiga segmen    : " + " | ".join(
        f"{lbl} n={len(seg)} ({b[1][:10]}..{b[2][:10]})" for (lbl, seg), b in zip(blok, batas)) + "\n")

    semua = ukur(longs, candles, n_trials)
    print(f"{'kandidat':<52}{'n':>5}{'WR':>7}{'edge':>9}{'1x':>8}{'2x':>8}  2x?  S1/S2/S3-2x")
    print("-" * 118)
    print(f"{'(SEMUA LONG -- baseline)':<52}{semua['n']:>5}{semua['wr']*100:>6.1f}%"
          f"{semua['excess_bps']:>9.2f}{semua['cost1x_bps']:>8.2f}{semua['cost2x_bps']:>8.2f}"
          f"   {semua['net2x']}")

    kandidat_ok = []
    for nama, ket, sub in kands:
        m = ukur(sub, candles, n_trials)
        if m is None:
            continue
        seg_hasil = []
        for (lbl, _), (_, lo, hi) in zip(blok, batas):
            s = [r for r in sub if lo <= str(r.get("entry_time") or "") <= hi]
            seg_hasil.append(ukur(s, candles, n_trials))
        tanda_seg = "/".join("-" if x is None else ("OK" if x["net2x"] else "no")
                             for x in seg_hasil)
        # LAYAK hanya bila cost 2x positif di KETIGA segmen (bukan dua)
        layak = (m["net2x"] and all(x is not None and x["net2x"] for x in seg_hasil))
        if layak:
            kandidat_ok.append((nama, m))
        print(f"{nama[:51]:<52}{m['n']:>5}{m['wr']*100:>6.1f}%{m['excess_bps']:>9.2f}"
              f"{m['cost1x_bps']:>8.2f}{m['cost2x_bps']:>8.2f}   {str(m['net2x']):<5} "
              f"{tanda_seg} {'LAYAK' if layak else ''}")

    print()
    if kandidat_ok:
        print(f"LAYAK (lolos cost 2x di KETIGA segmen): {[k for k, _ in kandidat_ok]}")
    else:
        print("LAYAK: TIDAK ADA. Tidak ada subset komponen sinyal yang mencapai edge >= "
              f"{TARGET_EDGE_BPS:.0f} bps DAN bertahan di KETIGA segmen waktu.")
        print("-> Memperketat filter TIDAK menyelesaikan apa pun.")
        print("-> JANGAN simpulkan 'constraint = biaya'. Periksa baseline per segmen: bila")
        print("   segmen terkini negatif SEBELUM biaya, menurunkan fee (termasuk maker/rebate")
        print("   tier) TIDAK akan menolong -- masalahnya bukan fee, melainkan tidak adanya")
        print("   alpha beta-netral (lihat reports/sodex/D07_RCA_FILTER_DAN_FAKTOR_2026-10-05.md).")
        print("-> Jangan promosikan track ini dan jangan bangun mesin dari keluarga sinyal yang")
        print("   sama: eksposur faktornya sama, sehingga melanggar syarat korelasi antar-mesin.")

    if not args.dry_run:
        for nama, ket, sub in kands:
            m = ukur(sub, candles, n_trials)
            if m is None:
                continue
            reg.log(strategy=f"twoway:LONG:filter:{nama}", passed=bool(m["net2x"]),
                    note=f"studi filter entry LONG ({ket})",
                    n=m["n"], excess_bps=round(m["excess_bps"], 4),
                    cost2x_bps=round(m["cost2x_bps"], 4),
                    summary={"lolos_cost2x": m["net2x"]})
        print(f"\nregistry: {len(kands)} kandidat dicatat -> n_trials_total={reg.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
