---
name: prareg-23b-mode-a-5jam
description: PRAREG-23b — pra-registrasi dibekukan: Mode A spot (Donchian-ensemble BTC/ETH/XAUT) uji paper-forward 31 hari, target 0,01%/5 jam.
metadata:
  type: project
---

# PRAREG-23b — MODE A SPOT, PAPER-FORWARD, TARGET 0,01% / 5 JAM

**Status: DIBEKUKAN SEBELUM DATA FORWARD DIEVALUASI.** Tidak ada ambang di bawah yang boleh diubah setelah hasil terlihat.
Gagal → dicatat gagal, tanpa penyelamatan post-hoc.

- Tanggal beku: **26-Okt-2026 (UTC)** · Inisiatif & persetujuan: **user (Mas Anas)**, "approve keputusan 1, 2 & 3 … approve tulis PRAREG-23b".
- Jenis: **paper-forward, DRY-RUN.** Tidak ada order, tidak ada kredensial, modal berisiko **$0**. `dry_run` tidak diubah.
- Hubungan: lanjutan **PRAREG-23 H1** (Donchian-ensemble, GAGAL gerbang d & e pada 09-Okt-2026, `PRAREG_23_HASIL_PENUTUPAN.md`).
  23b **bukan** penyelamatan 23 H1: H1 gagal di dua gerbang yang tidak diubah di sini; 23b menguji hal lain (kualitas implementasi + perilaku forward).
- Tidak menggantikan target 0,8%/30 jam PRAREG-26/31 (AMANDEMEN_TARGET_AB). Itu butuh amandemen terpisah bila user ingin.

## 0. Keputusan user yang dicatat

| # | Keputusan | Isi yang dibekukan |
|---|---|---|
| 1 | Target | **0,01% per 5 jam** dipertahankan sebagai target arm ini, dengan peluang historis tercatat di §2 (bukan jaminan). |
| 2 | Mode B1/B2 | Paper-forward bersama Mode A. **Tidak punya jalur live dari dokumen ini.** |
| 3 | Commit | Boleh, setelah tes bersih dan Pre-Deploy Review. |

Definisi target: **M = rata-rata return harian bersih × 5/24 × 100 (%)**. Target M ≥ 0,010.

## 1. Spesifikasi (beku)

- Universe: BTC, ETH (Binance `BTCUSDT`, `ETHUSDT` 1d), XAUT (`XAUTUSDT`; riwayat sebelum 24-Mei-2026 dari Coin Metrics, disambung rantai-return).
- **Sumber data dibekukan di Binance** (hasil Mode A sensitif pada sumber: Binance → bobot BTC 7,4%/ETH 6,9%; Coin Metrics → semua 0% pada 24-Okt).
- Sinyal: Donchian-ensemble 9 lookback (5,10,20,30,60,90,150,250,360), long-only spot, tanpa leverage, vol-target 0,50, band 20%.
- Eksekusi paper: bobot diputuskan di penutupan hari *d*, dieksekusi di penutupan *d+1* (lag 1). Biaya primer **0,10%/sisi**; sensitivitas 0,25%/sisi.
- Arm: **A** (dibekukan dokumen 26-Okt), **B1** (sisa kas → XAUT), **B2** (sisa kas × sinyal XAUT). B1/B2 dipilih **setelah** melihat data (post-hoc).
- Jendela: target pertama asof 25-Okt (dieksekusi 26-Okt); **31 hari-return 26-Okt s.d. 25-Nov-2026**; evaluasi **26-Nov-2026**.
- Kode: `scripts/research/mode_a_20261026/` — `mode_a_engine.py`, `paper_forward.py`, `bt_indep.py`. Hash di registry.
- Gagal data (`DataError`) → **tidak ada target**, dicatat sebagai kejadian `GAGAL_DATA`; tidak ada tebakan.

## 2. Bukti historis yang melandasi (in-sample, BUKAN bukti edge)

Replikasi dokumen 26-Okt: persis (0,0157 / Sh 1,33 / MDD −21,1; sejak 2022 0,0055 / 0,65 / −13,0). Biaya 0,10%/sisi, sejak 2022:

