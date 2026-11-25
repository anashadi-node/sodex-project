# ANANTARA SAKTI — SoDEX API Patterns & Best Practices

Panduan integrasi dengan SoDEX (sodex.com) — perps DEX di ValueChain mainnet.
Dokumen ini mencakup autentikasi, endpoint mapping, format data, dan error handling.

---

## 1. Arsitektur Integrasi

SoDEX menggunakan dua jalur komunikasi:
- **Public data** (unsigned): REST API untuk market data, ticker, klines, account state
- **Signed actions** (EIP-712): Trading via `bin/sodex` CLI (Go binary, Ethereum EIP-712 signing)

```
┌─────────────────────┐     ┌────────────────────────┐
│  ANANTARA (Python)  │────▶│  SoDEX REST API         │
│  hermes_bridge.py   │     │  mainnet-gw.sodex.dev    │
│  sodex_farming.py   │     │  /api/v1/perps/*        │
└─────────┬───────────┘     │  (public, unsigned)      │
          │                 └────────────────────────┘
          │ CLI subprocess
          ▼
┌─────────────────────┐     ┌────────────────────────┐
│  bin/sodex (Go)     │────▶│  SoDEX Signed Actions   │
│  EIP-712 signing    │     │  orders/place, leverage, │
│  perps orders       │     │  transfer, cancel        │
└─────────────────────┘     └────────────────────────┘
```

---

## 2. Public REST API Endpoints

Base URL: `https://mainnet-gw.sodex.dev/api/v1/perps`

### Market Data (unsigned, gratis, no rate limit)

| Endpoint | Method | Purpose |
|---|---|---|
| `/markets/symbols` | GET | List semua symbol + metadata (minQty, tickSize, leverage tiers) |
| `/markets/tickers` | GET | Price 24h: lastPx, highPx, lowPx, quoteVolume, changePct |
| `/markets/{symbol}/klines` | GET | OHLCV klines: ?interval=1h&limit=72 |
| `/markets/{symbol}/orderbook` | GET | L1 order book (best bid/ask) |

### Account Data (unsigned, pakai address)

| Endpoint | Method | Purpose |
|---|---|---|
| `/accounts/{addr}/state` | GET | Account value (av), margin, PnL |
| `/accounts/{addr}/balances` | GET | Balance per asset |
| `/accounts/{addr}/positions` | GET | Open positions + unrealized PnL |
| `/accounts/{addr}/orders` | GET | Open/closed orders |
| `/accounts/{addr}/trades` | GET | Trade history |
| `/accounts/{addr}/fundings` | GET | Funding payment history |
| `/accounts/{addr}/fee-rate` | GET | Maker/taker fee rates |

### Klines Format
```json
{
  "data": [
    {
      "t": 1714000000,    // timestamp epoch seconds
      "o": "0.1623",      // open (string!)
      "h": "0.1650",
      "l": "0.1601",
      "c": "0.1634",
      "v": "45230.12"     // volume (string!)
    }
  ]
}
```
⚠️ **PENTING:** Semua harga dan volume adalah **STRING**, bukan number!
Konversi dengan `float()` sebelum perhitungan.

---

## 3. Signed Actions (via bin/sodex CLI)

### CLI Command Format
```bash
bin/sodex --rpc-url <RPC_URL> \
          --private-key <PRIVATE_KEY> \
          <command> <subcommand> [flags...]
```

### Perintah Penting

| Command | Purpose | Contoh |
|---|---|---|
| `balance perps <addr>` | Cek balance (vUSDC) | `bin/sodex balance perps 0x...` |
| `orders place perps` | Place order baru | `--symbol BTC-USD --side buy --type limit --price ... --qty ... --tif gtx` |
| `orders cancel <id>` | Cancel order | `--symbol BTC-USD` |
| `leverage set <symbol> <lev>` | Set leverage | `bin/sodex leverage set BTC-USD 5` |

### Order Parameters
```bash
--symbol BTC-USD       # Format: BASE-QUOTE
--side buy|sell        # Direction
--type limit|market    # Order type
--price "65000.00"     # Limit price (string)
--qty "0.001"          # Quantity (string)
--tif gtc|ioc|gtx      # Time-in-force: GTC=Good-Till-Cancel, IOC=Immediate-or-Cancel, GTX=Good-Till-Crossed (post-only)
```

### Leverage Command
```bash
# SoDEX leverage set MENCETAK TEXT, bukan JSON.
# Parsing output: cari "leverage set to X" di stdout
bin/sodex leverage set BTC-USD 5
```

