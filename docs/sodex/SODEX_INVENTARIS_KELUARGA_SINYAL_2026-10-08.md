# SODEX — OPSI C: INVENTARIS KANDIDAT KELUARGA SINYAL

**Tanggal:** 2026-10-08 · **Status:** INVENTARIS (read-only — tidak ada uji baru, tidak ada perubahan ambang/live-flag/parameter).
**Otoritas:** Keputusan Mas Anas 2026-10-08 (**Opsi C** pasca-TA15; Opsi B/PRAREG-16 sudah TERBEKU & berjalan paralel).
**Tidak berubah:** Target **0,8%/48 jam** = harga mati · HARD_STOP **20-Nov-2026** · semua gerbang/ambang pra-registrasi beku.

---

## 1. Ringkasan eksekutif

Setelah keluarga **directional alpha** (fade/trend/momentum/mean-reversion) habis difalsifikasi
dan Opsi B (forward lead tunggal) dikomit, Opsi C memetakan apa yang **tersisa** dari seluruh
ruang sinyal — bukan untuk menambah ide, tapi untuk menjawab satu pertanyaan jujur:

> Dari **semua** keluarga sinyal yang pernah diajukan, mana yang **belum difalsifikasi**,
> mana yang **aktif mengumpulkan episode**, dan mana yang **belum pernah diuji**?

Jawaban ringkas: hampir seluruh ruang **directional alpha** sudah tertutup dengan bukti.
Yang tersisa bukan "strategi arah yang lebih pintar", melainkan **satu keluarga yang berbeda
secara struktural — CARRY/funding (delta-netral)** — plus beberapa kandidat belum-uji.

---

## 2. Peta keluarga sinyal

### 2a. DITUTUP — difalsifikasi dengan bukti (directional alpha)

| # | Keluarga | Uji | Hasil | Verdict |
|---|---|---|---|---|
| 1 | Fade H48 (teknikal cermin) | TA7 + TA10 | 0/16 + 0/16 (2 venue) | FALSIFIED |
| 2 | Fade H48 × rezim makro | TA13, TA14, TA15 | 0/18 + 0/18 + 0/18 | FALSIFIED — **fade H48 resmi tutup** |
| 3 | Cross-sectional 12 mech | PANEL_PANJANG | n_pass=0 (H24/H48 × 2 venue) | FALSIFIED |
| 4 | Trend / momentum | top4-h7, strong_24h_trend, vol_above_avg | 3-segmen → **0 valid** (4 false-pass dikoreksi) | FALSIFIED |
| 5 | Mean-reversion pasca-breakout | ALT2 H5 | arah BERLAWANAN (p=0,001) | FALSIFIED |
| 6 | Cross-sectional desil (92 pasar) | ALT3 | "lolos" = artefak likuiditas | FALSIFIED |
| 7 | Lead-lag Binance→SoDEX (menit) | SPEC4 H9 | 0 sel, edge kotor ≈ +0,4 bp | FALSIFIED |
| 8 | Order-flow native (menit) | SPEC4 H10 | 0 sel, edge kotor ≈ +0,4 bp | FALSIFIED |
| 9 | Maker pasif (spread capture) | F2 | adverse selection + spread < fee | DITUTUP-desain |
| 10 | Exit geometry RANGEPOS | TA11, PRAREG3/4/5 | 0/10, 0 lolos | FALSIFIED |
| 11 | SOL forward | S1 | n=6, 2/30 jendela | INCONCLUSIVE |

**Pola lintas-putaran:** setiap arsitektur yang mengasumsikan *directional edge* bersih setelah
biaya taker 8 bp pada horizon ≤48 jam gagal — bukan karena kalibrasi, tapi karena
**rasio biaya-terhadap-edge** (SPEC4 §6): edge kotor terukur ≈ 0,4–1,5 bp/posisi vs biaya 8 bp.

### 2b. AKTIF — forward mengumpulkan episode (belum ada verdict)

