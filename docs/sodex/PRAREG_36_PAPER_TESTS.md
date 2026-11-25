# PRAREG-36 — Baterai Paper Test (26-Okt-2026)

Dijalankan sebelum jam pertama jendela. **21/21 lulus.** Hasil mentah: `reports/sodex/PRAREG36_PAPER_TESTS.json`. Tidak ada order, tidak ada kredensial, tidak ada jaringan exchange.

## 1. Hasil per kelompok

| Kelompok | Uji | Hasil |
|---|---|---|
| Determinisme & manipulasi | D01 evaluasi identik 2×; D02 target diubah 1e-6 terdeteksi; D03 hari bolong ditolak; D04 baris duplikat tidak menggandakan; D05 backfill >3 ditolak; D06 funding kosong ditolak | 6/6 |
| Akuntansi | A01 biaya+funding eksak; A02 pemisahan lapisan (spot 1×, perp (L−1)×); A03 anti-lookahead | 3/3 |
| Ketahanan operasional | R01 record idempoten; R02 3 proses bersamaan → 1 baris; R03 apply 2× → 0 order; R04 tanpa ledger ditolak; R05 notional <10 USDC dibuang; R06 5 penanda live ditolak | 6/6 |
| Risiko & statistik | X01 ambang likuidasi L=1,5 = −66,5% (analitis vs simulasi); X02 bootstrap naik→p=0, turun→p=1; X03 ambang BH 2 sel = 0,025 | 3/3 |
| Data & daya uji | S01 base rate 30 hari; S02 daya uji; S03 sebaran M | 3/3 (informatif) |

Angka kunci: entry day biaya **−0,200%** (2 lapisan × 10 bps), hari stabil **−0,010%** (funding lapisan perp saja) — cocok dengan rumus sampai 1e-12. Return pada hari lompatan harga saat target baru muncul = **0,00e+00** → tidak ada lookahead.

## 2. Tiga cacat nyata yang ditemukan baterai ini (sudah diperbaiki)

1. **Gap jendela tidak pernah divonis.** Bila satu hari hilang, `n < 30` membuat evaluator berhenti di status `BERJALAN` selamanya — G1 tak pernah dievaluasi. Sekarang: bila tanggal akhir jendela sudah lewat dan hari tidak lengkap → `DATA_INVALID` + jumlah hari hilang.
2. **Tidak ada kunci tulis.** Dua proses `record` bersamaan bisa menulis rec ganda. Ditambah `flock` eksklusif per direktori; diuji 3 proses paralel → tetap 1 baris.
3. **Funding kosong lolos diam-diam.** Evaluator mengisi `fillna(0)` sehingga drag funding hilang dan G3 bias ke atas. Sekarang funding kosong di jendela menggagalkan **G1**.

Ketiganya cacat yang membuat hasil *terlihat lebih baik* dari kenyataan — bukan sekadar bug kosmetik.

## 3. Pembelajaran utama: 30 hari tidak bisa membuktikan apa pun

Dari 1.729 jendela 30-hari historis (2022–2026, B2 hybrid 1,5×, biaya 10 bps):

| Metrik | Nilai |
|---|---|
| Jendela dengan M ≥ 0,010 %/5j | **41,0%** (kebetulan, bukan edge) |
| Jendela dengan MDD ≥ −35% | **100,0%** → G4 tidak pernah mengikat |
| Jendela lolos G3 **dan** G4 | **41,0%** |
| Sebaran M (p10 / p50 / p90) | −0,0375 / +0,0004 / +0,0741 %/5j |
| sd return harian | 1,39% |
| **M terkecil yang bisa signifikan** (p=0,025, n=30) | **0,108 %/5j — 10,8× target** |
| n yang dibutuhkan agar 0,010 %/5j signifikan | **≈3.482 hari ≈ 9,5 tahun** |

**Konsekuensi yang harus diterima sekarang, bukan nanti:**
- **G6 hampir pasti gagal.** Verdict realistis 25-Nov adalah `LANJUT_EKSEKUTOR_DRY_RUN` (bukan `..._TERBUKTI`). Itu hasil yang benar, bukan kegagalan proses.
- **G3 lulus bukan bukti.** 41% jendela acak juga lulus; jangan menaikkan eksposur karena 30 hari hijau.
- **G4 praktis mati** pada L=1,5 dengan data 2022–2026 (MDD terburuk masih di atas −35%). Nilainya hanya sebagai penjaga bencana.
- Nilai sesungguhnya dari 30 hari ini: **validasi operasional** (recorder, funding, eksekutor, fail-closed) — bukan inferensi statistik.

## 4. Batas yang tetap berlaku
- Likuidasi dihitung dari gerak **penutupan**, bukan low intraday → lebih longgar dari PRAREG-34/35.
- Funding memakai Binance USDM sebagai proksi SoDEX.
- Live tetap terlarang: 3 kunci live + GO eksplisit pengguna.
