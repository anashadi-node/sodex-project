# Pra-Registrasi — Uji Forward MOMENTUM pada Tape Nyata SoDEX

**Tanggal commit pra-registrasi:** 2026-10-05
**Status:** DIBEKUKAN SEBELUM EVALUASI. Setelah hasil keluar, ambang di dokumen ini
**TIDAK BOLEH DIUBAH**. Mesin tidak boleh ditambah ke keluarga setelah dibekukan.
**Lingkup:** SODEX SAJA (sesuai instruksi user: "hanya pengerjakan project SODEX").
**Asal lead:** eksplorasi tape 3-hari (2026-07-30..08-02) memberi arah momentum +3,3…+4,7%/24 jam,
tetapi n tidak independen dan gagal BH → lead itu **belum boleh dipakai**; dokumen ini
mengujinya secara sah.

---

## 1. Data (nyata, dikumpulkan forward — bukan backfill)

Collector `scripts/sodex_obi_collector.py` (READ-ONLY, tanpa auth, tanpa jalur order) berjalan
sejak 2026-05-22 dan menulis **append-only**:

| Berkas | Isi |
|---|---|
| `freqtrade_user_data/data/sodex/trades/trades_YYYYMMDD.jsonl` | trade prints: `id, ts(ms), sym, side, price, qty` |
| `freqtrade_user_data/data/sodex/obi/obi_YYYYMMDD.jsonl` | L2 10 level + `mid, bid, ask, spread, obi5/10/20` |

**Integritas terverifikasi:** 131 hari-berkas, 2026-05-22 .. 2026-10-05, **124 hari penuh (≥23 jam)**,
5 hari sebagian, 6 hari hilang (2026-08-03..08-08 — jeda restart collector).
**TOTAL 12.483.416 trade**, 3 simbol: **BTC-USD, ETH-USD, SOL-USD**.
Data ini **waktu-nyata** (tidak bisa di-backfill) → tidak ada risiko look-ahead dari penulisan.

## 2. Pemisahan sampel (dibekukan sekarang)

| Set | Rentang | Dipakai untuk |
|---|---|---|
| **DEV** | 2026-05-22 .. 2026-08-31 | evaluasi + putusan DEV |
| **LOCKBOX** | 2026-09-01 .. 2026-10-05 | **DISEGEL** — hanya dibuka jika DEV lulus |

Aturan: LOCKBOX tidak boleh dibaca, diagregasi, atau "dilihat sekilas" sebelum DEV lulus.

## 3. Hipotesis (dibekukan — 3 ambang, tanpa grid search)

> **H-M1**: Setelah SoDEX bergerak **≥ θ** dalam jendela **15 menit**, arah **LANJUTAN
> (momentum)** memberi return bersih positif pada horizon **24 jam**.

θ ∈ **{1,0% ; 1,5% ; 2,0%}** — ketiganya dilaporkan, koreksi **BH-FDR** diterapkan pada
ketiganya. Sisi cermin (**fade**) dihitung sebagai **kontrol arah**, bukan hipotesis terpisah.

## 4. Aturan eksekusi (dibekukan)

| Aspek | Aturan |
|---|---|
| Deteksi | return rolling 15 menit pada harga trade terakhir; event bila \|r\| ≥ θ |
| Pengelompokan episode | event dalam **60 menit** digabung jadi **1 episode** (independensi) |
| Masuk | **taker** di trade pertama setelah jendela event tutup (silang spread penuh) |
| Keluar | **taker** pada jam ke-**24** |
| Stop | **TIDAK ADA** (uji murni arah; stop akan diuji terpisah bila lulus) |
| Biaya | **setengah spread NYATA** per sisi (dibaca dari `bid/ask` di berkas OBI pada detik terdekat) + **fee taker venue** |
| Funding | ≤1 settlement dalam 24 jam — dibebankan bila tersedia; jika tidak, **dicatat sebagai batas** |

## 5. Kriteria LULUS (dibekukan)

DEV **lulus** hanya jika **SEMUA** terpenuhi:

1. `n_episode` ≥ **30** (independen, setelah pengelompokan 60 menit)
2. `mean_net_24j` > **0**
3. `p_signflip` < **0,05** setelah **BH-FDR** (3 ambang)
4. `p_day_cluster` < **0,05** (robust terhadap klaster hari)
5. `segments_positive` ≥ **2 dari 3** (DEV dibagi 3 segmen waktu sama panjang)
6. mengalahkan **kontrol arah** (fade) secara bersih
7. `mean_net_24j` ≥ **0,40%** — syarat target 0,8%/48 jam pada tahan 24 jam (2 posisi
   non-tumpang-tindih per 48 jam)

**Gagal salah satu → DEV GAGAL**, LOCKBOX tetap tersegel, kelas ditutup.

## 6. Batas yang dinyatakan di muka (tidak boleh diubah setelah hasil)

- 3 simbol saja (BTC/ETH/SOL) — hasil **tidak boleh** digeneralisasi ke 20 simbol lama.
- 124 hari = **satu rezim pasar**; tidak ada klaim lintas rezim.
- Biaya diukur dari spread L2 yang tercatat; eksekusi taker diasumsikan terisi penuh
  (optimistis untuk ukuran besar) — **batas atas**, bukan janji.
- Tidak ada leverage; `SODEX_TOTAL_WALLET` tidak diubah; gate T1 utuh; arm A1 tetap mati;
  `RW_MARGIN_UTIL_CAP` default OFF.

## 7. Berkas yang akan dihasilkan

- `scripts/sodex_forward_momentum.py` (READ-ONLY terhadap lane; hanya baca berkas JSONL + tulis laporan)
- `reports/sodex/SODEX_FORWARD_MOMENTUM_dev_results.json`
- Laporan: `docs/sodex/SODEX_FORWARD_MOMENTUM_2026-10-05.md`

**Pra-registrasi ini di-commit SEBELUM skrip evaluasi dijalankan.**
