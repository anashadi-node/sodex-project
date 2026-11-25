# KEPUTUSAN 23-10-2026 — Opsi (2) + (3) Disetujui dan Dijalankan

**Pemberi keputusan:** Mas Anas · **Pelaksana:** Hermes Anantara v3
**Bukti pendukung:** `docs/sodex/RCA_SODEX_2026-10-23.md`, `docs/sodex/RCA_OPSI1_MAKER_2026-10-23.md`

---

## 1. Yang diputuskan

| # | Keputusan | Status |
|---|---|---|
| 2 | **Hentikan lebih awal** keluarga mesin sinyal SoDEX (sebelum 25 Nov). Tidak ada arm baru, P31 tidak dijalankan forward, tidak ada modal. | **DIJALANKAN** |
| 3 | **Lanjutkan** akuisisi data L2 sampai 25 Nov (bukan hanya 7 hari). | **DIJALANKAN** |

---

## 2. Koreksi penting atas asumsi keputusan (2)

Keputusan (2) menyiratkan "alihkan ke market-making". **Asumsi itu tidak lolos uji aritmetika**
dan harus dikoreksi sebelum sumber daya dipindahkan:

1. **MM di top-of-book mustahil.** Fee maker 2 × 1,14 = **2,28 bps** per round trip; spread median
   seluruh 10 simbol terukur **0,08–1,03 bps**. Tidak ada satu pun yang lolos ambang.
2. **MM di kedalaman juga tidak layak.** Quote 2–20 bps dari mid, isi ≤15 menit, keluar 30/60 menit:
   **0 dari 15 simbol** menghasilkan nilai positif (rata-rata −5,0 s/d −7,4 bps setelah fee).

**Konsekuensi:** tidak ada jalur market-making di venue ini pada tier fee sekarang. Data L2 tetap
direkam karena biayanya nol dan menjadi bukti bila kondisi berubah — bukan karena MM dianggap
menjanjikan.

---

## 3. Eksekusi keputusan (2) — penutupan keluarga mesin

| Item | Status |
|---|---|
| Arm baru / P31 forward | **Tidak dijalankan.** Tidak ada unit, tidak ada modal, tidak ada order. |
| Modal risiko | **$0** (SoDEX sudah frozen 30-09; `LIQ_DRY=1`) |
| Registry trial | 2 trial ditambahkan (`maker_entry_X0`, `maker_pullback_X20`), keduanya `passed=false` |
| Verdict resmi | Tetap **25 Nov 2026** sebagai tanggal penutupan formal, bukan karena masih ada harapan |
| Give-up | 30 Nov 2026 (tidak berubah) |

**Yang TIDAK diubah:** arm A produksi, konfigurasi daemon, lane apa pun yang sedang berjalan.
Penutupan bersifat **keputusan alokasi** (tidak menambah eksperimen/modal), bukan perubahan kode.

---

## 4. Eksekusi keputusan (3) — kolektor L2 sampai 25 Nov

| Jaminan | Nilai terverifikasi |
|---|---|
| Unit | `sodex-l2-collector.service` (user) |
| Status | `active (running)` sejak 23 Okt 06:03 WIB |
| Restart | `Restart=always` |
| Tahan logout | `loginctl Linger=yes` |
| Cakupan | 10 simbol, orderbook top-20 + trades, siklus 15 detik |
| Rotasi | harian; append-only JSONL |
| Pengaman disk | berhenti sendiri bila free < 5 GB |
| Heartbeat | `data/sodex_l2/_heartbeat.json`, `errors=0` |
| Integritas | 367 snapshot book, **0 pelanggaran bid<ask**; trade monotonik (seed state saat restart) |

**Perkiraan volume sampai 25 Nov:** ±33 hari × 10 simbol × ±5.700 siklus/hari ≈ 1,9 juta snapshot
book + trades. Pada laju sekarang (±1,1 MB/jam) total ±0,9 GB — aman terhadap guard 5 GB.

---

## 5. Syarat yang membuka kembali keputusan

Keputusan ini **boleh** ditinjau ulang hanya bila salah satu terpenuhi (pra-registrasi baru wajib):

1. Fee maker turun/berbalik menjadi rebate sehingga `2×fee < spread` pada ≥3 simbol.
2. Spread median ≥3 bps bertahan ≥7 hari pada ≥3 simbol.
3. Sinyal arah baru dengan gross ≥10 bps terbukti OOS pada n≥100, pra-registrasi terpisah.

Tanpa salah satu di atas, tidak ada eksperimen baru yang dijalankan.

---

## 6. Ringkasan angka yang menjadi dasar

| Metrik | Nilai |
|---|---|
| Gross/trade (populasi tercakup 5m) | **−42,07 bps** |
| Gross/trade (16–22 Okt, 1m) | **−90,80 bps** |
| Biaya tersirat ledger | **6,49 bps RT** |
| Perbaikan eksekusi maksimum terukur (X=20) | **+21,36 bps** → sisa **−20,71 bps** |
| Seleksi terisi vs tidak terisi (X=0) | **111,1 bps** |
| Spread vs fee maker | **0,08–1,03** vs **2,28 bps** |
