# RCA — Monitor Pemulihan SoDEX "GAGAL" (unit systemd failed)

**Tanggal:** 2026-10-06 · **Lingkup:** SODEX · **Sifat:** READ-ONLY (tanpa perubahan gate/leverage/sizing/target)
**Objek:** `anantara-sodex-recovery-monitor.service` — `scripts/sodex_recovery_monitor.py`

---

## 1. Gejala

`systemctl --user list-units` menampilkan unit berstatus **`failed`**. Journal sejak 1 Okt mencatat
**18 baris ALERT/WARNING**, terakhir:

```
2026-10-04 12:15  ALERT | ... issues=1
2026-10-04 18:15  ALERT | ... issues=1
2026-10-05 00:15  ALERT | ... issues=1
2026-10-05 06:17  ALERT | ... issues=1
2026-10-05 12:15  ALERT | ... issues=1
2026-10-05 18:15  ALERT | ... issues=1
2026-10-06 00:15  NORMAL | ... issues=0   <- hilang sendiri
2026-10-06 06:15  NORMAL | ... issues=0
```

Perhatikan: **teks isu tidak pernah tercatat** — journal hanya memuat `issues=1`.

**Penyebab hilangnya ALERT (baru diketahui belakangan):** commit `c309e3c` (5 Okt 23:36 WIB)
memperbaiki **false-positive** pada `chop_gate_violations()` — detektor lama menandai LONG
dengan `regime != {BULL, UNKNOWN}`, sehingga ikut menghitung arm `RANDOM_CONTROL` (kontrol
negatif, memang tidak di-gate oleh desain) dan `btc_regime=None` (fail-open terdokumentasi).
Isu 4–5 Okt = `CHOP gate violations: 9` (8 RANDOM + 1 SIGNAL/None) → **alarm palsu**.
Run berikutnya (6 Okt 00:15) → NORMAL. Timeline cocok persis.

## 2. Diagnosis — tiga cacat, bukan satu

### D1 · Exit code mengaburkan *temuan* menjadi *kegagalan proses*
```python
return 0 if payload["verdict"] == "NORMAL" else 1     # baris 428 (lama)
```
Unit ini `Type=oneshot`. systemd membaca exit 1 = **proses gagal**, padahal artinya
"monitor berhasil jalan dan menemukan sesuatu".

**Mengapa ini serius (bukan kosmetik):** monitor yang **crash** (mis. impor rusak, berkas tak
terbaca) juga keluar dengan exit 1 dan **tampak identik** dengan temuan yang diharapkan.
Pada monitor pemulihan, artinya: *mati diam-diam menyamar sebagai laporan normal*. Status unit
tidak lagi bisa dipercaya sebagai sinyal apa pun.

### D2 · Tidak ada kanal notifikasi
`grep -cE "telegram|urllib|requests"` = **0**. ALERT bertahan **30 jam** (4 Okt 12:15 → 5 Okt 18:15)
hanya di journal yang tidak ada yang membaca.

### D3 · Tidak ada riwayat — temuan menjadi tak dapat diaudit
- Laporan `SODEX_RECOVERY_MONITOR_LATEST.{md,json}` **ditimpa** tiap 6 jam.
- Journal hanya mencatat `issues=1`, **tanpa teks isu** → tidak ada jejak apa yang ditandai.
- Berkas state paper juga **dipangkas** (REALWIDE menyimpan 255 trade tertutup, TWOWAY 396;
  `filter_since` hanya melihat 123/171) → kalaupun pelanggaran **nyata** terjadi, rinciannya
  bisa lenyap sebelum sempat diperiksa.

**Bukti bahwa cacat ini nyata:** saat menyelidiki, saya **tidak dapat menentukan** dari catatan
apakah ALERT 4–5 Okt itu pelanggaran nyata atau alarm palsu. Atribusi pertama saya
("pelanggaran terpangkas dari state") ternyata **SALAH** — jawabannya baru diketahui dari commit
lain (`c309e3c`) yang memperbaiki false-positive detektor. Jadi:

- **Penyebab ALERT 4–5 Okt:** false positive detektor (bukan pelanggaran nyata).
- **Penyebab hilangnya ALERT:** perbaikan detektor 5 Okt 23:36, **bukan** pemangkasan state.
- **Yang tidak bisa dilakukan tanpa riwayat:** membedakan keduanya dari catatan monitor sendiri.

Kesimpulan: **alarm palsu membunyikan unit `failed` selama ~30 jam**, tidak ada yang diberi tahu,
dan bukti yang diperlukan untuk mendiagnosisnya tidak tersedia. Itulah kombinasi D1+D2+D3 —
bukan tiga cacat terpisah, melainkan satu kegagalan sistemik: monitor yang temuan dan
kesehatannya sendiri tidak dapat dibedakan maupun diaudit.

## 3. Perbaikan

| # | Perbaikan | Bukti |
|---|---|---|
| P1 | **Kontrak exit code dipisah**: `0` = monitor berhasil jalan (putusan apa pun); `1` = monitor **rusak**. `--strict` mengembalikan perilaku lama sebagai opt-in. | unit via systemd: `Result=success`, `ExecMainStatus=0` |
| P2 | **Notifikasi Telegram** saat ada temuan, dengan **dedupe** (tanda-tangan temuan berubah, atau temuan sama bertahan >12 jam → ingatkan ulang). | uji kirim nyata: **BERHASIL** |
| P3 | **Riwayat append-only** `reports/sodex/RECOVERY_MONITOR_HISTORY.jsonl` + snapshot rincian pelanggaran ke `reports/sodex/recovery_violations/` — bertahan walau state dipangkas. | 3 baris tercatat |
| P4 | **Teks isu dicetak ke journal** (`ISSUE: ...`) — sebelumnya hanya `issues=N`. | tampak di log |
| P5 | 4 test baru: exit 0 saat temuan · exit 1 hanya saat crash · riwayat menyimpan rincian · dedupe notifikasi. | 11 test lulus |

**Uji regresi penuh: 1426 lulus, 36 dilewati, 0 gagal.**

## 4. Yang TIDAK diubah

Gate T1 · leverage · sizing · target 0,8%/48 jam · `SODEX_TOTAL_WALLET` · arm A1 ·
`RW_MARGIN_UTIL_CAP` · jadwal timer (tetap 6 jam). Monitor tetap **READ-ONLY** — tidak ada
jalur order/sign/withdraw (diverifikasi dengan grep).

## 5. Pelajaran yang dipakai ulang

1. **Jangan pakai exit code untuk menyampaikan temuan.** systemd hanya boleh melihat
   "proses hidup/mati"; temuan disampaikan lewat notifikasi + riwayat.
2. **Monitor wajib punya riwayat append-only** bila sistem yang dipantau memangkas datanya —
   jika tidak, bukti hilang tepat saat paling dibutuhkan.
3. **Monitor tanpa kanal notifikasi = bukan monitor**, hanya berkas yang menua.
