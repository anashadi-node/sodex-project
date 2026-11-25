# Riset: Laju Episode Nyata & Keterjangkauan Gerbang F1/F3

Tanggal: 2026-10-07 WIB · Mode: **read-only** (tidak ada perubahan kode selain HARD_STOP yang di-approve).
Pemicu: user menyetujui **opsi A — perpanjangan maksimal 13 hari** (7-Nov → 20-Nov-2026) dan meminta
riset ulang bila ada indikasi bukti belum cukup.

## 0. Verdict (jujur)

| Mesin | Laju terukur | Proyeksi 44 hari | Butuh | Verdict |
|---|---|---|---|---|
| **F1** | 1,07 episode/hari (32 episode / 30 hari kontinu) | **~47** | 150 | **TIDAK CUKUP** |
| **F3** | 0,56 onset/hari (cakupan 20 simbol) | **~25** | 100 | **TIDAK CUKUP** |

> **Perpanjangan 13 hari TIDAK membuat target terjangkau dengan desain sekarang.**
> F1 kekurangan ~3×; F3 kekurangan ~4×.

## 1. R1 — Laju F1 (|Δ15m| ≥ 2%, klaster 60 mnt, hold 24 j)

Sumber: `freqtrade_user_data/data/sodex/trades/` — **kontinu** 2026-09-01..2026-10-06 (30 file).
Metode: definisi `find_events`/`HOLD_MIN` F1 persis, dijalankan pada jendela 30 hari.

- Total episode lengkap: **32** → **1,07 episode/hari**
- **Hari ber-episode: 9 dari 30** (30%) → gerbang `DAYS_MIN=14` **tidak tercapai bahkan secara historis**
- Simbol unik dalam jendela: **10** (= tepat `SYMS_MIN=10`; tidak ada margin)
- Hari terbaik 2026-10-05 (12 episode) = outlier; median hari aktif ≈ 2

**Implikasi:** ambang F1 beku (θ=2%). Tidak ada tuas cakupan data — trigger-nya memang jarang.
Untuk mencapai 150 dalam 44 hari butuh **3,4 episode/hari (3× laju nyata)**.

### Batas optimis vs jujur (jangan tertukar)

Skrip mentah juga melaporkan **3,6 episode/hari** (32 episode ÷ **9 hari ber-episode**). Angka itu
**menyesatkan**: ia mengandaikan *setiap* hari adalah hari aktif. Kenyataannya hanya **9 dari 30
hari (30%)** yang menghasilkan episode.

| Pembagi | Laju | Proyeksi 44 hari | Syarat yang tersembunyi |
|---|---|---|---|
| 9 hari ber-episode | 3,6/hari | ~156 | mengandaikan 100% hari aktif — **tidak sah** |
| **30 hari kontinu** | **1,07/hari** | **~47** | asumsi realistis (30% hari aktif) |

Yang dipakai untuk verdict = **1,07/hari**. Konsekuensi tambahan: `DAYS_MIN=14` butuh 14 hari
ber-episode; pada laju 30% itu berarti **~47 hari kalender** — melewati 20-Nov.

## 2. R2 — Laju F3 + dekomposisi bottleneck

Sumber: `data/sodex_funding/funding_rates_history.jsonl` (9.844 baris, 92 simbol, span 4,49 hari)
× OBI20 (`freqtrade_user_data/data/sodex/obi/`, 132 file) × tape harga.

```
FUNDING_THR=3e-05 | OBI_THR=0,15 | GAP_S=3600 | HOLD_S=1800
irisan simbol (funding ∩ OBI) = 20 dari 92

Jendela cakupan 20-simbol (sejak 5-Okt, span 1,78 hari):
  [1] funding lolos ambang          :  21  -> 11,8/hari
  [2] + OBI tersedia pada onset     :   9  ->  5,1/hari   (-57%)
  [3] + OBI SELARAS (onset nyata)   :   1  ->  0,56/hari  (-89% dari [2])
```

**Bottleneck = [3] penyelarasan OBI** (hanya ~11% dari onset funding yang punya OBI berlawanan arah
dengan |OBI| ≥ 0,15). Bukan masalah pasar — **masalah cakupan**: OBI hanya mengamati **20 dari 92**
simbol yang punya data funding.

### 2b. Tuas yang sah (bukan pelonggaran ambang)

`scripts/sodex_obi_collector.py:20` membaca `OBI_SYMBOLS` dari environment — **bisa diperluas tanpa
mengubah satu pun ambang pra-registrasi**. Estimasi linier: 20 → 92 simbol ≈ 4,6× laju.

```
[1] 11,8/hari x (92/20) = 54/hari  ->  [3] ~6/hari  ->  44 hari = ~264 episode  (butuh 100)
```

**Catatan kejujuran:** rasio penyelarasan (1/9) diestimasi dari **n=9** — sampel sangat kecil;
proyeksi ini **indikatif, bukan jaminan**. Perlu diukur ulang setelah perluasan.

