# D12 — Analisis Mendalam & Akurat: Struktur Return Lane REAL-WIDE

**Divisi SoDEX · Hermes Anantara v3 · 5 Oktober 2026**
**Lanjutan D11.** D11 membuktikan *apa* yang gagal. D12 membuktikan ***mengapa*** — dan menemukan **dua bug yang membatalkan dua hasil sebelumnya**.

---

## 0. Ringkasan — Lima Temuan Baru

| # | Temuan | Dampak |
|---|---|---|
| **1** | **`atr_pct` HILANG pada 89% trade** → `_entry_vol_gate` praktis **tidak pernah aktif** | **Membatalkan kesimpulan A/B** — arm "gate ON" bukan gate |
| **2** | **Margin lane paper = 328% wallet** ($800 vs $243,57) | Return "+61%" adalah **artefak**, bukan hasil yang bisa didanai |
| **3** | **Return akurat (dibatasi margin wallet): +0,652%/hari** | **163% target** — tetapi lihat #4 |
| **4** | **Median window 48 jam = +0,452% vs target 0,8%** (baru 46,2% window capai) | Masalahnya **RELIABILITAS**, bukan level |
| **5** | **Exit parsial menaikkan median trade** (−0,044% → +0,248%) **tetapi GAGAL ketahanan 3 segmen** (S2 < 0) | Tidak boleh dipakai; sudah dicatat di registry |

---

## 1. Penutupan Arm A1 — Opsi A Dieksekusi

| Tindakan | Hasil |
|---|---|
| `systemctl --user stop anantara-paper-realwide-atrvol.service` | ✅ OK |
| `systemctl --user disable ...` | ✅ `disabled` |
| Status akhir | `inactive` / `disabled` |
| Arsip bukti → `data/archive/arm_a1_atrvol_20261005/` | 5 berkas, **SHA256 tercatat** |
| State dihapus? | **TIDAK** — jejak falsifikasi wajib dipertahankan |
| `README_KEPUTUSAN.md` | ✅ ditulis (dasar, bukti, larangan hapus) |

Arm yang tersisa: **KONTROL** dan **A2 `_atrvolopen`** (keduanya `active running`).

> Catatan jujur: A1 memiliki **3 posisi terbuka** saat dihentikan. Karena ini **paper** dan arm-nya dihentikan permanen, posisi tersebut tidak dieksekusi lebih lanjut — state-nya terarsip apa adanya. Tidak ada uang nyata yang terdampak.

---

## 2. 🐛 BUG #1 — Gerbang Vol Praktis TIDAK PERNAH AKTIF

```
trade dengan atr_pct ADA & > 0 :  27 / 245   ( 11,0%)
trade dengan atr_pct 0 / NULL  : 218 / 245   ( 89,0%)
```

`_entry_vol_gate(thr=2.0%)` menilai volatilitas dari `atr_pct`. Bila `atr_pct` = 0/NULL, gerbang **tidak bisa menolak apa pun.**

### Konsekuensi yang membongkar kesimpulan D11

Desain eksperimen A/B adalah **"gate ON" (A1) vs "gate OFF" (A2)**. Tetapi bila gerbang itu sendiri no-op pada 89% entry:

> **A1 dan A2 sesungguhnya adalah PERLAKUAN YANG SAMA. Eksperimen membandingkan dua hal yang tidak berbeda — karena perbedaannya memang tidak ada.**

Ini menjelaskan **kenapa A2 ≈ KONTROL** (D11) tanpa perlu berhipotesis apa pun. Bukan "vol gate bukan akar masalah" — melainkan **vol gate tidak pernah berjalan**.

> **D11 menyimpulkan hal yang benar dari alasan yang salah. Koreksi ini wajib.**

**Ini juga cacat pada arm A/B itu sendiri** (`AB_REALWIDE_ATR_ARM_20260925`): dokumennya menyatakan *"vol gate ATR>2%: AKTIF"* pada arm kontrol & A1. **Tidak aktif.** Dokumen arm salah menggambarkan perilaku sistemnya sendiri.

