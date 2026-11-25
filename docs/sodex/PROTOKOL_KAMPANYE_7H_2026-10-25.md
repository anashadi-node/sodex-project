# PROTOKOL KAMPANYE 7 HARI — VENUE MARKET SODEX

**Mulai:** 2026-10-25 02:39 UTC · **Berakhir:** 2026-11-01 02:39 UTC
**Status:** BERJALAN (`sodex-venue-7d.service`, PID aktif, linger=yes)
**Sifat:** pra-registrasi. Analisis final WAJIB mengikuti rencana di bawah.

---

## 1. Apa yang direkam

| Aliran | Isi | Frekuensi | Perkiraan volume |
|---|---|---|---|
| `book` | top-20 bid/ask, `blockTime`, `updateID` | **10 detik** | ~95 MB/hari |
| `trades` | id, timestamp venue, side, harga, qty (incremental) | 10 detik | ~20 MB/hari |
| `klines` | 1m OHLCV (aliran silang verifikasi) | 60 detik | <1 MB/hari |
| `deep` | orderbook limit=50 (menguji kedalaman) | 1 jam | <1 MB/hari |

**Simbol (10 paling likuid, dipilih dari volume 24 jam):**
BTC-USD, ETH-USD, ZEC-USD, SOL-USD, SNDK-USD, XAUT-USD, SUI-USD, HYPE-USD, ARB-USD, LIT-USD

**Hash konfigurasi:** `da6752b001df08af` (tercatat di `run.json`, tidak boleh berubah)

---

## 2. Kontrol integritas (berjalan otomatis)

| Pemeriksaan | Aksi bila gagal |
|---|---|
| `bid < ask` | dihitung, data **tidak dibuang** |
| harga ≤ 0 | dihitung |
| trade id tidak monoton | duplikat dihitung & dibuang |
| trade terpotong (>200/siklus) | `truncations` + log |
| request gagal | `errors` + atribusi simbol |
| disk < 5 GB | berhenti |
| umur heartbeat > 60 s | dianggap mati |

**Ambang gugur:** jika `errors` > 2% request ATAU `truncations` > 50/hari ATAU
`spread_violations` > 0,1% baris → data **tidak layak** dan harus diulang.

---

## 3. Hipotesis yang diuji setelah 7 hari

| Kode | Hipotesis | Metrik | Ambang lulus |
|---|---|---|---|
| **H1** | Spread menutup biaya maker | median spread per simbol/jam | ≥ 2,28 bps (fee maker RT) |
| **H2** | Adverse selection < spread | mean mid-move 1s/5s/30s/5m setelah trade, bertanda sisi agresor | AS₅ₛ ≤ ½ spread |
| **H3** | Fill mungkin pada antrean | P(harga menyentuh level dalam 30 s) | ≥ 20% |
| **H4** | Kedalaman cukup untuk $250 | notional 10 level teratas | ≥ $2.500 per sisi |
| **H5** | Ada musim intraday | variasi spread antar-jam | ≥ 1,5× median |
| **H6** | MM net positif | spread − 2·AS₅ₛ − fee | > 0 bps/RT |

**Aturan statistik:** semua hipotesis diuji dengan **n per simbol**, bukan pooled;
BH-FDR q=0,10 untuk 6 hipotesis; CI95 bootstrap 10.000 ulangan.

---

## 4. Yang TIDAK boleh dilakukan setelah melihat data

1. Mengubah horizon AS (1s/5s/30s/5m) — sudah dibekukan.
2. Memilih simbol setelah melihat hasil.
3. Menambah hipotesis baru lalu melaporkannya sebagai "ditemukan".
4. Menghapus hari yang buruk.

Semua pelanggaran harus dicatat di laporan akhir.

---

## 5. Keterbatasan yang diakui sejak awal

1. **Snapshot, bukan diff** — perubahan di antara 2 snapshot (10 s) tidak terlihat.
2. **Fill tidak bisa dipastikan** — H3 hanya proxy (harga menyentuh), bukan antrean nyata.
3. **Satu venue, satu minggu** — tidak bisa menggeneralisasi ke kondisi pasar lain.
4. **Tanpa data funding/OI** — endpoint gateway tidak menyediakan (404 saat diuji).
5. **10 simbol** — simbol di luar daftar tidak terwakili.

