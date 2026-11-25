# PAPER HEALTH — 4 arm A/B 9 SoDEX (ab9a/ab9b/ab9c/ab9d)

*Dibuat: 2026-11-12 09:36:41 WIB (WIB). Sumber: funnel & state JSON arm ab9* + `data/paper_test_twoway_state.json` + journal systemd. Semua angka dari eksekusi nyata; READ-ONLY.*

Skrip: `/home/USER/.hermes/profiles/sodex/cache/scratch/paper_health_ab9.py` (ekstraksi) dan `.../render_paper_health.py` (render). Perintah:

```bash
cd /home/USER/anantara-sakti
unset PYTHONPATH
.venv-research/bin/python3 ~/.hermes/profiles/sodex/cache/scratch/paper_health_ab9.py \
    --json ~/.hermes/profiles/sodex/cache/scratch/paper_health_ab9.json
.venv-research/bin/python3 ~/.hermes/profiles/sodex/cache/scratch/render_paper_health.py
```

## 0. Konfigurasi arm (dari ExecStart efektif)

| Arm | Gate makro BTC | Filter PRE24 | Sinyal | Geometri | Mulai funnel (WIB) |
|---|---|---|---|---|---|
| 9a | ON (`TW_REGIME_GATE=1`) | — | dibalik | TP1.5%/SL6%/24h | 2026-11-12 07:00:36 WIB |
| 9b | ON | — | dibalik | TP1.5%/SL6%/24h | 2026-11-12 07:00:38 WIB |
| 9c | ON | **ON (+3%/24j)** | dibalik | TP1.5%/SL6%/24h | 2026-11-12 07:00:40 WIB |
| 9d | **OFF** (`TW_REGIME_GATE=0`) | — | dibalik | TP1.5%/SL6%/24h | 2026-11-12 09:01:04 WIB |

Catatan: `TW_INVERT_SIGNAL=1` di keempat arm (sinyal diperdagangkan terbalik). Batas posisi: 6 sinyal + 2 random (`max_signal`/`max_random`). Interval siklus entry = 300 s (12 siklus/jam).

## 1. Laju blackout feed & laju kandidat per arm

