#!/usr/bin/env python3
"""Oracle Aritmetika (program-aided reasoning) — Anantara Sakti.

MENGAPA BERKAS INI ADA
----------------------
Agen dan manusia sama-sama bisa salah baca angka: "$19,055" berubah menjadi
order 3,39x ukuran wajar dan berujung rugi nyata. NARASI tidak boleh dipercaya
untuk angka; KOMPUTASI boleh. Prinsip program-aided reasoning (PoT,
arXiv:2211.12588 — +24,1 pp pada FinQA dibanding penalaran-teks): serahkan
aritmetika ke program, bukan ke bahasa.

Modul ini melakukan dua hal:
  1. MENGHITUNG dari fakta mentah (entry, exit, size, fee) -> angka kanonik.
  2. MEMVERIFIKASI angka yang DIKLAIM pihak lain -> tandai yang tak cocok.

HUKUM MODUL
-----------
- **Decimal, bukan float**, untuk uang. Galat representasi float cukup untuk
  membalik keputusan pada notional kecil (wallet $243).
- **Murni & deterministik.** Tanpa I/O, tanpa jam dinding, tanpa RNG.
- **Fail-closed.** Input tak lengkap -> raise atau tandai TIDAK TERVERIFIKASI.
  TIDAK PERNAH mengembalikan "ok" karena data tak terbaca (kelas cacat A9).

BATAS PERAN: ini kalkulator + pemeriksa. Ia tidak tahu harga benar, tidak
memutuskan trading, dan tidak menggantikan oracle venue. Ia memastikan angka
yang dipakai konsisten dengan fakta yang diberikan.
"""
from __future__ import annotations

import json
import pathlib
import sys
from decimal import Decimal, InvalidOperation, getcontext
from typing import Any, Callable, Iterable

getcontext().prec = 40

TWO = Decimal("2")
CENT = Decimal("0.01")
BPS = Decimal("10000")

# Batas kewajaran ukuran order terhadap wallet. Melampaui ini = TIDAK WAJAR
# dan wajib ditolak sebelum order (pelajaran UNI: 3,39x -> -$19,06).
MAX_ORDER_FRAC = Decimal("2.0")


class ArithError(ValueError):
    """Input tak memadai untuk komputasi. Fail-closed: pemanggil harus berhenti."""


# ── Konversi & pembulatan ─────────────────────────────────────────────────────
def D(v: Any) -> Decimal:
    """Ke Decimal dengan aman. None/""/teks -> ArithError (fail-closed).

    MENGAPA lewat str: Decimal(float) mewarisi galat biner float
    (Decimal(0.1) = 0.1000000000000000055511151231257827021181583404541015625).
    Decimal(str(0.1)) = 0.1 — yang dimaksud manusia.
    """
    if v is None:
        raise ArithError("nilai None tidak bisa dihitung")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ArithError("bool bukan besaran aritmetika")
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(repr(v))
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if not s:
            raise ArithError("string kosong bukan besaran aritmetika")
        try:
            return Decimal(s)
        except InvalidOperation as e:
            raise ArithError(f"bukan angka: {v!r}") from e
    raise ArithError(f"tipe tak didukung: {type(v).__name__}")


def money(v: Any) -> Decimal:
    """Bulatkan ke sen (2 desimal, ROUND_HALF_UP)."""
    return D(v).quantize(CENT, rounding="ROUND_HALF_UP")


def _f(d: Decimal) -> float:
    """Ke float untuk pelaporan/JSON. Jangan dipakai untuk aritmetika lanjutan."""
    return float(d)


# ── Inti: PnL, notional, fraksi wallet ────────────────────────────────────────
def notional(size: Any, price: Any) -> Decimal:
    """Nilai nosional = ukuran x harga. Selalu >= 0."""
    n = abs(D(size)) * abs(D(price))
    return money(n)


