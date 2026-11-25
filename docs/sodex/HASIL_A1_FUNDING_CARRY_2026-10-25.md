# HASIL A1 — FUNDING CARRY OOS (PRAREG-SIG-08) — 25 Okt 2026

**Verdict: NO-GO.** Bukan karena biaya saja, tetapi karena **basis**, bukan funding,
yang menentukan hasil. Nol modal dialokasikan.

---

## 1. Dua percobaan, satu invalid

| Versi | Basis | Hasil | Status |
|---|---|---|---|
| v1 | `markPrice` dari file funding | mean **−211 bps/hari**, t=−30 | **INVALID** — data |
| v2 | klines spot & perp tersinkron (jam sama) | mean **−0,97 bps/hari**, t=−2,16 | **sah** |

**Mengapa v1 invalid:** basis BTC dari `markPrice` berdistribusi p1 −121 bps / p99 +129 bps,
16,6% observasi di luar ±50 bps. Basis perp/spot BTC yang wajar adalah ±5–10 bps.
Artinya `markPrice` di dataset funding bukan snapshot tersinkron. Semua angka v1 dibuang.

**Data v2:** 8 simbol, klines ditarik ulang dari Binance (spot + futures), 24.212 bar
perp per simbol (Des 2023 → Okt 2026), pasangan dihitung pada jam yang sama.

---

## 2. Hasil OOS (2025-01-01 → 2026-10-24)

Dua universe, keduanya NO-GO:

| Universe | n hari | mean (bps/hari) | sd | t | SR tahunan |
|---|---|---|---|---|---|
| **A — likuid** (BTC, ETH, SOL, WIF, ORDI) | 625 | **−0,08** | 7,63 | −0,25 | −0,19 |
| **B — + small cap** (MORPHO, ONDO, VIRTUAL) | 550 | **−0,97** | 10,55 | **−2,16** | −1,76 |

Interpretasi: pada nama likuid carry **tepat nol** setelah biaya (bukan positif tipis);
pada small cap **negatif nyata** (CI95 [−1,85 ; −0,09]). Tidak ada universe yang memberi edge.

| Ukuran pendukung | Nilai |
|---|---|
| Funding saja (tanpa basis), universe B | +0,72 bps/hari (t=1,14, SR 2,37) — **bukan strategi** |
| B1: P(edge>0), universe B | **1,56%** → kill = true |
| B1: P(edge>0), universe A | **40,2%** → tidak ada dasar bertindak |

Naikkan leverage tidak menolong: t tidak berubah, dan SD ikut naik.

---

## 3. Mekanisme kegagalan (ini yang penting)

Coupon funding yang dipanen: **0,7 bps/hari**. Risiko basis yang ditanggung: **10,5 bps/hari**.
Rasio **1 : 15** — carry ini sebenarnya **perdagangan basis yang menyamar sebagai carry**.

Filter trailing funding adalah **indikator yang terlambat**:
- masuk setelah funding tinggi (premi perp biasanya sudah terlanjur naik),
- keluar setelah funding rendah (premi sudah turun),
- jadi posisi membeli basis mahal dan menjualnya murah — selisihnya lebih besar
  daripada funding yang dikumpulkan.

Konsekuensi riset: **menguji carry dengan filter funding adalah menguji versi terburuknya.**
Yang menentukan bukan "apakah funding positif", tetapi **apakah basis sedang mahal atau murah**.

---

## 4. Hipotesis berikutnya (belum dijalankan, wajib pra-registrasi)

**SIG-09 — CARRY BASIS-Z (mean-reversion pada basis, bukan momentum pada funding):**

- Sinyal masuk: z(basis, 7 hari) ≥ +1,5 **dan** funding 8 jam > 0 → long spot, short perp.
- Keluar: z ≤ 0 **atau** funding < −1 bps dua periode.
- Biaya: 6,49 bps round trip; tidak ada filter trailing funding.
- Uji: simbol yang sama, OOS 550 hari, ambang t=4,11.
- Kriteria gugur: mean ≤ 0 setelah biaya, atau edge hilang di setengah nama paling likuid.

Alasan ini berbeda secara mendasar: bukan mengejar funding, melainkan **menjual premi
saat mahal dan membelinya kembali saat wajar**. Funding hanya bonus.

---

## 5. Yang TIDAK diklaim

- Tidak ada klaim bahwa carry tidak pernah bekerja di tempat lain.
- Tidak ada klaim bahwa SIG-09 akan lolos; ini hipotesis, bukan hasil.
- Angka funding-only (+0,72 bps/hari) **bukan** strategi yang bisa diperdagangkan —
  ia mengabaikan basis, dan basis adalah 15× lebih besar.
