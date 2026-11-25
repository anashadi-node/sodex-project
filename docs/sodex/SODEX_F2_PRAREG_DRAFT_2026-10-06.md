# SODEX F2 — DESAIN PRA-REGISTRASI Kandidat Struktur-Mikro (DRAFT — belum beku)

**Tanggal:** 06-Okt-2026 · **Status:** DRAFT. Menjadi **BEKU** hanya setelah (a) jadwal fee SoDEX (maker vs taker) dikonfirmasi pemilik, (b) persetujuan pemilik, (c) commit. Setelah beku, tidak boleh diubah sampai putusan.
**Discovery:** `scripts/sodex_micro_discovery.py` (READ-ONLY, data 22 Mei–31 Agu 2026 saja; lockbox & F1 tidak disentuh).

## 1. Hasil discovery (angka, bukan opini)

Pola diukur pada OBI SoDEX nyata, 3 simbol basis, 101 hari, event dipisah gap 4 jam:

| Pola | n | Drift 1m | 15m | 60m | net 1m (taker) |
|---|---|---|---|---|---|
| A: spread melebar ≥2× median | 1.279 | −0,46 bp | −0,93 bp | −2,47 bp | −155 bp |
| B: balon OBI20 ≥0,35 (≥3 snap) | 1.007 | **+2,00 bp** | **+2,79 bp** | +2,74 bp | −69 bp |
| A setelah B (≤10 m) | 46 | −1,95 bp | +3,24 bp | +4,32 bp | — |

**Kesimpulan discovery:** sinyal arah ADA (balon OBI didahului drift naik, median +1,24 bp sejak menit pertama — bukan artefak satu episode), tetapi **sebagai taker biaya bulat (8–28 bp) menelan habis**. Pola A (spread melebar) drift-nya negatif dan lebih kecil → ditolak sebagai kandidat.

**Satu pintu yang tersisa:** masuk/keluar **sebagai maker** — mendapat spread alih-alih membayarnya. Model biaya berbalik: dari ±(spread+fee) menjadi ≈ fee_maker saja. Maka H2 diusulkan sebagai strategi maker.

## 2. Hipotesis H2 (satu, dibekukan saat commit)

> **H2:** Setelah balon OBI20 (≥ +0,35 selama ≥3 snapshot berturut, klaster 30 menit/simbol, gap antar-event ≥2 jam), **order post-only di best bid** terisi, dan keluar post-only di best ask 45 menit kemudian, menghasilkan **rata-rata ≥ +4 bp bersih per episode** pada 20 simbol, sehingga portofolio (15% dompet/posisi, gross ≤1×) mencapai rata-rata ≥0,8% per jendela 48 jam.

## 3. Definisi operasional (beku saat commit)

- **Data:** OBI forward + tape forward ≥2026-10-07 (collector sudah merekam keduanya). Data ≤2026-10-06 dan LOCKBOX tidak dibaca.
- **Masuk:** post-only di best bid pada t0+≤10 detik. Belum terisi di t0+5 menit → episode **dibuang** (dihitung `unresolved`).
- **Keluar:** post-only di best ask pada t0+45 menit. Belum terisi di t0+75 menit → **paksa keluar taker** (dihitung kasus terburuk: fee taker + setengah spread saat itu).
- **Biaya:** `fee_maker × 2` (nilai dari jadwal fee; placeholder **0 bp** sampai dikonfirmasi). Tanpa biaya spread (justru diperoleh). Slip maker = 0 (limit).
- **Simulasi fill:** dari tape — beli terisi jika ada trade harga ≤ bid kita setelah t0; jual terisi jika ada trade ≥ ask kita. (Konservatif: tanpa antrean.)

## 4. Gerbang & kriteria (semua beku saat commit)

- **Gerbang pemicu:** ≥**300** episode tuntas, ≥14 hari, ≥8 simbol, `unresolved` ≤10%; atau **HARD_STOP 2026-11-07** (sejajar F1). `--final` menolak berjalan sebelum gerbang (anti-intip, sama dengan F1).
- **C1'** rata-rata ≥ +4 bp/episode · **C2'** p sign-flip harian <0,05 · **C3'** kalahkan kontrol fade-maker · **C4'** buang 3 terbaik masih >0 · **C5'** versi taker murni (audit: buktikan sinyal, bukan biaya) positif · **C8'** jendela 48 jam: rata-rata ≥0,8% **dan** CI95 bawah >0 (kriteria resmi, sama F1).

## 5. Aritmetika yang membuat desain ini jujur

Laju pola B: 1.007 episode / 101 hari / 3 simbol ≈ 3,3/hari/simbol → 20 simbol ≈ **67/hari ≈ 134 per 48 jam**. Butuh: 0,8% / (0,15 × 4 bp) ≈ **134 episode**. Artinya desain ini **tepat-habis** jika kedua syarat benar: 20 simbol aktif DAN biaya maker ≈ 0. Jika fee maker SoDEX = fee taker (2 bp), H2 mati di model biaya sebelum diuji — karena itu jadwal fee WAJIB dikonfirmasi lebih dulu.

## 6. Batas kejujuran

- Simulasi fill maker tanpa antrean → hasil forward nyata hampir pasti lebih buruk dari simulasi; itulah gunanya C8' CI dan micro-live berukuran kecil.
- Discovery hanya 3 simbol basis; 17 simbol baru (spread lebih lebar) bisa berbeda — justru itu yang diuji forward.
- PASS F2 bukan GO-LIVE. Keputusan live tetap milik pemilik.

## 7. Perintah (setelah evaluator F2 ditulis)

```
.venv-research/bin/python3 scripts/sodex_micro_discovery.py        # ulangi discovery
.venv-research/bin/python3 scripts/sodex_prereg_f2.py --count-only # kapan saja
.venv-research/bin/python3 scripts/sodex_prereg_f2.py --final      # saat gerbang terbuka
```
