# PRAREG-40 — PILOT walk-forward (bukan verdict)

Tanggal: 31-Okt-2026 · `scripts/reflect_gate.py` (6 tes unit lulus)
Aturan beku: `n ≥ 30`, `t ≤ −1,5`, maksimum **3** aturan, hanya dari trade yang
`exit_ts < entry_ts` (tanpa lookahead). Gate memblokir bila salah satu aturan cocok.

## Aturan yang terbentuk dari 1.690 trade
| Dimensi | Nilai | n | alpha_net | t |
|---|---|---|---|---|
| sym | ETH | 128 | −0,567% | **−7,06** |
| sym | ASTER | 59 | −0,645% | −2,82 |
| sym | SUI | 51 | −0,574% | −1,63 |

Diagnosis: kerugian **terkonsentrasi di 3 simbol**, bukan tersebar. ETH paling parah
dan paling pasti (t = −7).

## Hasil pilot (n = 1.658 trade yang punya ≥30 pendahulu settled)
| Kelompok | n | mean alpha_net | t | alpha>0 |
|---|---|---|---|---|
| A — semua | 1.658 | −0,141% | −2,71 | 37,8% |
| B — diizinkan gate | 1.221 | −0,058% | −0,93 | 39,6% |
| Diblokir | 437 (26,4%) | −0,372% | −4,03 | 33,0% |

Delta B−A = **+8,3 bps**. ΔWR = **+1,8 pp**.

## Bacaan jujur
1. **Gate bekerja sebagai penyaring, bukan pencipta edge.** Ia membuang 26% trade
   dengan alpha jauh lebih buruk, tetapi sisa bukunya **masih negatif** (−0,058%,
   t = −0,93). Tidak ada bukti alpha positif.
2. **Terhadap gerbang PRAREG-40, pilot ini GAGAL di G3:** ΔE +8,3 bps lolos (≥5 bps),
   tetapi ΔWR +1,8 pp < 3 pp. Sesuai aturan, tidak boleh dilonggarkan setelah hasil.
3. **Implikasi ke target 0,8%/30 jam:** masalahnya bukan seleksi entry, melainkan
   sinyal itu sendiri. Menyaring lebih rapat hanya memperlambat pendarahan.
4. Pilot ini **retrospektif** (walk-forward, tapi tetap memakai data yang sama untuk
   memilih ambang). Ia tidak boleh dipakai sebagai verdict — hanya untuk memastikan
   mekanismenya waras sebelum 60 hari berjalan.

## Status forward
- Overlay harian **06:45 WIB** (`anantara-reflect-overlay.timer`) mencatat keputusan
  gate untuk setiap trade baru dengan `entry_ts ≥ 2026-11-01`.
- Evaluasi verdict tetap **31-Des-2026** memakai G1–G7, termasuk kontrol negatif
  shuffle.
- Sampai 31-Okt: overlay kosong (belum ada trade jendela baru) — bukan error.
