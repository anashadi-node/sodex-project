# RENCANA MIGRASI TAKER → MAKER (SoDEX) — 27-09-2026

## Kondisi terukur sekarang (jangan salah asumsi)
| Engine | Maker fills | Taker fills | Catatan |
|---|---|---|---|
| E1 (spot PEPE) | **61.145 (98,3%)** | 1.062 | Sudah maker-dominan; fee efektif maker 3,04 bps/fill |
| E2 (perps churn) | 3.368 (100%) | 0 | Sudah murni maker; fee 1,08 bps/fill |
| **PVE** | 0 | **898 (100%)** | **Ini yang masih taker penuh** |

**Artinya:** "pindah taker → maker" untuk E1/E2 sudah selesai. Yang tersisa: (a) tarif fee, (b) **capture per RT** (7,93 bps vs tick/spread PEPE 22,5 bps → hanya 35% spread tertangkap), (c) **PVE masih taker**, (d) churn tanpa batas.

## 6 langkah konkret
1. **PVE → maker.** Ganti eksekusi PVE dari IOC/taker ke quote passif (GTC/post-only) memakai pola offset E2 (`TE_E2_MAKER_TICK_OFFSET=1.0`, `_maker_leg(..., aggressive=0)`). Target: maker share PVE ≥ 80%, fee dari ~2 bps → ~1,1 bps/fill.
2. **Post-only/GTX sebagai default.** Set TIF post-only untuk semua quote agar order tidak bisa menyilang (mencegah takers tak sengaja — 1.062 fill taker E1 Juni adalah kebocoran yang tak perlu).
3. **Gate spread minimum.** Jangan quote bila spread < 2× tick pair (PEPE 22,5 bps, SHIB 16,7 bps). Gate lama `min=0.00100` (10 bps) terlalu longgar untuk PEPE → quote di kondisi spread tipis = pasti rugi setelah fee.
4. **Governor churn per 30 jam.** Batas keras: notional diputar ≤ 4× wallet per 30 jam, dan blokir quote bila `edge_per_churn` < fee RT + buffer. Ini yang mencegah terulangnya 17 Jul ($398.823 notional, net −$14).
5. **Cap order terbuka & anti-spam.** Maksimum 1 order terbuka per pair (terbukti kejadian nyata: 3 BUY GTC menumpuk saat dana masuk 26-09), plus cancel/replace rate limit.
6. **Naikkan capture, bukan frekuensi.** Prioritas: kualitas fill (posisi antrean, size ≤ 20% depth), bukan menambah RT. Counterfactual Juni: capture 7,93 → 12 bps = **net naik 3,0×**; fee separuh = **net naik 2,4×**; keduanya = **4,4×**.

## Kriteria sukses (terukur, per 30 jam)
| Metrik | Sekarang (Juni) | Target |
|---|---|---|
| Maker share (identitas E1) | 98,3% | ≥ 98% (jaga) |
| Maker share PVE | 0% | ≥ 80% |
| Net margin per RT | 2,08 bps | ≥ 5 bps |
| Churn notional/30 jam | ~906 RT (≈$61k) | ≤ 4× wallet |
| Blok 30 jam ≥ 0,7% wallet | 3/9 (33%) | ≥ 70% |

*Tanpa perubahan parameter produksi sampai disetujui Owner. Semua usulan bersifat rencana.*
