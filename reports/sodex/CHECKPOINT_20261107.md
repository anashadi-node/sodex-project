# CHECKPOINT 07-Nov-2026 — status sementara

Diambil: 2026-11-07 01:00 UTC · hari jendela: 6.0

**Bukan verdict.** Verdict 01-Des memakai G1–G8 lengkap.

| Arm | n | mean alpha_net | t | alpha>0 | status |
|---|---|---|---|---|---|
| 40 (refleksi) | 158 | -0.328% | -2.42 | 44.3% | AWAS (negatif signifikan) |
| 41 (blocklist) | 158 | -0.328% | -2.42 | 44.3% | AWAS (negatif signifikan) |
| 42 (night-short) | 12 | -0.200% | -0.68 | 66.7% | DATA_INVALID (<60) |

## Cakupan

- 40 (refleksi): 6 hari, gap maks 1
- 41 (blocklist): 6 hari, gap maks 1
- 42 (night-short): 6 hari, gap maks 1

## Catatan

- Jika n < 60: jangan tafsirkan arah, hanya cek pipeline.
- Gerbang tidak boleh diubah; AWAS bukan alasan menurunkan ambang.
- Periksa juga `journalctl --user -u anantara-paper-settle -n 20`.