---

## 3. 🐛 BUG #2 — Lane Paper Butuh Margin 328% Wallet

Dari kode (`scripts/paper_test_realwide.py`):

```python
LEVERAGE = 3                      # baris 95
return NOTIONAL * LEVERAGE        # baris 182 — "exposure-based denominator"
pnl_usd = pnl * NOTIONAL * LEVERAGE   # baris 620
```

| Besaran | Nilai |
|---|---|
| Exposure per posisi | **$300** |
| Margin per posisi | **$100** |
| **Konkurensi maksimum terukur** | **8 posisi** |
| **Margin puncak** | **$800** |
| Wallet | **$243,57** |
| **Margin / wallet** | **328%** |

**Lane paper mengambil posisi yang tidak bisa didanai wallet-nya sendiri.**

Bandingkan dengan lane live yang **punya** plafon:
```
realwide_micro_live.py:79   LEVEL2_MARGIN_UTIL_CAP = 0.70
```

> **Lane paper TIDAK punya plafon margin; lane live punya (70%).**
> **Dua lane memakai anggaran risiko berbeda → hasil paper tidak bisa dipindahkan ke live.**
> Inilah sebabnya angka "+61,27%" tidak bermakna: ia dihitung dari notional yang tidak akan pernah tersedia.

---

## 4. Return yang AKURAT — Disimulasi dengan Batas Margin Wallet

Simulasi: jalankan kronologis, ambil trade hanya bila margin tersedia.

| Plafon margin | Trade diambil | Lewat | PnL | Return | Per hari |
|---|---|---|---|---|---|
| Tanpa batas | 245 | 0 | $+149,24 | +61,27% | +1,029% |
| **100%** | 115 | 130 | $+142,51 | +58,51% | +0,982% |
| **70% (aturan live)** | **65** | **180** | **$+94,58** | **+38,83%** | **+0,652%** |
| 50% | 65 | 180 | $+94,58 | +38,83% | +0,652% |
| 33% | **0** | 245 | $0,00 | 0,00% | **0,000%** |

**Poin-poin penting:**

1. **Pada plafon 33%, lane tidak bisa mengambil SATU trade pun** ($80 < margin $100). Lane ini **rentan mati** bila modal kecil.
2. **Pada aturan live (70%): +0,652%/hari = 163% dari target 0,4%/hari.** Ini **kabar baik** — dan jauh lebih baik dari kesan D11.
3. **Tetapi kapasitasnya hanya 1 posisi serentak** (bukan 8) — 180 dari 245 trade harus dilewatkan.

---

## 5. Distribusi Window 48 Jam — Angka yang Paling Penting

Ini unit target yang sebenarnya (0,8% per 48 jam). Pada plafon 70%:

| Ukuran | Nilai | Target | Status |
|---|---|---|---|
| **Mean window** | **+1,493%** | 0,8% | ✅ 187% |
| **Median window** | **+0,452%** | 0,8% | ⚠️ **56%** |
| **Window ≥ 0,8%** | **12/26 = 46,2%** | ≥50% | ❌ |
| Window positif | 15/26 = 57,7% | — | — |
| Window terburuk | **−5,45%** | — | — |
| Window terbaik | +16,05% | — | — |

> **Inilah diagnosis sebenarnya, dan ia BUKAN "tidak ada edge".**
>
> **Mean jauh di atas target (+1,49% vs 0,8%). Yang gagal adalah MEDIAN (+0,452%) dan HIT-RATE (46,2%).**
>
> **Target kita adalah "harga mati" — harus nyaris selalu terpenuhi. Lane ini memenuhinya kurang dari separuh waktu.**
>
> **Masalahnya RELIABILITAS, bukan LEVEL.** Level sudah lewat; konsistensinya belum.

