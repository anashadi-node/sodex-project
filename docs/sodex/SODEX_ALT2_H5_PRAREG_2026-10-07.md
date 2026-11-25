# SODEX-ALT2 — PRA-REGISTRASI H5: Mean-Reversion Pasca-Breakout (48 jam)

**Status: BEKU sejak commit ini.** Ambang & arah tidak boleh diubah setelah hasil dilihat.
Tanggal: 2026-10-07 · Lingkup: proyek SODEX · Mode: READ-ONLY (tidak menyentuh produksi).

---

## §1 Asal hipotesis — TRANSPARANSI PENUH (baca dulu)

Hipotesis ini **dihasilkan dari hasil uji Binance** (`SODEX_ALT_TOP4_HASIL_2026-10-07.md` §4):
kedua sisi breakout di Binance menunjuk hal yang sama — **breakout ekstrem cenderung balik arah**.

**Konsekuensi yang harus diakui jujur:**

- Arah (fade, bukan ikut tren) dipilih **SETELAH** melihat hasil Binance → uji ini **BUKAN** uji
  prospektif murni. Risiko overfitting **tidak** hilang hanya karena venue-nya berbeda.
- Yang menjadikannya tetap berharga: **data SoDEX belum pernah dipakai** untuk hipotesis ini,
  dan **venue berbeda** (DEX, likuiditas jauh lebih tipis, mikro-struktur berbeda).
- Karena risiko di atas, syarat LULUS dibuat **ketat**: **kedua sisi wajib lulus**, kontrol negatif
  wajib, BH-FDR lintas horizon. Tidak boleh mencari sisi mana pun yang "kebetulan lulus".

## §2 Data & definisi (BEKU)

- **Sumber:** `scratch/sodex_minutes/day=*.parquet` (bar-menit dari tape SoDEX; READ-ONLY).
- **Simbol:** **BTC, ETH, SOL** — satu-satunya yang punya histori panjang di SoDEX.
- **Bar:** 4 jam, dibentuk dari bar-menit.
- **Rentang:** seluruh cakupan tersedia (22 Mei – 7 Okt 2026).
- **Trigger** (semua rolling memakai `shift(1)` → tidak ada look-ahead):
  - **FADE_BREAKDOWN (LONG):** `close < min(low, 30 bar)` DAN `volume ≥ 1,5 × median(volume, 30 bar)`
  - **FADE_BREAKOUT (SHORT):** `close > max(high, 30 bar)` DAN `volume ≥ 1,5 × median(volume, 30 bar)`
- **Entry:** `open` bar berikutnya. **Exit:** `close` H bar setelah entry.
- **Horizon H:** 1, 2, 6, **12** bar (4H / 8H / 24H / **48H**). **H = 12 = horizon PRIMER**
  (sesuai observasi Binance).
- **Biaya:** taker SoDEX resmi **4 bp/leg → 8 bp round trip**. Uji ketahanan **1,5× (12 bp)**.

## §3 Syarat LULUS (BEKU — 5 syarat, pada horizon primer H=12)

Untuk **masing-masing** sisi (FADE_BREAKDOWN, FADE_BREAKOUT):

| # | Syarat |
|---|---|
| c1 | n ≥ **100** episode |
| c2 | net rata-rata > **0** setelah biaya 8 bp |
| c3 | tetap > 0 pada biaya **1,5× (12 bp)** |
| c4 | p_kontrol < **0,05** (kontrol entry acak, 1000 permutasi) |
| c5 | kontribusi simbol tunggal ≤ **30%** dari total net |

**H5 dinyatakan LULUS hanya bila KEDUA sisi lulus c1–c5.**
Horizon lain dilaporkan sebagai pendukung, dengan **BH-FDR q = 0,10** lintas 8 uji.

## §4 Tiga hasil yang mungkin (DITETAPKAN SEBELUM DATA)

1. **LULUS** — kedua sisi lulus c1–c5. → layak dilanjutkan ke uji modal.
2. **GAGAL** — n ≥ 100 pada kedua sisi tetapi ada syarat c1–c5 yang gagal.
3. **BELUM CUKUP BUKTI** — n < 100 pada salah satu sisi. → **tidak boleh disimpulkan**;
   laporan wajib menyebut berapa lama data tambahan dibutuhkan.

Hasil **#3 bukan kekalahan dan bukan kemenangan** — itu "belum tahu".

## §5 Kontrol negatif WAJIB

- Entry acak pada **(simbol, hari) yang sama** dengan jumlah sampel identik; **1000 permutasi**.
- Kontrol harus **sign-aware** (return disesuaikan arah sebelum dibandingkan) — bug ini pernah
  ditemukan di SODEX-ALT1 dan wajib tidak terulang.
- Harness harus lulus `tests/test_binance_alt_harness.py` (6 tes) sebelum hasil dipercaya.

## §6 Batasan yang diakui (jangan dihapus dari laporan hasil)

- **Hanya 3 simbol** → daya uji rendah; n kemungkinan **< 100** → hasil mungkin "BELUM CUKUP BUKTI".
- **Funding diabaikan.** Untuk H=12 (48 jam) funding bisa ~10–15 bp dan bisa mengubah verdict.
  Histori funding SoDEX hanya ~5 hari (sejak 2 Okt) → **tidak cukup** untuk penyesuaian penuh.
  Karena itu verdict H=12 wajib dibaca dengan catatan ini.
- **SoDEX ≠ Binance**: likuiditas, spread, dan mikro-struktur berbeda. Hasil Binance tidak
  membuktikan apa pun tentang SoDEX, dan sebaliknya.
- Batas maksimum yang boleh diklaim bila LULUS: **"layak diuji dengan modal"** — **bukan**
  "target 0,8%/48 jam tercapai".

## §7 Cara verifikasi ulang

```bash
.venv-research/bin/python3 scripts/sodex_h5_meanrev_study.py
```
