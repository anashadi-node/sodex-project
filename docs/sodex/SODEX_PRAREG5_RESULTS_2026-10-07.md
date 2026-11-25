# PRAREG-5 — HASIL: FALSIFIED (model fill maker + gerbang sentuh, SoDEX 1h)

**Tanggal evaluasi:** 2026-10-07
**Prareg beku:** commit `ca8b8f0` (dibuat & di-commit SEBELUM evaluasi)
**Skrip beku:** `scripts/research/xsec_fill_maker_prereg5.py` (deterministik, seed tetap)
**Keluaran:** `reports/sodex/PRAREG5_FILL_MAKER_SODEX_1H.json`

---

## 1. VERDICT

> **FALSIFIED.** Hipotesis "reversal hold-1 di SoDEX 1h bisa dibayar dengan fee maker"
> **GUGUR — dan gugur di level BRUTO**, yaitu bentuk falsifikasi terkuat:
> tidak ada asumsi fee yang bisa menyelamatkannya.

Ambang prareg yang gagal: **#1** (net OOS & net48 positif), **#4** (kontrol bruto),
**#5** (≥2 dari 3 segmen OOS positif), **#6** (segmen terkini bruto positif),
**#7** (p-terburuk ≤ 0,05).
Ambang yang lulus: **#2** (fill rate ≥ 30%), **#3** (arm gated tidak mengalahkan shadow).

---

## 2. ANGKA DEFINITIF (hold = 1 jam)

| arm | asumsi isi | fee (bps/leg) | net bps/jam | **gross bps/jam** | t(NW) | net/48j | hit48 |
|---|---|---|---|---|---|---|---|
| `A_maker_nogate` | **selalu di close** | 1,14 | **+1,346** | +1,930 | +5,66 | **+64,55** | 0,585 |
| `A_shadow_taker` | selalu di close | 4,00 | **−0,121** | +1,930 | −0,51 | −5,83 | 0,340 |
| `A_maker_gated` optimis | gerbang sentuh | 1,14 | **−0,621** | **−0,107** | −2,78 | −29,90 | 0,333 |
| `A_maker_gated` **primer** | gerbang sentuh | 2,80 | **−1,369** | **−0,107** | −6,13 | **−65,81** | 0,211 |
| `A_maker_gated` pesimis | gerbang sentuh | 4,46 | **−2,118** | **−0,107** | −9,49 | −101,73 | 0,156 |

### Pisah-waktu (arm gated, fee primer)

| irisan | net bps/jam | gross bps/jam | fill rate |
|---|---|---|---|
| IS (60% tertua) | **−2,327** | **−1,091** | 0,770 |
| OOS (40% termuda) | **−0,341** | +0,949 | 0,879 |

### Segmen OOS (3×~1/3), arm gated H1

| segmen | net bps/periode | gross bps/periode | MDE | powered? |
|---|---|---|---|---|
| 1 | +0,83 | +2,16 | 1,77 | **tidak** (`-`) |
| 2 | −0,02 | +1,26 | 1,46 | **tidak** (`-`) |
| 3 | **−1,84** | **−0,57** | 1,77 | **YA → negatif** |

> Segmen OOS yang **satu-satunya bertenaga statistik** justru **NEGATIF**,
> dan **bruto**-nya juga negatif (−0,57). Tidak ada pemotongan fee yang bisa memperbaiki.

### p-value (terburuk yang mengatur)
`p_terburuk = 0,3394` (H1 0,339 / H2 0,199 / H4 0,045) → **gagal** ambang ≤ 0,05.

---

## 3. MEKANISME KEGAGALAN — ADVERSE SELECTION TERUKUR

Ini temuan utama dan **dapat dipakai ulang**:

**Lantai adverse selection order maker yang "terisi saat tersentuh" di SoDEX 1h = ≈ 3,9 bps/periode.**

Kontrol negatif (bobot acak, gerbang sentuh, fee 2,80) menghasilkan **bruto NEGATIF**:

