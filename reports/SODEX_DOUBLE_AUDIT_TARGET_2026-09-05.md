# DOUBLE AUDIT — Pencapaian Target 0,7% (Harga Mati)
2026-09-05 | Scope: SoDEX live + 8 paper track + Deep Loop Learning

## RINGKASAN EKSEKUTIF
4 rekomendasi dieksekusi (commit decfeb5, service restart, state
rekonsiliasi, audit). Audit menemukan **3 masalah struktural** yang
menghambat pencapaian target 0,7% — dua di antaranya BARU (belum
pernah teridentifikasi di sesi sebelumnya).

---

## TEMUAN 1 (KRITIS): Live sizing SECARA MATEMATIS tak bisa capai target

Data empiris n=62 REALWIDE paper: avg net **+0,700%** per trade (harga).

| Konfigurasi | notional | wallet ROI/trade | Target 0,7% |
|---|---|---|---|
| Paper (klaim) | $100 @3x | +2,2214% | LULUS |
| **Live sekarang** | **$30 @3x** | **+0,4522%** | **GAGAL (65% target)** |
| Live minimum lulus | $46,44 @3x | +0,7000% | threshold |

Penyebab: denominator ROI = total wallet ($139,37 real), sedangkan
exposure live hanya $90/trade. Paper memakai $300 exposure.

### Kendala keamanan yang menyertai
| notional | margin 2 slot | % wallet perps ($99,30) | worst/trade |
|---|---|---|---|
| $30 (skrg) | $60 | 60,4% | -$1,80 |
| $46,44 | $92,88 | **93,5%** | -$2,79 |
| $60 (maxpos 1) | $60 | 60,4% | -$3,60 |

SESSION_LOSS_CAP saat ini -$2,00 → notional $46,44 memicu cap setelah
1 SL saja. Naikkan notional TANPA menyesuaikan cap = sistem halt terus.

---

## TEMUAN 2 (KRITIS BARU): Degradasi edge tajam 20 trade terakhir

| Periode | WR | avg net |
|---|---|---|
| 20 trade PERTAMA | 65% | +1,27% |
| **20 trade TERAKHIR** | **25%** | **-0,44%** |

Exit 20 terakhir: **14 SL vs 5 TP** (rasio 2,8:1).
Agregat n=62: WR 50,0%, PF 1,79, hit>=0,7% hanya 48,4%.

---

## TEMUAN 3 (KRITIS BARU): Root cause degradasi = TIMING ENTRY, bukan arah pasar

Falsifikasi hipotesis "bear market":
- BTC 7 hari: **+2,92%**, di ATAS SMA50 & SMA200, ADX 36
- SEMUA pair yang rugi justru NAIK 3 hari: ASTER +6,38%, ADA +8,08%,
  BNB +5,40%, SUI +4,61%, ENA +3,55%, AVAX +2,04%, HYPE +1,85%

Bukti timing buruk:
- **64% SL terjadi dalam <6 jam** (9 dari 14)
- Ada SL pada hold **0,0 jam** (ARB) — masuk tepat di lokal top
- avg hold SL = 6,1 jam (vs TIME_STOP 30h)

Kesimpulan: sinyal masuk saat harga sudah extended (lokal top), kena
SL -2% karena pullback normal, lalu tren lanjut naik tanpa posisi.
Ini masalah STRUKTURAL sinyal, bukan kondisi pasar.

### Drag per-pair (20 terakhir)
Rugi: ASTER -5,27% (n=3), ADA -3,12%, BTC -2,19%, HYPE -2,17%,
SUI -2,16%, ENA -2,10%, AVAX -2,10%, BNB -2,10%
Untung: UNI +5,81% (n=4), ARB +4,56% (n=4), AAVE +2,07% (n=2)

---

## TEMUAN 4 (informasi): Denominator wallet usang
- `.env.swing` SODEX_TOTAL_WALLET = $94,57
- Wallet REAL sekarang = **$139,37** (perps $99,30 + spot $40,06)
- ROI dilaporkan terlalu OPTIMIS ~47% karena denominator kekecilan

Catatan: sempat terlihat $300 saat audit, tapi itu artefak shell yang
source `.env` bukan `.env.swing`. Service produksi memuat `.env.swing`
dengan benar ($94,57) — TIDAK ada bug di produksi untuk ini.

---

## STATUS EKSEKUSI 4 REKOMENDASI
1. Commit fix `spot_holdings()` — SELESAI (decfeb5, 13 test pass,
   4 regression test baru untuk semantik absent-coin vs API-failure)
2. Verifikasi posisi BTC $6,38 — SELESAI. Fill terverifikasi di exchange
   (vBTC 0,0000799506). State lokal sempat ter-overwrite race condition
   → ditulis ulang saat service stop. Dry cycle konfirmasi `BTC:HOLD -0,15%`
   → exit engine (TP+2,5%/SL-1,5%/30h) mengelola normal.
3. Restart service kode v2 — SELESAI (spot pid 322709, realwide pid 322710)
4. Double audit — SELESAI (dokumen ini)

## STATUS SISTEM
- 8/8 paper track AKTIF
- Deep Loop Learning AKTIF: swing-deep-learner.timer,
  anantara-paper-learning.timer, hl-deep-learn.timer, paper-learning-watchdog
- Watchdog rekonsiliasi 3 menit AKTIF, sync realtime 2 menit AKTIF
- perps-short live: OFF permanen (file service dipindah .DISABLED)

---

## REKOMENDASI (BUTUH APPROVAL — parameter fundamental)

### A. Perbaiki timing entry (prioritas #1, akar masalah)
Tambah filter anti-extended-entry ke `signal_now()` di
`paper_test_realwide.py` (otomatis ikut ke live karena sudah tersinkron):
- Tolak entry jika harga > X% di atas SMA24 (sudah extended)
- ATAU: wajibkan pullback — entry hanya saat r1 (return 1 jam) negatif
  tapi tren utama masih naik
- Uji di paper dulu, promosi ke live setelah n>=30 OOS

### B. Sizing agar target tercapai secara matematis
Opsi: notional $46-50, maxpos 1, SESSION_LOSS_CAP -$3,50
→ margin $46-50 (47-50% wallet), worst/trade -$2,79 s/d -$3,00

### C. Update denominator wallet
SODEX_TOTAL_WALLET: 94,57 → 139,37 (atau auto-baca dari sync snapshot)
Catatan: ini menaikkan bar target (0,7% dari $139,37 = $0,976/trade
vs $0,662 sebelumnya) — lebih jujur tapi lebih berat.

### D. Blokir ASTER (drag terbesar)
n=3 masih di bawah threshold n>=5, monitor dulu.

