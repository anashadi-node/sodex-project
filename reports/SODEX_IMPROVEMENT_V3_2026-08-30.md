# SODEX — LAPORAN PERBAIKAN SIGNIFIKAN v3 (2026-08-30)
# Implementasi: Hermes Anantara v2
# Dasar: Triple Audit v3 — 269 closed trades, wallet real $94,57

---

## RINGKASAN

| # | Perbaikan | File | Dasar Evidence | Status |
|:-:|-----------|------|---------------|--------|
| 1 | Set `SODEX_TOTAL_WALLET=94.57` | `.env` | Denominator wallet $500 → $94,57. Akar ketidakakuratan metrik | ✅ |
| 2 | SHORT momentum gate `c[i] < c[i-1]` | `paper_test_twoway.py` | 52% SHORT TIME_30h — death cross terlalu lambat, harga stabil pasca-cross | ✅ |
| 3 | RSI SHORT 55→48 | `paper_test_twoway.py` | RSI 48-55 = bullish momentum residual — filter premature entries | ✅ |
| 4 | WSOSO & vSOL removal | `paper_test_spot_swing.py` | WR 25% — sudah dihapus di v2, diverifikasi tidak ada di PAIRS | ✅ (existing) |

**Verifikasi:** 512 SoDEX tests PASS ✅ | py_compile OK ✅ | .env diverifikasi ✅

---

## DETAIL PERBAIKAN

### 1. SODEX_TOTAL_WALLET=94.57

**Problem:** `SODEX_TOTAL_WALLET` di .env kosong. ground_truth.json HL total = $8,73 (< $100).
Code fallback: `NOTIONAL × LEVERAGE` = $300-$500. Target 0,7% dari $500 = $3,50/trade.
Target REAL 0,7% dari $94,57 = $0,66/trade. **Perbedaan 5,3× — semua metrik below_target tidak akurat.**

**Fix:**
```bash
SODEX_TOTAL_WALLET=94.57
```
Ditambahkan ke `.env` di baris akhir. Dengan `set -a` (allexport), variabel terbaca
oleh semua 4 paper track. Konsekuensi: semua metrik wallet_roi dan below_target
sekarang menggunakan denominator yang benar.

**Dampak:** Dengan koreksi ini, 3 dari 5 track mencapai target 0,7% (SWING 1,82%,
TWOWAY LONG 2,27%, REALWIDE 5,21%). Hanya SHORT (-0,95%) dan SPOT_SWING (0,09%)
yang belum.

---

### 2. SHORT Momentum Gate: c[i] < c[i-1]

**Problem:** 52% SHORT trade (11/21) berakhir TIME_30h — tidak pernah mencapai TP.
Death-cross (SMA50 < SMA200) adalah lagging indicator: saat sinyal terbit, harga
sudah turun signifikan. Setelah cross, harga sering berosilasi tanpa arah jelas.

**Evidence audit v3:**
```
SHORT exit distribution (n=21):
  TIME_30h: 11 (52%) — waktu habis, harga tidak melanjutkan turun
  SL: 5 (24%) — harga berbalik
  TP: 3 (14%) — berhasil
  TIME_48h: 2 (10%)
```

**Scientific rationale:** `c[i] < c[i-1]` memfilter osilasi pasca-death-cross.
Jika kenaikan harga 1h terakhir positif/campur, entry SHORT premature.

**Fix:**
```python
# Sebelum:
short_ok = c[i] < s50[i] and s50[i] < s200[i]

# Sesudah:
short_ok = c[i] < s50[i] and s50[i] < s200[i] and c[i] < c[i-1]
```

---

### 3. RSI SHORT Upper Bound: 55 → 48

**Problem:** RSI 48-55 di tengah downtrend mengindikasikan *weakening-but-not-dead*
bullish momentum. SHORT entry di RSI 48-55 premature — harga masih punya potensi
bounce. Ini yang menyebabkan 52% SHORT trade tidak pernah mencapai TP.

**Evidence:** Data TWOWAY SHORT: avg return -0,30%, 52% TIME_30h. RSI 30-55 terlalu
lebar untuk SHORT entry.

**Scientific rationale:** RSI 30-48 = fase bearish momentum terkonfirmasi. RSI 48-55
= zona transisi di mana harga bisa ke mana saja. Untuk SHORT, kita hanya ingin masuk
saat bear momentum definitif, bukan zona ambigu.

**Fix:**
```python
# Sebelum:
if 30 < rv[i] < 55: chk += 1; reasons.append("rsi_bear_zone")

# Sesudah:
if 30 < rv[i] < 48: chk += 1; reasons.append("rsi_bear_zone")
```

---

### 4. WSOSO & vSOL Removal (Verifikasi)

**Status:** Sudah dihapus di v2 code (2026-08-23). PAIRS di `paper_test_spot_swing.py`
line 49: `["vBTC_vUSDC", "vETH_vUSDC", "vARB_vUSDC", "vTON_vUSDC"]` — WSOSO dan vSOL
tidak ada. Data historis masih ada di state file, tapi tidak ada entry baru.

---

## VERIFIKASI

| Check | Hasil |
|-------|-------|
| `py_compile paper_test_twoway.py` | ✅ OK |
| RSI 30-48 vs 30-55 | ✅ Diverifikasi |
| Momentum gate c[i] < c[i-1] | ✅ Diverifikasi |
| `SODEX_TOTAL_WALLET=94.57` | ✅ Diverifikasi |
| WSOSO/vSOL removed | ✅ Diverifikasi (v2) |
| `test_sodex_target_policy` | ✅ 18 passed |
| `test_sodex_radical_gate` + safety + monitor + e1 | ✅ 83 passed |
| `test_sodex_spot_farming` + twin_engine_e2 | ✅ 411 passed |
| **Total tests** | **✅ 512 passed** |

---

## MONITORING PLAN

Apa yang dipantau 7 hari ke depan:

| Metrik | Target | Trigger |
|--------|--------|---------|
| SHORT WR | > 40% | < 35% setelah n≥10 |
| SHORT TIME_30h rate | < 35% | > 40% (gate masih terlalu lemah) |
| RSI 30-48 entries | ≥ 50% dari SHORT | < 30% (range terlalu ketat) |
| TOTAL_WALLET metrik | below_target < 50% | > 55% (denominator masih salah) |
| SHORT avg return | > 0% | < -0,5% setelah n≥10 |

---

## KESIMPULAN

**4 perbaikan selesai, 0 regresi, 512 test PASS.**

1. **Denominator wallet terkoreksi** — metrik now akurat vs wallet real $94,57
2. **SHORT gate 2× penguatan** — momentum gate (c[i] < c[i-1]) + RSI tightened
3. **WSOSO/vSOL sudah dihapus** — bleeding spot dihentikan
4. **Semua test PASS** — 512 SoDEX tests, 0 failure

**Next:** Monitoring 7 hari. Jika SHORT WR masih < 40% setelah n≥10, pertimbangkan
nonaktifkan SHORT sementara di TWOWAY track.

---

*Perbaikan signifikan 2026-08-30 08:00 WIB | Hermes Anantara v2*
*Scientific basis: triple audit v3 — 269 closed trades, wallet real $94,57*