| kontrol | H1 | H2 | H4 |
|---|---|---|---|
| C-a (acak-dalam-baris) | −3,8605 | −4,3768 | −4,6724 |
| C-b (acak-penuh) | −3,8506 | −4,0905 | −4,7888 |
| C-c (panel sintetis GBM) | +0,0630 | +0,2708 | +0,6885 |

Kontrol **C-c ≈ 0** ⇒ instrumen bersih. Kontrol **C-a/C-b ≈ −3,9** ⇒ **bukan cacat**: begitulah cara gerbang sentuh bekerja. Limit beli hanya terisi jika harga **turun menembus** bid; limit jual hanya terisi jika harga **naik menembus** ask. Jadi Anda **selalu** menjadi pihak yang terkena pergerakan lawan — inilah "separuh spread" yang ingin Anda ambil, dibayar terbalik.

**Gap adverse selection terukur langsung** (arm gated, OOS):
`adv_sel(terisi) − adv_sel(tidak terisi)` = **−49,3 bps** (H1), −65,6 (H2), −82,8 (H4).
Simbol yang **terisi** sistematis adalah simbol yang pergerakan majunya **melawan** arah posisi.

**Aritmetika pembunuh:**
```
gross sinyal (terbaik, full)      = +1,93 bps/periode
lantai adverse selection (null)   = −3,90 bps/periode
fee maker (primer, to×fill)       = −1,26 bps/periode
                                  ────────────────────
net                                = −1,37 bps/periode  →  −65,8 bps/48 jam
```
Sinyal **memang punya skill relatif**: bruto gated −0,107 vs kontrol −3,86 ⇒ sinyal
memulihkan **+3,75 bps** seleksi dibanding buku acak. **Tetapi tidak cukup** untuk
melewati 0, apalagi biaya. Skill relatif ≠ edge yang dapat dibayar.

---

## 4. REPRODUKSI & VALIDASI INSTRUMEN

1. **Reproduksi PRAREG-4:** `A_shadow_taker` bruto H1 full = **+1,930** = **negasi persis** dari −1,930 beku PRAREG-4 ✓
2. **Determinisme:** RUN 2 vs RUN 3 → JSON **identik bit-per-bit**, tanda tangan `9367dd6a322ac01f` ✓
3. **Rekonsiliasi akuntansi** (net = gross − to × fill_rate × fee), cocok ≤ 0,001 bps:

| arm | gross | to×fill×fee | hitung | lapor | ✓ |
|---|---|---|---|---|---|
| shadow 4,00 | +1,930 | 0,513×1,000×4,00 = 2,052 | −0,122 | −0,121 | ✓ |
| nogate 1,14 | +1,930 | 0,513×1,000×1,14 = 0,585 | +1,345 | +1,346 | ✓ |
| gated optimis | −0,107 | 0,550×0,820×1,14 = 0,514 | −0,621 | −0,621 | ✓ |
| gated primer | −0,107 | 0,550×0,820×2,80 = 1,263 | −1,370 | −1,369 | ✓ |
| gated pesimis | −0,107 | 0,550×0,820×4,46 = 2,011 | −2,118 | −2,118 | ✓ |

4. **Dua bug ditemukan & diperbaiki SEBELUM verdict dirilis** (kode menyimpang dari dokumen beku, bukan ambang diubah):
   - **Bug high/low tertukar**: beli dicek `high ≤ limit` (seharusnya `low ≤ limit`) ⇒ `fill_rate = 0,000`, net gated tidak sensitif fee (0,063 identik di 3 tingkat fee). Dokumen beku §3 sudah benar; kode diperbaiki agar patuh.
   - **Panel sintetis C-c degenerate** (`h=l=o=c`) ⇒ gerbang "sentuh" jadi sekadar "harga turun", bruto −15,5/−29,0/−46,4. Diperbaiki pakai rentang intrabar nyata (skala wick terukur dari panel riil = **0,816%** median). Setelah perbaikan C-c = +0,063/+0,271/+0,689 ≈ 0 ✓

---

## 5. KOREKSI KLAIM SEBELUMNYA (RETRAKSI)

