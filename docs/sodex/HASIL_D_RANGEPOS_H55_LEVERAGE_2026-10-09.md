# HASIL TUGAS A + D — 2026-10-09 (mode D, R2 leverage izin, R3 horizon ≤55 jam)

Prareg: `reports/sodex/PRAREG17_FORWARD_RANGEPOS_PROTOCOL.json` (commit `4a54fe1`, AMANDEMEN 1+2)
Data deskriptif: `reports/sodex/RANGEPOS_H55_DESCRIPTIVE.json`, `RANGEPOS_H55_REVERSAL_DESCRIPTIVE.json`
Harness: `scripts/research/rangepos_forward_eval.py` + timer `sodex-rangepos-forward` (**aktif**, 6 jam)

---

## A — Instrumen forward PRAREG-17: HIDUP
Timer aktif; keluaran pertama: **bar_forward = 0** untuk semua 8 sel (4 sel × 2 venue) → `TIDAK_KONKLUSIF`.
Sebabnya benar dan bukan bug: data 1h terakhir **2026-10-08T21:00Z** lebih tua dari `freeze_ts` **2026-10-09T10:06+07:00**. Sampel akan terisi saat `sodex-klines-forward` memasok bar baru. Keluarga sel kini **{rank, kuintil} × {48 PRIMER, 55 sekunder}** (BH q=0,10), sesuai AMANDEMEN-2.

## D — Uji mekanisme terbaik pada horizon ≤55 jam (DESKRIPTIF)

Net realistis (biaya nyata; arah **REVERSAL** = short dekat puncak rentang, long dekat dasar):

| Venue | hold | rank: net / t | kuintil: net / t |
|---|---:|---:|---:|
| **SoDEX 1h** | 24 | **+5,28 / 4,36** (PRAREG-4) | **+7,03 / 1,47** |
| **SoDEX 1h** | **48** | **+10,58 / 4,35** (PRAREG-4) | **+13,14 / 1,89** |
| SoDEX 1h | 50 | — | +4,56 / 0,65 |
| SoDEX 1h | 52 | — | −10,87 / −1,35 |
| SoDEX 1h | 55 | — | −12,75 / −0,94 |
| Binance 1h | 48 | — | **−17,64 / −2,67** (arah berlawanan) |

Arah MOMENTUM (kebalikannya) di SoDEX 1h H=48: bruto **−20,47 bps, net −28,03, t=−3,79** → **negatif signifikan**.

### Temuan
1. **Arah reversal terkonfirmasi dua pembobotan.** Rank: +10,58 net (t=4,35); kuintil: +13,14 net (t=1,89). Tanda dan besaran konsisten.
2. **Horizon > 48 jam LEBIH BURUK, bukan lebih baik.** H=50/52/55 = +4,56 / −10,87 / −12,75 → edge mati setelah 48 jam. **R3 (≤55 jam) tidak membuka nilai apa pun.** 48 jam adalah batas efektif, bukan sekedar konvensi target.
3. **Tanda berlawanan di Binance** (reversal −17,64, t=−2,67, BH) — bendera overfitting lintas-venue paling kuat: mekanisme ini bergantung venue.
4. **Kontrol acak lebih baik dari sinyal** di arah momentum (ctrl +35,6 vs gross −20,5) → di arah itu memang tidak ada sinyal.

## Konsekuensi untuk keputusan Mas Anas (aritmetika, bukan opini)

| Kandidat | net/48 jam | % dari target 80 bps | leverage yang dibutuhkan |
|---|---:|---:|---:|
| rank (terkuat, t=4,35) | 10,58 bps | 13,2% | **7,56×** |
| kuintil | 13,14 bps | 16,4% | **6,09×** |
| rank @2× fee | 6,47 bps | 8,1% | 12,36× |

Biaya ekor pada leverage yang dibutuhkan: 6,09× → ekor −5,4% jadi **−33%**, ekor −10,7% jadi **−65%**, jarak likuidasi ~15,4%. 7,56× → −41% / −81%, jarak likuidasi ~12,2%.

> **R2 (leverage diizinkan) tidak menutup celah tanpa risiko likuidasi.** Menutup 80 bps butuh ~6–7,6×; pada level itu satu periode ekor = likuidasi. Pagar yang saya usulkan (langkah 30%) membatasi leverage efektif ~3×, yang hanya menutup ~40% dari celah.

> **R2 juga TIDAK mempercepat sertifikasi.** `t = S_ann × √T`; leverage mengalikan mean dan simpangan baku dengan faktor sama → **t invarian terhadap leverage**. Sertifikasi dalam 42 hari butuh **S_ann ≥ 5,90**; kandidat terbaik kita S_ann 3,06 → **t = 1,04**. Ini kalender, bukan modal.

## Kesimpulan
Mode D berjalan: instrumen forward hidup, dan pengujian ≤55 jam sudah memberi jawaban definitif — **memperpanjang horizon tidak menolong; leverage tidak menolong; yang mengikat adalah kualitas edge (S_ann)**. Kandidat terbaik tetap **16,4% dari target**, dengan bendera overfitting lintas-venue yang belum dijawab.

**Tidak ada** perubahan target, gerbang, ambang, atau lane uang. Lane uang tetap freeze (unfreeze = execution arbiter + persetujuan).