def pnl_usd(side: str, entry: Any, exit: Any, size: Any,
            fee_bps_roundtrip: Any = 0) -> Decimal:
    """PnL bersih (USD) sebuah posisi, setelah fee bolak-balik.

    side: "long"/"buy" atau "short"/"sell".
    fee_bps_roundtrip: biaya TOTAL masuk+keluar dalam basis poin (mis. 12 = 0,12%).
    """
    s = str(side).strip().lower()
    if s in ("long", "buy"):
        sign = Decimal(1)
    elif s in ("short", "sell"):
        sign = Decimal(-1)
    else:
        raise ArithError(f"side tidak dikenal: {side!r} (pakai long/short)")
    e, x, q = D(entry), D(exit), abs(D(size))
    if e <= 0:
        raise ArithError(f"harga masuk tidak wajar: {entry!r}")
    gross = (x - e) * q * sign
    fee = (money(e * q) + money(x * q)) * D(fee_bps_roundtrip) / BPS
    return money(gross - fee)


def wallet_frac(notional_usd: Any, wallet_usd: Any) -> Decimal:
    """Fraksi wallet = notional / wallet. Wallet <= 0 -> ArithError."""
    w = D(wallet_usd)
    if w <= 0:
        raise ArithError(f"wallet tidak wajar: {wallet_usd!r}")
    return (abs(D(notional_usd)) / w).quantize(Decimal("0.0001"), rounding="ROUND_HALF_UP")


def check_order_sane(size: Any, price: Any, wallet_usd: Any,
                     max_frac: Any = MAX_ORDER_FRAC) -> dict:
    """GERBANG: apakah ukuran order ini wajar terhadap wallet?

    Inilah penjaga kelas kesalahan yang memakan $19,06 pada UNI: order 3,39x
    lebih besar dari batas. Fail-closed: harga/wallet tak wajar -> TOLAK.
    """
    try:
        n = notional(size, price)
        frac = wallet_frac(n, wallet_usd)
        mx = D(max_frac)
    except ArithError as e:
        return {"ok": False, "alasan": f"TIDAK BISA DIVERIFIKASI: {e}",
                "notional_usd": None, "fraksi_wallet": None}
    ok = frac <= mx
    return {
        "ok": bool(ok),
        "notional_usd": _f(n),
        "fraksi_wallet": _f(frac),
        "batas_fraksi": _f(mx),
        "alasan": ("wajar" if ok
                   else f"order {frac}x wallet > batas {mx}x — TOLAK sebelum kirim"),
    }


def window_pnl(fills: Iterable[dict], fee_bps_roundtrip: Any = 0) -> dict:
    """Agregat PnL satu jendela dari daftar fill.

    Setiap fill: {"side","entry","exit","size","fee_bps_roundtrip"?}.
    """
    total = Decimal(0)
    n = 0
    for f in fills:
        total += pnl_usd(f["side"], f["entry"], f["exit"], f["size"],
                         f.get("fee_bps_roundtrip", fee_bps_roundtrip))
        n += 1
    return {"n_fill": n, "pnl_usd": _f(money(total))}


def target_status(pnl_usd_total: Any, wallet_usd: Any, target_pct: Any) -> dict:
    """Status capaian terhadap target % dari TOTAL wallet (North Star).

    Target divisi: 0,8% dari total wallet per window 30 jam. Contoh:
    wallet $243,4583 -> $1,9477.
    """
    try:
        p = D(pnl_usd_total)
        w = D(wallet_usd)
        if w <= 0:
            raise ArithError("wallet <= 0")
        tgt = D(target_pct) / Decimal(100)
        need = money(w * tgt)
        got_pct = (p / w * Decimal(100)).quantize(Decimal("0.0001"), rounding="ROUND_HALF_UP")
    except ArithError as e:
        return {"terverifikasi": False, "alasan": f"TIDAK BISA DIVERIFIKASI: {e}"}
    return {
        "terverifikasi": True,
        "pnl_usd": _f(money(p)),
        "wallet_usd": _f(money(w)),
        "target_pct": _f(D(target_pct)),
        "target_usd": _f(need),
        "capaian_pct": _f(got_pct),
        "selisih_usd": _f(money(need - p)),
        "tercapai": bool(p >= need),
    }


