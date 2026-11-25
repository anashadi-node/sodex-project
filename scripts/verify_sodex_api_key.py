#!/usr/bin/env python3
"""Verifikasi API key SoDEX pasca-rotasi — TANPA menampilkan nilai secret.

Cek: (1) env var ADA, (2) auth bekerja via orders list, (3) balance terbaca.
Output HANYA status boolean + angka, bukan nilai key.
"""
import json, os, subprocess, sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SODEX = str(PROJECT / "bin" / "sodex")


def run(args, timeout=25):
    return subprocess.run([SODEX] + args, capture_output=True, text=True,
                          timeout=timeout, env=os.environ.copy())


def main():
    api_name = os.environ.get("SODEX_API_KEY", "")
    priv = os.environ.get("SODEX_PRIVATE_KEY", "")
    print(f"API key name: {'ADA ✓' if api_name else 'KOSONG ✗'}")
    print(f"Private key:  {'ADA (hex, disembunyikan) ✓' if priv.startswith('0x') else ('ADA (format?!) ⚠️' if priv else 'KOSONG ✗')}")
    if priv and not priv.startswith("0x"):
        print("  ⚠️ SODEX_PRIVATE_KEY harus diawali 0x (hex). Cek .env.")
    if not (api_name and priv):
        print("FAIL: salah satu key kosong — rotasi belum lengkap.")
        sys.exit(1)

    # Test 1: orders list perps (butuh auth)
    r = run(["orders", "list", "perps", "--format", "json"])
    auth_ok = r.returncode == 0 and "error" not in (r.stdout or "").lower()
    print(f"Auth (orders list): {'OK ✓' if auth_ok else f'GAGAL ✗ ({r.stderr[:80]})'}")
    if not auth_ok:
        sys.exit(1)

    # Test 2: balance perps
    r2 = run(["balance", "perps", "--format", "json"])
    bal_ok = r2.returncode == 0
    print(f"Balance perps: {'OK ✓' if bal_ok else 'GAGAL ✗'}")
    sys.exit(0 if (auth_ok and bal_ok) else 1)


if __name__ == "__main__":
    main()
