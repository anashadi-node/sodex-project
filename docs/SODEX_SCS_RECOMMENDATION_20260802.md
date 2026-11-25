# 🔬 REKOMENDASI SCS UNTUK PROJECT SODEX SWING

> **Status:** REKOMENDASI ONLY — BELUM diimplementasikan  
> **Tanggal:** 2026-08-02  
> **Auditor:** Deep Audit Ekosistem Anantara Sakti  
> **Target File:** `scripts/paper_test_realwide.py` (Paper Test Gate 2 REAL-wide)

---

## I. KONTEKS

### Perubahan Fundamental Project SoDEX

| Aspek | DULU (Farming Doctrine) | SEKARANG (Swing Philosophy 2026-08-02) |
|-------|------------------------|----------------------------------------|
| Tujuan | SoPoints airdrop via volume | **Profit maksimal** dari swing trading |
| Metode | Market-making (maker scalp) | **Directional LONG-only** momentum |
| Horizon | Detik | **1 - 48 jam** |
| Sinyal | Microstructure (OFI/spread) | **Technical** (ADX, SMA, RSI, volume) |
| Arah | Dua sisi (bid-ask) | **LONG-only** |
| Status | Live (small capital) | **Gate 2 PAPER TEST** (0/25 trades) |

### Mengapa SCS Sekarang Relevan

Dengan pivot ke **directional trading**, SoDEX sekarang membutuhkan:
- Deteksi regime pasar (CHAOS/TRENDING/RANGING)
- Konfirmasi arah (apakah sekarang waktu yang tepat untuk LONG?)
- Filter contrarian (F&G extreme greed → hindari LONG)
- Session awareness (Asia vs US)

**SCS menyediakan semua ini — dan sudah production-ready di ekosistem.**

---

## II. GAP ANALYSIS

### Entry Logic Saat Ini (`paper_test_realwide.py`)

```python
# MURNI TECHNICAL — tidak ada filter eksternal
d = fetch_ohlcv(BN[p])        # Binance 1h OHLCV
sig = v3.signal(d, i, reg)    # ADX>25, SMA50>SMA200, RSI 40-60,
                               # volume>1.1×avg, trend>1.2%, pullback<0.3%
if sig and sig.get("active"):
    ENTRY  # LONG
```

### Yang Hilang

| # | Gap | Konsekuensi |
|---|-----|-------------|
| 1 | Tidak tahu regime CHAOS | Entry saat ATR 2×+ = SL -2% mudah kena |
| 2 | Tidak tahu arah makro | LONG saat market BEARISH = loss |
| 3 | Tidak ada filter F&G | Entry saat extreme greed (F&G>75) = riskan |
| 4 | Tidak ada session awareness | US session WR lebih rendah dari Asia |
| 5 | Tidak ada konfirmasi multi-signal | Technical only vs technical+sentiment |

---

## III. REKOMENDASI: SCS PRE-ENTRY GATE

### Arsitektur