Dokumen `STRUKTUR_BIAYA_EKSEKUSI_SODEX` (commit `13aadb4`) dan laporan lisan saya
menyatakan: *"reversal hold-1 dengan fee maker = **+64,6 bps/48 jam = 81% target**"*.

**KLAIM ITU DITARIK.** Angka +64,6 hanya sah pada arm `A_maker_nogate` yang
**mengasumsikan setiap order terisi persis di harga close** — asumsi eksekusi yang
sekarang terbukti **tidak mungkin**. Dengan gerbang sentuh nyata, angka yang sama
jadi **−29,9 s/d −101,7 bps/48 jam**.

Pelajaran metodologis: `t = +5,66` (p≈1,5e−8) pada arm nogate terlihat sangat
signifikan, tetapi seluruh signifikansinya bersandar pada asumsi eksekusi yang
gagal. **Signifikansi statistik tidak pernah menyelamatkan asumsi eksekusi yang salah.**

---

## 6. PREDIKSI vs HASIL (kalibrasi)

| item | diprareg-kan | aktual |
|---|---|---|
| verdict | gagal net | **FALSIFIED** ✓ |
| net gated primer | ≈ +0,50 bps/jam | **−1,369** ✗ (lebih buruk) |
| penyebab | adverse selection | **benar, tapi saya meremehkan besarnya** |

Saya memperkirakan adverse selection sebagai biaya yang *mungkin* muncul; ternyata ia
**lantai struktural ≈3,9 bps/periode** yang lebih besar dari seluruh edge kotor sinyal.

---

## 7. KONSEKUENSI

1. **Jalur 1h DITUTUP secara formal.** PRAREG-4 §5 aturan pra-komit: bila hasil =
   *"semua gagal; hanya reversal yang kuat"* ⇒ jalur 1h ditutup. PRAREG-4 memang
   berakhir begitu; PRAREG-5 adalah upaya menghidupkannya lewat fee maker, dan gagal.
   **Aturan itu kini dieksekusi.**
2. **Kelas strategi "maker passif mengejar spread" di SoDEX 1h ditutup secara umum** —
   bukan hanya sinyal ini. Lantai 3,9 bps/periode berlaku bagi **semua** order maker
   yang terisi hanya saat tersentuh di 1h. Edge kotor apa pun di keluarga ini harus
   melewati lantai itu dulu.
3. **Yang tersisa: 1d + data forward** (sesuai konsekuensi PRAREG-4). Sertifikasi sah
   hanya dari data forward — jendela historis terpakai hanya boleh **membunuh**, tidak
   boleh **mensertifikasi**.

---

## 8. AMBANG YANG SALAH SPESIFIKASI (dicatat jujur, TIDAK diubah surut)

Ambang **#4** prareg berbunyi "kontrol bruto bersih (≈0)". Ia **gagal** karena
kontrol bernilai −3,86, bukan 0. **Premis ambang ini salah saya tulis sebelum run**:
saya menganggap gerbang sentuh tidak bias, padahal ia bias secara mekanis terhadap
**semua** sinyal termasuk acak. Null yang benar = **bruto kontrol ber-gerbang**, bukan 0.

**Ambang TIDAK diubah setelah melihat hasil.** Dan verdict **tidak bergantung** pada
#4: ambang #1, #5, #6, #7 semuanya gagal secara independen. Bahkan dengan null yang
diperbaiki, bruto gated sinyal tetap **negatif absolut** (−0,107) ⇒ tetap FALSIFIED.
Untuk PRAREG-6 (jika ada), ambang kontrol harus ditulis sebagai *"gross sinyal > gross
kontrol ber-gerbang yang sama"* + *"gross sinyal > 0 secara absolut"*.

---

## 9. STATUS REGISTRY

Entri trial ditambahkan **append-only** ke `reports/sodex/sodex_trial_registry.json`
(tidak ada reset, tidak ada penghapusan entri lama).

---

*PRAREG-5 selesai. Verdict: FALSIFIED. Jalur 1h ditutup. Tidak ada klaim sertifikasi.*
