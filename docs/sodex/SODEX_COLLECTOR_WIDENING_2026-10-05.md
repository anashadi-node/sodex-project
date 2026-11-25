# Perluasan Cakupan Collector SoDEX + Guard Anti-Jeda + Penghitung Episode

**Tanggal:** 2026-10-05 · **Lingkup:** SODEX saja · **Persetujuan user:** Opsi 1, 2 & 3 (berurutan)
**Sifat:** READ-ONLY terhadap lane uang — tidak menyentuh gate T1, leverage, sizing, target,
`SODEX_TOTAL_WALLET`, arm A1, maupun `RW_MARGIN_UTIL_CAP`.

---

## Latar: mengapa ini dilakukan

Uji forward momentum (`docs/sodex/SODEX_FORWARD_MOMENTUM_2026-10-05.md`) menghasilkan
**0/3 LULUS**, tetapi menemukan bahwa pada **θ=2,0%** magnitudonya **sudah cukup**
(+0,8232% bersih/24 jam; ambang pra-registrasi 0,40%/trade terlampaui 2,06×; SR +3,44;
3/3 segmen positif). Yang gagal adalah **kekuatan bukti**: n=53 episode →
`p_signflip` 0,196, `p_day_cluster` 0,495.

**Bottleneck bergeser**: dari *magnitudo edge* menjadi *jumlah episode*. Karena itu tiga
langkah ini dikerjakan — semuanya menambah bukti **tanpa** melonggarkan batas keamanan.

## Step 1 — Perluasan simbol collector (3 → 20)

Unit: `anantara-obi.service` (READ-ONLY, tanpa auth, tanpa jalur order).
Drop-in: `~/.config/systemd/user/anantara-obi.service.d/10-symbols.conf`
(disalin ke `systemd/` di repo).

**Aturan pemilihan OBJEKTIF — bukan pilih-pilih:**
semua pasar SoDEX dengan **quoteVolume 24 jam > 50.000 USD**, diambil dari endpoint publik
`/api/v1/perps/markets/tickers` (**92 pasar** terdaftar; **20 lolos** ambang).

| # | Simbol | quoteVol 24j | spread |
|---|---|---|---|
| 1 | BTC-USD | 55,1 jt | 0,12 bp |
| 2 | ETH-USD | 48,5 jt | 0,37 bp |
| 3 | ZEC-USD | 3,63 jt | 0,52 bp |
| 4 | SOL-USD | 1,95 jt | 0,83 bp |
| 5 | DOGE-USD | 1,61 jt | 1,04 bp |
| 6 | SUI-USD | 1,51 jt | 0,81 bp |
| 7 | XAUT-USD | 1,27 jt | 0,24 bp |
| 8 | QNT-USD | 1,22 jt | 0,79 bp |
| 9 | BNB-USD | 914 rb | 1,27 bp |
| 10 | PONS-USD | 754 rb | 2,51 bp |
| 11 | LIT-USD | 558 rb | 0,51 bp |
| 12 | HYPE-USD | 435 rb | 0,11 bp |
| 13 | AAVE-USD | 362 rb | 0,55 bp |
| 14 | XRP-USD | 302 rb | 0,66 bp |
| 15 | US500-USD | 245 rb | 0,13 bp |
| 16 | UNI-USD | 223 rb | 1,11 bp |
| 17 | ARB-USD | 173 rb | 0,97 bp |
| 18 | SNDK-USD | 90,6 rb | 0,06 bp |
| 19 | AVAX-USD | 74,1 rb | 0,91 bp |
| 20 | SPCX-USD | 57,3 rb | 0,63 bp |

Semua 17 simbol baru diuji endpoint-nya lebih dulu: **orderbook 200 & trades 200** ✓.

**Efek sampling:** latensi orderbook terukur ≈ 0,17 s/panggilan → sweep 20 simbol ≈ 7–10 s
(sebelumnya 3 simbol ≈ 4 s). Analisis memakai bar 1 menit, jadi kepadatan ini tetap memadai.
`OBI_POLL=4.0` tidak diubah agar tidak menyimpang dari data lama.

**Terverifikasi setelah restart:** 20 simbol menulis di `obi_*.jsonl` dan `trades_*.jsonl`,
baris terbaru **0,1 menit** lalu.

