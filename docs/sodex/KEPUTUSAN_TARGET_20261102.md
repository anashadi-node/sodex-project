# KEPUTUSAN RESMI USER — 02-Nov-2026 (± 07:50 WIB)

## 1. Keputusan (verbatim approve user)

> "Approve C dan Target untuk Experiment/Live Awal jika hasil nya bagus maka yang
> menjadi Target Utama adalah target Experiment/Live awal, tolong catat dan ingat
> baik-baik, tolong juga report dan jaga agar Experiment selalu aktive berjalan dan
> berkesinambungan sampai 01 Desember 2026 dan sudah harus siap real live trading di
> sodex.com pada 01 Desember 2026"

Terjemahan resmi (terverifikasi silang dengan dokumen sumber):

1. **Butir C — pembedaan dua target CEX**: 0,7% = gate awal protokol GATE_33_HARI
   (pre-registered 6-Sep, modal $400); 0,8% = target North Star operasional unit
   paper CEX (SOUL §3, Description unit). Keduanya sah di lapisan berbeda.
2. **Target Utama bersyarat**: bila hasil eksperimen/live awal 01-Des **bagus**
   (memenuhi gate), maka target Experiment/Live Awal — yaitu **0,010%/5 jam**
   (Mode A arm A, spot 1×) — **naik menjadi Target Utama**. Sambil bersyarat,
   **North Star 0,8%/window 30j tetap target akhir jangka panjang dan tetap
   berdampingan** dengan target operasional live (Amandemen Tangga 22-Okt §2.4
   tetap berlaku; 0,8% tidak dicabut, tidak diturunkan statusnya).

### 1a. Definisi operasional "hasil bagus" — REV2 KUMULATIF (dikunci 02-Nov-2026 09:35 WIB)

Keputusan Mas Anas (klarifikasi 09:20 WIB + koreksi 09:35 WIB: **"kumulatif"**):

| Parameter | Nilai mengikat |
|---|---|
| Kriteria hasil | **M kumulatif ≥ 0,010% / 5 jam atas window 30 hari berturut-turut** |
| Risiko | **MDD window tersebut tidak lebih buruk dari −15%** |
| Efek | bila terpenuhi → target live awal (0,010%/5j) **naik menjadi Target Utama** |

Aturan hitung (dibekukan; tidak boleh diubah setelah verdict 25-Nov-2026):

1. Window = **30 hari kalender UTC berturut-turut** (720 jam). Window dengan hari
   hilang **tidak sah** — tidak diinterpolasi, tidak dikompensasi.
2. `M_kum` = mean return **per bucket 5 jam** atas seluruh window
   = `total return window ÷ 144 bucket`, **net** setelah fee + spread +
   slippage + funding.
3. **Gate A**: `M_kum ≥ 0,010%/5j` (ekuivalen ≥ **0,060% / 30 jam** kumulatif).
4. **Gate B**: **MDD** kurva ekuitas dalam window yang sama **≥ −15%**
   (drawdown dari puncak berjalan).
5. Promosi sah hanya bila **A DAN B** terpenuhi pada data **live** (bukan
   paper/simulasi), lalu dikonfirmasi ulang pada window berikutnya sebelum
   status Target Utama dipakai untuk menaikkan risiko.
6. Evaluasi **rolling**: window bergerak harian; window pertama yang lolos
   dicatat sebagai tanggal pemenuhan gate (bukti permanen).
7. Sebelum gate lolos: 0,010%/5j berstatus **target eksperimen**, BUKAN Target
   Utama; 0,8%/window 30j tetap target akhir yang berdampingan.

**Status 02-Nov-2026:** window 30 hari belum lengkap (live dimulai 01-Des) →
`DATA KURANG`. Window live pertama yang bisa dinilai: **31-Des-2026**.

**Implementasi gate (bukan prosa):** `scripts/sodex_target_promotion_gate.py`
— read-only, `--equity-file <jsonl {ts,equity}>` atau `--ledger-file <jsonl {ts,net_pct}>`;
exit `0`=PASS, `1`=FAIL, `3`=DATA_KURANG, `2`=error input. Regresi:
`tests/test_sodex_target_promotion_gate.py` (8 test, termasuk hari-hilang dan MDD breach).
Alasan koreksi: pembacaan harian-per-hari terlalu ketat (noise harian besar) dan
tidak sesuai maksud "akumulasi 30 hari"; koreksi dilakukan **sebelum** data live
berjalan, sehingga tidak melanggar aturan anti p-hacking.

### 1b. Kontinuitas & kesiapan

3. **Kontinuitas**: eksperimen (semua lane paper forward) wajib aktif, berjalan,
   dan berkesinambungan sampai 01-Des-2026.
4. **Kesiapan**: sistem wajib SIAP untuk real live trading di sodex.com pada
   **01-Des-2026** — kesiapan diukur syarat GO (§3 di bawah), bukan tanggal saja.

## 2. Kewajiban agen (dicatat permanen)

- Menjaga 11 timer lane eksperimen aktif; restart/lapor bila ada yang mati.
- Melaporkan status harian (cron `sodex-experiment-continuity`).
- Tidak mengubah target/gate tanpa approval eksplisit Mas Anas.
- Penuhi garis waktu persiapan live (§4).

## 3. Syarat SIAP LIVE 01-Des (dari LIVE_01DES_KEPUTUSAN.md — tidak berubah)

1. `preflight.py` → 0 FAIL.
2. Selftest TESTNET sukses (dilakukan USER).
3. PRAREG-23b/36 bukan `DATA_INVALID`; 0 error eksekusi paper.
4. `LIVE_ARMED.json` ditandatangani USER (hash engine cocok).
5. `CONFIRM_LIVE=YES` ditambahkan USER.

## 4. Garis waktu persiapan (kewajiban)

| Tanggal | Tugas | Pelaku |
|---|---|---|
| ≤ 05-Nov | Akun/kunci khusus bot + `secrets/sodex.env` (chmod 600) | USER |
| ≤ 10-Nov | Selftest TESTNET | USER |
| 25-Nov | Verdict PRAREG-36 | AGEN |
| 26-Nov | Evaluasi PRAREG-23b | AGEN |
| 27–29-Nov | Preflight harian, perbaiki FAIL | AGEN |
| 30-Nov | Tanda tangan `LIVE_ARMED.json` | USER |
| 01-Des 07:50 WIB | Aktivasi live | USER |

## 5. Status ketergantungan saat dokumen ini dibuat (02-Nov ± 07:50 WIB)

- `secrets/sodex.env` BELUM ADA (hanya .template) → **blocker #1, tugas USER, deadline 05-Nov**.
- Verifikasi timer: 11/11 timer aktif (`sodex-prereg23b-record`, `sodex-prereg26-mesin`,
  `sodex-prereg32-eval`, `sodex-hybrid36-record`, `anantara-reflect-overlay`,
  `anantara-prereg41-universe`, `anantara-prereg42-nightshort`, `sodex-paper-arena`,
  `sodex-klines-forward`, `anantara-sodex-realsync`, `sodex-monitor-eval`).
- PRAREG-36 ledger: 8 rec (harus ≥29 pada 25-Nov; track berjalan).
- Status gate hari ini: semua NO-GO / DATA_INVALID (<60) — normal untuk awal jendela.