**Definisi** (diturunkan dari `scripts/paper_test_twoway.py` baris 740–878):
- `scans` = `totals.pairs_scanned` = 23 pair × siklus entry (tiap 5 menit).
- `fetch_error` = pair gagal fetch (blackout). 23 error = 1 siklus blackout penuh (semua pair gagal → 1 baris `Signal error` per pair).
- `kandidat aktif` (sinyal) = `entry_signal + skip_chop_gate + skip_btc_gate + skip_dir_gate + `skip_pre24 + skip_block_long_signal + skip_signal_cap + skip_pair_pos_cap + skip_no_price`.
- Blok cabang **RANDOM** dihitung terpisah (`skip_random_btc_gate`, `entry_random`).

| Arm | cycles | scan | scan/cycle | fetch_error | laju blackout | siklus blackout penuh | jam berjalan | kandidat aktif | kandidat/jam (desain) | kandidat/jam (teramati) | entry SINYAL | entry RANDOM |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 9a | 35 | 805 | 23.0 | 161 | **20.0%** | 7 | 2.53 | 17 | 5.83 | 6.72 | 0 | 0 |
| 9b | 33 | 759 | 23.0 | 161 | **21.2%** | 7 | 2.53 | 17 | 6.18 | 6.71 | 0 | 0 |
| 9c | 33 | 759 | 23.0 | 161 | **21.2%** | 7 | 2.53 | 17 | 6.18 | 6.71 | 0 | 0 |
| 9d | 8 | 184 | 23.0 | 0 | **0.0%** | 0 | 0.53 | 8 | 12.00 | 15.10 | 0 | 2 |

Rincian blokir gate (siklus berjalan):

| Arm | skip_chop_gate | skip_btc_gate | kandidat SINYAL (gates_signal) | skip_random_btc_gate | entry_random |
|---|---|---|---|---|---|
| 9a | 11 | 6 | 17 | 21 | 0 |
| 9b | 11 | 6 | 17 | 19 | 0 |
| 9c | 11 | 6 | 17 | 19 | 0 |
| 9d | 8 | 0 | 8 | 0 | 2 |

**Bacaan:**
- Laju blackout ~**20–21%** di 9a/9b/9c (161 fetch_error dari 759–805 scan = tepat 7 siklus blackout penuh per arm). Arm **9d 0%** (0 fetch_error, 184 scan) — berbeda karena jendelanya pendek (mulai 09:01) dan/atau periode blackout belum terulang.
- Kandidat SINYAL aktif muncul ~**5,8–6,2 per jam** (desain) di 9a/9b/9c; 9d ~**12/jam**. Artinya feed & sinyal TIDAK langka — yang menahan entry adalah **gerbang** (`skip_chop_gate` + `skip_btc_gate`), bukan ketiadaan sinyal.
- **Entry SINYAL = 0 di keempat arm** sejak funnel diaktifkan. Jadi 100% kandidat aktif diblokir gerbang.

### Proyeksi waktu mencapai n=20 / n=100 trade tertutup (per arm)

**Asumsi proyeksi (eksplisit):**
1. Geometri TP 1,5% / SL 6% / time-stop 24 jam (`TW_TIME_STOP_H=24`).
2. Plafon posisi sinyal = 6 (`max_signal`), hold maksimum 24 jam.
3. Laju tiba pada kondisi tunak (steady state), tanpa berhenti/restart, cuaca feed sama.
4. "Trade tertutup" butuh jeda keluar ≤ 24 jam (time-stop) setelah entry terakhir.

**Baris A — laju sekarang (apa adanya).** Entry aktual = 0/jam di semua arm → n=20 dan n=100 tak terhingga (tidak akan tercapai tanpa mencabut gerbang).

**Baris B — andai gerbang dibuka, plafon tidak mengikat** (waktu = target/laju kandidat + 24 jam):

| Arm | laju kandidat/jam (desain) | t(n=20) jam | t(n=20) hari | t(n=100) jam | t(n=100) hari |
|---|---|---|---|---|---|
| 9a | 5.83 | 27.4 | 1.14 | 41.2 | 1.71 |
| 9b | 6.18 | 27.2 | 1.13 | 40.2 | 1.67 |
| 9c | 6.18 | 27.2 | 1.13 | 40.2 | 1.67 |
| 9d | 12.00 | 25.7 | 1.07 | 32.3 | 1.35 |

**Baris C — andai gerbang dibuka DAN plafon 6 posisi mengikat** (hold penuh 24 jam → throughput ≤ 6/24jam = 0,25 trade tertutup/jam, sama untuk semua arm):

| Arm | t(n=20) jam | t(n=20) hari | t(n=100) jam | t(n=100) hari |
|---|---|---|---|---|
| 9a | 104 | 4.33 | 424 | 17.67 |
| 9b | 104 | 4.33 | 424 | 17.67 |
| 9c | 104 | 4.33 | 424 | 17.67 |
| 9d | 104 | 4.33 | 424 | 17.67 |

Karena laju kandidat (5,8–12/jam) jauh melebihi throughput plafon (0,25/jam), **Baris C yang relevan** apabila gerbang dicabut: ≈ **104 jam (~4,3 hari) untuk n=20** dan ≈ **424 jam (~17,7 hari) untuk n=100**, per arm. Baris B hanya berlaku bila TP 1,5% terpicu jauh lebih cepat dari 24 jam sehingga plafon tak sempat mengikat (belum terukur).

## 2. Riwayat kandidat (lane twoway produksi, `data/paper_test_twoway_state.json`)

- Total trade tertutup: **602** → **512 SIGNAL** (470 LONG, 42 SHORT) + **90 RANDOM_CONTROL** (LONG).
- **Semua 42 entry SHORT berada di regime `BEAR_MOMENTUM`** (42/42) — tak ada SHORT di regime lain.
- `btc_regime` per entry SIGNAL: **BULL 286, NA 226**. Field `btc_regime` baru diisi sejak **2026-09-16**; 226 entry lama (2026-08-06 → 2026-10-03) bernilai `None`. `CHOP` (53) hanya pada entry RANDOM, bukan SIGNAL.
- Rentang data: 2026-08-06 → 2026-11-06. **Tidak ada entry baru di lane ini sejak 2026-11-06** (6 hari, konsisten dengan 0 entry di arm ab9*).

### Tabel harian (20 hari terakhir; SIGNAL only untuk kolom regime)

| Tanggal | SIGNAL | RANDOM | LONG | SHORT | SHORT/BEAR | btc_regime (SIGNAL) |
|---|---|---|---|---|---|---|
| 2026-10-11 | 8 | 2 | 8 | 0 | 0 | BULL:8 |
| 2026-10-19 | 8 | 4 | 8 | 0 | 0 | BULL:8 |
| 2026-10-20 | 9 | 4 | 9 | 0 | 0 | BULL:9 |
| 2026-10-21 | 3 | 1 | 3 | 0 | 0 | BULL:3 |
| 2026-10-22 | 5 | 6 | 5 | 0 | 0 | BULL:5 |
| 2026-10-23 | 5 | 1 | 5 | 0 | 0 | BULL:5 |
| 2026-10-24 | 0 | 2 | 0 | 0 | 0 | — |
| 2026-10-25 | 2 | 3 | 2 | 0 | 0 | BULL:2 |
| 2026-10-26 | 8 | 4 | 8 | 0 | 0 | BULL:8 |
| 2026-10-27 | 7 | 1 | 7 | 0 | 0 | BULL:7 |
| 2026-10-28 | 4 | 2 | 4 | 0 | 0 | BULL:4 |
| 2026-10-29 | 7 | 4 | 7 | 0 | 0 | BULL:7 |
| 2026-10-30 | 2 | 5 | 2 | 0 | 0 | BULL:2 |
| 2026-10-31 | 11 | 2 | 11 | 0 | 0 | BULL:11 |
| 2026-11-01 | 6 | 2 | 6 | 0 | 0 | BULL:6 |
| 2026-11-02 | 2 | 3 | 2 | 0 | 0 | BULL:2 |
| 2026-11-03 | 7 | 3 | 7 | 0 | 0 | BULL:7 |
| 2026-11-04 | 16 | 4 | 16 | 0 | 0 | BULL:16 |
| 2026-11-05 | 3 | 1 | 3 | 0 | 0 | BULL:3 |
| 2026-11-06 | 1 | 1 | 1 | 0 | 0 | BULL:1 |

**Ringkasan rentang penuh (85 hari aktif, 2026-08-06 → 2026-11-06):** SIGNAL 512 (LONG 470, SHORT 42), RANDOM 90, SHORT/BEAR_MOMENTUM 42.

### Berapa hari untuk mengumpulkan n=20 / n=100 entry SHORT di regime BEAR_MOMENTUM

**Temuan kunci:** seluruh 42 entry SHORT/BEAR_MOMENTUM terjadi dalam jendela sempit **2026-08-06 → 2026-09-02** lalu **berhenti total** (0 entry selama ~71 hari terakhir, 2026-09-03 → 2026-11-12). Regime `BEAR_MOMENTUM` tidak lagi menghasilkan kandidat SHORT di lane ini.

| Basis laju | Laju | t(n=20) | t(n=100) |
|---|---|---|---|
| Rata-rata kalender penuh (42 / 93 hari) | 0,452 entry/hari | 44,3 hari | 221,4 hari |
| Hanya hari yang benar-benar menghasilkan (42 / 14 hari) | 3,00 entry/hari-aktif | 6,7 hari-aktif | 33,3 hari-aktif |
| **Laju hidup saat ini (0 entry sejak 2026-09-02)** | **0 /hari** | **tak terhingga** | **tak terhingga** |

Angka 44/221 hari adalah **ekstrapolasi historis**, bukan laju hidup: jendela produktif sudah tutup 71 hari lalu dan kandidat SHORT/BEAR saat ini justru **diblokir gerbang** (`skip_btc_gate`/`skip_chop_gate`) di arm ab9*. Pada laju sekarang, target n=20/100 tidak tercapai.

## 3. Uji kesamaan waktu blackout dengan jadwal timer systemd lain

**Bukti timestamp yang tersedia:**
- File log arm (`logs/paper_test_twoway_ab9*.log`) di-`StandardOutput=append:` **tanpa prefix timestamp** → tidak bisa membaca menit tiap siklus dari file.
- `journalctl --user -u anantara-paper-ab9a` **tidak** memuat baris `Signal error`/`feed blackout` (stdout/stderr arm dialihkan ke file) → tidak ada timestamp per-siklus di journal.
- `logs/paper_test_twoway_ab9a_error.log` = 11 baris FATAL **tanpa timestamp**; `logs/paper_test_twoway_ab9d_error.log` **kosong (0 byte)**.

**Satu-satunya bukti ber-timestamp:** event *proses keluar* (FATAL hanya dicetak setelah 3 siklus entry blackout berturut-turut; `_EMPTY_STREAK` hanya naik pada siklus entry 5-menit) — terbaca dari journal. Total 11 event, selaras dengan 11 baris FATAL di error.log:

| Tanggal (WIB) | Jam keluar | Menit | Detik |
|---|---|---|---|
| 2026-11-09 | 07:23:45 | :23 | :45 |
| 2026-11-09 | 07:42:05 | :42 | :05 |
| 2026-11-09 | 07:52:36 | :52 | :36 |
| 2026-11-09 | 08:12:15 | :12 | :15 |
| 2026-11-09 | 08:22:46 | :22 | :46 |
| 2026-11-09 | 08:33:18 | :33 | :18 |
| 2026-11-09 | 08:43:49 | :43 | :49 |
| 2026-11-11 | 09:32:18 | :32 | :18 |
| 2026-11-11 | 09:52:03 | :52 | :03 |
| 2026-11-12 | 08:42:12 | :42 | :12 |
| 2026-11-12 | 08:52:43 | :52 | :43 |

**Pengamatan:**
- Pada 2026-11-12 08:42:12 dan 08:52:43, arm **9a, 9b, dan 9c keluar pada detik yang sama persis** → blackout **tersinkron lintas-arm**, mengindikasikan sebab feed/venue bersama, bukan acak per-arm.
- Jarak antar-keluar ≈ kelipatan ~10 menit (mis. 07:42:05 → 07:52:36 = 10,5 menit; 08:42:12 → 08:52:43 = 10,5 menit), menandakan pola blackout berulang ~10 menit.
- Menit keluar teramati: **:42** dan **:52** (Nov 12); **:32** dan **:52** (Nov 11); **:23/:42/:52/:12/:22/:33/:43** (Nov 9). Jadwal timer Binance lain ber-`OnCalendar`: swing-deep-learner `*:0/5`, anantara-sentiment & hl-watchdog `*:0/10`; cex-futures-deep-loop `OnUnitActiveSec=15min` (fase :12/:27/:42/:57).

**Kesimpulan (taat bukti):** **TIDAK ADA bukti timestamp per-siklus blackout.** Yang tersedia hanya timestamp kejadian keluar. Detik keluar teramati (:03, :05, :12, :15, :18, :36, :43, :45, :46, :49) tidak menunjukkan kesamaan yang konsisten dengan jadwal timer mana pun; hal ini wajar karena anchor siklus tiap arm = waktu start prosesnya sendiri (bukan wall-clock bulat), sehingga kesamaan menit/detik dengan timer lain tidak diharapkan. **Tidak dapat disimpulkan** bahwa siklus blackout jatuh pada menit yang sama dengan timer systemd lain — diperlukan logging ber-timestamp pada siklus fetch untuk membuktikannya. Yang BISA dikatakan: blackout berulang tiap ~10 menit dan tersinkron lintas-arm.

## 4. Kesehatan proses 4 arm + lane paper lain

| Arm | is-active | NRestarts | Mulai proses (WIB) | PID | RAM (MB) | state size | state mtime | funnel size | funnel mtime | posisi terbuka | n_trades |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 9a | active/running | 0 | Thu 2026-11-12 09:27:15 WIB | 106919 | 62.3 | 2155 B | 2026-11-12 09:36:34 WIB | 890 B | 2026-11-12 09:32:33 WIB | 0  | 0 |
| 9b | active/running | 0 | Thu 2026-11-12 09:27:23 WIB | 106986 | 62.3 | 2155 B | 2026-11-12 09:36:40 WIB | 890 B | 2026-11-12 09:32:39 WIB | 0  | 0 |
| 9c | active/running | 0 | Thu 2026-11-12 09:27:31 WIB | 107044 | 62.2 | 2155 B | 2026-11-12 09:36:02 WIB | 889 B | 2026-11-12 09:33:01 WIB | 0  | 0 |
| 9d | active/running | 0 | Thu 2026-11-12 09:27:39 WIB | 107115 | 62.2 | 3351 B | 2026-11-12 09:36:02 WIB | 848 B | 2026-11-12 09:33:02 WIB | 2 ['ENA_LONG_20261112_020104_R', 'XAUT_LONG_20261112_020147_R'] | 0 |

- Keempat arm `active (running)`, **NRestarts=0** (counter ter-reset oleh start manual), RAM ~62 MB (plafon 512 MB). State & funnel ter-update baru-baru ini (fresh).
- **Posisi terbuka:** 9a/9b/9c = 0; **9d = 2 posisi RANDOM** (`ENA_LONG_20261112_020104_R, XAUT_LONG_20261112_020147_R`). 9d juga mencatat 2 entry RANDOM; 0 entry SINYAL.
- Error log FATAL (feed buta): 9a=11, 9b=11, 9c=11, 9d=0.

### Lane paper lain yang berhenti (mtime > 2 jam)

Diperiksa lewat mtime **log** setiap unit paper yang running (proxy liveness paling langsung; 23 unit `anantara-paper-*` running per `systemctl --user list-units --state=running`):

| Hasil | Jumlah | Keterangan |
|---|---|---|
| Unit paper running dgn log segar (< 2 jam) | **23 / 23** | termasuk 4 arm ab9* |
| Unit paper running dgn log basi (> 2 jam) | **0** | tidak ada lane yang berhenti |

Log terbaru: paling tua `paper_test_portfolio.log` (49 menit); sisanya < 10 menit. Tidak ada lane paper aktif yang berhenti. Namun ada **file state ter-tinggal** (tidak ada unit running-nya) dengan mtime > 2 jam — bukan lane aktif, hanya sisa/diarsipkan. Contoh terbaru: `realwide_micro_live_state.DRY.json` (23 jam), `sodex_recovery_notify_state.json` (423 jam), selebihnya >1000 jam. Daftar penuh ada di `paper_health_ab9.json` (kunci `stale_lanes`).

## Yang belum bisa dijawab (data kurang)

1. **Menit pasti tiap siklus blackout** — log arm tak ber-timestamp, journal tak merekam stdout arm. Hanya waktu keluar proses yang tersedia; kesamaan menit dengan timer systemd lain **tidak terbukti**.
2. **Sebab blackout** (`no klines (spot+fapi)`) — apakah rate-limit IP bersama (cex-futures-deep-loop, swing-deep-learner, anantara-sentiment dll.) atau gangguan Binance/geoblock, tidak bisa dipisahkan tanpa log ber-timestamp + log sisi Binance.
3. **Throughput trade tertutup nyata** — keempat arm masih 0 trade tertutup, jadi laju keluar (TP vs time-stop) belum bisa diukur; proyeksi memakai asumsi plafon & hold 24 jam.
4. **`btc_regime` untuk 226 entry lama** = `None` (field baru 2026-09-16) — pecahan regime makro per hari sebelum tanggal itu tidak tersedia.
5. **Alasan 9d hanya lewat chop-gate (0 btc-gate)** — jendela 9d baru 0,5 jam; sampel terlalu kecil untuk membandingkan laju gate dengan 9a/9b/9c secara statistik.

---
*Dibuat otomatis pada 2026-11-12 09:36:41 WIB. READ-ONLY terhadap produksi: tidak ada state JSON, unit systemd, atau service yang diubah.*