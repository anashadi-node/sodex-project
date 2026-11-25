# FUNDING-CARRY STAT-ARB — STATUS & REKOMENDASI (2026-09-05)

## Apa itu (awam)
Beli spot + short perps pada aset sama = posisi netral arah.
Untung hanya dari funding rate (biaya yang dibayar long ke short tiap 8 jam).

## Status infrastruktur (SUDAH ADA & BEKERJA)
| Komponen | Status | Detail |
|---|---|---|
| funding_harvest_paper.py | ✅ AKTIF | Binance, since 27-Mei: net +$4.82 (ROI +0.96%) dgn cap $500 |
| funding_carry_factor.py | ✅ AKTIF | CEX factor (paper, arXiv-backed) — TAPI sedang rugi |
| hl_harvest.py / funding_harvest.py | ✅ AKTIF | HL harvesting infra |
| hl-harvest-auto.timer | ✅ AKTIF | auto cycle 30 menit |
| job_funding_monitor | ✅ di daemon | daily opportunity monitor |

## REALITA PENTING (funding-carry TIDAK semanis teori)
- CEX funding-carry: total_pnl_pct = **-11,19%** saat ini (5 posisi aktif), ZEC -10,2%
  max_loss. Kenapa? funding rendah (~8%/tahun) + basis/arah melawan posisi delta-neutral
  + biaya spread. "Delta-neutral" bantu, tapi TIDAK HILANGKAN risiko basis & fee.
- funding_harvest_paper: +0,96%/3bln = **tipis** (~4%/tahun), kalah dari yang diharapkan
  (paper Elsevier +115%/6bln itu di kondisi funding ekstrem 2021-2022, saat ini 2026 funding
  biasa-biasa saja).

## Kesimpulan untuk modal $139
1. Funding-carry layak **SEBAGAI SATU LEG KECIL** (diversifikasi), BUKAN andalan — karena
   saat ini edge-nya tipis & ada risiko kerugian basis.
2. Modal $139 terlalu kecil utk spread 2 leg (spot+perps ~$100×2) — biaya proporsional besar.
3. REKOMENDASI: terus jalankan PAPER funding (kumpul data), JANGAN live dulu. Fokus tetap
   REALWIDE live (n=62 lulus, tunggu gate) + short terfilter (r1h<0, no-weekend).

## Aksi saya
- Verifikasi semua komponen funding masih jalan (audit tim).
- Monitoring berkala: funding_harvest_paper +0.96% (sehat), CEX funding-carry -11.19% (awas,
  flag — tapi ini paper, tidak sentuh uang).
- Tidak ada perubahan kode — infrastruktur sudah lengkap; yang kurang hanyalah data cukup
  utk keputusan live, dan kondisi funding saat ini belum menguntungkan.