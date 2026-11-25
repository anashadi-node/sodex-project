"""Tes evaluator F3 (data sintetis; TIDAK menyentuh tape nyata).

Regresi audit 07-Okt-2026:
- C2 WAJIB uji sign-flip klaster-HARI (bukan binomial episode / "Bonferroni m=1" = identitas).
- Funding HANYA untuk settlement yang benar-benar terlewati (bukan baris berikutnya -> kredit).
- C5 WAJIB segmen WAKTU (bukan urutan symbol-major).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sodex_prereg_f3 as f3  # noqa: E402

T0 = 1_000_000


def _ep(sym, t_in, net, day):
    return {"sym": sym, "t_in": t_in, "net": net, "day": day, "side": "buy"}


def test_c2_uses_day_clustered_signflip_not_raw_binomial():
    """REGRESI KRITIS: 10 hari, 7 hari semua-positif (day-shock), 3 hari semua-negatif.
    C1 (binomial episode) LOLOS, tetapi C2 harus GAGAL (hanya 7/10 hari positif).
    Kode lama (C2 = Bonferroni m=1 = p_raw) akan LULUS PALSU di sini."""
    eps = []
    for d in range(10):
        day = f"202610{d + 1:02d}"
        net = 0.01 if d < 7 else -0.01
        for k in range(10):
            eps.append(_ep(f"S{k % 5}", T0 + d * 2880 + k, net, day))
    res = f3.judge(eps, T0, T0 + 10 * 2880)
    assert res["criteria"]["C1_WR>50%_p<0.05"] is True
    assert res["criteria"]["C2_p_hari_klaster<0,05"] is False
    assert res["p_day"] > 0.05


def test_funding_charged_only_for_crossed_settlements():
    rows = [(T0 - 100, 0.001, T0 - 50), (T0 + 100, 0.0005, T0 + 900), (T0 + 2000, 0.002, T0 + 5000)]
    assert f3.settlements_in_window(rows, T0, T0 + f3.HOLD_S) == 0.0005
    # dedup: funding_time sama dikumpul beberapa kali -> dihitung sekali
    dup = [(T0 + 10, 0.0005, T0 + 900), (T0 + 20, 0.0005, T0 + 900)]
    assert f3.settlements_in_window(dup, T0, T0 + f3.HOLD_S) == 0.0005


def test_simulate_funding_sign_and_no_settlement():
    obi = [(T0, 0.5, 100.0), (T0 + 900, 0.5, 100.0), (T0 + f3.HOLD_S, 0.5, 100.0)]  # (ts, obi20, mid)
    rows = [(T0, 0.001, T0 + 900)]  # settlement di dalam jendela, rate +0,001
    buy = f3.simulate("X", [(T0, "buy", 0.001, 0.5, 100.0)], obi, rows)[0]
    assert abs(buy["net"] - (0.0 - 2 * f3.TAKER_FEE - 0.001)) < 1e-12  # long membayar
    sell = f3.simulate("X", [(T0, "sell", 0.001, -0.5, 100.0)], obi, rows)[0]
    assert abs(sell["net"] - (0.0 - 2 * f3.TAKER_FEE + 0.001)) < 1e-12  # short menerima
    # tak ada settlement terlewati -> funding 0 (bug lama: kredit dari baris berikutnya)
    none_rows = [(T0, 0.001, T0 - 500)]
    e = f3.simulate("X", [(T0, "buy", 0.001, 0.5, 100.0)], obi, none_rows)[0]
    assert abs(e["net"] - (0.0 - 2 * f3.TAKER_FEE)) < 1e-12


def test_c5_segments_use_time_order_not_symbol_major():
    """REGRESI: C5 harus 'segmen WAKTU'. Daftar symbol-major -> 2/3 positif (True);
    urutan waktu -> 1/3 (False). Kode lama (symbol-major) akan salah lulus."""
    vals = [1, 1, 1, 1, 1, -1, -1, -1, -1]  # symbol-major: [P,P,P][P,P,N][N,N,N] -> 2/3
    perm = [0, 1, 2, 3, 6, 4, 5, 7, 8]       # index -> posisi waktu -> [P,P,P][P,N,N][P,N,N] -> 1/3
    eps = [_ep("S", T0 + perm[i], vals[i] * 0.01, "20261008") for i in range(9)]
    res = f3.judge(eps, T0, T0 + 100)
    assert res["criteria"]["C5_segmen>=2/3_konsisten"] is False


def test_taker_fee_is_official_4bp_per_leg():
    """Konstanta F3 sudah benar (0,04%/leg); tes ini mengunci agar tak turun jadi 2 bp."""
    assert f3.TAKER_FEE == 0.0004
