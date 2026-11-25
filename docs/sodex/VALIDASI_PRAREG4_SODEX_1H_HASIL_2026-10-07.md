# PRAREG-4 — HASIL: RANGEPOS rank-proporsional di panel SoDEX 1h

**Dijalankan:** 2026-10-07 · **Pra-reg:** commit `2a8fcdf` (dibekukan SEBELUM evaluasi)
**Label: DESKRIPTIF** — jendela historis sudah terpakai. **Bukan verdict.** Verdict sah hanya dari data FORWARD.

---

## 1. Verdict beku

> ## H4 TIDAK DIDUKUNG.
> Tidak ada satu pun dari 7 sel grid yang lolos gerbang. **Bruto NEGATIF di seluruh grid**
> (−1,93 … −16,93 bps), sedangkan hipotesis menuntut tanda MOMENTUM (bruto > 0).

Reproduksi indeks (95 nama × 8.533 bar, 2025-10-12 07:00 → 2026-10-07 11:00 UTC, PPY=8760):

| hold | n | nama | bruto | net 1× | net real | net 2× | to | fee | S_ann | t_NW | p | seg+ |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 7062 | 75 | −1,93 | −3,98 | −4,42 | −6,03 | 0,51 | 2,05 | −19,26 | −16,59 | 0,0000 | 0 |
| 2 | 3531 | 75 | −2,24 | −4,93 | −5,51 | −7,62 | 0,67 | 2,69 | −12,67 | −10,88 | 0,0000 | 0 |
| 4 | 1765 | 75 | −2,75 | −6,16 | −6,89 | −9,57 | 0,85 | 3,41 | −8,11 | −7,18 | 0,0000 | 0 |
| 8 | 882 | 75 | −2,57 | −6,74 | −7,63 | −10,91 | 1,04 | 4,17 | −4,59 | −4,55 | 0,0000 | 0 |
| 12 | 588 | 75 | −2,21 | −7,02 | −8,04 | −11,82 | 1,20 | 4,80 | −3,04 | −3,16 | 0,0016 | 0 |
| 24 | 293 | 75 | **−11,68** | −16,95 | −18,08 | −22,22 | 1,32 | 5,27 | −3,98 | −4,36 | 0,0000 | 0 |
| 48 | 146 | 75 | **−16,93** | −22,15 | −23,27 | −27,38 | 1,31 | 5,23 | −3,06 | −4,35 | 0,0000 | 0 |

**Reproduksi PRAREG-2 yang baik:** PRAREG-2 (63 nama) memberi SoDEX 1h hold=24 net **−16,61**;
PRAREG-4 (95 nama) memberi **−16,95**. Selisih 2% — hasil lama terkonfirmasi, bukan derau.

## 2. Tanda berlawanan = temuan sesungguhnya

Karena t_NW bersifat **dua-sisi**, tanda negatif yang kuat **juga** signifikan. Membalik tanda
(menerapkan arah REVERSAL: short yang dekat puncak, long yang dekat dasar) memberi:

| hold | bruto | fee 1× | **net 1×** | **net real** | **net 2×** | S_ann | t_NW | BH |
|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| 1 | 1,93 | 2,05 | −0,12 | −0,56 | −2,17 | 19,26 | 16,59 | PASS |
| 2 | 2,24 | 2,69 | −0,45 | −1,03 | −3,14 | 12,67 | 10,88 | PASS |
| 4 | 2,75 | 3,41 | −0,67 | −1,39 | −4,08 | 8,11 | 7,18 | PASS |
| 8 | 2,57 | 4,17 | −1,60 | −2,49 | −5,76 | 4,59 | 4,55 | PASS |
| 12 | 2,21 | 4,80 | −2,59 | −3,62 | −7,39 | 3,04 | 3,16 | PASS |
| **24** | 11,68 | 5,27 | **+6,41** | **+5,28** | +1,14 | **3,98** | **4,36** | PASS |
| **48** | 16,93 | 5,23 | **+11,70** | **+10,58** | **+6,47** | **3,06** | **4,35** | PASS |

**Bacaan:** efek REVERSAL itu nyata dan kuat, **tetapi hanya menguntungkan di hold 24–48 jam**.
Di hold ≤12 jam bruto-nya (≤2,75 bps) **lebih kecil daripada biaya** (2,05–4,80 bps) → tidak bisa
diperdagangkan; di situlah S_ann yang tinggi (19,26) menyesatkan — Sharpe tinggi di atas spread
yang lebih tipis dari biaya adalah Sharpe yang tidak bisa diuangkan.

## 3. Uji null — apakah ini artefak random-walk?

Kontrol C-c satu-seed tampak "bocor", jadi saya jalankan **null 10 seed** panel random-walk
berukuran sama (adendum yang **memperketat**, tidak mengubah parameter beku):

