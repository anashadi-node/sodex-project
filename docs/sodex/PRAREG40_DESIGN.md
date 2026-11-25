# PRAREG-40 — Settled-Alpha Reflection (paper A/B)

Status: **BEKU (desain)**, implementasi belum ada, belum ada data terlihat.

## Hipotesis (falsifiable)
Menambahkan blok *settled-alpha reflection* — maksimum 3 pelajaran dari episode yang
sudah selesai, dihitung sebagai return bersih dikurangi BTC buy-and-hold pada horizon
yang sama — ke gate pemilihan entry menaikkan WR ≥ 3 pp dan expectancy ≥ 5 bps
dibanding gate identik tanpa reflection, pada 60 hari paper-forward.

## Desain
- Arm A (baseline): gate PRAREG-23b apa adanya.
- Arm B: gate sama + blok reflection (≤3 baris, hanya dari episode settled).
- Refleksi **deterministik** (agregasi statistik per kategori: sesi, rezim, arah),
  bukan LLM di jalur keputusan. LLM hanya boleh merangkum offline, tidak mengubah gate.
- Unit observasi: satu entry tervalidasi. Settlement pada horizon tetap per trade.
- Jendela: rekaman 2026-11-01 .. 2026-12-30; evaluasi 2026-12-31.
- Biaya: fee taker + spread + funding bila perp (sama untuk kedua arm).

## Gerbang keputusan (dibekukan)
- G1 data lengkap: ≥ 60 hari rekaman, tidak ada hari bolong > 2.
- G2 kekuatan sampel: ≥ 100 entry per arm.
- G3 efek: ΔWR ≥ +3 pp **dan** ΔE(R) ≥ +5 bps.
- G4 signifikansi: t ≥ 2,5 (registry ambang) pada uji dua sisi.
- G5 multiple testing: hanya 1 hipotesis utama → p ≤ 0,05; jika ditambah uji lain,
  BH q = 0,05.
- G6 risiko: MDD arm B tidak lebih buruk > 5 pp dari arm A.
- G7 kontrol negatif: arm B dengan refleksi **diacak** (shuffle antarepisode) harus
  gagal mencapai G3 — kalau lolos, efeknya bukan dari refleksi.

## Pohon keputusan
`DATA_INVALID` | `GAGAL` (dibuang, tanpa penyelamatan post-hoc) | `LOLOS` (kandidat
implementasi, tetap butuh GO terpisah untuk menyentuh gate produksi).

## Batasan
Tidak menyentuh PRAREG-23b/26/36. Tidak mengubah eksekutor. Tidak ada order live.
