# D07 — RCA: Strategi `twoway` LONG Tidak Ber-Alpha; T1 FAIL itu Benar

**Tanggal:** 2026-10-05
**Divisi:** SoDEX
**Alat:** `scripts/sodex_long_entry_filter_study.py` (read-only, reproducible)
**Memperbaiki temuan:** D06 (`reports/sodex/D06_BREAKDOWN_PER_SISI_2026-10-04.md`)

---

## 0. Koreksi Diri atas D06

D06 menyimpulkan: *"constraint T1 adalah BIAYA, bukan sinyal."*

Itu **benar pada resolusi agregat, tetapi menyesatkan sebagai arahan.**
D06 memakai **satu angka agregat** untuk seluruh periode — dan agregat itu
**menyamarkan keruntuhan rezim**. Analisis per-segmen di bawah membantahnya.

Angka agregat `twoway LONG` = **+8,01 bps** adalah **rata-rata dari tiga periode
yang sangat berbeda**: −10,19 / **+62,96** / −28,40 bps. Angka positifnya datang
seluruhnya dari **satu jendela 15 hari yang berakhir 19-Sep (2 minggu lalu)**.

**Pelajaran:** jangan pernah menyimpulkan dari agregat satu-periode. Pecah menurut
waktu sebelum menamai penyebab.

---

## 1. Baseline per Segmen (harness beku, beta-netral, fee RT 8 bps)

`twoway` LONG, arm SIGNAL, n=325, dibagi tiga menurut `entry_time`:

| segmen | rentang | n | WR | edge (excess) | cost 2× | Sharpe | maxDD | TP/SL |
|---|---|---:|---:|---:|---:|---:|---:|---|
| S1 | 06-Agu → 04-Sep | 108 | 38,9% | **−10,19 bps** | −26,19 | −1,06 | −27,1% | 51/35 |
| **S2** | **04-Sep → 19-Sep** | 108 | 50,9% | **+62,96 bps** | **+46,96** | 5,31 | −22,2% | 39/45 |
| S3 | **19-Sep → 03-Okt** | 109 | 29,4% | **−28,40 bps** | **−44,40** | −2,30 | −36,6% | **26/55** |

**SHORT per segmen: S1 = 42, S2 = 0, S3 = 0.**
Kaki ber-edge (SHORT, +60,9 bps) berhenti total setelah 01-Sep.

### 1.1 S3 adalah periode TERKINI — dan ia kalah bahkan pada fee NOL

S3 kehilangan **−28,40 bps/trade** *sebelum* dikurangi biaya apa pun. Artinya:

> **Menurunkan fee (maker / rebate tier) TIDAK akan menyelamatkan S3.**
> Bahkan fee 0 bps pun S3 tetap rugi.

Ini membatalkan arah yang D06 rekomendasikan.

---

## 2. Uji 12 Filter Entry — TIDAK ADA YANG LAYAK

Kandidat dideklarasikan **di muka** dari komponen logika yang sudah ada
(`entry_reasons`) + satu dimensi rezim. Penalti multiple-testing memakai
mekanisme harness sendiri (`n_trials` = 11 registry + 12 kandidat = 23 → DSR).

Validasi: **tiga segmen waktu**; LAYAK hanya bila cost 2× positif di **ketiganya**.

| kandidat | n | edge | cost 2× | S1/S2/S3 | LAYAK |
|---|---:|---:|---:|:--:|:--:|
| flag: `strong_24h_trend` | 231 | +24,28 | +8,28 | no/**OK**/no | ❌ |
| flag: `vol_above_avg` | 185 | +20,70 | +4,70 | no/**OK**/no | ❌ |
| combo `above_sma24+strong_24h_trend+vol_above_avg` | 90 | +51,65 | +35,65 | −/**OK**/no | ❌ |
| flag: `above_sma24` | 310 | +9,63 | −6,37 | no/**OK**/no | ❌ |
| flag: `minor_pullback` | 208 | −15,66 | −31,66 | no/**OK**/no | ❌ |
| `btc_regime:BULL` | 141 | +5,37 | −10,63 | −/**OK**/no | ❌ |
| *(6 kandidat lain)* | — | negatif | negatif | semua `no` | ❌ |

**Hasil: `LAYAK: TIDAK ADA`.**

### 2.1 Pola `no/OK/no` — inilah temuan sebenarnya

**SEMUA** kandidat yang tampak lolos punya pola identik: **positif hanya di S2.**
Itu bukan tanda adanya filter yang bagus — itu tanda bahwa **seluruh profit
berasal dari satu jendela waktu**, dan filter apa pun yang memuat S2 akan tampak
"berhasil".

### 2.2 Jebakan yang ketangkap di tengah jalan (jangan hilangkan)

Percobaan pertama memakai **validasi belah-dua** (median `entry_time`) dan
**meloloskan** `strong_24h_trend` — edge +24,28 bps, cost 2× +8,28, "lulus di
kedua paruh".

