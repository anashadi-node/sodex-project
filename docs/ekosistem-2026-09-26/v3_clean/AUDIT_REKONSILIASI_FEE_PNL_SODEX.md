# AUDIT REKONSILIASI FEE/PnL SoDEX — 27-09-2026

## Hipotesis yang diuji (dan TERFALSIFIKASI)
Hipotesis awal: "ledger `rts.net_pnl` tidak memotong fee → Juni sebenarnya rugi ~$335, bukan untung $53."
**Hasil: SALAH.** Bukti kode (`anantara/sodex_twin_engine.py`):
- Jalur live fill (L2197): `pnl = (o.price - bpx) * take - vol * self.cfg.spot_maker_fee` dengan `vol=(bpx+o.price)*take` → fee dipotong pada KEDUA kaki.
- Jalur rekonsiliasi (L2266): `eff_px = d_usdc_signed / qty` (harga efektif sudah termasuk fee) → `pnl = (eff_px - bpx) * take` bertanda komentar "harga efektif sudah net fee".
**Kesimpulan: `rts.net_pnl` SUDAH net of fee.** Pembukuan konsisten.

## Rekonsiliasi Juni (12–30 Jun, engine E1)
| Pos | Nilai |
|---|---|
| Round-trip (RT) | 13.042 |
| Net PnL (ledger) | **+$91,42** |
| Fee dibayar | **$257,23** |
| Gross implied (net + fee) | $348,65 |
| Notional 1-sisi | $439.783 |
| Gross capture | **7,93 bps/RT** |
| Fee drag | **5,85 bps/RT** |
| **Net margin** | **2,08 bps/RT** ($0,0070/RT) |
→ Fee memakan **74%** dari gross capture. Konsisten, tidak ada anomali.

## Temuan sampingan yang tetap penting
1. **14 Jul–17 Jul: badai churn PVE.** 17 Jul memutar **$398.823 notional dalam 1 hari** (≈1.450× wallet $275) dengan fee $47,86 dan net PVE Juli **−$14,02** → gross capture hanya ~0,85 bps. Churn tanpa edge.
2. **Fee efektif per engine (all-time)**: E1 $262,28 fee / $897.256 notional; E2 $106,64 / $987.366; PVE $84,12 / $607.482. Total fee lifetime ≈ $453.
3. **PnL lifetime per engine**: E1 **+$87,18**, E2 **−$35,90**, PVE **−$16,76** → total **+$34,52**.
4. **Seri equity weekly TIDAK bisa dijelaskan oleh PnL trading** (186→642→21,48 vs PnL trading lifetime +$34,52) → residual besar = transfer/deposit/withdrawal atau MTM inventori. **Belum terselesaikan** — butuh riwayat transfer venue; ledger lokal tidak menyimpannya.

## Yang harus dilakukan berikutnya
- Tarik riwayat transfer/deposit SoDEX (CLI `transfer` / ekspor venue) untuk menutup residu equity.
- Tambah kolom `ts_open` eksplisit pada `rts` agar holding-time per RT terukur (saat ini hanya `ts_close`).
- Standarkan `fee` pada tabel `fills` agar taker/maker memakai tarif yang benar (ditemukan fee efektif taker Juni 1,08 bps < maker 3,04 bps — indikasi baris taker memakai estimasi tarif maker di jalur rekonsiliasi).

*Sumber: `twin_engine.db` (rts, fills, state) + kode `sodex_twin_engine.py`. Read-only, tanpa perubahan parameter.*