---

## 6. Keluaran akhir (otomatis + manual)

- `_FINAL_SUMMARY.json` — ringkasan otomatis saat berhenti
- `_quality_YYYY-MM-DD.json` — kualitas harian
- Laporan analisis `HASIL_KAMPANYE_7H_2026-11-01.md` — H1–H6 + keterbatasan

**Keputusan yang mungkin:** (a) layak diuji forward dengan modal kecil, (b) ditolak,
(c) data tidak layak → ulangi. **Tidak ada order otomatis dalam bentuk apa pun.**

---

## 6b. Harness evaluasi (dibekukan sebelum data matang)

- `scripts/research/campaign_eval.py` menghitung H1–H6 dan **fail-closed**:
  data < 6 hari → semua status `INSUFFICIENT` (tidak ada PASS/FAIL);
  penilai yang error → status `ERROR`, verdict `INSUFFICIENT`.
- Tes: `tests/test_campaign_eval.py` — 7 tes, termasuk penilai sengaja dibuat
  error dan kontrol negatif spread tipis (harus NO-GO).
- Otomatis: `sodex-campaign-eval.timer` tiap **10:30 WIB** →
  `reports/sodex/campaign_eval_latest.json`.
- H2 horizon **1 s tidak diukur** (book hanya 10 s) dan dilaporkan sebagai
  ketiadaan, bukan diisi angka karangan.
- Verdict `GO` hanya bila **H1, H2, H4, H6 semuanya PASS** pada ≥50% simbol.

## 7. Status pasca-insiden listrik (25 Okt 03:00 UTC)
| Item | Nilai terukur |
|---|---|
| Gap total | **392 detik** (0,065% kampanye) |
| Record hilang | **6** (blok null-byte, tidak dapat dipulihkan) |
| Baris rusak pada data aktif | **0** (terverifikasi 9.500+ baris) |
| Interval antar-snapshot | median **10,0 s**, p90 **18,6 s** |
| Deadline baru | **1 Nov 03:06 UTC** (10:06 WIB) |

**Ambang gugur:** total gap > **30 menit** → kampanye diulang, bukan dianalisis.
Detail lengkap: `INSIDEN_POWER_LOSS_2026-10-25.md`.

**Catatan istilah:** `dup_trades` di heartbeat = jumlah **trade ID yang disaring**
karena sudah pernah dilihat (endpoint mengembalikan window 200 trade terakhir tiap
poll), **bukan** duplikat yang tersimpan. Verifikasi 25 Okt: 1.718 baris BTC = 1.718
ID unik, 0 duplikat tersimpan.

## 8. Amandemen v1.1 — 25 Okt 03:51 UTC

**Dua cacat ditemukan saat verifikasi, keduanya diperbaiki sebelum 1/7 data terkumpul.**

1. **Daftar simbol dinamis.** `top_symbols()` memeringkat simbol dari file klines lokal;
   saat service restart, peringkat bisa berubah. Terbukti: smoke test menulis
   `LITE-USD`, `SMCI-USD`, `US500-USD` — simbol yang **bukan** anggota kampanye —
   ke folder data aktif. Perbaikan: `SYMBOLS` dipatok di unit systemd; ketiga simbol
   asing dipindahkan ke `data/sodex_venue_7d_foreign_20261025/` (tidak dihapus, untuk audit).
2. **Burst klines tiap 60 detik.** Sepuluh permintaan klines jatuh pada detik yang sama
   dengan 20 permintaan book/trades → timeout beruntun (32 error per 03:50, pola tepat
   tiap 60 detik). Perbaikan: klines dirotasi 3 fase (tiap simbol ~30 s).

| Item | v1.0 | v1.1 |
|---|---|---|
| config hash | `da6752b001df08af` | `7fe3b40d88365e27` |
| simbol | dinamis | dipatok 10 |
| klines | 10 serentak/60 s | rotasi 3 fase |
| book/trades/deep | — | **tidak berubah** |

Data v1.0 (02:38–03:50 UTC) tetap sah untuk book/trades/deep. Batas v1.0/v1.1
dicatat di `_run_history.jsonl`. Deadline baru: **1 Nov 2026 03:51 UTC (10:51 WIB)**.