| hold | bruto NYATA | null rata² | null sd | nyata − null | z | p_empiris |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | −1,93 | −0,08 | 0,10 | −1,85 | **−19,14** | 0,00 |
| 12 | −2,21 | −0,23 | 2,05 | −1,99 | −0,97 | 0,20 |
| 24 | −11,68 | +0,56 | 4,28 | **−12,24** | **−2,86** | 0,00 |
| 48 | −16,93 | −0,64 | 7,14 | **−16,29** | **−2,28** | 0,00 |

**Kesimpulan null:** efek reversal di **H=1, 24, 48 keluar dari null**; di H=12 tidak bisa
dibedakan dari null (z=−0,97). Sebaran null ±4–7 bps di H=24/48 → "artefak rentang" yang saya
khawatirkan **tidak terbukti**; angka sintetis negatif sebelumnya hanyalah **derau seed**.

## 4. Dua alarm yang saya rais dan saya TARIK

| # | Alarm saya | Status sebenarnya |
|---|---|---|
| 1 | "Kontrol C-c bocor 7/7 → protokol tidak valid" | **SALAH.** Cetakan konsol saya memakai kriteria terlalu lemah (**BH saja**), sedangkan gerbang beku §3 mensyaratkan **bruto > 0**. Bruto sintetis negatif di seluruh grid → sintetis **gagal gerbang penuh** → **C-c patuh**. Ini bug *pelaporan* saya, bukan pelanggaran protokol. |
| 2 | "Sebagian besar reversal = artefak statistik rentang" | **SALAH/berlebihan.** Null 10-seed terpusat di ~0. Efek nyata di H=24/48 keluar dari null. |

Keduanya saya catat agar tidak terulang: **kriteria kontrol harus selalu = gerbang penuh yang
dibekukan, bukan proksi (BH) yang lebih lemah.**

## 5. Yang TIDAK berubah (batas kejujuran)

1. **DESKRIPTIF.** Jendela 2025-10-12 → 2026-10-07 sudah terpakai (PRAREG-2 memakai 63 dari
   nama yang sama). **Tidak sah** dipakai sebagai verdict. Verdict sah hanya dari data forward.
2. **Tanda berlawanan dengan yang tervalidasi di Binance.** Ini bendera overfitting paling kuat
   yang ada. Mekanisme yang tandanya bergantung venue **belum layak produksi.**
3. **Satu venue, satu panel, tanpa pemisahan OOS** — seluruh jendela in-sample.
4. Turnover tinggi (1,31–1,32) → sensitif biaya: di 2× fee H=24 hanya +1,14 bps, H=48 +6,47 bps.
5. Reversal H=1 dengan bruto hanya 1,93 bps **konsisten dengan bid-ask bounce** — bukan kandidat
   yang bisa diuangkan tanpa eksekusi maker; tidak saya promosikan.

## 6. Jarak ke target

Kandidat terbaik: **reversal H=48 net realistis 10,58 bps per 48 jam = 13,2% dari target 80 bps.**
(Notional 1× karena portofolio dollar-neutral Σ|w|=1; leverage dilarang aturan.)

Sejalan dengan temuan sebelumnya (mekanisme terbaik = 25–28% target), bukan lompatan.

## 7. Implikasi pada rencana — batas yang tidak bisa dikompresi

Ini temuan terpenting untuk keputusan, dan ia aritmetika:

`t = S_ann × √T`. HARD_STOP 20 Nov 2026 = **44 hari** → T = 0,1205 thn → √T = 0,347.

| Agar t ≥ 2,0 dengan T = 44 hari | Butuh S_ann |
|---|---|
| sertifikasi dalam 44 hari | **≥ 5,76** |

Kandidat terbaik yang kita punya (reversal H=48) ber-S_ann **3,06** → t = 3,06 × 0,347 = **1,06**.

> **Kesimpulan jujur: sertifikasi mekanisme apa pun sebelum 20 Nov 2026 adalah mustahil secara
> aritmetika, kecuali ada mekanisme ber-S_ann ≥ 5,8 — dan kita belum pernah menemukan satu pun
> (tertinggi yang pernah terukur di SoDEX: 3,06, deskriptif).**

Ini bukan soal kerja lebih keras atau data lebih banyak. Ini **kalender**.

## 8. Tindakan

| # | Tindakan | Status |
|---|---|---|
| 1 | PRAREG-4 dijalankan sesuai spesifikasi beku | ✅ selesai (`2a8fcdf` → hasil ini) |
| 2 | Verdict: H4 (momentum) tidak didukung | ✅ |
| 3 | Lead baru: reversal H=24/48 (deskriptif, kuat, keluar dari null) | ✅ tercatat |
| 4 | Dua alarm saya ditarik + akar penyebab dicatat | ✅ |
| 5 | **Rekomendasi:** jalur **verifikasi FORWARD 1h reversal H=48** — bukan produksi; 1h memberi 24× periode/hari dibanding 1d | **menunggu keputusan Mas Anas** |
| 6 | Produksi / ubah target / ubah ambang | **TIDAK ADA** — tidak ada yang layak |

— Hermes Anantara v3 — 2026-10-07
