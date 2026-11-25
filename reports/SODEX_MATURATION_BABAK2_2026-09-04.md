# SODEX — PEMATANGAN SISTEM BABAK 2 (2026-09-04)
# Infrastruktur monitoring + audit lanjutan pasca-fix SL-t=0

---

## ✅ PERBAIKAN INFRASTRUKTUR (bukan parameter strategi — aman tanpa approval)

### 1. Reporter buta terhadap 3 dari 8 service — DIPERBAIKI
`scripts/sodex_progress_report.py` sebelumnya hanya melacak 6 track lama, tidak
tahu SPOT_SWING_v4 maupun Hyperliquid/Aster ada. Ini artinya laporan harian
otomatis (08:00 WIB) SELAMA INI TIDAK LENGKAP.

**Fix:** ganti referensi SPOT_SWING (v3, retired) → SPOT_SWING_v4. Tambah
section MULTI-VENUE (Hyperliquid, Aster) ke laporan.

**Dampak nyata:** setelah fix, resume berubah dari "4/6 track melampaui
target" menjadi **"5/6 track melampaui target"** — SPOT_SWING_v4 (+2.733%,
WR 100%, n=4) sekarang benar-benar terlihat, bukan tersembunyi di balik
nama file lama.

### 2. Deep learner (`anantara/swing_deep_learner.py`) buta terhadap 3 service sama
`TRACKS` list masih mengarah ke `paper_test_spot_swing_state.json` (v3 retired,
file statis sejak stop). Tambah 2 adapter skema baru:
- `_adapt_spot_v4`: baca `spot_sym`/`gross_pct`/`mode` (skema SPOT_SWING_v4)
- `_adapt_multivenue`: baca `pair`/`net_pct`/`venue` (skema Hyperliquid/Aster)

**Verifikasi:** `python3 -m anantara.swing_deep_learner once` jalan bersih,
`swing_deep_learning.json` sekarang punya entry `spot_swing_v4` (WR 100%,
ucb1=2.81 — tertinggi kedua setelah spot_live) dan `aster` (WR 25%, n=4).

**Test regression:** 28/28 test `test_swing_deep_learner.py` PASS,
69/70 test terkait swing/realwide/spot/donchian PASS (1 skip, tidak terkait).

---

## 🔍 AUDIT LANJUTAN (tidak ada aksi — evidence belum cukup)

### DONCHIAN masih -0.113% — root cause: RESIDUAL DRAG, bukan bug baru
Payoff 1.39:1, breakeven WR 41.9% vs aktual 40.9% (margin tipis tapi sehat).
Breakdown pair: **HYPE (-$25.56) + ENA (-$9.62) = -$35.18 dari total -$4.71
defisit** — keduanya SUDAH diblokir sejak 23-24 Agustus. Tanpa drag historis
ini, track sebenarnya sudah **+$30.47 positif**. 10 trade terakhir (pasca-block)
100% bersih dari HYPE/ENA. Kesimpulan: DONCHIAN akan otomatis pulih ke positif
seiring waktu — TIDAK perlu intervensi baru.

ARB muncul n=3, WR 0%, PnL -$10.75 — **belum cukup sampel** (ambang block
konsisten n≥5). Terus dipantau, jangan overfit di sampel kecil.

### TWOWAY: HYPE n=4, WR 25%, PnL -$7.19 — mendekati ambang block
Konsisten dengan pola HYPE buruk di 3 track lain (DONCHIAN, REALWIDE historis,
SWING lama). Belum n≥5 — pantau, jangan block prematur.

### REALWIDE & TWOWAY (non-HYPE): semua pair sehat
ARB, ETH, BTC, UNI, SOL, DOGE — semua WR≥50%, PnL positif. Tidak ada kandidat
block baru di kedua track ini.

---

## STATUS FINAL SEMUA TRACK (setelah pematangan babak 2)

| Track | n | WR | ROI/trade | Status |
|-------|:-:|:-:|:-:|:-:|
| 🟢 REALWIDE | 51 | 60.8% | +4.232% | ✅ 6.0× — role model |
| 🟢 TWOWAY (LONG) | 96 | 60.4% | +2.601% | ✅ 3.7× |
| 🟢 SPOT_SWING_v4 | 4 | 100% | +2.733% | ✅ 3.9× — baru, n kecil |
| 🟢 SWING | 133 | 48.9% | +1.432% | ✅ 2.0× — menunggu efek SL-t0 |
| 🟢 SWING_PARTIAL | 124 | 60.5% | +1.435% | ✅ 2.0× |
| 🔴 DONCHIAN | 44 | 40.9% | -0.113% | Residual drag, membaik otomatis |

**5 dari 6 track resmi melampaui target ≥0.7%** (sebelumnya buta, sekarang
transparan penuh via reporter yang diperbaiki).

---

## KEPUTUSAN: TIDAK ada tindakan baru pada ARB/HYPE-TWOWAY
Kriteria block (n≥5, WR<40%, EV<0) konsisten dipertahankan — mencegah
keputusan berdasarkan sampel kecil (overfitting). Kedua kandidat ini akan
dievaluasi ulang setelah n≥5.

## NEXT: monitor efek SL-t=0 di SWING/SWING_PARTIAL setelah lebih banyak
trade baru masuk (baru 1-3 trade sejak fix, terlalu dini untuk kesimpulan).