### Divergensi dari tracker resmi (dilaporkan apa adanya)

| Sumber | n | Median window | Hit ≥0,8% |
|---|---|---|---|
| Tracker resmi (`sodex_maturation_status.json`) | 145 | **0,00%** | **39,1%** (9/23) |
| D12 (plafon 70%, n=245→65) | 65 | **+0,452%** | **46,2%** (12/26) |

Kedua konstruksi **berbeda** (subset & definisi window berbeda) dan **keduanya di bawah target pada median**. Tidak ada yang saling membatalkan: **arahnya sama, besarnya berbeda.** Dilaporkan keduanya agar tidak menyesatkan.

---

## 6. Exit Parsial — Naikkan Median, tapi GAGAL Ketahanan

**Kandidat dideklarasikan di muka: 5 threshold (0,50 / 0,75 / 1,00 / 1,50 / 2,00).**
Aturan: 50% posisi keluar di +t% bila puncak menyentuh +t% (limit order — **pasti terisi**, tanpa look-ahead); 50% sisanya exit apa adanya.

| Varian | mean | **median** | WR | S1 med | **S2 med** | S3 med | Lulus 3 segmen? |
|---|---|---|---|---|---|---|---|
| BASELINE | +0,203% | **−0,044%** | 49,4% | +0,756% | **−1,061%** | +0,014% | — |
| 50% di +0,50% | +0,141% | **+0,228%** | 51,8% | +0,756% | **−0,537%** | +0,257% | ❌ sebagian |
| **50% di +0,75%** | +0,141% | **+0,248%** | 51,4% | +0,756% | **−0,454%** | +0,353% | ❌ sebagian |
| 50% di +1,00% | +0,148% | +0,119% | 51,4% | +0,756% | **−1,046%** | +0,414% | ❌ sebagian |
| 50% di +1,50% | +0,176% | +0,155% | 51,8% | +0,756% | **−1,061%** | +0,242% | ❌ sebagian |
| 50% di +2,00% | +0,155% | +0,062% | 50,6% | +0,756% | **−1,061%** | +0,194% | ❌ sebagian |

### Bacaannya (jujur, termasuk yang tidak enak)

1. **Exit parsial MEMANG menaikkan median** (+0,044% → +0,248%) dengan mengorbankan mean (−31%). **Secara arah, ini tepat**: target kita median, dan kita menukar sedikit mean untuk median. **Mekanismenya nyata.**
2. **TAPI gagal ketahanan 3 segmen.** Di **S2 (n=103, segmen terbesar) median tetap NEGATIF** pada semua 5 varian.
3. Pola **S1 untung besar / S2 negatif / S3 datar** adalah **pola jendela mujur**, bukan pola filter bagus — persis peringatan di `skill: signal-falsification`.
4. **Segmen S1 hanya n=29** (mean +1,667%, WR 72,4%). **S1 adalah jendela keberuntungan**, dan seluruh kesan "edge" bersumber dari sana.

### Uji signifikansi MEDIAN (bootstrap 10.000, cluster-hari)

| Varian | median | CI95 | P(median ≤ 0) |
|---|---|---|---|
| BASELINE | −0,044% | [−0,752%, +0,206%] | **0,570** |
| Parsial +0,75% | +0,248% | [−0,250%, +0,468%] | **0,326** |
| Parsial +0,50% | +0,228% | [−0,338%, +0,347%] | **0,280** |

**P(median≤0) turun dari 0,570 → 0,280** — perbaikan nyata secara arah, **tetapi belum di bawah 0,05**. **Belum signifikan.**

### Registry (anti p-hacking)

```
sebelum: n = 31
sesudah: n = 36   (+5)
berkas stabil (tanpa tanggal), append-only, TIDAK ada reset
verdict tercatat: REJECTED — gagal ketahanan 3 segmen; tidak signifikan
```

**5 trial dideklarasikan & dicatat. Tidak ada penyembunyian trial.**

