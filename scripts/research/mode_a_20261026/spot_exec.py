#!/usr/bin/env python3
"""Utilitas eksekusi SPOT SoDEX (dipakai paper_exec, collector, live, preflight). Hanya baca publik kecuali fungsi live.
Semua fungsi gagal-tertutup: respons tak terduga -> ExecError, bukan tebakan."""
from __future__ import annotations
import json, math, os, subprocess
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BIN = os.path.join(ROOT, "bin", "sodex")
NAME = {"btc": "BTC/USDC", "eth": "ETH/USDC", "xaut": "XAUT/USDC"}
INTERNAL = {"btc": "vBTC_vUSDC", "eth": "vETH_vUSDC", "xaut": "vXAUt_vUSDC"}
# spesifikasi diverifikasi live 26-Okt-2026; preflight membandingkan ulang dengan /markets sebelum live
TICK = {"btc": Decimal("1"), "eth": Decimal("0.1"), "xaut": Decimal("0.1")}
STEP = {"btc": Decimal("0.00001"), "eth": Decimal("0.0001"), "xaut": Decimal("0.0001")}
MIN_NOTIONAL = Decimal("5")
TAKER, MAKER = 0.00065, 0.00035
PUBLIC_ENV_DROP = ("SODEX_PRIVATE_KEY", "SODEX_API_KEY", "SODEX_ACCOUNT_ID", "SODEX_ADDRESS")


class ExecError(RuntimeError):
    pass


