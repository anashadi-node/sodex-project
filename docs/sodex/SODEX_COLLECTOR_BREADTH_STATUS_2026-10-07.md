# SoDEX — STATUS BREADTH COLLECTOR & BATAS ATAS BUKTI — 2026-10-07

**Konteks:** Mas Anas memberi **GO perluasan collector SoDEX 3 → 76+ simbol**. Audit ini
dibuat karena GO tersebut **ternyata sudah dieksekusi lebih dulu**, dan audit menemukan batas
yang lebih keras daripada cakupan collector.

**Kesimpulan satu baris:** perluasan collector **sudah berjalan (92 simbol)** dan sehat, tetapi
ia **tidak bisa** menutup celah ke target — karena batasnya bukan cakupan, melainkan
**umur histori venue (~360 hari)** dan **besar efek (Sharpe)**, bukan jumlah data.

---

## 1. GO vs realitas: perluasan sudah dijalankan

Dibuktikan dari **tiga sumber independen** (bukan ingatan):

| Sumber | Isi |
|---|---|
| Env unit `anantara-obi.service` | `OBI_SYMBOLS` = **92 nama**, `OBI_POLL=4.0` |
| Env proses hidup (`/proc/3726/environ`) | daftar 92 nama identik |
| Isi tape `obi_20261007.jsonl` | **92 simbol distinct**, 1.000–1.005 baris masing-masing |

Kronologi roll-out (dari isi berkas):

| Tanggal | Simbol | Catatan |
|---|---:|---|
| 2026-10-05 | 20 | mulai diperluas (prorata) |
| 2026-10-06 | 92 | roll-out penuh |
| 2026-10-07 | 92 | paritas stabil |

**Kesalahan saya:** pada beberapa turn sebelumnya saya menyatakan collector "masih 3 simbol"
dan meminta GO untuk pekerjaan yang sudah selesai. Penyebabnya entri memori basi yang
menyamakan "cakupan tape tahun 2022-2026 (3 simbol)" dengan "kondisi collector saat ini".
**Memori sudah dikoreksi** agar tidak terulang.

## 2. Audit kesehatan — sehat

| Metrik | Nilai | Verdict |
|---|---|---|
| Service | `anantara-obi.service` active, 11 jam, PID 3726 | ✅ |
| RAM | 38,3 MB (puncak 89,2 MB) | ✅ |
| Error di 400 baris log terakhir | **0** | ✅ |
| Paritas baris antar-92-simbol | min 1.000 / median 1.003 / max 1.005 (sebaran 0,5%) | ✅ |
| Guard anti-gap | timer **aktif**, `OnUnitActiveSec=10min`, laporan terakhir "OK — 92 simbol, baris terbaru 0,2 menit lalu" | ✅ |
| Disk | +163 MB/hari → ~4,9 GB/bulan; sisa 112 GB (≈22 bulan) | ✅ bukan kendala |

## 3. Harga yang sudah terbayar: cadence 4 s → 48 s/simbol

Latensi venue terukur: orderbook **1,2–2,3 s**, trades **1,2–2,3 s** per request.
Satu sweep = 92 simbol × 2 request. Interval antar-sampling **terukur 48,0 s/simbol**
(bukan 4 s seperti ketika 3 simbol).

Ini konsekuensi aritmetika, bukan bug: `OBI_POLL=4.0` berarti *"istirahat 4 s antar-sweep"*,
bukan *"tiap simbol tiap 4 s"*.

**Apakah ini kerugian?** Untuk riset mikro-struktur resolusi-detik: ya. Tapi **SPEC4 sudah
membuktikan tidak ada edge di horizon menit** untuk BTC/ETH/SOL (0/13, net = persis biaya).
Jadi resolusi detik pada 3 major **tidak punya nilai yang terbukti** — tidak ada kapabilitas
terbukti yang hilang. Untuk riset harian/jam, 48 s jauh lebih dari cukup.

## 4. Backfill klines — hampir lengkap; kekurangan BUKAN bug

| Panel | Simbol | Bar/simbol (min/med/max) | Total bar | Rentang |
|---|---:|---|---:|---|
| `1h` | 100 | 0 / 5.999 / 8.525 | 522.358 | 2025-10-12 → 2026-10-07 |
| `1d` | 99 | 0 / 251 / 361 | 21.865 | 2025-10-12 → 2026-10-07 |

Median hanya **251 dari 361 hari (69,5%)**, hanya **1 simbol** penuh. Terlihat seperti cacat.

**Uji pemisah** (di mana tiap seri *berakhir* relatif ujung panel):

