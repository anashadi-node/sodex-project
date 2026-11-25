# RUNBOOK GO-LIVE 01-DES-2026 — Mode A spot SoDEX (arm A)

Dibuat 26-Okt-2026 · keputusan user: **siap live 01-Des-2026 bagaimanapun hasil paper**.
Status default: **DRY-RUN**. Tidak ada order yang bisa terkirim sampai user sendiri menyelesaikan langkah 5–6.

## 0. Apa arti "siap" di sini

| Sudah dikerjakan agen (otomatis, teruji) | Hanya bisa dikerjakan user (kredensial & dana) |
|---|---|
| Engine sinyal v2 + 61 tes | Membuat kunci API SoDEX khusus bot |
| Paper-forward harian + paper-eksekusi di buku nyata SoDEX | Mengisi `secrets/sodex.env` (chmod 600) |
| Kolektor buku spot tiap 30 mnt | Menjalankan selftest TESTNET |
| Eksekutor live `mode_a_live.py` (terkunci, 23 tes) | Menyetor USDC ke akun spot |
| `preflight.py` (14 cek) + timer live (belum aktif) | Menandatangani `LIVE_ARMED.json` + `CONFIRM_LIVE=YES` |

Agen **tidak** mengetik/menyimpan kunci pribadi dan **tidak** membalik apa pun ke live. Itu Red Line + Prinsip #1 (keamanan).

## 1. Garis waktu

| Tanggal | Kegiatan | Penanggung jawab |
|---|---|---|
| 26-Okt → 25-Nov | Paper-forward 31 hari berjalan otomatis (record 00:30 UTC, paper-exec, buku tiap 30 mnt) | otomatis |
| ≤ 05-Nov | Langkah 2 (buat kunci) + 3 (sodex.env) | **user** |
| ≤ 10-Nov | Langkah 4 (selftest testnet) | **user** + agen baca hasil |
| 26-Nov | Evaluasi PRAREG-23b: `paper_forward.py eval forward` + `paper_exec.py report forward` | agen |
| 27–29-Nov | Gladi bersih: `preflight.py` tiap hari; perbaiki FAIL | agen |
| 30-Nov | Langkah 5: user menandatangani `LIVE_ARMED.json` | **user** |
| 01-Des 00:50 UTC (07:50 WIB) | Langkah 6: live pertama (target asof 30-Nov) | **user** aktifkan timer |

## 2. Buat kunci API khusus bot (user)

- Akun/dompet **terpisah** yang hanya berisi modal yang rela dipertaruhkan (usulan: ≤ $243).
- Izin **trade saja**; **tanpa withdraw** bila SoDEX mendukung pembatasan itu.
- Jangan pakai kunci yang pernah terpublikasi (rotasi kredensial lama masih PENDING — `docs/sodex/ROTASI_KREDENSIAL`).

## 3. `secrets/sodex.env` (user, ketik sendiri)

```
cp secrets/sodex.env.template secrets/sodex.env && chmod 600 secrets/sodex.env
# isi SODEX_PRIVATE_KEY, SODEX_ACCOUNT_ID, SODEX_ADDRESS  (SODEX_API_KEY tidak diteruskan ke order spot)
```
File di-gitignore. Eksekutor menolak jalan bila mode ≠ 600.

## 4. Selftest TESTNET (user; wajib sebelum live)

```
cd ~/anantara-sakti/scripts/research/mode_a_20261026
SODEX_TESTNET=1 .venv/bin/python mode_a_live.py selftest
```
Memverifikasi: tanda-tangan, parsing saldo, place order. Order uji (limit 50% di bawah pasar) **dibatalkan manual** (perintah dicetak).
Jika sukses: `echo '{"ok":true,"utc":"'$(date -u +%FT%TZ)'"}' > forward/selftest_testnet_ok.json`.
**Jika gagal, live tidak boleh jalan** — format respons CLI belum pernah divalidasi dengan kunci nyata (celah terbesar).

## 5. Tanda tangan GO (user, 30-Nov)

```
cp docs/sodex/LIVE_ARMED.template.json secrets/LIVE_ARMED.json
sha256sum scripts/research/mode_a_20261026/mode_a_engine.py      # tempel ke engine_sha256
# edit: armed=true, go_utc, batas $, acknowledge_prareg23b_verdict=true
```
- `acknowledge_prareg23b_verdict=true` = Anda sudah membaca verdict (NO-GO/LAYAK/BERJALAN) dan **tetap memilih live**. Itu mekanisme untuk keputusan "bagaimanapun hasilnya": sah, tapi tercatat atas nama Anda.
- Usulan batas awal: `max_equity_usd 300`, `max_order_usd 60`, `max_total_buy_usd 120`.
- Mengubah `mode_a_engine.py` setelah ini = hash tak cocok = live otomatis terblokir (harus tanda tangan ulang).

## 6. Aktifkan 01-Des (user)

```
cd ~/anantara-sakti && cp systemd/sodex-modea-live.* ~/.config/systemd/user/ && systemctl --user daemon-reload
systemctl --user edit sodex-modea-live.service     # tambah: [Service]  Environment=CONFIRM_LIVE=YES
cd scripts/research/mode_a_20261026 && .venv/bin/python -W ignore preflight.py   # harus 0 FAIL; WAIT hanya yang belum Anda selesaikan
cd ~/anantara-sakti
systemctl --user enable --now sodex-modea-live.timer
```

## 7. Pengaman yang aktif saat live

| Pengaman | Perilaku |
|---|---|
| 9 gerbang `check_arm` | satu gagal → BLOK, tanpa order |
| `secrets/KILL` | `touch secrets/KILL` → semua run berhenti seketika |
| Cap ekuitas / per-order / total-beli | melebihi → BLOK (tidak diskalakan diam-diam) |
| Limit-IOC + batas slip 30 bps | tak pernah market; sisa tak terisi dibatalkan venue |
| Target ≤ 1 hari, bukan backfill | data basi → tanpa order |
| Idempoten per asof | tak mengirim ulang; `intent` tanpa `result` → rekonsiliasi MANUAL |
| Order gagal | berhenti di kegagalan pertama, **tanpa retry** (status tak pasti) |
| Tanpa short, tanpa leverage, jual ≤ saldo, beli ≤ USDC, ≥ minNotional $5 | dijamin planner (teruji) |

Log: `logs/modea_live.log`, `forward/live_exec.jsonl` (append-only).

## 8. Ekspektasi jujur (dari suite paper, `reports/sodex/PRAREG23B_PAPER_SUITE_2026-10-26.md`)

- Arm A: M ≈ 0,006 %/5 jam (2022+) → **di bawah target 0,010**; ≈ +0,9%/bulan ≈ $2 pada $243 bila rata-rata historis bertahan.
- Median hasil 31 hari −0,3%; P(hasil 31 hari < 0) = 54%; P(tahun rugi) ≈ 24%; MDD historis −13,8%; hari terburuk −4,6%.
- Timing sinyal belum signifikan vs acak (p=0,10).
- Live pertama = **uji eksekusi nyata**, bukan bukti edge.

## 9. Prosedur darurat

1. `touch secrets/KILL` (berhenti). 2. `systemctl --user disable --now sodex-modea-live.timer`.
3. Cek saldo: `bin/sodex balance spot`. 4. Bandingkan dengan `forward/live_exec.jsonl`. 5. Posisi dilepas manual atau tunggu target berikutnya.