| Arm | M (%/5j) | SD harian | MDD | P(tahun ≥ 0,010) | P(tahun < 0) | Median hasil 31 hari | P(31 hari < 0) |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 0,0061 | 0,76% | −14% | 32% | 23% | −0,3% | 54% |
| B2 | 0,0091 | 0,92% | −20% | 46% | 14% | +0,3% | 48% |
| B1 | 0,0118 | 1,13% | −27% | 59% | 13% | +1,4% | 39% |

- **Target 0,010 tidak tercapai oleh A pada rata-rata historis** (0,0061); peluang satu tahun kalender memenuhinya ≈32%.
- B1/B2 mendekati target hanya lewat eksposur emas (B1 rata-rata ±79% XAUT); tanpa 2025 (emas +65%) B1 turun ke 0,0091. Selisih B2−A: z≈2,3 ≪ ambang registry |t|≥4,11.
- Hasil Mei–Okt 2026 (di luar dokumen, forward semu): A +0,0011 (t=0,11).

## 3. Daya statistik — dinyatakan sebelum data

CI95 setengah-lebar M untuk 31 hari: **±0,056 %/5j (A)** ≈ 5,6× target. Untuk |t| ≥ 4,11 pada M historis A dibutuhkan ≈ **11.500 hari (±31 tahun)**.
Konsekuensi (beku): **jendela 31 hari TIDAK dapat membuktikan maupun menyangkal target 0,01%/5 jam.** Ia menguji implementasi, kepatuhan data, dan batas kerugian. Klaim "target tercapai/terbukti" **dilarang** dari 23b; boleh hanya "tidak terfalsifikasi di jendela ini".

## 4. Gerbang (semua wajib untuk arm A; B1/B2 hanya dilaporkan)

| # | Gerbang | Kriteria |
|---|---|---|
| G1 | Kelengkapan | tanpa tanggal bolong di ledger; backfill ≤ 3 hari; hari `GAGAL_DATA` ≤ 2 |
| G2 | Kebenaran | target di ledger == hitung ulang engine dari riwayat tercatat (selisih 0 pada 1e-12) |
| G3 | Risiko | MDD paper A ≥ **−10%** (historis: 0% jendela 31 hari melanggar → tripwire anomali) |
| G4 | Pembatas kerugian | hasil kumulatif bersih A ≥ **−5,0%** (historis P(gagal) ≈ 2%) |

G3/G4 adalah **pembatas kerugian, bukan uji edge**. Target 0,010 dilaporkan dengan CI95 tetapi **bukan gerbang**.

Vonis: semua G lulus → **"LAYAK DIPERTIMBANGKAN"** — tetap **butuh keputusan GO eksplisit user**; ukuran live diusulkan ≤25% modal, ditetapkan user saat GO. Ada yang gagal → **NO-GO**, tanpa perubahan ambang. Evaluasi diselesaikan sebelum give-up 30-Nov-2026; live paling cepat 01-Des-2026 dan **tidak bergantung** pada verdict PRAREG-26.

## 5. Pengungkapan percobaan (multiple testing)

Keluarga Donchian: PRAREG-23 H1 (gagal) + varian robustness sesi ini (biaya ×4, lag ×3, band ×2, VT ×2) + B1 + B2 = ≥ 11 sel yang dilihat. B1/B2 dipilih post-hoc. Tidak ada koreksi p yang dapat menyelamatkan klaim edge pada n ini; itu sebabnya §3 melarang klaim.

## 6. Batasan yang diketahui

- Likuiditas spot SoDEX tipis (volume 24 jam BTC ≈ $4k, ETH ≈ $3,5k, XAUT ≈ $1,7k): slippage live belum diuji; engine hanya merencanakan order dry-run.
- XAUT disambung dua sumber (korelasi return overlap 0,995).
- Kualitas hasil sangat bergantung pada rezim tren; 2022 −12,5%, 2026 YTD −3,8%.
- Eksekusi live di SoDEX belum pernah diuji.

## 7. Prosedur operasional

`paper_forward.py record forward/` harian 00:30 UTC (timer user); `paper_forward.py eval forward/` untuk vonis. Ledger append-only `forward/ledger.jsonl`.
