# D09 — Falsifikasi `sodex_model_server` (LightGBM 48 Jam)

**Divisi SoDEX · Hermes Anantara v3 · 5 Oktober 2026**
**Pertanyaan yang diuji:** apakah "mesin punya kecerdasan sendiri" (klaim PF 1,13 / akurasi arah 55–73% OOS) itu **nyata**?

---

## 0. Ringkasan Satu Menit

> **VERDICT: TIDAK ADA SATU PUN dari 57 simbol yang layak dipromosikan.**
>
> | Uji | Hasil |
> |---|---|
> | Lolos koreksi BH-FDR (q=0,10) | **0 / 57** |
> | P&L bersih > 0 setelah fee 8 bps | **27 / 57 (47,4%)** — koin |
> | Rata-rata P&L bersih | **−16,3 bps** |
> | Simbol "OK" di ketiga segmen waktu | **0 / 57** |
> | n sampel efektif (setelah koreksi jendela tumpang-tindih) | 504 → **10,5** (menciut 48×) |
>
> Angka unggulan **72,92% (AMD)** ternyata **lebih kecil** dari yang dihasilkan **kebetulan murni** (88,4%). Model ini bukan punya edge lemah — ia **tidak punya edge sama sekali**.

**Implikasi langsung ke pertanyaan "perlu integrasi LLM?":** tidak. Masalahnya bukan jenis kecerdasannya (LLM vs GBM) — melainkan **tidak ada sinyal** pada prediksi arah 48 jam dari fitur teknikal tersebut. Mengganti LightGBM dengan LLM tidak menciptakan sinyal yang tidak ada.

---

## 1. Apa yang Diuji, dan Kenapa Bukan Sekadar "Ukur Ulang"

Model melaporkan `dir_acc_oos` = **58,3%** (BTC), **72,9%** (AMD), **67,2%** (GOOGL). Angka-angka itu **dilaporkan oleh model itu sendiri**, dari baris kode yang sama yang membuatnya. Itu bukan verifikasi — itu **auto-sertifikasi**.

Studi ini menguji **apakah angka itu berarti**. Lima cacat ditemukan dengan membaca `anantara/sodex_model_server.py`.

---

## 2. Lima Cacat Metodologi (dengan rujukan kode)

### F1 — SELEKSI: model memilih sampel mana yang dinilai

```python
# sodex_model_server.py baris 132–134
sel = np.abs(pred) >= THRESHOLD          # THRESHOLD = 0.004
dir_acc = (np.sign(pred[sel]) == np.sign(act[sel])).mean()
```

Akurasi dihitung **hanya pada baris yang modelnya yakin**. Baris yang ragu dibuang dari penilaian. Model **menentukan sendiri ujiannya** — ini menaikkan angka tanpa menaikkan kemampuan.

**Bukti terukur:** pada 10 simbol unggulan, inflasi seleksi **+0,25 s/d +3,30 pp**. Paling parah **PENGU-USD: 60,45% → 57,14% (tipu +3,30 pp)**.

### F2 — JENDELA TUMPANG-TINDIH: n menciut 48×

```python
label = close.shift(-48) / close - 1     # return 48 jam ke depan, bar 1 jam
```

Dua label bersebelahan **berbagi 47 dari 48 jam**. Jadi baris-baris itu **tidak independen**. n efektif = n × (1/48).

| | Nilai |
|---|---|
| n_oos rata-rata dilaporkan | **504** |
| **n efektif (independen)** | **10,5** |
| SD proporsi null pada n_eff=10,5 | **±15,4 pp** |

Akurasi 58% pada n_eff≈10 punya CI95 kira-kira **[27%, 90%]** — **memuat 50%**, jadi tidak terbedakan dari koin.

### F3 — SELEKSI JUARA: statistik yang hanya bisa naik

```python
# baris 154
challenger["champion_best_acc"] = max(dir_acc, champ_acc)
```

`max(...)` = **monoton naik, tidak pernah turun**. Ini "prestasi terbaik sepanjang masa", bukan akurasi sekarang. Dikalikan saringan atas **57 simbol** → klasik *multiple testing*.

**Perhitungan penentu:** dengan n_eff ≈ 10,5, **E[max dari 57 undian acak murni] = 88,4%**. Angka "terbaik" model, **72,92%, berada DI BAWAH itu**. Artinya angka terbaik model itu **tidak istimewa sama sekali** — ia lebih buruk dari yang bisa muncul dari kebetulan.

### F4 — TANPA BIAYA: akurasi arah ≠ laba

Prediksi arah tidak dikonversi ke P&L. Padahal fee RT SoDEX = **8 bps**. Sinyal yang menghasilkan gerakan rata-rata < 8 bps **merugi meski arahnya benar**.

### F5 — DATA BEKU: model "retrain" tapi tidak belajar apa pun

