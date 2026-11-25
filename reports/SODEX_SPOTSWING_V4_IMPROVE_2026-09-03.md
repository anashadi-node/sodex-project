# SODEX — SPOT SWING v4 IMPROVING LANJUTAN (2026-09-03)
# Mode adaptif + fix ADX + FAPI fallback — menuju penyumbang profit utama
# Hermes Anantara v2

---

## BUG/BOTTLENECK DITEMUKAN (dari sarana riset & problem-solving)

### 🔴 Bug 1: ADX pakai close sebagai H/L (fatal)
- Gejala: v4 tidak pernah membuka posisi (0 trade)
- Root cause: `adx(c,c,c)` memakai close untuk high/low → ADX tertekan 11-24
  (real H/L = 15-48), hampir mustahil ≥25
- **Fix: fetch H/L sejati dari Binance klines → ADX benar (UNI 36, PEPE 48)**
- Pelajaran: verifikasi fungsi teknis SEBELUM men-tune parameter (systematic-debugging)

### 🔴 Bug 2: Sinyal terlalu ketat → 0 fire di market sideways
- Butuh c>SMA50 AND mom5>0 AND ADX≥25 AND regime BTC bersamaan
- Di market konsolidasi 5 hari, ADX 15-24 + BTC di bawah SMA200 → 0 entry
- **Fix: relaksasi ilmiah — momentum OR (c>SMA50 ATAU mom5>0.5%), ADX ambang 20**

### 🟡 Bottleneck 3: Regime SMA200 kaku → mati total di downtrend
- BTC 5 hari hanya 21% jam di atas SMA200 → gate selalu OFF
- **Fix: regime EMA50+mom6 (adaptif) + MODE ADAPTIF**

### 🟡 Bottleneck 4: HYPE tidak ada di Binance spot → HTTP 400
- **Fix: FAPI fallback utk perp-only (HYPE, XAUT)**

---

## MODE ADAPTIF — terobosan (deployed)

**Prinsip:** saat BTC down (regime OFF), jangan mati total — long pair yang
INDEPENDEN-BULL (momentum+ADX kuat tanpa mengandalkan BTC), batasi 1 posisi.

**Bukti ilmiah (data live 2026-09-03):**
```
Saat BTC di bawah EMA50: UNI (ADX 36, c>SMA50), TON (ADX 20, c>SMA50),
LTC (ADX 23, c>SMA50) → TETAP FIRE signal
```
→ 3/12 pair independen-bull. Mode adaptif memanfaatkan ini.

**Entry pertama tercatat:** `vTON_vUSDC LONG @ 1.601 | mode=adaptif` ✅

---

## STATUS DEPLOY (10 service total)

| Service | Status |
|---------|:------:|
| 6 track SoDEX (swing/partial/twoway/realwide/spot/donchian) | ✅ active |
| Hyperliquid & Aster (multi-venue) | ✅ active |
| **Spot Swing v4** (baru) | ✅ active, mode adaptif berjalan |
| Progress reporter | ✅ active |

---

## ARSITEKTUR SPOT_SWING v4 (final)

```
Sinyal: momentum (c>SMA50 ATAU mom5>0.5%) + ADX≥20 (H/L sejati) — long-only
          │
          ▼
Regime: BTC>EMA50 ATAU mom6>0?
   ├─ YA → mode NORMAL (bebas semua pair liquid, $100)
   └─ TIDAK → mode ADAPTIF (long 1 pair independen-bull saja)
          │
          ▼
Filter likuiditas: spot SoDEX ≥ $3K/24h (7 pair: vBTC/vTON/vETH/vHYPE/vXRP/vLINK/vUNI)
          │
          ▼
Exit: TP 2.5% / SL 1.5% DARI t=0 / time-stop 30h (pola REALWIDE)
          │
          ▼
State: data/paper_test_spot_swing_v2_state.json (bersih)
```

---

## KEPUTUSAN ILMIAH (dicatat di config canonical)

1. **ADX ambang 20** (bukan 25) — spot/alt lebih konsolidatif dari futures trending
2. **Momentum OR** (SMA50 ATAU mom5) — dua jalur, lebih adaptif
3. **Regime EMA50+mom6** — filter tren tapi tidak kaku
4. **Mode adaptif** — long pair independen saat BTC down, max 1 posisi
5. **FAPI fallback** — HYPE/XAUT perp-only

---

## MONITORING

- Posisi vTON adaptif: akan keluar via TP/SL/time-stop (SL t=0, aman)
- n≥50 → evaluasi bootstrap CI95
- Kriteria sukses: ROI ≥ 0.7% + CI95 EV>0 → jadi track penyumbang profit utama
- Banding mode: normal vs adaptif (mana yang EV lebih tinggi)

---

*Laporan 2026-09-03 | Hermes Anantara v2 | systematic debugging + data-driven*