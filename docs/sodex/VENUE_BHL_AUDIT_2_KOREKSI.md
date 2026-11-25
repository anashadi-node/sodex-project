# AUDIT-2 — Koreksi Laporan VENUE_BHL_TARGET_FEASIBILITY.md
## Ditemukan oleh audit ganda wajib (25-Okt-2026, pasca-commit 64aba3a)

**Status: AMANDEMEN WAJIB. Laporan induk tetap berlaku untuk semua temuan KUALITATIF
(venue bukan bottleneck, alpha mati pasca-flip, B gagal struktural) tetapi DUA angka
kuncinya salah dan dikoreksi di sini.**

---

## Bug 1 — Periode data salah diklaim (180 hari vs kenyataan 2,7 tahun)

`venue_arithmetic_windows.py::load_all()` memuat SELURUH isi file klines Binance
(**24.276 bar/simbol = Jan-2024 → Okt-2026**), bukan 180 hari seperti ditulis.
Klaim "482 window ≈ 180 hari" salah: 482 bucket mencakup 2,7 tahun, termasuk
**2.109 trade (61%) pra-angkor 03-Agu-2026** (k<0) yang ikut masuk rata-rata.

**Dampak:** angka "+1,375%/window (maker)" adalah campuran era 2024-2026, bukan
estimasi kondisi sekarang.

## Bug 2 — Dominasi simbol tunggal tidak diperiksa

1000BONK: n=335, total +16.346 bps ≈ 29% dari gross agregat. Laporan induk tidak
menjalankan uji sensitivitas leave-one-out.

---

## Angka terkoreksi (POST-ANGKOR saja, k≥0, 64 window, 1.367 trade)

| Skenario (donchian, path Binance) | n_win | mean/window | median | hit | A | B |
|---|---|---|---|---|---|---|
| maker size=1,0 semua simbol | 64 | +7,551% | −2,167% | 34,4% | ✓* | ✗ |
| maker size=1,0 TANPA 1000BONK | 64 | +7,197% | −2,167% | 35,9% | ✓* | ✗ |
| **maker EQUAL-WEIGHT per simbol** | 52 sym | **+0,689%** | — | — | **✗** | ✗ |
| taker size=1,0 post-angkor | 64 | +4,958% | −3,242% | 32,8% | ✓* | ✗ |
| maker, era berjalan (post-flip 25-Sep) | 23 | **−2,936%** | −2,644% | **17,4%** | ✗ | ✗ |

\* A "lolos" hanya pada agregasi cap-weighted yang mean-nya didorong ekor kanan
(window volatilitas ekstrem Agu–Okt-2026). Median negatif dan hit 34% di semua varian.

## Verdict terkoreksi (lebih TEGAS dari laporan induk)

1. **Equal-weight — agregasi paling jujur untuk "bisa dilakukan dengan sizing tetap
   per simbol" — memberi 0,689% < 0,8%. Syarat A GAGAL juga**, bukan hanya B.
2. Tidak ada skenario manapun yang memenuhi A∧B, bahkan in-sample, bahkan maker,
   bahkan di Binance/HL.
3. Era berjalan (post-flip): −2,94%/window, hit 17,4% — semua kriteria gagal.
4. Temuan yang TETAP SAHIH dari laporan induk: biaya venue 2,6–3,6 bps (bukan
   bottleneck); flip 25-Sep terdeteksi di path Binance; donchian = satu-satunya
   edge di atas kontrol acak; momentum/twoway kalah dari acak.

## Konsekuensi ke PRAREG-32

Protokol (lihat `reports/sodex/PRAREG32_MAKER_PROTOCOL.json`) mewajibkan:
- **A dinilai pada EQUAL-WEIGHT** (bukan cap-weighted) — anti-tail-dominance.
- Uji sensitivitas leave-one-out simbol terbesar wajib dilaporkan.
- Adverse selection maker diukur eksplisit: margin A = 13,4 bps/trade → AS > 13,4 bps = gagal otomatis.
- t ≥ 2,5 pada net per trade; kill-switch DD kumulatif > 5% wallet.

## Laporan verifikasi audit

- Metode: re-derive dari artefak committed + cek silang rentang timestamp entry
  (2024-01-10 → 2026-10-25) vs klaim 180 hari; cluster-bootstrap day-level
  (CI95 −55,6..−27,4 bps/hari, TIDAK memuat 0 — konsisten dengan net negatif
  full-history-pre-flip yang terekspos rezim 2024-2025 sebagian); sign-test
  WR 38,1% vs 0,5 → z=−13,98.
- Root cause: `load_all()` tanpa filter tanggal + tidak ada leave-one-out di
  pipeline awal. Fix dicatat: evaluator PRAREG-32 memfilter bar > freeze_ts dan
  mewajibkan equal-weight.
