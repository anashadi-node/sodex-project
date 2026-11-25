# PRAREG-23 H2 (satelit carry SoDEX) — HASIL & PENUTUPAN

**Vonis: TIDAK KONKLUSIF** — dan **batas atas ekonominya sudah terukur, jauh di bawah lantai tangga.**
Dieksekusi 09-Okt-2026 dari protokol beku `docs/sodex/PRAREG_23_TREN_HARIAN.md` §H2.

## 1. Gerbang yang dibekukan vs kenyataan data

| Aturan beku | Kenyataan | |
|---|---|---|
| Butuh **≥ 20 jendela independen 5 hari** | tersedia **1,44** | **GAGAL** |
| Funding neto positif ≥70% jendela | tidak dapat diuji | — |
| Tahunan neto ≥5% | tidak dapat diuji (belum tentu, lihat §3) | — |
| Gerak basis merugikan <1% | tidak dapat diuji | — |

Data: `data/sodex_funding/funding_rates_history.jsonl` — **14.812 baris, 92 simbol, 161 titik jam**,
rentang **2026-10-02 11:00 → 2026-10-09 16:00 UTC = 7,21 hari**.

**Kenapa tidak bisa dipaksa:** SoDEX hanya mengekspos funding **per-akun**
(`/api/v1/perps/accounts/{address}/fundings`) dan lewat **polling snapshot mark** — tidak ada endpoint
riwayat funding pasar luas. Empat endpoint kandidat saya probe → **HTTP 404**. Artinya riwayat funding
SoDEX **dimulai 2026-10-02 dan hanya bertambah real-time**.
`20 jendela × 5 hari = 100 hari` → vonis paling awal **≈ 10-Jan-2027** — yaitu **setelah HARD_STOP
20-Nov-2026** dan setelah rencana mulai live 1-Des-2026.

## 2. Yang BISA disimpulkan (deskriptif — bukan vonis)

Deskriptif ≠ vonis (aturan program), tapi cukup untuk membunuh **kelayakan ekonomi**:

| Simbol inti | median funding | %positif | Gross/tahun (jika rate = per jam) | Gross/tahun (jika rate = per 8 jam) |
|---|---|---|---|---|
| BTC | +0,0271 bps/j | 67,7% | **2,37%** | 0,30% |
| ETH | +0,0502 bps/j | 78,9% | 4,40% | 0,55% |
| SOL | +0,0396 bps/j | 65,2% | 3,47% | 0,43% |
| XAUT | +0,0625 bps/j | 88,2% | 5,48% | 0,68% |
| BNB | +0,1250 bps/j | 100,0% | 10,95% | 1,37% |
| LINK | +0,0300 bps/j | 59,6% | 2,63% | 0,33% |
| XRP | +0,0622 bps/j | 68,9% | 5,45% | 0,68% |

Median **+0,1250 bps** muncul pada lusinan simbol dengan **%positif 100%** — pola khas **plafon/default
rate**, bukan edge yang bisa dipilih-pilih.

> **Ambigu yang saya nyatakan terbuka:** interval funding SoDEX belum terverifikasi. Karena itu **kedua
> bacaan dilaporkan**. Kesimpulannya **robust terhadap ambiguitas itu** — lihat §3.

## 3. Batas atas kontribusi satelit ke target (inilah pembunuhnya)

Satelit dibatasi **≤20% modal** (protokol §H2). Maka kontribusinya ke total wallet:

| Skenario | Kontribusi ke wallet | vs lantai 0,10%/48 jam |
|---|---|---|
| Rate terbaik, bacaan per-jam | **+0,0276%/48j** | **3,6× terlalu kecil** |
| Rate terbaik, bacaan per-8-jam | +0,0034%/48j | 29,4× terlalu kecil |
| BTC (inti), per-jam | +0,0026%/48j | 38,5× terlalu kecil |
| BTC (inti), per-8-jam | +0,0003%/48j | **333× terlalu kecil** |

Dan **biaya** mematikan sisanya: satu putaran 4 kaki (semua maker) = **9,4 bps notional = 0,0188% wallet
per siklus** — setara **68% dari seluruh gross 48-jam** skenario terbaik. Balik modal biaya saja butuh
**75 jam** (simbol plafon) sampai **347 jam = 14,5 hari** (BTC).

**Kesimpulan yang tidak bisa dihindari:** satelit carry **tidak dapat menyumbang** ke lantai 0,10%/48 jam —
bahkan pada bacaan paling optimistis, ia menyumbang **3,6× lebih kecil**, dan itu **sebelum** biaya.

## 4. Rekomendasi (keputusan Anas)

1. **Keluarkan carry dari tangga target.** Bukan karena carry itu buruk secara universal, tetapi karena
   dengan batas 20% modal dan rate SoDEX yang terukur, kontribusinya ≤0,028%/48 jam — di bawah lantai.
2. **Jangan investasi waktu** membangun satelit sampai (a) ada endpoint riwayat funding pasar SoDEX,
   atau (b) kolektor poll berjalan **≥100 hari** (≈ 10-Jan-2027).
3. Bila tetap ingin dijalankan sebagai penghasil **arus kas kecil** (bukan pengejar target): wajib
   **dinyatakan terpisah** dari angka %/48 jam, dan **farming/SoPoints tetap dikecualikan** dari PnL.
4. **Jangan** memakai `mv_funding` (Binance × dYdX) sebagai bukti SoDEX — venue berbeda; t = 1,46,
   tidak lolos ambangnya sendiri (rekomendasi §5 sudah menetapkan ini).

## 5. Yang TIDAK saya lakukan (disiplin)

- Tidak melonggarkan ambang "≥20 jendela" agar bisa memberi vonis sekarang.
- Tidak mengganti data SoDEX dengan data Binance lalu melabelinya "bukti SoDEX".
- Tidak menaikkan porsi satelit >20% untuk mengejar angka.