## 3. KOREKSI — 4 entri registry "lolos" adalah FALSE PASS

Registry `reports/sodex/sodex_trial_registry.json` memuat **4 entri `passed=true`**
(`strong_24h_trend` n=231, `vol_above_avg` n=185, 2 combo). **Keempatnya palsu.**

Bukti: header `scripts/sodex_long_entry_filter_study.py` sendiri mencatat pelajaran 2026-10-05 —
validasi **belah-dua** meloloskan `strong_24h_trend` yang seluruh edge-nya berasal dari **satu
jendela 15 hari** (04–19 Sep, +93,6 bps) sementara dua periode lain **NEGATIF** (−7,7 dan −9,1 bps).

Dijalankan ulang (validasi **tiga segmen**):

```
kandidat                          n     WR    edge   2x?   S1/S2/S3-2x
flag:strong_24h_trend           239  40,2%  19,01  True   no/OK/no   <- hanya lolos segmen tengah
flag:vol_above_avg              193  42,5%  17,02  True   no/OK/no
combo:...strong+vol              92  44,6%  47,87  True   -/OK/no
(SEMUA LONG -- baseline)        340  38,5%   3,06  False  (cost 1x = -4,94 bps)
LAYAK: TIDAK ADA.
```

Keluarga sinyal tren/momentum = **jalan buntu terdokumentasi**. Studi itu sendiri melarang
membangun mesin dari keluarga sinyal ini (eksposur faktor sama → melanggar syarat korelasi antar-mesin).

> Koreksi atas laporan 07-Okt sebelumnya: saya menyebut 4 entri lolos sebagai "kabar baik jujur".
> Itu **salah** — bukti tiga-segmen menunjukkan sebaliknya. Angka efektif: **0 mesin valid.**

## 4. Tingkat keyakinan & keterbatasan

| Klaim | Keyakinan | Dasar |
|---|---|---|
| F1 tidak mencapai 150 dalam 44 hari | **Tinggi** | 30 hari data kontinu; butuh 3× laju |
| F3 tidak mencapai 100 tanpa perluasan OBI | **Tinggi** | 20 simbol; proyeksi 25 |
| Perluasan OBI 20→92 menutup kekurangan F3 | **Rendah–Sedang** | rasio penyelarasan dari n=9 |
| Keluarga tren/momentum = buntu | **Tinggi** | studi 3-segmen + aturan anti-overfit |

Keterbatasan lain: funding collector baru aktif 02-Okt (4,5 hari) → laju F3 musiman-tidak-diuji;
OBI 20-simbol baru sejak 05-Okt → [2] masih kehilangan 57%.

## 5. Rekomendasi (falsifiable)

1. **Perluas `OBI_SYMBOLS` 20 → seluruh 92 simbol funding**, restart collector. *Verifikasi:*
   hitung ulang [1]/[2]/[3] setelah 7 hari; harap ≥2,3 onset/hari agar gerbang F3 terjangkau.
   **Falsifier:** bila laju [3] < 1,0/hari setelah 7 hari → tuas ini GAGAL, cari lain.
2. **F1: jangan berharap gerbang terbuka.** Pada 20-Nov evaluasi tetap dijalankan (HARD_STOP),
   tetapi C0 (n≥150) akan FALSE → verdict FAIL/INCONCLUSIVE. Ini harus diterima apa adanya.
3. **Tidak menyentuh ambang** (θ, C0–C8, N_MIN) — semua proyeksi di atas dihitung dengan ambang
   yang berlaku. Setiap usulan menurunkan ambang wajib disertai analisis daya + approval eksplisit.
4. **Jangan bangun mesin dari keluarga tren/momentum** (dilarang studi 3-segmen).

## 6. EKSEKUSI 07-Okt-2026 — perluasan cakupan OBI 20 → 92

Di-approve user: *"GO — perluas OBI_SYMBOLS 20 → 92 simbol funding, restart collector"*.

### Koreksi pengukuran (lebih akurat dari §2)

Cakupan 20-simbol ternyata baru mulai **2026-10-05 ~11:30 UTC** (sebelumnya hanya 3 simbol;
terbukti dari `n_rows_sblm=0` untuk onset QNT/ARB/BNB pagi 5 Okt). Laju sejati dgn cakupan
20 penuh (5 Okt 11:30 → 6 Okt 22:50 UTC = 1,45 hari):

| Tahap | Kejadian | Laju |
|---|---|---|
| [1] funding lolos ambang | 9 | 6,2/hari |
| [2] + OBI tersedia | 9 | 6,2/hari (**100%** — OBI sehat: 24/24 jam, 0 error) |
| [3] + OBI selaras (onset nyata) | 1 | **0,69/hari → 44 hari ≈ 30 episode** (butuh 100) |

