# PRAREG-41 — Universe filter (blocklist simbol) — DIBEKUKAN SEBELUM JENDELA

Status: **BEKU 31-Okt-2026**, sebelum trade jendela pertama (01-Nov). Tidak boleh
diubah setelah hasil terlihat.

## Asal hipotesis
PRAREG-40 pilot (walk-forward, n=1.658) menemukan alpha negatif terkonsentrasi:
ETH (n=128, t=−7,06), ASTER (n=59, t=−2,82), SUI (n=51, t=−1,63). Gate refleksi
membuang 26% trade dan menaikkan mean +8,3 bps, tetapi buku tetap negatif.

## Hipotesis (falsifiable)
Mengeluarkan ETH, ASTER, dan SUI dari universe paper menghasilkan **mean alpha_net ≥ 0**
pada jendela forward, bukan sekadar lebih baik dari baseline.

## Desain
- Arm C: semua trade paper, kecuali `sym ∈ {ETH, ASTER, SUI}`.
- Pembanding: arm A (semua trade) pada jendela yang sama.
- Jendela: **rekam 2026-11-01 .. 2026-11-30**, evaluasi **2026-12-01**.
- Tidak menyentuh PRAREG-23b/26/36/40. Paper-only, tanpa order.
- Biaya 8 bps, unlevered, benchmark BTC 1h (sama dengan settlement).

## Gerbang (dibekukan)
- G1 cakupan: ≥ 25 hari rekaman, gap ≤ 2 hari.
- G2 sampel: ≥ 100 trade arm C.
- G3 efek absolut: mean alpha_net arm C **≥ 0**.
- G4 signifikansi: t ≥ 2,5.
- G5 perbandingan: delta(C − A) ≥ +10 bps.
- G6 risiko: tidak ada satu simbol tersisa dengan alpha < −0,3% dan t < −2.
- G7 kontrol negatif: memblokir **3 simbol acak** dengan porsi trade setara harus
  **gagal** G3 — kalau lolos, efeknya bukan dari simbol yang dipilih.

## Pohon keputusan
`DATA_INVALID` | `GAGAL` | `LOLOS` → kandidat untuk diuji ulang OOS 30 hari berikutnya.
LOLOS di sini **bukan** izin live; live 01-Des tetap butuh GO terpisah.

## Catatan kejujuran
Pemilihan 3 simbol berasal dari data yang sama dengan pilot. Karena itu verdict
**hanya sah pada jendela forward**, dan G7 wajib gagal. Tanpa dua syarat itu,
hasilnya data snooping.
