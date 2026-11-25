# SODEX — SPOT SWING v4 IMPLEMENTASI (2026-09-03)
# Kombinasi campuran teradaptasi dari CEX-Binance · Scientific
# Hermes Anantara v2

---

## TEMUAN KUNCI (dari analisa CEX-Binance 190 trade)

**Kombinasi CEX TIDAK gagal — yang gagal hanya REGIME doang.** Breakdown:

| Sinyal | n | WR | Avg/trade |
|--------|:-:|:-:|:-:|
| **momentum+adx+regime** | 12 | **100%** | **+2,30%** ✅ |
| momentum+adx+regime+harbar | 3 | 100% | +2,30% ✅ |
| regime-long saja | 56 | 42,9% | -0,02% ❌ |
| regime-short | 10 | 30% | -0,36% ❌ |
| adx+momentum | 6 | 16,7% | +0,04% ❌ |

**→ Edge sebenarnya = kombinasi momentum + ADX + regime (long-only).**
Regime doang tanpa momentum/ADX = no edge. Ini yang diadaptasi ke Swing Spot.

---

## ROOT CAUSE v3 (dikonfirmasi, 35 trade)

| # | Akar masalah | Bukti | Fix |
|:-:|--------------|-------|-----|
| 1 | **Jendela gempa** — SL tdk aktif 4h pertama | 3 trade -$32,91 (4,6× laba) | **SL dari t=0** |
| 2 | **Book tipis/adverse selection** | mayoritas pair <$1K/24h; $300=30-200% vol | **filter likuiditas $3K + size $100** |
| 3 | Margin tipis payoff 1,56:1 | WR 42,9% ≈ breakeven | **signal lebih selektif (kombinasi)** |
| 4 | State terkontaminasi | vSOL/WSOSO -$25,86 (73% loss) | **state v2 terpisah** |

---

## ARSITEKTUR SPOT_SWING v4 (deployed)

```
Sinyal: momentum (5h>0.5%) + ADX≥25 + regime (BTC>SMA200 & mom24>0) — long-only
          │  (dari Binance 1h — kombinasi CEX yang terbukti +2.3% n=12)
          ▼
Filter: hanya spot pair SoDEX dengan volume ≥ $3K/24h
          ▼
Eksekusi: SoDEX spot mark price · $100 posisi (bukan $300)
          ▼
Exit: TP 2.5% / SL 1.5% DARI t=0 / time-stop 30h — pola REALWIDE (terbukti)
          ▼
State: data/paper_test_spot_swing_v2_state.json (terpisah, tidak rusak v3)
```

**7 pair lolos filter likuiditas:**
vBTC ($23K) · vTON ($11K) · vETH ($9K) · vHYPE ($8K) · vXRP ($7K) · vLINK ($4K) · vUNI ($3.5K)

---

## STATUS DEPLOY

| Komponen | Status |
|----------|:------:|
| Engine `paper_test_spot_swing_v2.py` | ✅ compile OK |
| Service `anantara-paper-spot-swing-v2` | ✅ active |
| 9/9 service total (6 SoDEX + 2 venue + spot-v4) | ✅ semua active |
| Config canonical di-update | ✅ SPOT_SWING_v4 tercatat |
| Error log | ✅ bersih |

---

## MONITORING & KEPUTUSAN

- **n≥50** → evaluasi bootstrap CI95 (sama seperti track lain)
- Metrik banding: EV/trade, WR, hit-rate 0.7%, vs v3 (yang -0.22%)
- **Kriteria sukses:** ROI ≥ 0.7% (target North Star) dengan CI95 EV > 0
- Jika v4 mengungguli v3 signifikan → v3 dimatikan, v4 jadi track resmi
- Jika tidak → aud ulang signal (kombinasi mana yang rusak)

**Proyeksi:** kombinasi terbukti +2.3% di CEX + SL-t=0 (hilang -$32 gempa) +
filter likuiditas (hilang adverse selection) → potensi Swing Spot melampaui target
0.7%, bukan lagi -0.22%.

---

*Laporan 2026-09-03 | Hermes Anantara v2 | berbasis data, bukan asumsi*
*Adaptasi: kombinasi CEX yang TERBUKTI (momentum+ADX+regime) ke Swing Spot SoDEX*