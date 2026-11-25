# R2 CABANG B — KELAYAKAN DATA (cek "data B")

**Tanggal:** 10-Okt-2026 · **Sifat:** read-only, tanpa order · **Izin:** Mas Anas (`cek data B`)
**Pertanyaan:** apakah ada jalur harga intra-trade untuk menguji perubahan BENTUK payoff (exit parsial berlapis) pada 691 trade TWOWAY+REALWIDE?

## VERDICT: LAYAK, dengan 3 batas keras

Jalur harga tersedia dan jauh lebih bersih dari dugaan. Ambiguitas intrabar hampir nol (**0,3%**).
Uji berbasis jalur **bisa** dijalankan dengan resolusi **1 jam** (bukan 1 menit).

## 1. Data yang ada — dan yang TIDAK ada

| Sumber | Isi | Catatan |
|---|---|---|
| `data/sodex_klines/1h/` | 100 simbol, JSON `{t,o,h,l,c,v,q,n}` | **satu-satunya** sumber jalur harga |
| `data/sodex_klines/1d/` | 100 simbol | terlalu kasar untuk intra-trade |
| **1 menit** | **TIDAK ADA** | uji "partial exit bertingkat halus" tidak mungkin; hanya level kasar |

Kesegaran: `pulled_utc` 2026-10-09 18:20–18:30Z; bar terakhir **18:00Z** untuk semua simbol,
sementara exit trade terakhir **21:27Z** → **3,5 jam ekor belum ter-cover; perlu satu kali refresh** sebelum uji dijalankan.

## 2. Cakupan & sidik jari (snapshot 10-Okt-2026)

23/23 simbol yang dipakai trade punya berkas 1h. Tidak ada yang hilang.

| Pemeriksaan | Hasil |
|---|---|
| Trade dengan jalur layak (≥2 bar + riwayat menutup rentang) | **589/691 = 85,2%** |
| Tidak layak (<2 bar) | 102 (14,8%) |
| Berkas hilang | **0** |
| Timestamp duplikat | **0** di semua 23 berkas |
| Gap jam hilang | BTC **18**, ETH **3**, sisanya **0** |
| Bar intra-trade per trade | median **10** (p10=1, p90=30) |

sha256-12 tiap berkas dicatat (mis. BTC `6642f4369c66`, ETH `fdb9f244735e`, SOL `e2a698f9e363`, DOGE `d10bb046e9e7`, XAUT `f9809e4213e3`, XRP `1aa4e3e663d4`) — **wajib** karena berkas ditulis ulang tiap jam.

## 3. Ambiguitas intrabar — masalah terbesar uji berbasis jalur, dan hasilnya baik

Bahaya resolus 1 jam: satu bar bisa memuat level keluar parsial (+1R) **dan** SL sekaligus → urutannya tak diketahui.
Diukur dari level SL/TP tiap trade (`sl_price`/`tp_price` TWOWAY; `sl`/`tp` × `entry_p` REALWIDE):

- Trade dengan ≥1 bar ambigu: **2/589 = 0,3%**
- Bar ambigu: **2/9.584 = 0,02%**

→ Urutan peristiwa dalam rentang hold praktis **tidak ambigu**. SL≈2% dan TP≈4% terlalu jauh untuk masuk ke satu bar 1 jam yang sama.

## 4. Batas keras (harus masuk protokol sebagai pengecualian eksplisit)

1. **Resolusi 1 jam.** Hanya level kasar (+0,5R / +1R / +1,5R) yang bisa diuji; tidak bisa menguji exit parsial bertingkat dengan timing halus.
2. **Bias pengecualian — arahnya BERBAHAYA (optimistis).** Yang terbuang justru trade yang cepat kena SL:

| Kelompok exit | Total | Terpakai | % |
|---|---|---|---|
| TIME_20h/24h/30h/48h (semua track) | 180 | 180 | **100,0%** |
| TP (kedua track) | 159 | 138 | 86,8% |
| SL_PROTECT (REALWIDE) | 58 | 50 | 86,2% |
| **SL (TWOWAY)** | 181 | 146 | **80,7%** |
| **SL (REALWIDE)** | 86 | 58 | **67,4%** |
| **SL_BEAR (REALWIDE)** | 20 | 11 | **55,0%** |

   Kelompok waktu 100% terpakai; kelompok cepat rugi terbuang paling banyak. Uji apa pun di atas 589 trade ini akan **melebih-lebihkan** hasil aturan exit baru (karena stop cepat yang justru paling dirugikan tidak ikut dihitung). Wajib: laporkan versi ber-bobot ulang atau sensitivitas cakupan.
3. **Harga jalur = SoDEX.** Ada drift terukur vs Binance (−15..−26 bps/48j). Untuk uji R, jalur dan level berasal dari venue yang sama sehingga konsisten — tapi hasilnya **tidak** boleh dipindah ke venue lain tanpa koreksi drift.

## 5. Yang TIDAK saya lakukan di sini
Tidak ada perhitungan touch/outcome apa pun (tidak hitung berapa trade menyentuh +1R, tidak hitung aturan exit alternatif).
Agar ambang dan aturan beku **sebelum** hasil dilihat — sesuai protokol R2 dan aturan program.

## 6. Langkah berikutnya (butuh izin)
1. Refresh klines (tutup ekor 3,5 jam) → sidik jari baru dicatat.
2. Tulis & bekukan **protokol cabang B** (hash sebelum run): level parsial, aturan pembobotan bias cakupan, split discovery/hold-out, ambang lulus-gagal, pencatatan trial di registry.
3. Baru jalankan.

*Dokumen kelayakan · Hermes Anantara v3 · 10-Okt-2026*