## Step 2 — Guard anti-jeda (`sodex-collector-guard`)

`Restart=always` pada unit sudah menangani proses yang **mati**. Yang **tidak** tercakup:
proses **hidup tapi macet** — persis pola yang diduga menyebabkan jeda **2026-08-03..08-08**
(6 hari data hilang).

`scripts/sodex_collector_guard.py` (READ-ONLY):
- membaca baris terbaru `obi_*.jsonl` + `trades_*.jsonl` (256 KB terakhir, cepat);
- mendeteksi: unit tidak aktif · baris terbaru > **15 menit** · simbol < 20;
- bila bermasalah → **restart unit** + notifikasi Telegram, dibatasi **3 restart/jam**
  (anti-loop), lalu **memverifikasi pemulihan** (baris baru < 5 menit);
- toleran pergantian hari UTC (berkas hari baru belum ada < 20 menit).

Timer: `sodex-collector-guard.timer`, **tiap 10 menit**.
**Uji dua arah berhasil:** jalur normal → `OK — 20 simbol, baris terbaru 0,1 menit lalu`;
jalur deteksi (ambang dipaksa 0) → mendeteksi → restart → **pemulihan BERHASIL**.

## Step 3 — Penghitung episode + pemicu re-uji (`sodex-episode-count`)

`scripts/sodex_episode_counter.py` (READ-ONLY) menghitung episode independen pada θ=2,0%
dan melaporkan kapan ambang **150 episode** tercapai → pemicu re-uji DEV dengan
**pra-registrasi BARU**.

**SEGEL LOCKBOX DIHORMATI SECARA EKSPLISIT:**
- BTC/ETH/SOL pada **2026-09-01..2026-10-05 = LOCKBOX → tidak pernah dibaca**;
- simbol baru dihitung sejak 2026-10-05 (mereka tidak punya lockbox);
- keluaran mencatat `lockbox_read: false`.

**Hasil hitung saat ini:**

| Komponen | Episode θ=2,0% |
|---|---|
| Basis DEV (BTC/ETH/SOL, 94 hari) | **54** |
| Simbol baru (17 simbol, hari ke-1) | 0 |
| **TOTAL** | **54 / 150** |
| Laju proyeksi | ≈ 3,83 episode/hari |
| **Perkiraan capai 150** | **≈ 2026-10-31** |

Timer: `sodex-episode-count.timer`, **harian 08:30 WIB** (`Persistent=true`).
Saat ≥150 → **notifikasi Telegram otomatis** dengan instruksi: tulis pra-registrasi baru,
jalankan re-uji DEV; lockbox lama tetap tersegel.

## Batas & catatan jujur

- 17 simbol baru = pasar **lebih kecil** (quoteVol 57 rb–3,6 jt) → spread lebih lebar dan
  likuiditas lebih tipis; hasilnya **harus distratifikasi** (kecil vs besar) di re-uji nanti.
- Termasuk instrumen **non-kripto** (XAUT, US500, SNDK, SILVER-like) → dinamika bisa berbeda;
  stratifikasi juga disarankan.
- Perluasan simbol **tidak** mengubah pra-registrasi lama; re-uji nanti **wajib** memakai
  pra-registrasi baru (ambang, sampel, lockbox baru) sebelum evaluasi.
- **Tidak ada** perubahan pada: gate T1 · leverage · sizing · target 0,8%/48 jam ·
  `SODEX_TOTAL_WALLET` · arm A1 (tetap mati) · `RW_MARGIN_UTIL_CAP` (default OFF).

## Berkas

| Berkas | Peran |
|---|---|
| `scripts/sodex_collector_guard.py` | guard anti-jeda |
| `scripts/sodex_episode_counter.py` | penghitung episode + pemicu |
| `systemd/sodex-collector-guard.{service,timer}` | jadwal guard 10 menit |
| `systemd/sodex-episode-count.{service,timer}` | jadwal hitung harian |
| `systemd/anantara-obi.service.d/10-symbols.conf` | perluasan 20 simbol |
| `reports/sodex/SODEX_FORWARD_EPISODE_COUNT.json` | keluaran hitung |
