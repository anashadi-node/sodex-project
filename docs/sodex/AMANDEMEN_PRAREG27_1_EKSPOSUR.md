# AMANDEMEN-1 PRAREG-27 — Paritas eksposur (wajib sebelum data)

**Tanggal:** 2026-10-21 (WIB)
**Alasan:** audit menemukan arm B tidak sebanding dengan arm A pada **eksposur**, bukan hanya slot.

## Temuan audit (fakta terukur)

| Item | Nilai |
|---|---|
| Wallet SoDEX total (snapshot on-chain 21-Okt 03:00Z) | spot $58,40 + perps $184,97 = **$243,37** |
| Eksposur per posisi (A) | `NOTIONAL 100 × LEVERAGE 3` = **$300** (1,23× seluruh wallet) |
| Eksposur arm A (6 slot) | **$1.800 = 7,4× wallet** |
| Eksposur arm B sebelum amandemen (12 slot × $300) | **$3.600 = 14,8× wallet** ← **tidak sebanding** |
| Window terburuk A (wallet-based) | **−30,53%** |

Konsekuensi bila dibiarkan: Δhit arm B akan mencampur efek **slot** dengan efek **leverage 2×** —
persis kesalahan yang PRAREG-27 ingin hindari.

## Amandemen (mengikat)

| Parameter | Arm A (kontrol) | Arm B (revisi) |
|---|---|---|
| Slot sinyal | 6 | 12 |
| `TW_NOTIONAL` | 100 (default) | **50** |
| Eksposur per posisi | $300 | **$150** |
| **Eksposur total** | **$1.800** | **$1.800 (identik)** |
| Hold | 30 jam | 30 jam |
| Cooldown | 12 jam | 6 jam |

Eksposur total arm B **wajib sama** dengan arm A; hanya jumlah posisi & cooldown yang berbeda.

## Konsekuensi pada data arm B

- Arm B baru berjalan ±4 jam, **0 trade tertutup** → tidak ada sampel yang hilang bila state di-reset.
- State lama diarsipkan: `data/paper_test_twoway_p27_state.json.bak.20261021_sebelum_amandemen1`.
- Data sebelum amandemen **tidak dipakai** untuk verdict (0 trade tertutup; 14 posisi terbuka dibatalkan).

## Aturan tetap

Semua aturan keputusan di `PRAREG_27_SLOT_TURNOVER.md` **tidak berubah**: ADOPT jika Δhit ≥ +3 pp
dan Δmedian ≥ −0,2 pp (n≥25); ABANDON jika Δhit ≤ 0; batas waktu 2026-11-25; baca interim 2026-10-28.

*Hash SHA-256 dihitung sebelum arm dijalankan ulang.*