| Bukti | Nilai |
|---|---|
| Rentang data SEMUA simbol | berakhir **2026-05-21** |
| Hari ini | **2026-10-05** → **basi 4,5 bulan** |
| Mount data | `/data/perps` **`rw=false`** (read-only, mustahil update) |
| Container dibuat | **2026-05-21** |

Log retrain berulang kali:
```
2026-10-04 09:17:30 BTC-USD: promoted — 5127 rows, OOS dir-acc 58.307210031347964 (was 58.307210031347964)
2026-10-04 15:57:30 BTC-USD: promoted — 5127 rows, OOS dir-acc 58.307210031347964 (was 58.307210031347964)
```

Angkanya **bit-identik**. Endpoint `/health` melaporkan `age_min: 387` (6,5 jam) — itu **umur proses, bukan umur pengetahuan**. Model melayani pasar Oktober dengan pengetahuan Mei.

---

## 3. Metode (disiplin yang dipegang)

| Aturan | Penerapan |
|---|---|
| Tanpa look-ahead | Semua indeks train/OOS `< n − LABEL_H`; diuji otomatis (`TestTanpaLookAhead`) |
| Reproduksi persis | `LABEL_H`, `THRESHOLD`, `PERIODS`, split 85/15, hyperparameter — **diuji anti-drift** terhadap sumber server |
| Kontrol negatif | Label diacak, latih ulang, ukur ulang (6 simbol × 15 ulangan) |
| Multiple testing | BH-FDR q=0,10 atas p binomial pada **n efektif** |
| Ekonomi nyata | Fee RT 8 bps dikurangkan dari setiap sinyal |
| Ketahanan rezim | 3 segmen kronologis; segmen tanpa daya uji dilaporkan **`-`**, bukan `no` |
| Tanpa menyentuh produksi | Read-only; container tidak diubah; `unfreeze = NO` |

---

## 4. Hasil Lengkap

### 4.1 Kontrol negatif — pipeline itu sendiri jujur

| | Nilai |
|---|---|
| Akurasi null (label diacak) rata-rata | **48,26%** (sd 2,10) |
| Akurasi jujur (tanpa seleksi) | 56,09% |
| Selisih | **+7,83 pp** (4 dari 6 simbol > 5 pp) |

Pipeline **tidak menghasilkan positif palsu secara sistematis** — null-nya duduk di ~50% sebagaimana mestinya. Ini penting: berarti hasil "gagal" di bawah **bukan karena alat ukurnya rusak**, melainkan karena efeknya memang tak ada.

### 4.2 10 simbol "unggulan" — dibongkar

| Simbol | Dilaporkan | Jujur | Inflasi | n_eff | CI95 | Net (bps) | 3 segmen |
|---|---:|---:|---:|---:|---|---:|---|
| AMD-USD | 72,92% | 71,43% | +1,50 | 6,3 | [30, 90] | +101,7 | `-OK-` |
| GOOGL-USD | 67,17% | 65,22% | +1,95 | 8,1 | [31, 86] | +58,5 | `OK-OK` |
| XMR-USD | 66,94% | 65,85% | +1,09 | 8,5 | [35, 88] | +131,8 | `OKnoOK` |
| DASH-USD | 66,83% | 66,58% | +0,25 | 8,5 | [35, 88] | +161,9 | `OKOKno` |
| MU-USD | 65,37% | 64,45% | +0,92 | 6,3 | [30, 90] | +154,9 | `-OKOK` |
| ZEC-USD | 64,11% | 63,00% | +1,11 | 11,5 | [32, 81] | +453,0 | `OKOK-` |
| TRX-USD | 63,61% | 62,63% | +0,98 | 9,8 | [31, 83] | +9,5 | `noOKOK` |
| SILVER-USD | 60,80% | 59,27% | +1,53 | 8,5 | [27, 81] | +210,8 | `-OKOK` |
| PENGU-USD | 60,45% | 57,14% | **+3,30** | 11,4 | [35, 85] | +171,9 | `OKOK-` |
| SKHX-USD | 59,50% | 57,33% | +2,17 | 4,7 | [23, 88] | +106,3 | `OK--` |

**Setiap CI95 memuat 50%.** Tidak ada satu pun yang terbedakan dari koin.

### 4.3 Ekonomi setelah fee

| Metrik | Nilai |
|---|---:|
| Rata-rata net | **−16,3 bps** |
| Median net | **−16,8 bps** |
| Positif | 27/57 (47,4%) |
| Rentang 95% | [−238,2 ; +195,2] bps |
| Terburuk | **−488,9 bps (LIT-USD)** |

Sebaran selebar ini dengan median negatif = **tanpa edge terukur**.

### 4.4 Ketahanan tiga segmen

