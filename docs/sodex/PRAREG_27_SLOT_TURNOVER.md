# PRAREG-27 — Ekspansi Slot & Turnover TWO-WAY (arm paralel, non-invasif)

**ID:** PRAREG-27
**Tanggal pra-registrasi:** 2026-10-21 (WIB) — **sebelum** arm dijalankan
**Status:** pra-registrasi (hash dihitung sebelum data pertama)
**Pemilik keputusan:** Mas Anas (approval: 21-Okt-2026, "memperbesar slot/hold")
**Mesin:** `anantara-paper-twoway-p27` (unit terpisah, state terpisah)
**Modal:** $0 (paper, `LIQ_DRY=1`) — tidak menyentuh uang

---

## 1. Konteks terukur (sumber: `sodex_maturation_tracker.py`, 21-Okt-2026 06:27 WIB)

| Metrik TWO-WAY (arm produksi, grid 30 jam tetap) | Nilai |
|---|---|
| Trade | n = 463, WR 40,6%, PF 1,112 |
| Window 30 jam berisi | n = 57 |
| Mean window | **+1,146%** (lolos A: ≥0,8%) |
| Median window | **+0,167%** (lolos B: >0) |
| Hit ≥0,8% | **27/57 = 47,4%** (gagal: butuh ≥50% → 29/57) |
| Window terburuk | **−30,52%** |

**Diagnosis:** satu-satunya komponen target yang gagal adalah **hit rate** (kurang 2 window) — bukan jumlah window.
Mean lolos karena ekor kanan; median tipis positif. Menaikkan jumlah trade **tidak otomatis** menaikkan hit;
hipotesis di bawah harus diuji, bukan diasumsikan.

## 2. Keputusan metodologis penting — HOLD tidak diperbesar

`TIME_STOP_H` = **30 jam** = panjang window target. Memperpanjang hold (mis. 48 jam) membuat satu trade
melintasi **dua** window → definisi A/B (mean/median/hit per window 30 jam) rusak dan tidak sebanding
dengan baseline. Karena itu:

- **Hold: DIBEKUKAN 30 jam** (bukan diubah).
- Tuas yang diuji: **jumlah slot sinyal** dan **cooldown per pair** (turnover di dalam window yang sama).

## 3. Desain eksperimen (A/B, paralel, pra-registrasi)

| Parameter | Arm A — KONTROL (produksi) | Arm B — P27 (diuji) |
|---|---|---|
| `TW_MAX_SIGNAL` (slot sinyal) | 6 | **12** |
| `TW_COOLDOWN_H` (per pair) | 12 | **6** |
| `TW_TIME_STOP_H` | 30 | **30 (identik)** |
| `TW_MAX_RANDOM` | 2 | 2 |
| Universe, TP/SL, biaya, gate | identik | identik |
| State/log/monitor | `paper_test_twoway_*` | `paper_test_twoway_p27_*` |

Arm B berjalan sebagai **proses terpisah** dengan state terpisah; arm A tidak diubah sama sekali, sehingga
seri PRAREG-26 tetap valid.

## 4. Hipotesis (falsifiable)

**H1:** menaikkan slot 6→12 dan memotong cooldown 12→6 jam menaikkan **hit rate grid 30 jam** ≥ **+3 pp**
tanpa menurunkan **median window** lebih dari **0,2 pp**.

**H0 (yang harus dibantah):** Δhit ≤ 0 atau median turun > 0,2 pp → ekspansi hanya menambah trade marginal
(memperburuk WR), **ditolak**.

## 5. Aturan keputusan (ditetapkan sekarang, tidak boleh diubah setelah melihat hasil)

| Keputusan | Syarat |
|---|---|
| **ADOPT** | Δhit ≥ +3 pp **dan** Δmedian ≥ −0,2 pp **dan** n window arm B ≥ 25 |
| **ABANDON** | Δhit ≤ 0 **atau** Δmedian < −0,5 pp (dengan n ≥ 25) |
| **INCONCLUSIVE** | selain di atas, atau n < 25 → lanjut sampai batas waktu |

Uji statistik: dua-proporsi (hit) + bootstrap CI95 median; **tanpa** p-hacking, tanpa uji ganda.
Metrik primer dihitung dengan fungsi grid yang sama (`window_metrics`, jangkar tetap 2026-08-03Z).

## 6. Batas waktu & berhenti

- **Baca interim pertama:** 2026-10-28 (≥7 hari).
- **Batas akhir:** **2026-11-25** (bersamaan verdict PRAREG-26) — tidak diperpanjang.
- **Berhenti darurat:** bila arm B menghasilkan window terburuk < −40% **atau** feed buta > 3 siklus
  (self-heal akan restart otomatis).

## 7. Risiko & mitigasi

| Risiko | Mitigasi |
|---|---|
| Dua arm berebut rate-limit Binance | 19 pair × 2 arm / 5 menit — jauh di bawah limit; pantau `Signal error` |
| Data arm B mengontaminasi PRAREG-26 | state/log/monitor terpisah + unit berbeda; tidak masuk UNIVERSE PRAREG-26 |
| Slot 12 menggelembungkan risiko per window | paper; risiko diukur sebagai window terburuk, bukan notional |
| Overfit karena mengubah 2 parameter | hanya 2 parameter, arah ditetapkan sebelum data, keputusan biner |

## 8. Yang TIDAK diuji di sini

Exit geometry (R2B/R2C sudah final), biaya/fill (R2D final), filter entry mikro (R3 gagal holdout),
SHORT (mati diukur), gate regime (R4/R5 lemah). PRAREG-27 **bukan** pengganti PRAREG-26.

---

*Pra-registrasi ini di-hash (SHA-256) sebelum unit dijalankan; hash dicatat di `PRAREG_27.sha256` dan commit.*