> Jadi kehilangan 57% di tahap [2] pada §2 adalah **artefak cakupan** (onset 2–4 Okt saat OBI
> baru 3 simbol), **bukan** gap data. Yang benar-benar menyumbat = rasio penyelarasan OBI
> (~11% dari onset funding) **× cakupan simbol**.

### Tindakan yang dieksekusi

- `~/.config/systemd/user/anantara-obi.service.d/10-symbols.conf`: 20 → **92 simbol**
  (backup: `10-symbols.conf.bak-20261007`); `daemon-reload` + `systemctl --user restart`.
- **Terverifikasi:** PID 1652170, 92 simbol di env, **72 simbol baru menulis baris** ke
  `obi_20261006.jsonl` (UTC) dalam 2 menit.

### Konsekuensi yang harus disadari

1. **Granularitas turun:** sweep 92 simbol × 2 request (orderbook+trades) ≈ **37–40 s**
   (collector single-thread, ~0,2 s/request) → interval per-simbol ~40 s (sebelumnya ~7 s).
   Laju request efektif **tidak naik** (~5 req/s, dibatasi latensi; uji 60 req cepat = 0 error).
2. **LIKUIDITAS — penting:** 92 pasar termasuk **~34–45 pasar volume 24 jam < 10.000 USD**
   (snapshot 07-Okt-2026: **34**; angka bergerak mengikuti volume bergulir). Episode dari
   pasar tipis **tidak boleh** dianggap tradeable. Bila PASS bergantung pada pasar tipis,
   verdict harus **ditolak**. Ini sudah diperiksa otomatis dgn stratifikasi likuiditas
   (non-gating) di evaluator F3 + snapshot `data/sodex_market_tickers.json`.
3. Ambang pra-registrasi **tidak diubah** (θ, C0–C8, N_EP_MIN=100).

### Verifikasi yang dijanjikan (falsifiable)

Setelah **7 hari** (≈14-Okt) hitung ulang [1]/[2]/[3] pada cakupan 92 simbol.
- **Target:** ≥ 2,3 onset/hari (agar 100 episode tercapai dalam 44 hari).
- **Falsifier:** bila laju [3] < 1,0/hari → tuas perluasan **GAGAL**; jangan diteruskan
  sebagai alasan optimisme, dan laporkan bahwa gerbang F3 tidak terjangkau.

## 7. KOREKSI PENTING 07-Okt (≥9 jam setelah perluasan) — penyumbat SEJATI bukan cakupan

Pengukuran awal pada cakupan 92 simbol (`scripts/sodex_rate_check.py`, jendela 0,42 hari):

| Tahap | Laju | Catatan |
|---|---|---|
| [1] funding lolos | **116,6/hari** | naik **14×** vs cakupan 20 (6,2/hari) |
| [2] + OBI tersedia | **111,8/hari (96%)** | ✅ cakupan OBI **BERHASIL diperbaiki** |
| [3] + OBI selaras (onset) | **0** | 0 dalam 9,4 jam |

### Bongkar 47 event tahap [2] satu per satu

**47 dari 47 gagal karena `|obi20| < 0,15`.** Nol event mencapai ambang OBI.
Sehingga penyumbat **bukan** ketersediaan OBI, dan **bukan** arah tanda (`sign`).

Diperluas ke seluruh riwayat funding (2–7 Okt, n=58 event):

| Statistik | Nilai |
|---|---|
| P(\|obi20\| ≥ 0,15 \| event funding) | **3,45%**  (CI95 [0,95%, 11,7%], n=58) |
| median \|obi20\| saat event | 0,0268 |
| p90 / p99 \|obi20\| saat event | 0,1123 / 0,6454 |
| ambang beku | 0,15 → **di atas p90** |

Jadi ambang OBI hanya bisa dilewati oleh ≈3,5% event funding; separuh di antaranya
diperkirakan selaras arah → P(onset \| event) ≈ 1,7%.

### Koreksi diri (klaim saya sebelumnya salah separuh)

Saya menyatakan *"penyumbat F3 = CAKUPAN OBI (20/92)"*. Itu **benar hanya untuk tahap [2]**.
Penyumbat **sebenarnya** = **konjungsi dua kondisi langka**: `|funding| ≥ 0,003%` **dan**
`|obi20| ≥ 0,15` yang terjadi bersamaan. Cakupan adalah syarat perlu, **bukan** syarat cukup.

### Proyeksi (belum memutuskan)

[3] ≈ 116/hari × 1,7% ≈ **2,0 onset/hari → 44 hari ≈ 87 episode** (butuh 100).
**Ambang batas / borderline** — CI lebar (0,95%→11,7% pada gerbang OBI) sehingga hasilnya
bisa 48 atau 600. **Belum dapat dipastikan dari data sekarang.**

Ambang tetap **TIDAK diubah** (§ dan §9): θ, C0–C8, N_EP_MIN=100 beku.
Pemeriksaan 7 hari (≈14-Okt) **tetap dijalankan** dan tetap menentukan.