Itu **FALSE POSITIVE**. Median (12-Sep) kebetulan jatuh **di dalam** jendela
mujur 04–19 Sep, sehingga kedua paruh memuatnya dan keduanya tampak lulus.
Tiga segmen langsung membongkarnya: sepertiga-1 **−7,72** | sepertiga-2
**+93,60** | sepertiga-3 **−9,10**.

> **Aturan tetap:** validasi ketahanan WAJIB ≥3 segmen waktu. Dua bagian data
> yang berdekatan tidak menguji ketahanan terhadap rezim. Skrip sudah dikunci ke
> tiga segmen dengan catatan ini.

---

## 3. Akar Masalah: Eksposur Faktor, Bukan Alpha

**Konteks pasar per segmen:**

| segmen | BTC | vol 1h | mean P&L di-atas-SMA200 | di-bawah |
|---|---|---:|---:|---:|
| S1 | **+23,36%** | 0,428% | +0,335% | +1,374% |
| S2 | +2,08% | **0,341%** | +0,649% | +0,648% |
| S3 | +4,50% | 0,371% | **−0,124%** | **−0,141%** |

**Bukti kunci — S1:** P&L mentah **positif** (+0,335%) tetapi excess beta-netral
**negatif** (−10,19 bps). BTC naik +23,36% pada S1; "long alt" hanya memanen
beta, sehingga **secara beta-netral ia tertinggal**. Harness menangkapnya dengan
benar.

**Interpretasi:**

> Kaki LONG `twoway` adalah **taruhan faktor "alt mengalahkan BTC"**, bukan alpha.
> Ia mencetak laba ketika alt mengungguli BTC (S2 = jendela alt-season 15 hari),
> dan berdarah ketika tidak (S3 = BTC naik +4,50% tetapi alt tertinggal).

Konsisten dengan catatan yang sudah ada: **beta 0,887, alpha ≈ 0 → decay era-2
= PASAR (p = 0,234)**.

### 3.1 Kode engine TIDAK berubah di batas S2→S3

Tidak ada commit ke `scripts/paper_test_twoway.py` pada 17–22 Sep. Commit lain di
rentang itu adalah CEX/ops/security. **Hipotesis "ada yang rusak di sistem pada
19-Sep" DITOLAK.** Yang berubah adalah **pasar**, bukan mesin.

### 3.2 Geometri exit memburuk di S3

S3: **SL = 55 vs TP = 26** (dua kali lebih sering stop daripada target).
Sinyal `strong_24h_trend` (24h return > 1,2%) tetap menyala, tetapi di S3
**tidak ada kelanjutan** → kena stop. Ini gejala, bukan sebab: sinyal momentum
butuh persistensi tren, dan S3 tidak memberikannya.

---

## 4. Konsekuensi terhadap T1 & Target

| pertanyaan | jawaban |
|---|---|
| Apakah T1 gagal karena fee? | **Tidak (untuk S3).** S3 rugi sebelum biaya. |
| Apakah filter entry bisa memperbaiki? | **Tidak.** 12 kandidat diuji, nol layak. |
| Apakah turunkan fee membantu? | **Tidak.** S3 negatif pada fee 0. |
| Apakah tunggu rezim BEAR membantu? | SHORT ber-edge +60,9 bps, tapi **0 trade sejak 01-Sep** — tak dapat dijadwalkan. |
| Apakah GO-LIVE mesin ini layak? | **Tidak.** T1 FAIL adalah penilaian yang **benar** dan struktural. |

**Implikasi untuk strategi 6–8 mesin (ρ ≤ 0,1):**
Mesin yang dibangun dari keluarga sinyal ini akan **mewarisi eksposur faktor yang
sama** (alt-vs-BTC). Itu otomatis **melanggar syarat ρ ≤ 0,1** — jadi
memperbanyak mesin dari keluarga ini **tidak menambah mesin, hanya menambah
leverage terselubung**. Target 0,8%/48h hanya bisa datang dari **sumber return
yang benar-benar tidak berkorelasi**, bukan dari memperbanyak varian sinyal yang
sama.

---

## 5. Yang TIDAK boleh dilakukan (fail-closed dipertahankan)

- ❌ Jangan membuka E1 maker. Ia tidak menolong: S3 rugi sebelum biaya.
- ❌ Jangan memasang filter `strong_24h_trend` (atau lainnya) ke produksi.
  Semua gugur validasi tiga-segmen.
- ❌ Jangan menurunkan gate T1 agar lolos.
- ❌ Jangan menambah mesin dari keluarga sinyal ini (melanggar ρ ≤ 0,1).
- ❌ Jangan mengubah target / leverage.

**Tidak ada guard yang disentuh. Tidak ada track yang dipromosikan. `unfreeze = NO`.**

---

## 6. Reproduksi

```bash
python3 scripts/sodex_long_entry_filter_study.py --dry-run   # tanpa tulis registry
python3 scripts/sodex_long_entry_filter_study.py             # catat 12 trial
```

Semua 12 kandidat — lulus maupun gagal — dicatat ke
`reports/sodex/sodex_trial_registry.json` sesuai mandat.

---

*D07 — Hermes Anantara v3 | SoDEX | 2026-10-05*
