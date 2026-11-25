# PRAREG-5 — REALISME FILL MAKER pada arah reversal, panel SoDEX 1h

**Dibekukan:** 2026-10-07 · **Status: BEKU — commit SEBELUM evaluasi**
**Label keluaran: DESKRIPTIF** · **Verdict sertifikasi: MUSTAHIL dari dokumen ini**

---

## 0. Dua hal yang WAJIB dibaca sebelum apa pun

### 0.1 Konflik yang harus diakui, bukan disembunyikan

Dokumen biaya `STRUKTUR_BIAYA_EKSEKUSI_SODEX_2026-10-07.md` (commit `13aadb4`) melaporkan arah
**reversal** di hold-1 sebagai **+64,6 bps/48 jam = 81% target** dengan fee maker. Tiga masalah:

1. **PRAREG-4 (commit `2a8fcdf`) sudah pra-komit** di §5 baris 97: bila hasilnya "semua gagal;
   hanya reversal yang kuat" → **jalur 1h DITUTUP**. Hasil aktual persis di baris itu
   (H4 momentum gagal 7/7; hanya reversal kuat). **Menghidupkan jalur 1h karena satu tweak baru
   = mode kegagalan yang dijaga protokol.**
2. **Tanda reversal dipilih SESAAT SETELAH melihat data.** Sinyal beku PRAREG-4 adalah
   `+(close−lo20)/(hi20−lo20)` (tanpa minus, lihat `rangepos_sodex_1h_prereg4.py` baris 48).
   Gross = −1,93 → arah untung adalah negasinya. Per kerangka §11(g): tanda pasca-hoc **wajib
   dipraregistrasi ulang sebagai hipotesis BARU** + uji **pisah-waktu**, bukan diteruskan.
3. **Jendela 2025-10-12 → 2026-10-07 sudah terpakai** (PRAREG-2/3/4).

### 0.2 Asimetri epistemik yang membuat dokumen ini tetap berharga

> **Falsifikasi asimetris.** Menguji di jendela terpakai **tidak bisa mensertifikasi**, tetapi
> **BISA MEMBUNUH**. Jadi kekuatan sah PRAREG-5 = **membunuh atau berkata "menjanjikan, butuh
> forward"** — dan **tidak pernah** "lulus".

Karena itu ambang di dokumen ini **sengaja lebih ketat** daripada PRAREG-4, dan verdict
positif hanya boleh **menyalakan verifikasi forward**, **bukan** membuka jalan 1h untuk modal.

---

## 1. Pertanyaan yang dijawab

Klaim yang diuji: *"reversal hold-1 di SoDEX 1h bisa ditangkap dengan eksekusi maker"*.

Kerangka §7 (`anantara-master-evidence-framework`) memaksa pertanyaan pendahulu:
`gross > 0` sebelum biaya? **Ya tak terbantah** (bruto +1,93 bps/jam, t=+16,6, IC_reversal=+0,0432
— tanda kebalikan dari IC momentum −0,0432 yang beku). Maka masalahnya **BUKAN sinyal,
melainkan BIAYA/EKSEKUSI** → tepat menguji realisme fill.

Dokumen venue (`sodex.com/documentation/trading-mechanics/trading-fees`) + kode produksi repo
(`anantara/sodex_farming.py` baris 8 & 3199) memberi fee akun ini: **maker 1,14 bps / taker 3,80 bps**.

## 2. Hipotesis (falsifiable)

> **H5 (hipotesis BARU, §11(g)):** Pada panel SoDEX 1h, sinyal RANGEPOS **tanda-reversal**
> `−(close−lo20)/(hi20−lo20)` dengan **eksekusi maker-gated** (limit `close_i ∓ ½spread`, terisi
> hanya bila bar `i+1` menyentuh `low`/`high`) menghasilkan **net > 0 pada OOS 40% termuda**
> dan tahan di ketiga sub-segmen OOS.
>
> **H0:** net ≤ 0 pada OOS, ATAU gagal salah satu ambang §5.

**Prediksi jujur (ditulis sebelum hasil):** saya memperkirakan **GAGAL**. Fee realistis
maker-masuk/taker-keluar = 5,60 bps per round-trip, sedangkan bruto hold-1 hanya 1,93 bps/jam
dengan turnover 0,51 → biaya ≈ 0,51 × 2,80 = **1,43 bps/jam** → net ≈ **0,50 bps/jam ≈ 24 bps/48 jam
= 30% target**, dan itu **sebelum** adverse selection. Bila gerbang sentuh menolak ≈>50% notional
atau mengisi justru sisi yang salah, ini mati.

## 3. Spesifikasi BEKU

