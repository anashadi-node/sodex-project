# Uji Forward MOMENTUM pada Tape Nyata SoDEX — Hasil DEV

**Tanggal:** 2026-10-05 · **Lingkup:** SODEX saja · **Pra-registrasi:** `docs/sodex/SODEX_FORWARD_MOMENTUM_PRAREG_2026-10-05.md` (beku `d9ffcec`, di-commit **sebelum** evaluasi)
**Skrip:** `scripts/sodex_forward_momentum.py` (READ-ONLY terhadap lane)
**Keluaran:** `reports/sodex/SODEX_FORWARD_MOMENTUM_dev_results.json`

---

## 1. Jawaban singkat

**Putusan DEV: 0 dari 3 hipotesis LULUS. LOCKBOX (2026-09-01..10-05) tetap TERSEGEL — tidak dibaca.**

Tetapi ada temuan yang **mengubah arah** dibanding semua uji sebelumnya:

> Pada θ = **2,0%**, mesin momentum memberi **+0,8232% bersih per 24 jam** dengan **SR +3,44**,
> **3 dari 3 segmen positif**, dan **mengalahkan kontrol fade sebesar 1,74 pp**.
> Ini **pertama kali** sebuah mesin SoDEX menghasilkan magnitudo yang **cukup** untuk target
> 0,8%/48 jam (ambang pra-registrasi 0,40%/trade → **terlampaui 2,06×**).
> Yang gagal bukan magnitudonya, melainkan **kekuatan statistiknya** (n=53, p_signflip 0,196,
> p_day_cluster 0,495) → **tidak cukup bukti**, bukan "tidak ada efek".

## 2. Data yang dipakai (nyata, forward — tidak bisa di-backfill)

Collector `scripts/sodex_obi_collector.py` (READ-ONLY, tanpa auth, tanpa jalur order) berjalan
sejak **2026-05-22** dan menulis append-only ke
`freqtrade_user_data/data/sodex/{trades,obi}/YYYYMMDD.jsonl`.

| Item | Nilai terverifikasi |
|---|---|
| Hari-berkas | 131 (2026-05-22 .. 2026-10-05) |
| Hari penuh (≥23 jam) | **124** |
| Hari hilang | 6 (2026-08-03..08-08, jeda restart collector) |
| Total trade | **12.483.416** |
| Simbol | BTC-USD, ETH-USD, SOL-USD |
| **Dipakai DEV** | **94 hari (2026-05-24 .. 2026-08-31)** |
| Setengah-spread median nyata | BTC **0,08 bp** · ETH **0,27 bp** · SOL **0,66 bp** |

Spread diukur dari `bid`/`ask` di berkas OBI pada detik terdekat — **bukan asumsi**.

## 3. Hasil DEV (beku, tidak ada penyesuaian setelah hasil)

| θ | n episode | mean bersih 24j | SR | WR | segmen+ | p_signflip | p_day_cluster | kontrol fade | BH-FDR | Putusan |
|---|---|---|---|---|---|---|---|---|---|---|
| 1,0% | 452 | **−0,1659%** | −0,88 | 47,6% | 0/3 | 0,3286 | 0,4874 | +0,0694% | ✗ | **GAGAL** |
| 1,5% | 165 | +0,1039% | +0,52 | 49,7% | 2/3 | 0,7363 | 0,4792 | −0,2014% | ✗ | **GAGAL** |
| 2,0% | **53** | **+0,8232%** | **+3,44** | 49,1% | **3/3** | 0,1959 | 0,4953 | **−0,9216%** | ✗ | **GAGAL** |

Alasan gagal per hipotesis (mekanis, dari kriteria beku §5):

- **θ=1,0%** — mean ≤ 0 · BH gagal · p_day ≥ 0,05 · segmen < 2/3 · kalah kontrol · < 0,40%
- **θ=1,5%** — BH gagal · p_day ≥ 0,05 · < 0,40%
- **θ=2,0%** — BH gagal · p_day ≥ 0,05  ← **hanya dua alasan, keduanya soal kekuatan bukti**

## 4. Cara membaca hasil ini (jujur, tanpa membesar-besarkan)

1. **Arah terkonfirmasi berpola.** Di θ=1,0% momentum **kalah** (mean −0,17%; fade justru +0,07%).
   Di θ=2,0% momentum **menang telak** dan fade **kalah** (−0,92%). Ada **monotonisitas**:
   makin besar gerakan, makin kuat lanjutannya. Itu pola, bukan derau acak.
2. **Tapi belum signifikan.** `p_signflip` 0,196 berarti: bila efek ini benar-benar nol, peluang
   melihat hasil sebaik ini ≈ 1 dari 5 — **bukan bukti**. `p_day_cluster` 0,495 berarti efeknya
   **tidak tahan** terhadap pengelompokan per hari (terkonsentrasi di beberapa hari).
3. **Sampelnya yang kurang, bukan sinyalnya.** n=53 episode hanya dari **3 simbol × 94 hari**.
   Untuk mendeteksi efek sebesar ini pada taraf 0,05, perkiraan kebutuhan ≈ **150–200 episode**
   → butuh **3–4× lebih banyak** (tambah simbol dan/atau waktu).
4. **LOCKBOX tidak dibuka.** Aturan pra-registrasi: DEV gagal → LOCKBOX tetap tersegel.
   Itu justru **aset**: 35 hari terakhir (Sep 1 – Okt 5) masih murni untuk uji akhir nanti.

## 5. Batas (dinyatakan di muka, tidak berubah)

- 3 simbol saja → **tidak boleh** digeneralisasi ke 20 simbol lama.
- 94 hari = **satu rezim pasar**; tidak ada klaim lintas rezim.
- Masuk/keluar **taker** diasumsikan terisi penuh pada harga trade terakhir → **batas atas**,
  bukan janji eksekusi.
- Funding ≤1 settlement/24 jam **tidak** dibebankan (tidak tersedia di tape) → hasil ini
  **belum** memasukkan biaya funding.
- Tanpa leverage · gate T1 utuh · `SODEX_TOTAL_WALLET` tidak diubah · arm A1 tetap mati ·
  `RW_MARGIN_UTIL_CAP` default OFF.

## 6. Langkah berikutnya (SODEX saja, tanpa menyentuh batas keamanan)

1. **Perluas cakupan simbol collector** dari 3 → belasan simbol SoDEX (READ-ONLY, tidak
   menyentuh lane uang) → episode θ=2,0% naik ≈ 3–4× → uji ulang DEV **dengan pra-registrasi baru**.
2. **Jalankan collector tanpa jeda** (jeda 2026-08-03..08-08 hilang 6 hari; jangan terulang).
3. **Setelah episode ≥150**: uji ulang DEV → bila lulus, **baru** buka LOCKBOX.
4. **Jangan** menutup celah magnitudo dengan leverage — itu dilarang dan bukan bottlenecknya lagi.

**Catatan penting:** pada θ=2,0% hambatan **bukan lagi magnitudo** (0,82%/24 jam > 0,40% yang
dibutuhkan). Hambatannya **jumlah bukti**. Itu masalah yang bisa diselesaikan dengan
mengumpulkan lebih banyak data SoDEX — bukan dengan melonggarkan batas keamanan.
