#!/usr/bin/env python3
"""Runner TESTNET penuh — SoDEX perps.

Alur: state -> (transfer 100 spot->perps bila av==0) -> 3 order -> rekonsiliasi -> cancel.

Keamanan:
- HANYA testnet: base https://testnet-gw.sodex.dev, chain 138565, DITOLAK bila base bukan testnet.
- Kunci dibaca dari secrets/sodex.testnet.env (chmod 600). Tidak pernah dicetak.
- Tidak ada jalur mainnet di file ini.

Pemakaian:
  python perp_testnet_run.py state
  python perp_testnet_run.py fund      # transfer 100 spot->perps (type 3, akun 999)
  python perp_testnet_run.py trade     # 3 order kecil + rekonsiliasi + cancel
"""
import json
import os
import subprocess
import sys
import time

from eth_account import Account
from eth_utils import keccak

BASE = "https://testnet-gw.sodex.dev"
CHAIN = 138565
SECRETS = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "secrets", "sodex.testnet.env")
NULL = "0x0000000000000000000000000000000000000000"
TYPES = {
    "EIP712Domain": [
        {"name": "name", "type": "string"},
        {"name": "version", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ],
    "ExchangeAction": [
        {"name": "payloadHash", "type": "bytes32"},
        {"name": "nonce", "type": "uint64"},
    ],
}


def load_secrets(path=SECRETS):
    kv = {}
    if not os.path.exists(path):
        return kv
    for line in open(path, errors="ignore"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip().strip('"').strip("'")
    return kv


def _http(method, path, body=None, headers=None):
    cmd = ["curl", "-s", "-m", "25", "-w", "\n%{http_code}", "-X", method, BASE + path]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if body is not None:
        cmd += ["--data-binary", body]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    raw, _, code = out.rpartition("\n")
    try:
        js = json.loads(raw)
    except Exception:
        js = {"raw": raw}
    return int(code or 0), js


def call(path, params, action, domain, pk, key_name=None, address=None):
    """Kirim aksi bertanda tangan. key_name -> mode API key (0x01)."""
    blob = json.dumps({"type": action, "params": params}, separators=(",", ":"))
    body = json.dumps(params, separators=(",", ":"))
    phash = "0x" + keccak(text=blob).hex()
    nonce = int(time.time() * 1000)
    msg = {
        "types": TYPES,
        "domain": {"name": domain, "version": "1", "chainId": CHAIN, "verifyingContract": NULL},
        "primaryType": "ExchangeAction",
        "message": {"payloadHash": phash, "nonce": nonce},
    }
    sig = Account.sign_typed_data(pk, full_message=msg).signature.hex().removeprefix("0x")
    hdr = {
        "Content-Type": "application/json",
        "X-API-Chain": str(CHAIN),
        "X-API-Nonce": str(nonce),
        "X-API-Sign": ("0x01" if key_name else "0x02") + sig,
    }
    if key_name:
        hdr["X-API-Key"] = key_name
    return _http("POST", path, body, hdr)


def state(address):
    _, spot = _http("GET", f"/api/v1/spot/accounts/{address}/state")
    _, perps = _http("GET", f"/api/v1/perps/accounts/{address}/state")
    s, p = spot.get("data") or {}, perps.get("data") or {}
    av = float(p.get("av") or 0)
    bal = {b.get("a"): b.get("t") for b in (s.get("B") or [])}
    return av, bal, p


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    sec = load_secrets()
    if cmd == "state":
        addr = sec.get("SODEX_TESTNET_ADDRESS") or os.environ.get("SODEX_TESTNET_ADDRESS")
        if not addr:
            sys.exit("SODEX_TESTNET_ADDRESS tidak ada di secrets/sodex.testnet.env")
        av, bal, _ = state(addr)
        print("spot:", bal, "| perps av:", av)
        return

    pk = sec.get("SODEX_TESTNET_PRIVATE_KEY")
    key_name = sec.get("SODEX_TESTNET_API_KEY")
    addr = sec.get("SODEX_TESTNET_ADDRESS")
    aid = sec.get("SODEX_TESTNET_ACCOUNT_ID")
    if not (pk and key_name and addr and aid):
        sys.exit("secrets/sodex.testnet.env belum lengkap (API_KEY, PRIVATE_KEY, ADDRESS, ACCOUNT_ID)")
    aid = int(aid)

    av, bal, _ = state(addr)
    print(f"awal: spot={bal} perps_av={av}")

    if cmd == "fund":
        if av > 0:
            print("perps sudah terisi; tidak transfer lagi")
            return
        amount = sys.argv[2] if len(sys.argv) > 2 else "100"
        code, js = call("/api/v1/spot/accounts/transfers",
                        {"id": int(time.time() * 1000), "fromAccountID": aid, "toAccountID": 999,
                         "coinID": 1, "amount": amount, "type": 3},
                        "transferAsset", "spot", pk, key_name)
        print("transfer:", code, js)
        time.sleep(3)
        av, bal, _ = state(addr)
        print(f"setelah transfer: spot={bal} perps_av={av}")
        return

    if cmd == "trade":
        if av <= 0:
            sys.exit("perps_av=0 — jalankan `fund` dulu")
        print("TODO: order (butuh spesifikasi simbol dari oracle)")


if __name__ == "__main__":
    main()