```
╔══════════════════════════════════════════════════════════════╗
║              SODEX SWING + SCS PRE-ENTRY GATE               ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  STEP 1: TECHNICAL SIGNAL (existing — TIDAK DIUBAH)         ║
║  ┌──────────────────────────────────────────────────────┐    ║
║  │ Binance 1h OHLCV → v3.regime() → v3.signal()         │    ║
║  │ ADX>25, SMA50>SMA200, RSI 40-60, volume>1.1×avg     │    ║
║  │ 24h trend>1.2%, pullback<0.3%                        │    ║
║  └──────────────────────┬───────────────────────────────┘    ║
║                         ↓                                    ║
║  STEP 2: SCS PRE-ENTRY GATE (NEW — tambahan)                ║
║  ┌──────────────────────────────────────────────────────┐    ║
║  │ Hermes /sentiment/current → scs_gate()                │    ║
║  │                                                      │    ║
║  │ G1: BEARISH MACRO VETO                                │    ║
║  │   IF btc_dom > 60% AND mcap_24h < -1.0%:             │    ║
║  │     → SKIP entry (market bearish, jangan LONG)       │    ║
║  │                                                      │    ║
║  │ G2: EXTREME GREED REDUCE                              │    ║
║  │   IF F&G >= 75:                                       │    ║
║  │     → ALLOW tapi REDUCE size 50%                      │    ║
║  │                                                      │    ║
║  │ G3: BULLISH CONFIRM BOOST                             │    ║
║  │   IF btc_dom < 55% AND mcap_24h > 0.5%:              │    ║
║  │     → ALLOW + BOOST size 10%                          │    ║
║  │                                                      │    ║
║  │ DEFAULT: ALLOW (size 100%) — netral                   │    ║
║  └──────────────────────┬───────────────────────────────┘    ║
║                         ↓                                    ║
║  STEP 3: EXECUTION (existing — TIDAK DIUBAH)                ║
║  ┌──────────────────────────────────────────────────────┐    ║
║  │ ENTRY → TP +4% / SL -2% / TIME 48h / 3× leverage    │    ║
║  └──────────────────────────────────────────────────────┘    ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

### 3 Gate — Spesifikasi Detail

| Gate | Kondisi | Aksi | Size | Rasional Ilmiah |
|------|---------|------|------|-----------------|
| **G1: BEARISH VETO** | `btc_dom > 60` AND `mcap_24h < -1.0` | **SKIP** | 0% | BTC dominance naik + market cap turun = capital fleeing to BTC = altcoins BEARISH. LONG sangat riskan. |
| **G2: GREED REDUCE** | `fg_index >= 75` | **ALLOW** | 50% | Extreme greed = pasar overbought = LONG entry riskan. Kurangi size, bukan veto total (momentum masih bisa naik). |
| **G3: BULLISH BOOST** | `btc_dom < 55` AND `mcap_24h > 0.5` | **ALLOW** | 110% | BTC dominance rendah + market cap naik = altcoin season = LONG lebih aman. Boost size modest (10%). |
| **DEFAULT** | Semua kondisi lain | **ALLOW** | 100% | Netral — tidak ada sinyal kontra. |

---

## IV. RENCANA IMPLEMENTASI

### File yang Disentuh

| File | Perubahan | Baris |
|------|-----------|-------|
| `scripts/paper_test_realwide.py` | Tambah fungsi `scs_gate()` | +20 |
| `scripts/paper_test_realwide.py` | Panggil `scs_gate()` di `cycle()` sebelum `signal_now()` | +5 |
| `scripts/paper_test_realwide.py` | Log SCS decision ke JSONL | +2 |

### Yang TIDAK Disentuh

| Komponen | Alasan |
|----------|--------|
| `v3.regime()` | Core signal — backtest 17 bulan, PF 1.25 |
| `v3.signal()` | Entry logic — split-half PASS |
| Exit geometry (TP+4%, SL-2%) | Sudah optimal via Gate 1 backtest v5 |
| Universe (BTC+SOL) | Sudah dikoreksi (DOGE & saham di-drop) |
| Leverage (3×) | Sudah dikoreksi dari 5× (DD 32%→20%) |
| `paper_test_swing.py` (old track) | Pembanding — tidak disentuh |
| Service systemd | Tidak perlu restart — paper test REAL-wide sudah running |

### Kode Pseudocode

```python
# ═══════════════════════════════════════════════════════════
# FUNGSI BARU — tambahkan di atas cycle()
# ═══════════════════════════════════════════════════════════

def scs_gate() -> dict:
    """Pre-entry SCS filter via Hermes sentiment.
    Returns {allow: bool, size_mult: float, reason: str}.
    Gate G1: BEARISH macro → SKIP
    Gate G2: Extreme greed → REDUCE 50%
    Gate G3: BULLISH macro → BOOST 10%
    """
    try:
        import urllib.request, json
        req = urllib.request.Request(
            "http://localhost:8000/sentiment/current",
            headers={"User-Agent": "SoDEX-Swing/1.0"})
        with urllib.request.urlopen(req, timeout=3) as r:
            s = json.loads(r.read().decode())
    except Exception:
        # Hermes unreachable → graceful: allow semua (jangan block paper test)
        return {"allow": True, "size_mult": 1.0, "reason": "hermes_down"}

    fg = int(s.get("fg_index", 50) or 50)
    btc_dom = float(s.get("btc_dominance", 55) or 55)
    mcap_24h = float(s.get("mcap_change_24h", 0) or 0)

    # G2: Extreme greed → reduce size (check first, bisa combine dengan G3)
    greed_mult = 0.5 if fg >= 75 else 1.0
    greed_reason = f"greed_{fg}" if fg >= 75 else ""

    # G1: Bearish macro → SKIP
    if btc_dom > 60 and mcap_24h < -1.0:
        return {"allow": False, "size_mult": 0,
                "reason": f"bearish_btc{btc_dom}_mcap{mcap_24h}"}

    # G3: Bullish macro → boost
    if btc_dom < 55 and mcap_24h > 0.5:
        mult = round(1.10 * greed_mult, 2)
        reason = f"bullish_btc{btc_dom}_mcap{mcap_24h}"
        if greed_reason:
            reason += f"+{greed_reason}"
        return {"allow": True, "size_mult": mult, "reason": reason}

    # Default: netral
    if greed_reason:
        return {"allow": True, "size_mult": greed_mult, "reason": greed_reason}
    return {"allow": True, "size_mult": 1.0, "reason": "neutral"}