| Komponen | Nilai beku | Asal |
|---|---|---|
| Panel | `data/sodex_klines/1h` via `_sodex_panel("1h")` | 95 nama × 8.533 bar, 2025-10-12 → 2026-10-07 |
| Sinyal | `−range_position(px, 20)` (tanda **reversal**) | negasi `rangepos_sodex_1h_prereg4.py` |
| Bobot | `rank_w` — proporsional-peringkat, dollar-neutral, Σ\|w\|=1 | **verbatim** `xsec_mech_study` |
| Excess | `fwd − mean(fwd)` lintas-seksi | **verbatim** |
| Hold primer | **h = 1** (dari analisis biaya) | dibekukan |
| Hold sekunder | h = 2, 4 | dibekukan |
| **Fill rule** | naik: limit `close_i·(1−hs)`, terisi iff `low_{i+1} ≤ limit`; turun: limit `close_i·(1+hs)`, terisi iff `high_{i+1} ≥ limit`. **Tidak tersentuh → bobot tetap `prev_w`** (BUKAN dianggap terisi di close) | dibekukan |
| `hs` (setengah spread) | **0,66 bps** = ½ × median spread venue terukur (1,32) | `SODEX_SPREAD_CENSUS_2026-10-07.json` |
| **Fee primer** | `fee_oneway_eff = 2,80 bps` (maker-masuk 1,14 + taker-keluar 3,80+0,66=4,46; rata-rata) | dokumen venue + kode produksi |
| Band fee | 1,14 (maker-murni, optimis) … 4,46 (taker-murni, pesimis) | dibekukan |
| Pisah-waktu | **IS = 60% bar tertua, OOS = 40% termuda**; parameter TIDAK disetel ulang | §11(g) |
| Segmen | **3 sub-segmen pada OOS** | `anantara-*` + `signal-gate-falsification` |
| Koreksi banyak-uji | **BH-FDR q = 0,10** atas keluarga yang dideklarasikan | konstanta |
| Seed | 20261007 | dibekukan |
| Determinisme | 2× jalan harus **hash bit-identik** | fail-closed |

## 4. Tiga arm (kontrol terpisah, tidak boleh dicampur)

| Arm | Terisi di | Fee | Fungsi |
|---|---|---|---|
| **A_shadow_taker** | selalu, di `close_i` | 4,00 bps | baseline tabel §5 dokumen biaya |
| **A_maker_nogate** | selalu, di `close_i` | **1,14 bps** | mereplikasi klaim "81% target" |
| **A_maker_gated** ← **PRIMER** | hanya bila high/low tersentuh | **2,80 bps** | menguji H5 |

## 5. Ambang (SEMUA wajib benar; hanya boleh MEMPERKETAT)

1. **A_maker_gated: net OOS > 0** dan net per 48 jam **> 0** pada band fee primer.
2. **Fill rate ≥ 30%** menurut notional.
3. **A_maker_gated tidak boleh lebih baik daripada A_shadow_taker** → bila lebih baik, ada cacat model.
4. **Kontrol negatif bersih, dinilai pada BRUTO**: C-a acak-dalam-baris, C-b sinyal-acak-penuh,
   C-c panel sintetis → ketiga bruto ≈ 0 dan **tidak** melampaui sinyal. (§11(f): nilai pada bruto,
   karena bobot acak turnover ≈1,3–2,0 selalu kalah biaya.)
5. **Ketahanan 3 segmen OOS**: minimal **2 dari 3** positif. Segmen yang **efek < MDE** dilaporkan `-`
   (underpowered), **bukan** `no`, dan **tidak dihitung** sebagai lolos.
6. **Segmen TERKINI: bruto > 0 SEBELUM biaya.** Bila bruto segmen terkini ≤ 0 → tidak ada alpha kini;
   penurunan fee tidak menolong → **FALSIFIED**.
7. **p-TERBURUK ≤ 0,05** (bukan p terbaik) pada uji net > 0, SE terklaster per hari.

**Verdict beku:**
- **FALSIFIED** bila salah satu (1)–(7) gagal.
- **PROMISING (butuh verifikasi FORWARD)** bila semua lolos.
- **"LULUS/CERTIFIED" tidak boleh dikeluarkan dari dokumen ini** — jendela sudah terpakai, dan
  PRAREG-4 pra-komit menutup jalur 1h. Sertifikasi hanya dari data forward (§6 PRAREG-4).

## 6. Diagnostik yang WAJIB dilaporkan (tidak boleh dihilangkan)

1. **Fill rate** menurut jumlah simbol **dan** menurut notional.
2. **Adverse selection terukur:** rata-rata `excess` simbol **TERISI** vs **TIDAK TERISI**.
   Bila terisi jauh lebih buruk → seleksi merugikan terbukti kuantitatif (ini inti H5).
3. **MDE per segmen** = `1,96 · σ_seg · sqrt(2/(n_seg/2))`; efek < MDE = `-`.
4. **Daya statistik:** `SE(S_ann) ≈ sqrt((1+S²/2)/T)` tahun; laporkan agar tidak menilai alpha dari jendela pendek.
5. Titik impas: `net = bruto − turnover × fee` → berapa fee yang membuatnya impas (bandingkan fee nyata).
6. Cakupan: min/max timestamp, n bar, n simbol, nama tersedia per periode.

## 7. Yang akan mengubah arah kerja

| Hasil | Konsekuensi |
|---|---|
| FALSIFIED | Jalur reversal 1h **ditutup permanen**; tuas fee pindah ke mesin horizon lain (1d) |
| PROMISING | **Menyalakan verifikasi FORWARD 1h** (collector OBI sudah jalan, 24× periode/hari). Modal TIDAK bergerak |

## 8. Aturan main

- Skrip dibekukan; **tidak boleh diubah setelah melihat hasil**.
- Setiap trial (lulus/gagal) masuk registry **append-only**, idempoten, **tanpa tanggal**, tanpa reset.
- **Fail-closed:** komponen hilang/exception → verdict **bukan PASS**.
- Tidak menyentuh target, ambang, modal, `dry_run`, atau kode produksi mana pun.

— Hermes Anantara v3 — 2026-10-07
