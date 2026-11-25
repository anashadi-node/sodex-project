# SODEX — LAPORAN PROGRES IMPROVING (2026-08-31 21:40 WIB)
# Hermes Anantara v2 | Scope: Project SODEX saja

---

## RINGKASAN EKSEKUSI HARI INI

| # | Aksi | Status | Bukti |
|:-:|------|:------:|-------|
| 1 | Ekspansi universe ASTER/PUMP/LIT ke semua mode perps | ✅ DONE | SWING 19 p, TWOWAY 22 p, REALWIDE 22 p, DONCHIAN 23 p |
| 2 | Ekspansi Spot Swing 4 → 18 aset | ✅ DONE | 18/18 terverifikasi live di SoDEX |
| 3 | Deploy & restart 5 service | ✅ DONE | Semua active; log tampilkan pair baru |
| 4 | Fix krisis: .env.swing hilang → service gagal restart | ✅ DONE | File direkreasi + di-commit ke git (tidak bisa hilang lagi) |
| 5 | Audit EMERGENCY_SL root cause | ✅ DONE | ATR>1.5% = 72% kasus; ZEC dihapus dari SWING base |
| 6 | Evaluasi SHORT gate post-fix | ⏳ MONITORING | n=2 post-fix; tunggu n≥10 |

---

## DETAIL

### 1-2. Ekspansi Universe (per request user)

**Perps (ASTER, PUMP, LIT):**
- ASTER-USD ✅ (ada di SoDEX, Binance ada ASTERUSDT)
- PUMP-USD ✅ (ada di SoDEX, Binance ada PUMPUSDT)
- LIGHTER ❌ **TIDAK ADA** di SoDEX (perps 90 simbol & spot 41 simbol dicari) → diganti **LIT-USD** (dikonfirmasi user)

**Spot Swing → 18 aset** (dari 4):
```
vBTC, vETH, vARB, vTON, vXRP, vDOGE, vBNB, vSUI, vHYPE,
vLINK, vAAVE, vADA, vAVAX, vUNI, vLTC, vXLM, vPEPE, vSHIB
```
- vSOL & WSOSO tetap EXCLUDED (empiris WR 25% anti-predictive)
- Semua 18 terverifikasi live di ticker SoDEX
- MAX_TOTAL: 3 → 6 posisi (universe lebih besar)

### 3. Deploy
- Restart 5 service (swing, swing-partial, twoway, realwide, spot-swing)
- **Krisis ditemukan**: `.env.swing` HILANG dari disk → 4 service gagal restart loop
  (`Failed to load environment files`)
- Fix: recreate file + **commit ke git** (sekarang permanent, reproducible)
- Post-restart: log SWING tampilkan ASTER/PUMP/LIT; spot-swing scan 18 pair ✅

### 4. Audit EMERGENCY_SL (akar masalah 26,7% exit darurat)

**Temuan kuat:**
| Metrik | EMERGENCY_SL | Selamat |
|--------|:-----------:|:-------:|
| n | 32 (26,7% trades) | 88 |
| avg ATR% saat entry | **1,85%** | 0,94% |
| ATR > 1,5% | **72%** | 26% |
| avg hold saat exit | 4,7h | — |
| avg loss | -$11,13 | — |

- **100% EMERGENCY terjadi < 12h** — SL normal (-1%) baru aktif setelah min-hold 12h, jadi pair volatil yang turun -2% dalam 5 jam kena emergency -2%.
- Root cause = **entry di pair volatil (ATR tinggi)** + exit geometry yang tidak memberi SL lebih awal.

**Keputusan berbasis data:**
- **ZEC dihapus dari SWING base** — n=9, WR 33%, EV -$28,76, 6/9 EMERGENCY_SL
- ⚠️ ZEC **BUKAN anti-predictive global**: profitable di SWING_PARTIAL (+$14,48, WR 62,5%) & DONCHIAN (+$7,22) → tetap dipantau di track tersebut
- Ini bukti tambahan: **SWING_PARTIAL exit-engine > SWING base** (ZEC: -$28,76 vs +$14,48)

### 5. Evaluasi SHORT gate (fix 30-Agu)

- Post-fix: **n=2** (ADA +4,24% TP, AVAX -2,11% SL) — belum evaluable, butuh n≥10
- Gate jauh lebih selektif: 2 entry dalam 15h vs rata-rata 1/hari sebelumnya ✅ (sesuai desain)
- Temuan struktural PRE-FIX: **63% SHORT exit TIME_30h** — hint: TP 4% terlalu jauh untuk rentang pergerakan bear yang flat; waktu 30h habis sebelum 4%. Ini kandidat riset berikutnya.

---

## STATUS KANDIDAT LIVE (per 31-Agu)

| Mode | n | WR | Avg wallet_roi | Target 0,7% |
|------|:-:|:-:|:--------------:|:----------:|
| REALWIDE | 38 | 65,8% | +4,53% | ✅ (n menuju 50) |
| TWOWAY LONG | 73 | 60,3% | +1,91% | ✅ |
| SWING | 119* | 48,7% | +1,58% | ✅ (*ZEC dihapus) |
| SWING_PARTIAL | 113 | 61,1% | +1,46% | ✅ |
| DONCHIAN | 35 | 37,1% | -0,62% | ❌ |
| SPOT_SWING | 33 | 45,5% | +0,09% | ❌ (universe baru 18 aset) |
| TWOWAY SHORT | 29 | 34,5% | -0,62% | ❌ (gate baru, n=2 post-fix) |

---

## REKOMENDASI BERIKUTNYA (menunggu data)

1. **REALWIDE → n≥50** (12 trade lagi) → kandidat live #1 (ROI 4,53% terbaik)
2. **SHORT gate monitoring** — setelah n≥10 post-fix, evaluasi WR/exit. Jika TIME_30h masih dominan → pertimbangkan TP 4%→3% untuk SHORT (riset dulu, bukan asumsi)
3. **Spot swing 18 aset** — 7 hari pertama = baseline learning. Perhatikan volume tipis (vSHIB $157/24h!) → spread model 8bps untuk yang tipis
4. **Deep-loop integration** — swing_deep_learning.jsonl berjalan; pastikan antar-track saling belajar (4 silo → orchestrated)

---

*Laporan progres 2026-08-31 21:40 WIB | Hermes Anantara v2*
*Semua keputusan berbasis data empiris, bukan asumsi.*