---

## 7. Putusan

| # | Putusan |
|---|---|
| P1 | **Arm A1 ditutup permanen** (Opsi A) — bukti terarsip, tidak dihapus |
| P2 | **`_entry_vol_gate` RUSAK** — atr_pct hilang 89%. Harus diperbaiki atau diakui non-fungsional |
| P3 | **Lane paper tidak margin-feasible** (328% wallet) — hasil paper ≠ transferable ke live |
| P4 | **Lane punya LEVEL yang cukup** (+0,652%/hari = 163% target pada plafon live 70%) |
| P5 | **Lane GAGAL pada RELIABILITAS** (median 56% target; 46,2% window capai target) |
| P6 | **Exit parsial: mekanisme nyata, tapi ditolak** (gagal 3 segmen, belum signifikan) |
| P7 | **S1 adalah jendela mujur** — jangan menarik kesimpulan dari S1 |

> **Diagnosis akhir: masalahnya bukan "tidak ada edge". Masalahnya adalah DISTRIBUSI — mean lewat, median kurang, ekor menentukan.**
>
> **Ini memperkuat (bukan membatalkan) tesis D11.** D11 menemukan bentuknya; D12 mengukur besarnya.

---

## 8. Rekomendasi — Urutan yang Sudah Dikoreksi

### R1 — Perbaiki gerbang vol (murah, wajib)
`atr_pct` hilang pada 89% trade. Sebelum gerbang apa pun bisa dinilai, **ia harus benar-benar berjalan.**
→ Setelah diperbaiki, ulangi uji falsifikasi gerbang (`skill: signal-gate-falsification`) pada **gerbang yang benar-benar aktif.**

### R2 — Selaraskan anggaran risiko paper ↔ live
Lane paper tanpa plafon margin (328%) vs live 70%. **Tambahkan plafon yang sama ke lane paper**, lalu **hitung ulang seluruh hasil** dengan anggaran yang transferable. Tanpa ini, semua angka paper tidak sah sebagai bukti kesiapan live.

### R3 — Serang RELIABILITAS, bukan level
Level sudah cukup. Yang kurang median & hit-rate. Kandidat:
- **Exit parsial** — mekanisme terbukti menaikkan median; perlu **validasi forward** (bukan in-sample), karena in-sample gagal 3 segmen.
- Cari **sub-populasi dengan median positif**. Satu-satunya kandidat ber-n cukup: **SOL (n=26, mean +1,055%, median +0,325%, WR 53,8%)** — perlu verifikasi mandiri.

### R4 — Order Flow (acuan resmi #1) — setelah R1–R3
Masih kandidat terkuat yang **belum** diuji, dengan 1,6 GB data segar.

---

## 9. Verifikasi

| Item | Nilai |
|---|---|
| Data | `paper_test_realwide_state.json` (245 closed) |
| Kode diperiksa | `scripts/paper_test_realwide.py` (baris 95/168–182/620), `scripts/realwide_micro_live.py` (baris 79) |
| Simulasi margin | kronologis, margin $100/posisi, plafon 33/50/70/100% |
| Bootstrap | 10.000 resample; median; seed 7 & 11 |
| Segmen | 3, dibagi rata atas `entry_ts` (S1 n=29 / S2 n=103 / S3 n=113) |
| Registry | `reports/sodex/sodex_trial_registry.json` — **31 → 36**, append-only |
| Arsip | `data/archive/arm_a1_atrvol_20261005/` (5 berkas + SHA256 + README) |
| Produksi disentuh | 1 unit systemd paper **dihentikan** atas persetujuan user (Opsi A) |
| Skrip | `.hermes/cache/scratch/{deep_dist,deep2,accurate}.py` |

---

*D12 · Divisi SoDEX · Hermes Anantara v3 · 5 Oktober 2026*
*Terkait: D11 (falsifikasi exit), D10 (analisis dokumen), D09 (falsifikasi model)*