### Output Parsing
⚠️ **Masalah yang sering terjadi:**
- Balance print dalam format tabel text, bukan JSON
- Perlu parsing manual `.split()` untuk ambil angka
- Error print ke stderr dalam format text bebas

```python
# Pattern yang aman untuk parsing output:
result = subprocess.run(["bin/sodex", "balance", "perps", addr],
                        capture_output=True, text=True, timeout=30)
if result.returncode != 0:
    # Error handling
    log.error(f"sodex CLI error: {result.stderr[:200]}")
    return None
# Parse stdout — bisa JSON atau text
try:
    return json.loads(result.stdout)
except json.JSONDecodeError:
    return _parse_text_output(result.stdout)
```

---

## 4. EIP-712 Signing (Internal — tidak perlu disentuh)

Signing ditangani oleh bin/sodex CLI secara internal. Yang perlu diketahui:

- Private key: dari `.env` variabel `SODEX_PRIVATE_KEY` (format hex, 64 char)
- Address: dari `.env` variabel `SODEX_ADDRESS` (format 0x...)
- CLI menyimpan state di `~/.sodex/` (nonce tracker, contract addresses)
- Nonce management otomatis oleh CLI
- Gas sponsorship: ValueChain mensponsori gas fee untuk trading perps

---

## 5. Data Mapping: SoDEX ↔ Internal

### Price Format
| SoDEX | Internal | Catatan |
|---|---|---|
| `lastPx` | `last` | Harga terakhir |
| `bid` | `bid` | Best bid L1 |
| `ask` | `ask` | Best ask L1 |
| Semua STRING | Float | Konversi wajib |

### Symbol Format
| SoDEX | Internal | Freqtrade |
|---|---|---|
| `BTC-USD` | `BTC-USD` | `BTC/USDT:USDT` |
| `ETH-USD` | `ETH-USD` | `ETH/USDT:USDT` |
| `SOL-USD` | `SOL-USD` | `SOL/USDT:USDT` |

### Quantity Precision
- Qty precision per symbol dari endpoint `/markets/symbols` → `minQty`
- Round DOWN ke precision yang benar sebelum kirim order
- Contoh: BTC-USD minQty = 0.001 → qty harus kelipatan 0.001

### Price Precision
- Price precision dari `/markets/symbols` → `tickSize`
- Round ke precision yang benar
- Contoh: BTC-USD tickSize = 0.10 → price harus kelipatan 0.10

---

## 6. Error Handling

### CLI Error Patterns

| Pattern | Arti | Handling |
|---|---|---|
| `insufficient balance` | Balance tidak cukup | Skip pair, log warning |
| `order would cross` | Harga crossing order book | Adjust price ±1 tick, retry 1x |
| `position not found` | Posisi sudah tertutup | Ignore (race condition normal) |
| `nonce too low` | Nonce conflict | Retry after 2s |
| `RPC timeout` | Node tidak responsif | Retry 3x dengan backoff 5s |
| `symbol not found` | Symbol tidak ada | Hapus dari universe, alert |

### Retry Policy
```python
MAX_RETRIES = 3
BASE_DELAY = 2.0  # detik

for attempt in range(MAX_RETRIES):
    try:
        result = subprocess.run(sodex_cmd, timeout=30)
        if result.returncode == 0:
            return result
        if "nonce too low" in result.stderr:
            time.sleep(BASE_DELAY * (2 ** attempt))
            continue
        if "insufficient" in result.stderr:
            return None  # tidak bisa di-retry
    except subprocess.TimeoutExpired:
        time.sleep(BASE_DELAY * (2 ** attempt))
        continue
return None  # semua retry gagal
```

---

## 7. Fee Structure

| Tier | Maker | Taker | Syarat |
|---|---|---|---|
| Tier 0 | 0.012% | 0.024% | Default |
| Tier 1 | 0.009% | 0.018% | Volume > $10M / 30d |
| Tier 2 | 0.006% | 0.012% | Volume > $50M / 30d |

### SoPoints Airdrop
- SoPoints diberikan berdasarkan volume trading futures
- Weekly pool: 1,000,000 SoPoints / minggu
- Ranking menentukan share dari pool
- SoPoints → $VAR airdrop (ratio belum diumumkan)

---

## 8. Security

- [x] Private key di `.env`, chmod 600, tidak pernah di-commit
- [x] CLI hanya dipanggil via subprocess (tidak expose key ke log)
- [x] Leverage capped di 5x (governor gate)
- [x] Max daily volume cap untuk SoDEX farming
- [x] Kill switch menutup semua posisi SoDEX juga
- [x] Balance monitoring setiap 2 menit (stop-loss)
- [x] Isolated margin mode (satu posisi gagal tidak ganggu yang lain)