| # | Forward | Laju nyata | Kebutuhan | Proyeksi @20-Nov | Status |
|---|---|---|---|---|---|
| 1 | F1 momentum (#42) | 1,07 ep/hari | 150 | ~47 | TIDAK CUKUP (3× kurang) |
| 2 | F3 funding-squeeze + OBI (#44) | ~2,0 onset/hari | 100 | ~87 | borderline (konjungsi langka) |
| 3 | PRAREG-16 MACD_FADE\|BULL (Opsi B) | 1/6–8 hari | 40 | n≈5–8 | TIDAK_KONKLUSIF terdeklarasi |
| 4 | S1 SOL forward | — | 30 | — | INCONCLUSIVE |

**Bacaan jujur:** keempat forward di atas — walau sah secara protokol — **secara aritmetika
tidak akan mencapai ambang** sebelum HARD_STOP (dideklarasikan terbuka di masing-masing dokumen).
Ini bukan alasan menurunkan ambang; ini batas empiris: **penyumbat sejati = jumlah episode
independen pada horizon jam-ke-hari**, bukan ide strategi.

### 2c. NON-FALSIFIED / BELUM DIUJI — kandidat Opsi C

| # | Kandidat | Kelas | Bukti saat ini | Gap |
|---|---|---|---|---|
| C1 | **mv_funding** (funding carry) | CARRY, delta-netral | SR_thn 8,06 · 3/3 segmen · p_day 0,0359 · n_windows **15/20** | **+5 jendela ≈ +10 hari data** |
| C2 | Cross-venue funding arb SoDEX×Binance | CARRY, delta-netral | collector funding SoDEX aktif (92 simbol) | belum diuji / belum pra-reg |
| C3 | E2Dir amplifier (loser+funding) | CARRY-ish, direksional | kode ada di `sodex_twin_engine.py` | belum diuji / belum pra-reg |

---

## 3. Mengapa CARRY — bukan kebetulan

D15 (sensus 21 mesin) menjawab "apakah ada mesin lolos P9?" dengan **0**, kecuali satu
kandidat yang gagal hanya karena `n_windows=15<20`:

```
mv_funding  n=96  n_win=15  mean48=+0,397%  SR_thn=8,06  p_day=0,0359  3/3 segmen  BH=0  -> ❌ n<20
```

Ini satu-satunya sel dari seluruh ekosistem yang **lolos statistik** (p<0,05, 3/3 segmen,
SR ≫ 2,3) tanpa flag REPLAY. Kelasnya **bukan directional** — ia CARRY: menangkap spread
funding antar-venue secara delta-netral. Sifat ini yang membuatnya berbeda fundamental:

- **Directional alpha** butuh menebak arah → falsified di semua keluarga.
- **CARRY** tidak butuh menebak arah → ia memanen selisih settlement, dan satu-satunya
  mekanisme yang **belum difalsifikasi**.

Konsisten dengan F2 §"Artinya untuk jalur menuju Target Utama": kandidat tersisa adalah
**(a) funding lintas venue** dan **(b) amplifikasi loser+funding**.

### 3b. Caveat scope (dibuka, bukan disembunyikan)

`data/mv_funding_paper.json` menunjukkan `long_venue=Binance, short_venue=dYdX` — yaitu
**Binance×dYdX**, BUKAN SoDEX. Dua implikasi:

1. Bila target 0,8%/48 jam = **wallet SoDEX saja**, maka mv_funding **di luar scope** dan
   jalur SoDEX-nya adalah **C2** (funding arb SoDEX×Binance, settlement 1 jam vs 8 jam —
   keunggulan struktural 8×).
2. Bila portofolio 6–8 mesin boleh **lintas-venue** (D14 menyebut "seluruh mesin di
   ekosistem"), maka mv_funding tetap kandidat #1 dan hanya kurang data.

**KEPUTUSAN (08-Okt) — Mas Anas: scope = wallet SoDEX SAJA.** `mv_funding` (Binance×HL×dYdX×OKX×Bybit) **DIKELUARKAN** dari jalur target SoDEX. Konsekuensi: target SoDEX kini **tanpa kandidat non-falsified**; yang tersisa = forward F1/F3/PRAREG-16/S1 (semua venue-SoDEX) + keluarga belum-uji C3 (E2Dir amplifier).

---

## 4. Rekomendasi (falsifiable, butuh approval)

Urutan prioritas — **pilih SATU, jangan paralel** (anti p-hacking):

| Prioritas | Aksi | Falsifier | Biaya |
|---|---|---|---|
| **R1** | Biarkan mv_funding mengumpulkan data → n=20 (~15-Okt), P9 re-eval | n≥20 tapi p_day>0,05 atau segmen <3/3 → gugur | ~0 (data meluncur sendiri) |
| **R2** | Pra-reg C2: funding arb SoDEX×Binance (settlement 1 jam) | net ≤ 0 setelah fee+funding di n≥30 episode | butuh recorder funding SoDEX (read-only, collector sudah aktif) |
| **R3** | Pra-reg C3: E2Dir amplifier (loser+funding) | WR ≤ 50% binomial n≥60 | kode ada, butuh pra-reg + data |

**Rekomendasi saya:** **R1 sekarang** (nol biaya, verdict ~15-Okt), dan siapkan **R2**
(pra-reg funding-arb SoDEX) sebagai satu-satunya jalur directional-free yang masih punya
keunggulan struktural venue (settlement 1 jam = 8× frekuensi Binance).

---

## 5. Batas jujur

- Inventaris ini **tidak mengklaim** target 0,8%/48 jam bisa dicapai lewat CARRY. Ia mengklaim:
  directional alpha sudah tertutup dengan bukti; satu keluarga yang belum difalsifikasi
  (CARRY) layak diuji lebih dulu; sisanya membutuhkan **keputusan scope venue**.
- Tidak ada satu pun ambang/gerbang/live-flag yang diubah dalam penyusunan inventaris ini.
- Bila R1–R3 semuanya gugur sebelum HARD_STOP, kesimpulan yang jujur adalah **belum ada edge
  yang terbukti pada SoDEX**, dan itu harus diterima — bukan digeser ambangnya.

— Hermes Anantara v3 — 2026-10-08
