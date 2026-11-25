# PRAREG-35 — Hybrid spot+perp (uji utama) + pembanding lengkap

Rencana dibekukan 26-Okt-2026 sebelum hasil (`reports/sodex/PRAREG35_REGISTRY.jsonl`, hash + 1 amandemen pelaporan). RISET read-only: tanpa order, tanpa kredensial, tanpa mengubah parameter engine/live.

## Konstruksi
Lapisan dasar **1× di SPOT** (tanpa funding, fee taker 6,5 bps); eksposur tambahan **(L−1)× di PERP** (funding hanya pada notional perp, fee taker 4,5 bps). Pembanding: **all-perp** (seluruh notional di perp, PRAREG-34) dan **spot 1×** (baseline).

## Hasil utama — arm B2 (data 2022-01 → 2026-10-25)
| Konfigurasi | M %/5j | MDD | win31 terburuk | P(win31≥target) | P(win31 rugi) | drag funding/th | likuidasi stres | p(M≤0) | p kontrol |
|---|---|---|---|---|---|---|---|---|---|
| spot 1× (baseline) | 0,00906 | −19,5 | −9,4% | 0,398 | 0,476 | 0 | 0 | 0,015 | — |
| **hybrid 1,25×** | 0,01073 | −23,9 | −11,8% | 0,421 | 0,484 | 1,1% | 0 | 0,019 | — |
| **hybrid 1,5×** | **0,01237** | **−28,3** | −14,1% | 0,434 | 0,489 | 2,2% | 0 | 0,022 | 0,047 |
| hybrid 1,75× | 0,01402 | −32,4 | — | — | — | — | 0 | — | — |
| hybrid 2× | 0,01566 | **−36,4** | −18,6% | 0,454 | 0,495 | 4,4% | 0 | 0,027 | 0,047 |
| all-perp 1,5× | 0,00991 | −27,0 | −14,5% | 0,414 | 0,506 | — | 0 | 0,049 | — |
| all-perp 2× | 0,01382 | −33,9 | −18,8% | 0,439 | 0,512 | — | 0 | 0,042 | 0,060 |

## Hasil utama — arm A
| Konfigurasi | M %/5j | MDD | win31 terburuk | P(win31≥target) | p(M≤0) | p kontrol |
|---|---|---|---|---|---|---|
| spot 1× | 0,00606 | −13,8 | −8,6% | 0,282 | 0,044 | — |
| hybrid 1,5× | 0,00816 | −20,4 | −13,2% | 0,334 | 0,060 | 0,103 |
| **hybrid 2×** | **0,01025** | −26,8 | −18,0% | 0,359 | 0,071 | 0,103 |
| hybrid 2,5× | 0,01234 | −32,8 | −22,8% | 0,371 | 0,078 | — |
| all-perp 2× | 0,00884 | −26,5 | −18,5% | 0,344 | 0,101 | 0,133 |

## Titik kritis (grid 0,25; hybrid)
| | A | B2 |
|---|---|---|
| L pertama M ≥ 0,010 | 2,00 | 1,25 |
| L pertama MDD < −35% | 2,75 | 2,00 |
| L pertama likuidasi stres | >4,00 | >4,00 |
| puncak pertumbuhan geometrik | 3,50 | 3,50 |

Catatan: kolom drag funding all-perp tidak dilaporkan (tidak tersedia pada frame PRAREG-34); secara aritmetika ia ≈ 2× hybrid pada L yang sama karena funding dibayar pada seluruh notional.

## Temuan
1. **Hybrid mengalahkan all-perp pada setiap L.** Selisih M: A +16% (L=2: 0,01025 vs 0,00884), B2 +13% (L=2), B2 +25% (L=1,5). Sebabnya aritmetika: funding kini hanya dibayar pada (L−1)× notional, bukan L×, sementara fee perp lebih murah dari spot.
2. **Jendela target tercapai, tapi bukan bukti.** B2 hybrid 1,5×: M 0,01237 ≥ target, MDD −28,3% (dalam plafon −35%), 0 likuidasi stres, ekuitas stres minimum 0,637, OOS26 positif. Gerbang beku D lolos **mentah** (p=0,022; kontrol 0,047).
3. **Koreksi multiplisitas membatalkan klaim "terbukti".** 12 sel diuji (2 arm × 6 L). BH q=0,05 menuntut p ≤ 0,00417 untuk sel terkecil; **tidak ada yang lolos**, termasuk baseline spot B2 (p=0,0154). Karena itu vonis yang saya pakai: **LAYAK_PAPER_BUKAN_BUKTI**, bukan `TERBUKTI`. Gerbang D di rencana beku tidak memuat koreksi ini — itu cacat desain yang saya catat, bukan yang saya tutupi.
4. **Target adalah rata-rata, bukan jaminan per jendela.** Pada B2 hybrid 1,5×, 48,9% jendela 31 hari masih negatif dan jendela terburuk −14,1%. Hanya 3 dari 5 tahun kalender mencapai 0,010.
5. **Sensitivitas biaya (B2 hybrid 1,5×):** fee riil 0,0130 · 7 bps 0,0128 · 15 bps 0,0115 · **25 bps 0,00994 (gagal tipis)**. Funding SoDEX 1,3 bps/hari 0,0128; funding 0 → 0,0136. Artinya target bertahan sampai biaya round-trip ~20 bps.
6. **Risiko likuidasi hybrid kecil** karena lapisan perp hanya (L−1)×: pada L=1,5 ambang likuidasi ≈ −67% gerak satu hari, jauh di luar sampel 2022–2026. Ini bukan alasan mengabaikan gap risk; skenario stres ×1,5 tetap 0 kejadian.

## kesimpulan
Jalur **hybrid B2 1,5×** adalah konfigurasi terbaik yang ada sekarang: target 0,010 terlampaui dengan MDD −28,3% (dalam plafon yang Anda setujui) dan biaya realistis. Tapi statusnya **layak diuji paper, belum terbukti** — edge-nya tidak lolos koreksi 12-uji, dan separuh jendela 31 hari tetap negatif. Arm A baru menyentuh target di 2× dengan bukti yang lebih lemah (p=0,071).

## Langkah berikut (butuh persetujuan)
PRAREG-36: paper-forward **B2 hybrid 1,5×** (spot 1× + perp 0,5×) sebagai uji utama, **A hybrid 2×** sebagai pembanding, dievaluasi 30 hari, gerbang sama + BH atas seluruh sel. Perlu implementasi eksekutor dua lapisan (belum ada) dan tetap `dry_run`.