| Kategori | Jumlah | Arti |
|---|---:|---|
| Berakhir **di ujung panel** | **94** | kekurangan = **tanggal listing asli** → **tidak bisa diperbaiki** |
| Berakhir **jauh sebelum ujung** | 1 (`NATGAS-USD`, stop 2026-07-09) | backfill terpotong → bisa diperbaiki |
| 0 bar | 4 (`BREV/KIOXIA/SOSO/TAO`) | **tidak ada di venue** (`bids=0 asks=0`, klines 0) |

**Potensi perbaikan total: +205 bar dari 21.865 = +0,9%.** Praktis nol.

Artinya: kekurangan cakupan itu **cerminan jadwal listing venue** (saham/token baru seperti
`SMCI`, `MRNA`, `NBIS`, `QNT` listing belakangan), bukan kelemahan rantai data kita.

## 5. Batas atas bukti — angka sesungguhnya

**Histori venue dimulai 2025-10-12.** Itu plafon keras: tidak ada backfill yang bisa menarik
lebih dalam, dan collector hanya menambah ~1 hari/hari.

Konsekuensi aritmetika (`t ≈ S_ann × √T`, T = 360/365,25 = 0,9856 thn → √T = 0,9928):

| Untuk mencapai | Butuh S_ann (Sharpe tahunan) |
|---|---|
| t = 2,0 (ambang sertifikasi) | **≥ 2,015** |
| t = 2,3 (target proyek) | **≥ 2,317** |

Periode independen maksimum dari 360 hari: hold 1d → **360**; hold 2d → **180**; hold 3d → 120.

Dengan `N_eff ≈ 6,1` (korelasi antar-nama, dari sensus venue): observasi efektif hanya
**≈ 842** pada 138 periode, **≈ 1.238** pada 203 periode, **≈ 2.196** bahkan bila seluruh
360 periode terpakai.

**Mekanisme harian terbaik yang terukur di SoDEX: S_ann = 1,75** (RANGEPOS, PRAREG-2).

## 6. Konsekuensi yang harus disampaikan jujur

1. Memperluas cakupan data **tidak bisa** menaikkan Sharpe. Menaikkan jumlah nama/periode
   hanya **memperkecil galat baku** — ia menajamkan **pengukuran** efek, bukan **memperbesar**
   efek. Celah 1,75 → 2,02 (sertifikasi) / 2,32 (target) adalah celah **besar efek**.
2. Karena itu tuas "perluas collector" — yang saya mintakan GO — **sudah dieksekusi dan
   sekaligus bukan tuas yang menggerakkan target.** Saya salah menempatkannya sebagai tuas.
3. Tuas yang tersisa dan sah: **kualitas mekanisme** — dan di sini koreksi diperlukan.
   Klaim saya sebelumnya ("konstruksi kuintil menaikkan Sharpe 2,5×") **SALAH** dan sudah
   saya tarik: string itu tidak ada di satu pun hasil beku, hanya di dokumen ini.
   Angka sebenarnya pada panel Binance 1d (hasil beku PRAREG-2/PRAREG-3):

   | Konstruksi | S_ann | t_NW | net bps |
   |---|---:|---:|---:|
   | **rank-weight N=20** (PRAREG-2 OOS) | **1,749** | 2,80 | 14,43 |
   | kuintil (PRAREG-3 H1) | 1,22 | 3,75 | 11,37 |
   | desil (PRAREG-3 H1) | 1,15 | 3,51 | 16,10 |

   Artinya **rank-weight yang terbaik**; kuintil/desil justru **menurunkan** Sharpe
   (mereka menaikkan t hanya karena n lebih besar, bukan karena efek lebih kuat).
   Konstruksi yang layak diuji di SoDEX karena itu **rank-weight**, bukan kuintil.
4. Batas keras yang tidak bisa ditawar: **hari**. 360 hari histori tidak bisa dipercepat.

## 7. Tindakan

| # | Tindakan | Status |
|---|---|---|
| 1 | Perluasan collector 3 → 92 simbol | **sudah selesai** (5–6 Okt), tidak perlu diulang |
| 2 | Audit kesehatan collector + guard | **selesai** — sehat |
| 3 | Audit kelengkapan backfill | **selesai** — 94/99 terbentur listing |
| 4 | Koreksi memori (penyebab salah berulang) | **selesai** |
| 5 | Perbaiki `NATGAS-USD` (truncated) + buang 4 simbol mati | **tidak dilakukan** — nilai +0,9%, di bawah ambang layak kerjakan |
| 6 | Fokus berikutnya | **kualitas mekanisme + verifikasi forward**, bukan penambahan data |

**Tidak ada perubahan kode, ambang, target, atau modal dalam audit ini.** Semua read-only.

— Hermes Anantara v3 — 2026-10-07
