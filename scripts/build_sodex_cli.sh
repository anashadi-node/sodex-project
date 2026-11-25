#!/bin/bash
# ANANTARA SAKTI — Build official SoDEX CLI via Docker (no host Go needed)
#
# Produces bin/sodex (official sodex-tech/sodex-go-sdk-public CLI).
# CLI handles EIP-712 signing correctly — preferred over reimplementing.
# Read-only commands (markets/tickers/orderbook) need NO wallet.
# Trading commands need SODEX_PRIVATE_KEY + SODEX_API_KEY + SODEX_ACCOUNT_ID.
#
# Usage: bash scripts/build_sodex_cli.sh

set -euo pipefail
cd /home/USER/anantara-sakti

OUT=/tmp/gobuild_sodex
mkdir -p "$OUT" bin

echo "Building sodex CLI (requires Go >=1.25, using golang:1.25 container)..."
docker run --rm -v "$OUT":/out -e GOBIN=/out golang:1.25 \
    bash -c "go install github.com/sodex-tech/sodex-go-sdk-public/cmd/sodex@latest"

cp "$OUT/sodex" bin/sodex
chmod +x bin/sodex
echo "✅ bin/sodex installed:"
./bin/sodex --testnet tickers perps 2>&1 | head -3