| Veredict | Jumlah |
|---|---:|
| OK di **ketiga** segmen | **0 / 57** |
| ≥2 OK tanpa `no` | 6 / 57 (GOOGL, HYPE, MU, PENGU, SILVER, ZEC) |
| Mengandung `no` | 44 / 57 |
| Tak dapat dinilai (`-`) di ≥1 segmen | 33 / 57 |

Keenam kandidat lemah itu pun **gagal BH-FDR**.

---

## 5. Uji Penentu — Apakah Angka Terbaik Itu Istimewa?

```
n_eff rata-rata          = 10,5
SD proporsi null         = 15,4 pp
E[max dari 57 undian]    = 88,4%
Angka "terbaik" model    = 72,92%
```

**72,92% < 88,4%.** Angka terbaik model **lebih buruk** daripada yang bisa muncul dari **kebetulan murni** pada n efektif sekecil itu.

Inilah sebabnya **0 dari 57** lolos BH-FDR: tidak ada yang perlu dikoreksi — yang ada memang bukan sinyal.

---

## 6. Kesimpulan

1. **Klaim "PF 1,13 / akurasi 55–73%" tidak bertahan.** Angka-angka itu produk dari (a) seleksi baris, (b) jendela tumpang-tindih yang menciutkan n 48×, (c) pemilihan juara dari 57 simbol, (d) tanpa biaya.
2. **"Model retrain tiap 6 jam" adalah ilusi kesegaran.** Data beku 21 Mei, mount read-only, angka bit-identik.
3. **Menambah LLM tidak akan menolong.** Kekurangan bukan pada *jenis* kecerdasan, melainkan pada **tidak adanya sinyal** di prediksi arah 48 jam dari fitur teknikal tersebut.
4. **Ini hasil yang berguna.** Kita menghemat berbulan-bulan mengejar hantu, dan sekarang tahu pasti: sumber edge harus dicari di tempat lain — **struktur pasar** (funding, orderflow, likuidasi), bukan indikator harga.

---

## 7. Rekomendasi (berurut prioritas)

| # | Tindakan | Alasan |
|---|---|---|
| 1 | **Perbaiki kesegaran data** — mount `/data/perps` `rw=true` + job pengambil kline harian | Tanpa ini, setiap model yang dilatih di container ini **mustahil** punya nilai |
| 2 | **Koreksi pelaporan `/health`** — pisahkan `age_min` (proses) dari `data_age` (umur data); buang `champion_best_acc` | Saat ini endpoint **melaporkan kesegaran palsu** |
| 3 | **Buang seleksi `|pred| >= THRESHOLD`** dari penilaian, dan **blokir penilaian H0 pada n_eff < 30** | Cacat F1 & F2 adalah sumber inflasi |
| 4 | **Alihkan pencarian edge ke struktur pasar** — funding, orderflow (1,6 GB sudah ada), likuidasi | Arah harga dari TA: tidak ada sinyal (terbukti). Struktur pasar: prediktabilitas lebih tinggi (akademik AUC 0,62–0,68) |
| 5 | Pertahankan `unfreeze = NO`, gate T1 utuh, tanpa leverage, target tidak diubah | Temuan ini **memperkuat**, bukan mengubah, disiplin yang ada |

---

## 8. Verifikasi & Reprodusibilitas

```bash
# Uji (host): 30 test
python3 -m pytest tests/test_sodex_model_falsification.py -q

# Studi (container, punya lightgbm+talib):
docker exec -i anantara-sodex-model python3 - \
  --shuffles 15 --out /tmp/falsif_full.json < scripts/sodex_model_falsification.py
```

| Item | Nilai |
|---|---|
| Simbol diuji | **57** |
| Waktu jalan | 70,7 s |
| Test | **30 lulus, 0 gagal** |
| Data mentah | `reports/sodex/sodex_model_falsification_2026-10-05.json` (66.496 byte) |
| Kontrol negatif | 6 simbol × 15 ulangan label-acak |
| Look-ahead | 0 (diuji otomatis) |
| Produksi disentuh | **tidak** |

### Catatan integritas statistik
57 simbol **tidak** dicatat sebagai 57 trial di registry `sodex_trial_registry.json` karena registry itu milik famili hipotesis **track twoway**, bukan famili model. Penerapan multiple-testing sudah dilakukan **di dalam studi ini** (BH-FDR atas 57 simbol), yang merupakan perlakuan yang benar. Mencampurkan famili akan mendistorsi DSR track twoway.

---

*D09 · Divisi SoDEX · Hermes Anantara v3 · 5 Oktober 2026*
*Berkas pendamping: `D07_RCA_FILTER_DAN_FAKTOR`, `D08_PREDIKTOR_REZIM_EXANTE`, `PENJELASAN_AWAM_STRATEGI_TARGET_SODEX`*
