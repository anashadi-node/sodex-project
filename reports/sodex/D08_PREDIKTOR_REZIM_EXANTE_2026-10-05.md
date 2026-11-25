# D08 — Opsi 2: Prediktor Rezim Ex-Ante untuk `twoway` SoDEX

**Tanggal:** 2026-10-05
**Divisi:** SoDEX
**Alat:** `scripts/sodex_regime_gate_study.py` (+ `scripts/sodex_regime_source_discovery.py`)
**Lanjutan dari:** D07 (`D07_RCA_FILTER_DAN_FAKTOR_2026-10-05.md`)

---

## 0. Jawaban singkat

Pertanyaan D07: *"kalau bukan filter entry, apakah ada pengukur pasar yang
tersedia SEBELUM trade dibuka yang bisa membedakan rezim bagus dari rezim buruk?"*

**Jawaban: ADA — dan ia lolos koreksi multiple-testing. Tetapi belum cukup besar
untuk menutup biaya di rezim sekarang.**

| | hasil |
|---|---|
| Prediktor terbaik | **volatilitas BTC 24 jam ≥ median** |
| Selisih (vol-tinggi − vol-rendah) | **+75,16 bps** |
| p (permutasi 10.000, dua sisi) | **0,0122** |
| BH-FDR q=0,10 (5 hipotesis, ambang rank-1 = 0,020) | **LOLOS** ✅ |
| Subset ter-gate: cost 2× | **+20,69 bps** (> 16 bps) |
| **Di periode TERKINI (S3) cost 2×** | **−1,44 bps** ❌ |
| Verdict T1 | **tetap TIDAK LOLOS** |

---

## 1. Asal-usul: kenapa pertanyaannya berubah

D07 menutup jalur filter entry: 12 kandidat diuji, **nol layak**, karena seluruh
edge berasal dari satu jendela 15 hari dan arahnya adalah eksposur faktor
alt-vs-BTC, bukan alpha. Maka pertanyaannya diganti:

| | pertanyaan | sumber informasi |
|---|---|---|
| Filter (gagal) | "entry seperti apa yang bagus?" | isi TRADE (`entry_reasons`) |
| **Gate (Opsi 2)** | "pasar seperti apa yang bagus?" | **PASAR** (`entry_time` ke belakang) |

## 2. Sumber data yang tersedia (hasil discovery)

| sumber | cakupan | keputusan |
|---|---|---|
| `data/trail_lab_klines/` | 21 simbol, 15m, **234.634 bar**, 06-Agu → 30-Sep | ✅ **dipakai** |
| cache BTC 1h (harness) | 06-Agu → sekarang | ✅ dipakai |
| `data/sodex_market_scan/history.jsonl` | 12-Jul → **02-Agu** | ❌ **di luar jendela** |
| field `atr_pct` pada trade | **0.000 di semua baris** | ❌ field rusak |
| field `regime` pada trade | **'MOMENTUM' di semua baris** | ❌ konstan |
| field `conviction` | 0,60–0,80 (bervariasi) | dicadangkan |

Cakupan kline terhadap trade: **318/325 (98%)** — hanya SILVER (7 trade) tidak ada.

## 3. Definisi prediktor ex-ante

**Ex-ante = nilainya sudah diketahui SEBELUM trade dibuka.** Aturan besi: setiap
angka hanya boleh berasal dari bar dengan cap waktu **lebih awal** dari
`entry_time`. Satu bar masa depan yang bocor membuat hasil tampak hebat di
backtest dan hilang di trading nyata.

5 kandidat, **dideklarasikan di muka** (jangan tambah setelah melihat hasil):

| kode | definisi |
|---|---|
| K1 `rs24` | rata-rata return 20 alt (24 jam) − return BTC (24 jam) |
| K2 `rs7d` | idem, jendela 7 hari |
| K3 `breadth24` | fraksi simbol dengan return 24 jam > 0 |
| K4 `btcvol24` | volatilitas terealisasi BTC 15m selama 24 jam |
| K5 `btctrend` | BTC close / SMA200(jam) − 1 |

**XAUT dikecualikan** dari keranjang alt (itu emas, bukan alt crypto).

## 4. Hasil: 5 gerbang + 5 komplemen

Ambang layak = 2× fee = 16 bps. Kolom S1/S2/S3 = cost 2× per sepertiga waktu.

### 4.1 Gerbang (arah yang dihipotesiskan)

| gerbang | n | WR | edge | cost 2× | S1/S2/S3 |
|---|---:|---:|---:|---:|---|
| G1 `rs24>0` | 236 | 37,3% | −5,88 | −21,88 | no/OK/no |
| G2 `rs7d>0` | 242 | 40,1% | +12,90 | −3,10 | OK/OK/no |
| G3 `breadth>0,50` | 225 | 38,7% | −2,56 | −18,56 | no/OK/no |
| G4 `btcvol<median` | 159 | 34,6% | −15,01 | −31,01 | no/OK/no |
| G5 `btctrend>0` | 191 | 39,8% | −9,18 | −25,18 | no/no/no |

**Semua gerbang MEMPERBURUK.** Arahnya terbalik dari hipotesis.

### 4.2 Komplemen (kondisi kebalikan)