# ── Verifikasi klaim ──────────────────────────────────────────────────────────
def verify_claim(name: str, claimed: Any, compute: Callable[[], Any],
                 tol: Any = CENT) -> dict:
    """Bandingkan angka yang DIKLAIM dengan hasil komputasi ulang.

    compute() melempar ArithError -> status TIDAK_TERVERIFIKASI (bukan ok).
    """
    try:
        expected = D(compute())
    except (ArithError, KeyError, TypeError) as e:
        return {"klaim": name, "status": "TIDAK_TERVERIFIKASI",
                "alasan": f"{type(e).__name__}: {e}", "diklaim": claimed}
    try:
        got = D(claimed)
    except ArithError as e:
        return {"klaim": name, "status": "TIDAK_TERVERIFIKASI",
                "alasan": f"klaim bukan angka: {e}", "diklaim": claimed}
    beda = abs(got - expected)
    ok = beda <= D(tol)
    return {
        "klaim": name,
        "status": "COCOK" if ok else "SALAH",
        "diklaim": _f(got),
        "dihitung": _f(expected),
        "selisih": _f(beda),
        "toleransi": _f(D(tol)),
    }


def verify_claims(claims: dict[str, Any], facts: dict,
                  registry: dict[str, Callable[[dict], Any]] | None = None) -> dict:
    """Verifikasi sekumpulan klaim. Kembalikan laporan + ringkasan.

    claims: {"pnl_total": 1.94, ...}
    registry: nama -> fungsi(fakta) -> nilai benar. Default: REGISTRY di bawah.
    Klaim tanpa rumus dikenal -> TIDAK_TERVERIFIKASI (fail-closed, bukan ok).
    """
    reg = registry if registry is not None else REGISTRY
    hasil = []
    for k, v in claims.items():
        fn = reg.get(k)
        if fn is None:
            hasil.append({"klaim": k, "status": "TIDAK_TERVERIFIKASI",
                          "alasan": "tidak ada rumus pembanding terdaftar",
                          "diklaim": v})
            continue
        hasil.append(verify_claim(k, v, lambda fn=fn: fn(facts)))
    ringkas = {}
    for h in hasil:
        ringkas[h["status"]] = ringkas.get(h["status"], 0) + 1
    return {
        "n_klaim": len(hasil),
        "ringkasan": ringkas,
        "semua_cocok": ringkas.get("SALAH", 0) == 0
                        and ringkas.get("TIDAK_TERVERIFIKASI", 0) == 0,
        "detail": hasil,
    }


# ── Registry rumus (nama klaim -> cara menghitung yang benar) ─────────────────
REGISTRY: dict[str, Callable[[dict], Any]] = {
    # fakta: {"wallet_usd":..., "target_pct":..., "fills":[...]}
    "target_usd": lambda f: D(f["wallet_usd"]) * D(f["target_pct"]) / Decimal(100),
    "pnl_total_usd": lambda f: D(window_pnl(f["fills"],
                                            f.get("fee_bps_roundtrip", 0))["pnl_usd"]),
    "capaian_pct": lambda f: (D(window_pnl(f["fills"],
                                           f.get("fee_bps_roundtrip", 0))["pnl_usd"])
                              / D(f["wallet_usd"]) * Decimal(100)),
    # fakta: {"size":..., "price":..., "wallet_usd":...}
    "notional_usd": lambda f: notional(f["size"], f["price"]),
    "fraksi_wallet": lambda f: wallet_frac(notional(f["size"], f["price"]), f["wallet_usd"]),
}


