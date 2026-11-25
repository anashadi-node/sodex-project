# R2 (D11 §9) — PROTOKOL BEKU: adakah sub-populasi dengan MEDIAN window > 0?

**Tanggal:** 10-Okt-2026 · **Izin:** Mas Anas, "approve R2 dari D11" · **Sifat:** read-only, tanpa order/posisi/flag live.
**Runner:** `scripts/research/r2_subpopulasi_median.py` (di-hash bersama berkas ini SEBELUM dijalankan).

## Pertanyaan (falsifiable)
H0: tidak ada sub-populasi (rezim / sesi / simbol / sisi) yang median window 30j-nya > 0 melebihi kebetulan.
H1: ada ≥1 sub-populasi dengan median window > 0 yang bertahan di data yang TIDAK dipakai memilihnya.

## Data & metrik (identik dengan gate resmi)
- `data/paper_test_twoway_state.json` dan `data/paper_test_realwide_state.json` (sudah net biaya + slippage simulator).
- Window 30 jam non-overlap, grid per track dari exit pertama, PnL = Σ pnl_usd / **$242,71**; window kosong = 0
  (definisi `sodex_maturation_tracker.window_metrics`). Median > 0 otomatis menuntut > 50% window positif,
  sehingga sub-populasi jarang-trade tidak bisa lolos lewat window kosong.
- Hit = window ≥ 0,8% wallet (target).

## Desain
1. **Pembagian waktu:** 60% window pertama = DISCOVERY, 40% terakhir = HOLD-OUT. Hold-out tidak dipakai memilih apa pun.
2. **Dimensi (4, tetap, TANPA persilangan):** regime · sesi UTC saat entry (ASIA 00–08 / EU 08–16 / US 16–24) · simbol · sisi.
   Grup eligible = ≥ **30** trade di discovery. 2 track × 4 dimensi = **8 keluarga**.
3. **Statistik per keluarga:** median window discovery tiap grup; statistik keluarga = **MAKSIMUM** antar grup.
4. **Null:** permutasi label grup antar trade (ukuran grup dipertahankan), 5.000 kali, seed 20261010
   → `p_family` = P(maks null ≥ maks teramati). Ini mengontrol seleksi antar-grup di dalam keluarga.
5. **Antar keluarga:** Bonferroni 8 → α = 0,05 / 8 = **0,00625**.

## Kriteria (dibekukan sebelum data per-grup dibuka)
- **Kandidat** = median window discovery > 0 **dan** `p_family` < 0,00625.
- **Lolos hold-out** = median window hold-out > 0 **dan** hit-rate hold-out ≥ 50% (ambang gate resmi) **dan** ≥ 10 window hold-out.
- **R2_POSITIF** = ≥ 1 kandidat lolos hold-out. Selain itu **R2_NEGATIF**.
- Hasil positif BUKAN izin deploy: hanya menaikkan grup itu ke antrean forward (n ≥ 100, kill-rule, sebelum modal apa pun).
- Dilarang setelah melihat hasil: menambah dimensi/persilangan, mengganti MIN_N, memindah titik split, mengganti ambang.

## Pengakuan keterbatasan (ditulis sebelum hasil)
- Hold-out hanya ≈ 11–20 window per track → daya rendah. Hasil negatif berarti "tidak ada bukti", bukan "terbukti tidak ada".
- Simulator paper memodelkan fill dan slippage; fill nyata belum terbukti.
- Cabang B D11 (exit parsial berlapis) butuh jalur harga intra-trade yang TIDAK ada di rekaman ini → bukan bagian protokol ini;
  perlu pra-registrasi terpisah.
- Setiap grup yang diuji dicatat sebagai trial di `sodex_trial_registry.json` (ambang t program naik sesuai).

**Hash beku (sha256 protokol+runner, 16 hex):** `d8d77f9b37755c77` — dicatat di commit SEBELUM run.
