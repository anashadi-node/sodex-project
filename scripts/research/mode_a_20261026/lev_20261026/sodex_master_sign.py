#!/usr/bin/env python3
"""Penandatangan aksi SoDEX dengan MASTER WALLET (prefix 0x02).

CLI `bin/sodex` selalu memakai prefix 0x01 (mode API key) sehingga transfer
ditolak "API key not found" di testnet. Skrip ini menandatangani sendiri
sesuai dokumen resmi:
  payloadHash = keccak256(compact JSON {"type":..,"params":..})
  EIP-712 ExchangeAction{payloadHash, nonce} pada domain {name: spot|futures, version 1,
  chainId 286623|138565, verifyingContract 0x0}
  X-API-Sign = 0x02 || 65-byte signature

Kunci HANYA dibaca dari environment / .env; tidak pernah dicetak.
"""
import argparse
import json
import os
import sys
import time

import subprocess

from eth_account import Account
from eth_utils import keccak

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


def load_env(path=".env"):
    kv = {}
    if os.path.exists(path):
        for line in open(path, errors="ignore"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip().strip('"').strip("'")
    return kv


def payload_hash(action, params):
    # Compact JSON, urutan field = urutan dict (harus sama dgn struct Go).
    blob = json.dumps({"type": action, "params": params}, separators=(",", ":"))
    return "0x" + keccak(text=blob).hex(), blob


def sign(pk, phash, nonce, domain_name, chain_id, prefix="0x02"):
    msg = {
        "types": TYPES,
        "domain": {"name": domain_name, "version": "1", "chainId": chain_id, "verifyingContract": NULL},
        "primaryType": "ExchangeAction",
        "message": {"payloadHash": phash, "nonce": nonce},
    }
    sig = Account.sign_typed_data(pk, full_message=msg)
    return prefix + sig.signature.hex().removeprefix("0x")


def send(base, path, pk, params, action, domain_name, chain_id, nonce_unit="s", mode="master", key_name=None):
    phash, blob = payload_hash(action, params)
    body = json.dumps(params, separators=(",", ":"))
    nonce = int(time.time() * 1000) if nonce_unit == "ms" else int(time.time())
    prefix = "0x01" if mode == "apikey" else "0x02"
    sig = sign(pk, phash, nonce, domain_name, chain_id, prefix)
    hdr = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-Chain": str(chain_id),
        "X-API-Nonce": str(nonce),
        "X-API-Sign": sig,
    }
    if mode == "apikey" and key_name:
        hdr["X-API-Key"] = key_name
    cmd = ["curl", "-s", "-m", "25", "-w", "\n%{http_code}", "-X", "POST", base.rstrip("/") + path]
    for k, v in hdr.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd += ["--data-binary", body]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    body, _, code = out.rpartition("\n")
    return int(code or 0), body, phash, nonce


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["transfer"])
    ap.add_argument("--base", default="https://testnet-gw.sodex.dev")
    ap.add_argument("--chain", type=int, default=138565)
    ap.add_argument("--env", default=os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env"))
    ap.add_argument("--amount", default="1")
    ap.add_argument("--from-aid", type=int, required=True)
    ap.add_argument("--to-aid", type=int, default=999)
    ap.add_argument("--coin", type=int, default=1)
    ap.add_argument("--type", type=int, default=3)
    ap.add_argument("--nonce-unit", default="s", choices=["s", "ms"])
    ap.add_argument("--signer", default="master", choices=["master", "apikey"])
    ap.add_argument("--key-name", default=None)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    pk = os.environ.get("SODEX_PRIVATE_KEY") or load_env(a.env).get("SODEX_PRIVATE_KEY")
    if not pk:
        sys.exit("SODEX_PRIVATE_KEY tidak ada (isi .env; nilai tidak dicetak)")

    uniq = int(time.time() * 1000)
    params = {
        "id": uniq,
        "fromAccountID": a.from_aid,
        "toAccountID": a.to_aid,
        "coinID": a.coin,
        "amount": str(a.amount),
        "type": a.type,
    }
    if a.dry:
        ph, blob = payload_hash("transferAsset", params)
        print("blob:", blob)
        print("payloadHash:", ph)
        print("signer:", Account.from_key(pk).address)
        return
    code, text, ph, nonce = send(a.base, "/api/v1/spot/accounts/transfers", pk,
                                 params, "transferAsset", "spot", a.chain, a.nonce_unit,
                                 a.signer, a.key_name)
    print(f"http={code} nonce={nonce} ph={ph[:18]}...")
    print(text[:500])


if __name__ == "__main__":
    main()