# ── Uji mandiri (known-answer) ────────────────────────────────────────────────
def selfcheck() -> dict:
    """Nilai rujukan yang dihitung tangan + kasus negatif yang WAJIB tertangkap."""
    kasus = []

    def cek(nama, dapat, harus):
        ok = D(dapat) == D(harus)
        kasus.append({"uji": nama, "dapat": _f(D(dapat)), "harus": _f(D(harus)), "lulus": ok})

    # 1. notional: 0,1 BTC @ 76.000 = 7.600
    cek("notional_0.1x76000", notional("0.1", 76000), "7600")

    # 2. fee: 0,12% round-trip pada long 1 ETH 3.000->3.100 tanpa fee = 100
    cek("pnl_long_tanpa_fee", pnl_usd("long", 3000, 3100, 1), "100")
    # dengan 12 bps round-trip: fee = (3000+3100)*12/10000 = 7,32 -> 92,68
    cek("pnl_long_fee_12bps", pnl_usd("long", 3000, 3100, 1, 12), "92.68")

    # 3. short: turun = untung. 1 SOL 200->190 = +10
    cek("pnl_short_untung", pnl_usd("short", 200, 190, 1), "10")

    # 4. target divisi: wallet 243,4583 x 0,8% = 1,9477 (dibulatkan ke sen)
    cek("target_0.8pct_wallet_243.4583",
        money(D("243.4583") * D("0.8") / 100), "1.95")

    # 5. fraksi wallet: order 800 dengan wallet 243,4583 = 3,286x
    cek("fraksi_order_besar", wallet_frac(800, "243.4583"), "3.2860")

    # 6. NEGATIF — order kelas UNI (3,29x) HARUS ditolak
    g = check_order_sane(size="2", price=400, wallet_usd="243.4583")
    kasus.append({"uji": "tolak_order_3.29x", "dapat": g["ok"], "harus": False,
                  "lulus": g["ok"] is False})

    # 7. NEGATIF — wallet tak wajar -> TOLAK, bukan "ok"
    g2 = check_order_sane(size=1, price=100, wallet_usd=0)
    kasus.append({"uji": "tolak_wallet_nol", "dapat": g2["ok"], "harus": False,
                  "lulus": g2["ok"] is False and "TIDAK BISA DIVERIFIKASI" in g2["alasan"]})

    # 8. NEGATIF — klaim salah harus tertangkap
    v = verify_claim("pnl", claimed="19.055", compute=lambda: D("1.9055"))
    kasus.append({"uji": "tangkap_klaim_salah_10x", "dapat": v["status"], "harus": "SALAH",
                  "lulus": v["status"] == "SALAH"})
    # ... dan salah-baca itu memang 10x: 19,055 vs 1,9055
    r = abs(D("19.055") - D("1.9055"))
    kasus.append({"uji": "selisih_benar_17.1495", "dapat": _f(r), "harus": 17.1495,
                  "lulus": r == D("17.1495")})

    # 9. NEGATIF — klaim tanpa rumus -> TIDAK_TERVERIFIKASI (fail-closed)
    rep = verify_claims({"entah": 1.0}, {})
    kasus.append({"uji": "klaim_tak_dikenal_failclosed",
                  "dapat": rep["semua_cocok"], "harus": False,
                  "lulus": rep["semua_cocok"] is False})

    # 10. float vs Decimal: 0,1+0,2 harus TEPAT 0,3
    cek("decimal_tepat_0.1+0.2", D("0.1") + D("0.2"), "0.3")

    lulus = sum(1 for k in kasus if k["lulus"])
    return {"n_uji": len(kasus), "lulus": lulus,
            "gagal": len(kasus) - lulus, "semua_lulus": lulus == len(kasus),
            "detail": kasus}


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--verify":
        p = pathlib.Path(sys.argv[2])
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError) as e:
            print(f"TIDAK BISA MEMBACA {p}: {e}", file=sys.stderr)
            return 1
        rep = verify_claims(data.get("claims", {}), data.get("facts", {}))
        print(json.dumps(rep, indent=2))
        return 0 if rep["semua_cocok"] else 1
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        r = selfcheck()
        print(json.dumps(r, indent=2))
        return 0 if r["semua_lulus"] else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
