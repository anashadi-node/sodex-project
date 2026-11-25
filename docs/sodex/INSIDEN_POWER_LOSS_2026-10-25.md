# INSIDEN 2026-10-25 — LISTRIK MATI SAAT KAMPANYE 7 HARI

**Waktu mati:** ~10:00 WIB (03:00 UTC) · **Boot:** 10:01:52 WIB (03:01:52 UTC)
**Dampak:** kampanye terputus 392 detik, 6 record hilang, 0 data aktif rusak setelah perbaikan.

---

## 1. Apa yang terjadi

| Tahap | Waktu (UTC) | Keterangan |
|---|---|---|
| Baris terakhir sebelum mati | 03:00:09 | book BTC/ETH, semua simbol |
| Listrik mati | ~03:00:10 | tulisan disk terputus |
| Boot | 03:01:52 | 102 detik mati total |
| Auto-restart systemd | 03:02:01 | kampanye jalan lagi tanpa intervensi |
| Perbaikan data | 03:04–03:06 | 2× stop/start untuk repair deterministik |
| Baris pertama pasca-repair | 03:06:41 | data bersih |

**Total gap: 392 detik = 0,065% dari 7 hari.**

## 2. Kerusakan data

Power loss meninggalkan **blok berisi null byte** (`\x00`) di 10 file book —
satu per simbol — lalu run baru menyambung di belakangnya.

| Item | Jumlah |
|---|---|
| Baris terpotong | 20 |
| Record berhasil diselamatkan (salvage) | 20 |
| Record hilang (tidak bisa dipulihkan) | **6** |
| Baris rusak pada data aktif setelah perbaikan | **0** |

Backup file asli (termasuk yang rusak) disimpan di
`data/sodex_venue_7d/_repair_backup/<timestamp>/` untuk audit.
Manifest perbaikan: `_repair_manifest_*.json` (hash sebelum/sesudah).

## 3. Dampak terhadap analisis

1. **Gap 392 detik** — tidak memengaruhi estimasi spread/adverse selection
   (dihitung per trade, bukan per waktu kalender).
2. **6 record hilang** — 0,07% dari ~9.500 baris book; tidak mengubah median.
3. **Perubahan deadline** — `run.json` mencatat start terakhir 03:06 UTC,
   sehingga kampanye berakhir **1 Nov 03:06 UTC (10:06 WIB)**, bukan 02:39.
   Seluruh riwayat start dicatat di `_run_history.jsonl`.

## 4. Yang diperbaiki agar tidak terulang

| Masalah | Perbaikan |
|---|---|
| Daemon riset jalan via `nohup` → mati permanen saat reboot | dijadikan unit **`sodex-sig-search.service`** (`enable`, `Restart=on-failure`) |
| Log daemon dobel (stdout + file log path sama) | stdout diarahkan ke `.out` |
| Kerusakan tidak terdeteksi otomatis | verifikasi JSONL + deteksi gap ada di prosedur pasca-insiden |

## 5. Risiko yang MASIH terbuka

1. **Listrik bisa mati lagi** — gap akan bertambah. Rekomendasi: UPS kecil
   (≥15 menit) untuk PC ini, atau pindahkan kolektor ke VPS.
2. **Tidak ada pengecekan otomatis** bahwa gap < ambang. Jika mati > 30 menit,
   dataset 7 hari sebaiknya **diulang**, bukan dianalisis apa adanya.

**Ambang gugur yang ditetapkan sekarang:** total gap > 30 menit → kampanye diulang.