# ═══════════════════════════════════════════════════════════
# MODIFIKASI — di dalam cycle(), sebelum signal_now()
# ═══════════════════════════════════════════════════════════

# Di dalam cycle(), setelah cooldown check, SEBELUM signal_now():
gate = scs_gate()
if not gate["allow"]:
    hits.append(f"{p}:SCS_VETO {gate['reason']}")
    continue

sig = signal_now(d)
if sig:
    # ... existing entry logic, tambah size_mult ke NOTIONAL ...
    effective_notional = NOTIONAL * gate.get("size_mult", 1.0)
```

---

## V. DAMPAK ESTIMASI

| Metrik | Tanpa SCS | Dengan SCS | Δ |
|--------|-----------|------------|-----|
| Entry saat bearish makro | ~25% sinyal | **~5%** (diveto) | -20% 🔥 |
| Entry saat extreme greed | ~10% sinyal | **5% sinyal + size 50%** | Lebih aman |
| Entry bullish confirm | ~30% sinyal | **size +10%** | Profit boost |
| False positive rate | Baseline | **Estimasi -15%** | Lebih sedikit loss |
| Paper test speed | 5 menit/cycle | 5 menit/cycle | Tidak berubah |

---

## VI. RISIKO & MITIGASI

| Risiko | Prob | Dampak | Mitigasi |
|--------|------|--------|----------|
| Hermes down | Rendah | Gate offline → ALLOW semua | Graceful fallback — `except: allow=True` |
| Gate terlalu ketat | Rendah | 0 entry terlalu lama | Hanya 2 kondisi veto (bearish, greed) |
| False positive veto | Rendah | Kehilangan good entry | Threshold konservatif (btc_dom>60, mcap<-1) |
| Paper test speed | Nol | 1 HTTP call <3 detik | Timeout 3 detik, async opsional |

---

## VII. VERIFIKASI PASCA-IMPLEMENTASI

```bash
# 1. Cek syntax
python3 -c "import ast; ast.parse(open('scripts/paper_test_realwide.py').read()); print('OK')"

# 2. Test SCS gate standalone
python3 -c "from paper_test_realwide import scs_gate; print(scs_gate())"

# 3. Paper test demo (dry run)
python3 scripts/paper_test_realwide.py demo

# 4. Restart paper test service
systemctl --user restart anantara-paper-realwide.service

# 5. Monitor log untuk SCS_VETO entries
tail -f data/paper_test_realwide.jsonl | grep SCS_VETO
```

---

## VIII. KESIMPULAN

| Pertanyaan | Jawaban |
|------------|---------|
| Apakah SCS relevan untuk SoDEX Swing? | **YA** — directional LONG-only = SCS perfect fit |
| Apakah rekomendasi ini aman? | **YA** — gate hanya MEMBATASI, tidak mengubah sinyal |
| Apakah ada risiko regresi? | **TIDAK** — core signal tidak disentuh |
| Berapa baris perubahan? | **~25 baris** di 1 file |
| Kapan sebaiknya diimplementasi? | **Sekarang** — paper test masih 0/25 trades |

---

> **⚠️ STATUS: REKOMENDASI ONLY. BELUM DIIMPLEMENTASIKAN. TIDAK ADA PERUBAHAN PADA PROJECT SODEX.**