def run_cli(args: list[str], env: dict | None = None, timeout: int = 25):
    if not os.path.exists(BIN):
        raise ExecError(f"CLI tidak ada: {BIN}")
    e = env if env is not None else {k: v for k, v in os.environ.items() if k not in PUBLIC_ENV_DROP}
    try:
        r = subprocess.run(["timeout", str(timeout - 2), BIN] + args, capture_output=True, text=True, timeout=timeout, env=e)
    except subprocess.TimeoutExpired as ex:
        raise ExecError(f"timeout: {' '.join(args[:3])}") from ex
    if r.returncode != 0:
        raise ExecError(f"cli rc={r.returncode}: {r.stderr.strip()[:200] or r.stdout.strip()[:200]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as ex:
        raise ExecError(f"bukan JSON: {r.stdout[:120]!r}") from ex


def fetch_book(asset: str, depth: int = 20) -> dict:
    j = run_cli(["orderbook", "spot", NAME[asset], "--depth", str(depth), "--format", "json"])
    try:
        bids = [(Decimal(x["price"]), Decimal(x["quantity"])) for x in j["bids"]]
        asks = [(Decimal(x["price"]), Decimal(x["quantity"])) for x in j["asks"]]
    except (KeyError, TypeError, ArithmeticError) as ex:
        raise ExecError(f"format orderbook {asset} tak dikenal") from ex
    return validate_book({"asset": asset, "bids": sorted(bids, reverse=True), "asks": sorted(asks)})


def validate_book(b: dict, max_spread_bps: float = 100.0) -> dict:
    if not b["bids"] or not b["asks"]:
        raise ExecError(f"{b['asset']}: buku kosong satu sisi")
    bb, ba = b["bids"][0][0], b["asks"][0][0]
    if bb <= 0 or ba <= 0 or bb >= ba:
        raise ExecError(f"{b['asset']}: buku silang/tidak valid bid={bb} ask={ba}")
    mid = (bb + ba) / 2
    b["mid"] = float(mid)
    b["spread_bps"] = float((ba - bb) / mid * 10000)
    if b["spread_bps"] > max_spread_bps:
        raise ExecError(f"{b['asset']}: spread {b['spread_bps']:.1f} bps > {max_spread_bps}")
    return b


def limit_price(book: dict, side: str, slip_cap_bps: float) -> Decimal:
    """Harga batas IOC: beli = ask1*(1+cap) dibulatkan ke bawah tick; jual = bid1*(1-cap) dibulatkan ke atas tick."""
    t = TICK[book["asset"]]
    if side == "buy":
        p = book["asks"][0][0] * (Decimal(1) + Decimal(str(slip_cap_bps)) / 10000)
        return (p / t).to_integral_value(ROUND_FLOOR) * t
    p = book["bids"][0][0] * (Decimal(1) - Decimal(str(slip_cap_bps)) / 10000)
    return (p / t).to_integral_value(ROUND_CEILING) * t


def sim_fill(book: dict, side: str, qty: Decimal, slip_cap_bps: float = 30.0, taker: float = TAKER) -> dict:
    """Emulasi limit-IOC menembus buku nyata. Tidak mengisi di luar harga batas; sisa tidak terisi."""
    lim = limit_price(book, side, slip_cap_bps)
    levels = book["asks"] if side == "buy" else book["bids"]
    left, notional, got = qty, Decimal(0), Decimal(0)
    for p, q in levels:
        if (side == "buy" and p > lim) or (side == "sell" and p < lim):
            break
        take = min(left, q)
        notional += p * take; got += take; left -= take
        if left <= 0:
            break
    avg = float(notional / got) if got > 0 else None
    mid = book["mid"]
    slip = None if avg is None else ((avg / mid - 1) if side == "buy" else (1 - avg / mid)) * 10000
    return {"side": side, "req": float(qty), "filled": float(got), "avg_px": avg, "notional": float(notional),
            "fee": float(notional) * taker, "slip_bps_vs_mid": slip, "limit": float(lim), "partial": bool(left > 0)}


def depth_cost(book: dict, usd: float) -> dict:
    """Biaya (bps vs mid) menembus buku untuk order senilai usd; None bila buku kurang dalam."""
    out = {}
    for side, levels in (("buy", book["asks"]), ("sell", book["bids"])):
        left, cost, qty = Decimal(str(usd)), Decimal(0), Decimal(0)
        for p, q in levels:
            take = min(left, p * q); cost += take; qty += take / p; left -= take
            if left <= 0:
                break
        if left > 0:
            out[side] = None
        else:
            avg = float(cost / qty); m = book["mid"]
            out[side] = round(((avg / m - 1) if side == "buy" else (1 - avg / m)) * 10000, 3)
    return out


# --- Manajemen order spot (terverifikasi live 2026-11-06) -------------------
# Temuan lapangan: cancel spot DENGAN --order-id saja ditolak
# ("clOrdID is required"); --cl-ord-id saja ditolak ("order identity is
# required"). Satu-satunya bentuk yang diterima venue: KEDUANYA sekaligus.
# Order percobaan 7826255099 (vLINK_vUSDC) baru tertutup setelah keduanya
# dikirim. Karena itu semua cancel di bawah selalu mengirim dua identitas.

def spot_symbol_id(asset: str) -> int:
    mk = run_cli(["markets", "spot", "--format", "json"], env={})
    want = INTERNAL[asset]
    for m in (mk if isinstance(mk, list) else []):
        if isinstance(m, dict) and m.get("name") == want:
            return int(m["id"])
    raise ExecError(f"symbol spot tidak ditemukan: {want}")


def _auth_env(env: dict | None) -> dict:
    """Env lengkap (termasuk kunci). Dipakai hanya oleh panggilan ber-auth."""
    return dict(os.environ if env is None else env)


def open_orders(asset: str | None = None, env: dict | None = None) -> list[dict]:
    """Order spot yang masih hidup (butuh auth). Gagal-tertutup: error -> ExecError."""
    rows = run_cli(["orders", "list", "spot", "--format", "json"], env=_auth_env(env), timeout=25)
    rows = rows if isinstance(rows, list) else []
    if asset is None:
        return [r for r in rows if isinstance(r, dict)]
    want = INTERNAL[asset]
    return [r for r in rows if isinstance(r, dict) and r.get("symbol") == want]


def cancel_order(asset: str, order_id, cl_ord_id=None, env: dict | None = None) -> dict:
    """Cancel order spot. WAJIB kirim order-id DAN cl-ord-id sekaligus."""
    oid, cloid = order_id, cl_ord_id
    if cloid is None:  # ambil dari daftar order hidup, bukan menebak
        for r in open_orders(asset, env=env):
            if str(r.get("orderID")) == str(order_id):
                cloid = r.get("clOrdID")
                break
    if not cloid:
        raise ExecError(f"clOrdID tidak diketahui untuk order {order_id}; cancel ditolak venue")
    sid = spot_symbol_id(asset)
    return run_cli(["orders", "cancel", "spot", "--symbol-id", str(sid),
                    "--order-id", str(oid), "--cl-ord-id", str(cloid), "--format", "json"],
                   env=_auth_env(env), timeout=25)


def cancel_all(asset: str, env: dict | None = None) -> dict:
    """Sapu semua order spot hidup untuk satu aset. Return yang gagal (kosong = bersih)."""
    failed = []
    for r in open_orders(asset, env=env):
        try:
            cancel_order(asset, r.get("orderID"), r.get("clOrdID"), env=env)
        except ExecError as ex:
            failed.append({"orderID": r.get("orderID"), "err": str(ex)[:160]})
    sisa = open_orders(asset, env=env)
    return {"bersih": len(sisa) == 0, "gagal": failed, "sisa": sisa}