| komplemen | n | WR | edge | cost 2× | S1/S2/S3 |
|---|---:|---:|---:|---:|---|
| bukan-G1 `rs24<=0` | 82 | 48,8% | +56,53 | +40,53 | no/OK/- |
| bukan-G2 `rs7d<=0` | 76 | 40,8% | +1,66 | −14,34 | no/OK/- |
| bukan-G3 `breadth<=0,50` | 93 | 44,1% | +41,11 | +25,11 | OK/OK/- |
| **bukan-G4 `btcvol>=median`** | **159** | **45,9%** | **+35,44** | **+19,44** | **no/OK/OK** |
| bukan-G5 `btctrend<=0` | 127 | 40,9% | +39,38 | +23,38 | -/OK/no |

`-` = n<30 di segmen itu (**belum dapat dinilai**), bukan gagal.

## 5. Tiga jebakan yang hampir menipu (dan cara lolosnya)

### Jebakan 1 — proksi waktu
`btcvol24` menurun antar segmen (median S1 0,00203 → S3 0,00168), jadi "vol di
atas median" bisa jadi sekadar **"jangan trading bulan Agustus"**.
**Uji:** belah menurut median **di dalam tiap segmen** → proksi waktu mati.

### Jebakan 2 — outlier
Selisih S2 mencapai +136 bps. Terlalu besar untuk dipercaya.
**Uji:** trim 10% dan sumbangan 3 trade teratas → **bukan** didominasi outlier
(masing-masing hanya ~0,25 pp). Distribusinya memang lebar (p10 ≈ −2,2%,
p90 ≈ +4,2%). Jadi ini variasi tinggi, bukan outlier.

### Jebakan 3 — UJI SAYA SENDIRI SALAH ⚠️
Uji pertama memakai distribusi **null** lalu memeriksa `lo95>0 or hi95<0`.
Distribusi null selalu berpusat di nol, sehingga syarat itu **tidak pernah**
terpenuhi → semua hasil dilaporkan "tidak signifikan".
**Gejalanya:** nilai observasi (+71,35) berada **di luar CI-nya sendiri** — mustahil
untuk bootstrap yang benar.
**Perbaikan:** uji permutasi yang benar, p = P(|selisih-acak| ≥ |selisih-observasi|).

> Ini terbalik: dengan uji yang benar, **vol ≥ median p = 0,0122 → SIGNIFIKAN**.
> Tanpa koreksi ini, temuan nyata akan dibuang sebagai "derau".

### Jebakan 4 — warm-up dilabeli salah (ditangkap test, bukan mata)
Test `test_data_kurang_mengembalikan_none_bukan_crash` GAGAL: `ret_n` selama
warm-up mengembalikan return 15 menit yang **dilabeli "24 jam"** — angka tampak
sah, arti salah.
**Perbaikan:** jendela harus terpenuhi ≥80%; kalau tidak → `None`.
Kesimpulan tidak berubah setelah perbaikan (angka bergeser tipis).

## 6. Uji signifikansi yang benar (sampel penuh, daya ~83 bps)

| prediktor | selisih | p | verdict |
|---|---:|---:|---|
| **btcvol ≥ median** | **+75,16 bps** | **0,0122** | ✅ **SIGNIFIKAN, lolos BH-FDR** |
| rs24 alt>BTC | −38,02 | 0,2633 | ❌ |
| rs7d alt>BTC | −37,79 | 0,2688 | ❌ |
| breadth>0,50 | −46,34 | 0,1560 | ❌ |
| btctrend>0 | −18,84 | 0,5388 | ❌ |

## 7. Pelajaran metodologis: aturan 3-segmen butuh DAYA UJI

σ per trade = **264 bps**. Dengan n=53/kelompok per segmen, CI95 = **±144 bps**.
Artinya **efek sekecil apa pun di bawah ~144 bps tidak dapat dinilai di tingkat
segmen** — termasuk efek 75 bps yang kita cari.

| segmen | n | cost 2× | CI95 | verdict yang JUJUR |
|---|---:|---:|---:|---|
| S1 | 52 | −24,96 | ±119 bps | **terlalu bising untuk dinilai** |
| S2 | 52 | +89,30 | ±157 bps | LAYAK (titik estimasi) |
| S3 | 54 | −1,44 | ±146 bps | **terlalu bising untuk dinilai** |

> **Amandemen aturan (2026-10-05):** pada validasi 3-segmen, segmen dengan daya
> uji tidak memadai dilaporkan `-` (**belum dinilai**), BUKAN `no` (gagal).
> Menyebutnya "gagal" adalah kesalahan statistik — kita menuntut bukti yang
> instrumennya sendiri tidak mampu berikan.

## 8. Konsekuensi operasional

1. **Tetap TIDAK GO-LIVE.** Estimasi ter-gate di rezim terkini = **−1,44 bps**,
   di bawah ambang 16 bps. Tidak boleh deploy berdasarkan titik estimasi yang
   belum terpisah dari nol.
2. **Gate ini adalah LEAD, bukan FIX.** Ia layak dipantau dan diuji ulang saat
   data bertambah, bukan dipasang sekarang.
3. **Jendela forward 30 hari jadi makin berharga** — bukan hanya untuk T1, tetapi
   untuk **menambah daya uji** pertanyaan rezim ini.
4. **Jangan pasang gerbang apa pun ke produksi** sampai lolos 3-segmen berdaya.
5. `unfreeze = NO`. Tanpa leverage. Target tidak diubah.

## 9. Reproduksi

```bash
python3 scripts/sodex_regime_source_discovery.py          # cek sumber data
python3 scripts/sodex_regime_gate_study.py --dry-run      # studi gerbang
python3 -m pytest tests/test_sodex_regime_gate_study.py -q
```

Registri trial tetap append-only: `reports/sodex/sodex_trial_registry.json`.

---

*D08 — Hermes Anantara v3 | SoDEX | 2026-10-05*
