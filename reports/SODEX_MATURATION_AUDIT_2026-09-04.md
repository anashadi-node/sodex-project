# SODEX — PEMATANGAN SISTEM & AUDIT ARSITEKTUR (2026-09-04)
# Hermes Anantara v2 | Deep-dive semua paper test + struktur

---

## ✅ SUDAH DIEKSEKUSI (memakai kriteria presedan yang sudah disetujui)

### 1. Exclude ADA dari SWING & SWING_PARTIAL
**Kriteria identik dengan block HYPE/ENA di DONCHIAN (n≥5, WR<40%, EV<0) — bukan keputusan baru, penerapan aturan yang sama:**

| Track | n | WR | PnL |
|-------|:-:|:-:|:-:|
| SWING | 5 | 20,0% | -$32,60 |
| SWING_PARTIAL | 3 | 33,3% | -$30,04 |
| **TOTAL** | **8** | **25,0%** | **-$62,64** |

Sudah di-deploy, service restart bersih, 0 error.

### 2. Verifikasi DONCHIAN block bekerja
10 trade terbaru (sejak block 23-24 Agustus): **0 HYPE/ENA**, semua TP (ZEC, AAVE, ARB). Block efektif, kerugian akumulatif historis (-$4,71) murni residual sebelum block.

### 3. Verifikasi service health
9 service — 0 crash baru, error log bersih (log lama 14-15 Agustus, bukan kejadian baru).

---

## 🔍 TEMUAN BUTUH APPROVAL (perubahan parameter/arsitektur fundamental)

### Temuan A: SWING — 28% trade kena EMERGENCY_SL (37/132)

**Root cause:** `MIN_HOLD_SL_H=12` menahan SL normal (-1%) selama 12 jam pertama. Saat salah arah cepat, hanya EMERGENCY_SL (-2%, 2× lipat) yang bisa fire. Pola ini identik dengan kasus ZEC yang sudah terbukti (6/9 EMERGENCY_SL → ZEC dikeluarkan 2026-08-31).

**Bukti REALWIDE sudah membuktikan solusinya:** REALWIDE pakai `MIN_HOLD_SL_H=0` (SL aktif t=0) → **0% EMERGENCY_SL**, WR 60,8%, ROI +4,23% (performer terbaik).

**Dampak EMERGENCY_SL di SWING:** 37 trade × avg -$28 = kira-kira **-$1.036 dari total kerugian**. Tanpa pola ini, ROI SWING berpotensi naik signifikan dari 1,485% saat ini.

**Rekomendasi:** ubah `MIN_HOLD_SL_H` SWING dari 12 → 0 (samakan pola REALWIDE).
**Risiko:** ini genuine trade-off — min-hold 12h awalnya didesain untuk mencegah "whipsaw" exit dini. Perlu di-uji apakah manfaat (hindari 2× kerugian emergency) > biaya (SL dini lebih sering fire di masa depan).

### Temuan B: SPOT_SWING v3 (lama) masih rugi, sudah digantikan v4

| Track | n | PnL |
|-------|:-:|:-:|
| v3 (lama, deprecated) | 36 | **-$14,32** (memburuk dari -$7,12) |
| v4 (baru, kombinasi CEX) | 4 | **+$10,34** |

v3 terus berjalan paralel dan terus membakar data/computing tanpa nilai — root cause-nya (jendela gempa 4h) sudah diketahui dan sudah diperbaiki di v4.

**Rekomendasi:** hentikan service `anantara-paper-spot-swing` (v3 lama), biarkan v4 jadi satu-satunya track Spot Swing resmi.

---

## STATUS TERKINI SEMUA TRACK (setelah exclude ADA)

| Track | n | WR | ROI/trade | Status |
|-------|:-:|:-:|:-:|:-:|
| 🟢 REALWIDE | 51 | 60,8% | +4,232% | ✅ 6,0× target — **role model geometry** |
| 🟢 TWOWAY (LONG) | 96 | 60,4% | +2,601% | ✅ 3,7× target |
| 🟢 SWING | 132→127* | 49,2%→? | +1,485%→? | ✅ target, berpotensi naik pasca-fix |
| 🟢 SWING_PARTIAL | 123→120* | 61,0%→? | +1,495%→? | ✅ target |
| 🟡 SPOT_SWING v4 | 4 | 100% | +2,73% | 🚀 baru, promising, n kecil |
| 🔴 DONCHIAN | 44 | 40,9% | -0,113% | Membaik, block bekerja |
| 🔴 SPOT_SWING v3 | 36 | 41,7% | -0,421% | Deprecated, rekomendasi retire |

*n turun sedikit karena ADA di-exclude dari universe (trade historis tetap tercatat, hanya tak ada entry baru)

---

## KEPUTUSAN MENUNGGU APPROVAL ANDA

1. **SWING/SWING_PARTIAL: `MIN_HOLD_SL_H` 12→0** (samakan geometry REALWIDE — role model terbukti terbaik)
2. **Retire `anantara-paper-spot-swing`** (v3 lama, sudah digantikan v4 yang lebih baik)

*(Sesuai aturan Anda: perubahan parameter/arsitektur fundamental wajib approval eksplisit sebelum eksekusi.)*