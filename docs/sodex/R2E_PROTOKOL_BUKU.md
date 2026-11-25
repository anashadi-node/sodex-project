# R2E — PROTOKOL BEKU: UJI BUKU (BENTUK/VARIANS DISTRIBUSI)

**Dibekukan:** 10-Okt-2026, SEBELUM runner dijalankan / hasil dilihat
**Sifat:** read-only. TANPA order, TANPA posisi, TANPA flag live.
**Konteks:** lever capture-exit (R2B/R2C) TERTUTUP; lever biaya (R2D) TERTUTUP secara aritmetika (hadiah maksimum +0,195 pp = 12% kebutuhan). Satu-satunya keluarga lever yang belum diuji = bentuk/varians distribusi. Constraint terukur: TWO-WAY mean +1,467%/window vs median −1,771%/window (lotere).

## Hipotesis (falsifiable)

**H1:** Buku (portofolio) dari komponen track yang ada dapat menaikkan **median** window 30 jam di atas 0 — karena rata-rata lintas komponen meredam ekor kiri per-komponen — dan mencapai hit ≥50% pada ambang 0,8%.
**H0 (null):** Median buku ≤ 0. Artinya korelasi antar komponen cukup tinggi (majors ~0,7) sehingga diversifikasi tidak mengubah bentuk distribusi; lever bentuk-varians ikut mati untuk gate median.

## Data (beku)

Sumber: `data/paper_test_*_state.json`, hanya berkas dengan list transaksi `closed`/`closed_trades` dan pengukuran `pnl_usd` + `exit_ts`/`exit_time`.
**Kandidat terdaftar (8):** swing(539), twoway(422), realwide(269), spot_swing_v2(232), aster(221), donchian(221), hyperliquid(191), pasar_anantara_trade(47).
**Aturan inklusi (mekanis, beku):** (a) buang baris dengan `track`/`conviction` = `RANDOM` (kontrol negatif, bukan kandidat); (b) inklusi track bila punya **≥20 window** dengan aktivitas di grid evaluasi; (c) `pasar_anantara_trade` dikecualikan karena <20 window.
Wallet acuan: **$242,79** (sama dengan R2B/R2D) untuk semua komponen.

## Metrik (beku, = metrik gate resmi)

Window 30 jam. ROI window% = 100 × Σ`pnl_usd` dalam window / wallet.
Buku: ROI_window(buku) = 100/wallet × Σ_i w_i · pnl_usd_i(window), Σ w_i = 1 (100% wallet dibagi antar komponen; tanpa leverage).

**Grid primer:** grid kalender 30 jam berjangkar **2026-08-03 00:00Z** (sebelum semua track mulai). Komponen tak aktif di window = kontribusi 0; window dievaluasi hanya bila ≥2 komponen aktif.
**Grid sekunder (robustness):** grid resmi (t0 = exit_ts pertama, bucket 30 jam) pada irisan window yang tersedia.

## Buku yang diuji (beku, 3 varian + 1 kontrol)

1. **EW** — equal weight pada semua track yang lolos inklusi (tanpa fitting).
2. **MV** — w ∝ Σ⁻¹α, α = mean window return per komponen, Σ = kovarians window return; shrinkage λ=0,5 (Σ_s = (1−λ)Σ + λ·diag(Σ)); **tanpa short** (w ≥ 0); cap 40% per komponen; dinormalisasi Σw=1.
3. **TOP2** — hanya 2 komponen dengan mean window tertinggi (dipilih **per walk-forward**, bukan ex-post).
4. **KONTROL batas-atas diversifikasi** — EW dari komponen dengan korelasi silang DIHANCURKAN (permutasi independen per komponen, 500 iterasi, seed tetap 20261010). Ini batas atas matematis: berapa median buku bila korelasi = 0. Jika batas atas ini pun ≤ 0, lever buku mati tanpa syarat.

## Walk-forward (beku — anti look-ahead)

Minimum **12 window latihan** (expanding). Bobot untuk window t diestimasi HANYA dari window < t. EW tidak butuh latihan tetapi dievaluasi pada himpunan OOS yang sama agar sebanding.
OOS = window ke-13 dan seterusnya pada grid primer.

## Kriteria keputusan (beku, SEBELUM melihat hasil)

- **LOLOS:** median window buku OOS **> 0** dengan ≥20 window OOS.
- **KUAT:** median ≥ **0,8%** DAN hit ≥ **50%**.
- **GAGAL:** median ≤ 0 pada EW dan MV dan TOP2.
- Jika GAGAL tetapi batas-atas (kontrol permutasi) > 0 → penyebab teridentifikasi = korelasi; laporkan sebagai temuan, bukan sebagai kelolosan.
- Uji ini **deskriptif/in-sample-lampau**: kelolosan TIDAK mengizinkan klaim forward; hanya mengizinkan pra-registrasi lanjutan.

## Yang TIDAK dilakukan (beku)

Tanpa mengubah ambang/level/α/target. Tanpa menambah koin/leverage demi p-value (pelanggaran tercatat sebagai trial tambahan, ambang t naik). Tanpa menyentuh file state (hanya baca). Muat ulang protokol di-hash sebelum run; hash runner dicatat di laporan bersama hash protokol.

*Protokol beku · Hermes Anantara v3 · 10-Okt-2026*
