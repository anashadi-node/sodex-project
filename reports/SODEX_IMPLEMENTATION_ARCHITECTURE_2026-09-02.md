# SODEX — IMPLEMENTASI ARSITEKTUR & PENYEMPURNAAN (2026-09-02)
# Hermes Anantara v2 | Berbasis riset venue + validasi statistik bootstrap

---

## 🎯 INTI KEPUTUSAN (semua evidence-based)

Setelah riset paralel 4 subagent + validasi statistik bootstrap pada 473 trade:

| Keputusan | Dasar | Dampak |
|-----------|-------|--------|
| **Long-only permanen** | SHORT CI95 P(EV>0)=3%, n=37, WR 29,7% | Hentikan bleeding -$55 |
| **REALWIDE exit = template** | CI95 EV [+1,26, +5,79], P=100% | Konvergen ke geometry terbaik |
| **TETAP di SoDEX** | Riset venue: switch HL = -$17 EV | Hindari migrasi merusak |
| **REJECT ATR entry filter** | Data: net -$60 (mencegah 259, buang 319) | Cegah optimasi yang merugikan |

---

## 📐 ARSITEKTUR BARU (2-TIER, evidence-first)

```
TIER 1 — PROVEN (CI95>0)                 TIER 2 — EXPERIMENT
├── REALWIDE    n=43  ROI +3,77% ✅      ├── SWING       n=124 ROI +1,79% 🟡
├── TWOWAY-LONG n=80  ROI +1,51% ✅      ├── PARTIAL     n=117 ROI +1,57% 🟡
└── (kandidat GO-LIVE)                   ├── DONCHIAN    n=37  ROI -0,60% 🔴
                                         └── SPOT_SWING  n=35  ROI -0,22% 🔵
```

Setiap track punya peran ilmiah; naik/turun keputusan lewat Decision Gate
(bootstrap CI95 · WFE · P(EV>0)).

---

## ✅ YANG DIIMPLEMENTASIKAN

### 1. Canonical Config — `scripts/sodex_paper_config.py` (BARU)
Single source of truth: NORTH STAR, universe, spread model, geometry per track,
sizing, LESSONS LEARNED. Mencegah drift parameter (bug class ASTER/PUMP/LIT).

### 2. Architecture Map — `docs/SODEX_ARCHITECTURE_MAP.md` (BARU)
Peta lengkap sistem: keputusan arsitektur, tier, alur data, decision gate,
struktur file, prioritas. = struktur yang jauh lebih baik yang kamu minta.

### 3. Konsistensi universe — BNB ditambahkan ke 3 track
**Bug drift ditemukan:** TWOWAY, REALWIDE, DONCHIAN tidak memantau BNB
(pair proven +$1,43 di SWING). Ditambahkan ke semua + spread model.
- TWOWAY: 22→23 pairs ✅
- REALWIDE: 22→23 pairs ✅
- DONCHIAN: 23→24 pairs ✅

### 4. Semua 6 paper service active (verified)
swing · partial · twoway · realwide · spot-swing · donchian ✅
+ progress reporter harian 08:00 WIB.

---

## 📊 BUKTI VALIDASI (bootstrap 10.000×)

| Track | EV/trade | CI95 | P(EV>0) | Verdict |
|-------|:---:|:---:|:---:|:---:|
| REALWIDE | +$3,57 | [+1,26, +5,79] | 100% | 🟢 TERBUKTI |
| TWOWAY-LONG | +$1,43 | [+0,05, +2,75] | 98% | 🟢 TERBUKTI |
| SWING | +$1,69 | [-0,26, +3,55] | 96% | 🟡 belum |
| PARTIAL | +$1,48 | [-0,16, +3,06] | 96% | 🟡 belum |
| DONCHIAN | -$0,57 | [-2,47, +1,37] | 28% | 🔴 kills |
| SPOT_SWING | -$0,20 | [-2,41, +2,04] | 43% | 🔵 baseline |

**Terobosan scientific:** ATR filter (dari literatur) ternyata MERUGIKAN di data kita
— analisa kuantitatif sebelum implementasi menyelamatkan kita dari optimasi palsu.

---

## NEXT STEPS (terstruktur di architecture map)

1. **REALWIDE n≥50** → proposal GO-LIVE #1 (tinggal 7 trade lagi)
2. **DONCHIAN n≥50** → keputusan KILL formal
3. **Drift-check berkala** vs canonical (cegah inkonsistensi)
4. **TWOWAY-LONG n≥100** → konfirmasi stabil

*Laporan implementasi 2026-09-02 ~10:00 WIB | Hermes Anantara v2*