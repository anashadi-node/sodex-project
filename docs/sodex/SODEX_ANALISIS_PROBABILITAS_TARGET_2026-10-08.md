# SODEX — ANALISIS PROBABILITAS KETERCAPAIAN TARGET UTAMA
## Apakah penurunan 0,8% → 0,6% / 0,5% per 48 jam membuat target lebih memungkinkan?

**Tanggal:** 2026-10-08 · **Status:** ANALISIS READ-ONLY (tidak ada perubahan target/ambang/live-flag).
**Sumber data:** `data/sodex_edge_census.json` (generated 2026-10-08T21:11 UTC, protokol D14) + `data/mv_funding_paper.json`.
**Metode:** posterior Bayesian non-informatif (t-student, df=n−1) untuk P(μ≥T); normal-approx untuk P(jendela<0); annualisasi compounding.

---

## 1. Jawaban langsung (jujur, sebelum detail)

> **Secara aritmetika: YA, probabilitas naik — tapi secara kelayakan statistik: TIDAK, tidak
> mengubah apa pun.** Menurunkan target = menurunkan "nilai kelulusan", bukan menurunkan
> "kesulitan membuktikan edge". Soal ujiannya (buktikan edge signifikan p<0,05, 3/3 segmen,
> Sharpe≥2,3, n≥20) **tidak bergantung pada angka target sama sekali**.

---

## 2. Lapisan 1 — Aritmetika (trivial, monoton)

P(μ ≥ T) turun monoton terhadap T. Penurunan T **selalu** menaikkan probabilitas — ini bukan
bukti kelayakan, ini aritmetika. Besarannya (posterior non-informatif):

| Mesin | n_w | mean48 | sd48 | P(μ≥0,8%) | P(μ≥0,6%) | P(μ≥0,5%) | Δ(0,8→0,5) |
|---|---|---|---|---|---|---|---|
| mv_funding (CARRY) | 17 | +1,22% | 3,46% | 0,690 | 0,766 | 0,800 | +0,11 |
| spot_swing_cex | 15 | +2,11% | 8,14% | 0,728 | 0,758 | 0,772 | +0,04 |
| twoway | 32 | +2,42% | 15,67% | 0,718 | 0,742 | 0,753 | +0,04 |
| realwide | 32 | +1,03% | 9,93% | 0,551 | 0,596 | 0,617 | +0,07 |
| donchian | 24 | +1,08% | 12,04% | 0,545 | 0,577 | 0,593 | +0,05 |

**Kenaikan nyata hanya +4–11 poin persentase** untuk penurunan 0,3%. Tidak material.

---

## 3. Lapisan 2 — Varians adalah pembunuh sejati

Target "0,8%/48 jam" adalah **MEAN**. Tapi jendela 48-jam individual sangat liar. Kolom kunci:

| Mesin | sharpe_48h | P(jendela RUGI) | CI95 mean sebenarnya |
|---|---|---|---|
| mv_funding | 0,354 | **36%** | [−0,42%, +2,87%] |
| spot_swing_cex | 0,259 | 40% | [−2,01%, +6,23%] |
| twoway | 0,154 | 44% | [−3,01%, +7,85%] |
| realwide | 0,104 | 46% | [−2,41%, +4,47%] |
| donchian | 0,090 | 46% | [−3,73%, +5,90%] |

Untuk **konsisten tidak merugi per jendela** (P rugi < 5%) dibutuhkan **sharpe_48h ≥ 1,645**.
Mesin terbaik (mv_funding) baru **0,354** — **kurang 4,6×**. Artinya: bahkan mesin yang
"lulus mean ≥ target" tetap rugi di **~36% jendela**. Target sebagai *hasil andal* belum
terjangkau oleh mesin mana pun, pada level 0,8% **atau** 0,5%.

---

## 4. Lapisan 3 — Penurunan target TIDAK mengubah verdict

Gerbang P9 (D14): `n≥20 ∧ SR_thn≥2,3 ∧ 3/3 segmen ∧ p_terburuk<0,05 ∧ BH-FDR q=0,10`.
**Target bukan bagian dari gerbang ini.** Verdict identik di 0,8 / 0,6 / 0,5%:

| Mesin | Mengapa GAGAL | Target manapun? |
|---|---|---|
| Semua direksional (realwide/donchian/twoway/swing/…) | p_day_cluster 0,39–0,93 → edge **tak bisa dibedakan dari noise** | GAGAL |
| mv_funding (CARRY) | p_worst **0,079 > 0,05** DAN n=17 < 20 | GAGAL |
| hl_replay | flag **REPLAY** (in-sample by construction) | DIKELUARKAN |

**0 mesin lulus** — pada 0,8%, 0,6%, maupun 0,5%. Menurunkan target tidak menyentuh satu pun
penyebab kegagalan.

---

## 5. Lapisan 4 — Target "diturunkan" tetap fantasi

Annualisasi compounding (182,6 jendela/tahun):

| Target /48j | +%/tahun |
|---|---|
| 0,8% | **+329%** |
| 0,6% | +198% |
| **0,5%** | **+149%** |

Bahkan 0,5%/48 jam = **+149%/tahun** — tetap jauh di atas batas struktural venue. Data batas
venue (dari riset biaya/efektif): fee RT 6,68 bp, N_eff 6,1 simbol efektif, BTC+ETH 87,8%
volume; **Sharpe terbaik terukur 3,06 → 0 mesin**; untuk mensertifikasi Sharpe 2,30 dibutuhkan
**~266 jam (≈2027-06)**. Penurunan target 0,8→0,5 hanya menggeser annualisasi 329%→149% —
**tidak membuatnya realistis**, hanya membuatnya "kurang fantastis".

---

## 6. Integritas ilmiah — ini goalpost-moving, bukan rekalibrasi

Target 0,8% dideklarasikan **"harga mati"** (D15 §6: *"Target 0,8%/48j = harga mati. TIDAK
di-turunkan"*). Menurunkannya **setelah 5 putaran falsifikasi**, tanpa rasional pra-registrasi,
adalah bentuk **look-ahead / goalpost-moving** yang justru dilawan oleh protokol falsification-first.

**Pengecualian sah** (satu-satunya jalur legal untuk menurunkan target): jika penurunan
didasarkan pada **analisis kapasitas venue pra-registrasi** (fee, N_eff, konsentrasi likuiditas,
holding-period minimum untuk sertifikasi Sharpe) — yaitu rekalibrasi target yang *aspiratif* ke
target yang *fisiknya* bisa dicapai. Ini rekalibrasi yang jujur, bukan akomodasi kegagalan.

---

## 7. Kesimpulan & rekomendasi

1. **JANGAN turunkan target ke 0,6/0,5 sebagai "perbaikan".** Ia tidak menaikkan kelayakan
   (kenaikan P hanya +4–11 pp, dan verdict P9 tetap 0-mesin-lulus di semua level). Ia hanya
   menyeret 329%→149%/tahun — tetap tidak realistis — dan menodai integritas pra-registrasi.

2. **Penyumbat sejati bukan angka target, melainkan dua hal:**
   - **(a)** tidak ada edge yang terbukti signifikan (p_day direksional 0,39–0,93);
   - **(b)** varians per-jendela terlalu tinggi (sharpe_48h terbaik 0,354 ≪ 1,645).

3. **Satu-satunya kandidat non-direksional = mv_funding (CARRY),** Sharpe_thn 4,78, 3/3 segmen,
   mean 1,22% > 0,8%. **Tapi tiga masalah jujur:** (i) venue-nya **Binance×HL×dYdX×OKX×Bybit —
   BUKAN SoDEX** (di luar scope bila target = wallet SoDEX); (ii) p_day_cluster **melemah
   0,036→0,079** seiring data masuk (regresi ke mean); (iii) n=17→20 butuh ~5–6 hari lagi.

4. **Rekomendasi tindakan:** pertahankan target 0,8% (harga mati). Fokus pada **KEPUTUSAN SCOPE (08-Okt): wallet SoDEX SAJA — `mv_funding` DIKELUARKAN**; yang tersisa = forward F1/F3/PRAREG-16/S1 (venue-SoDEX) + keluarga belum-uji C3 (E2Dir).
   Bila itu pun gugur, jawaban jujurnya adalah **"belum ada edge terbukti di SoDEX"** — dan itu
   harus diterima, bukan digeser ambangnya.

— Hermes Anantara v3 — 2026-10-08
