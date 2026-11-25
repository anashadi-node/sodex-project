# SODEX — LIVE READINESS & GO-LIVE CHECKLIST
2026-09-05 | Target: ≥0,7% wallet ROI/trade (HARGA MATI) | Wallet $139,37

## WAJIB BACA: Kondisi Saat Ini
- **REALWIDE live**: AKTIF, $50 notional @3x, TP4%/SL2% (pinned, maturasi).
  Macro-BTC gate sedang BLOKIR LONG (BTC < SMA50: close 79.569 vs 79.797) — aman.
- **SPOT live**: AKTIF, $6/trade, TP2.5%/SL1.5%, posisi BTC -0,27% sedang dikelola.
- **PERPS-SHORT**: OFF permanen (belum tervalidasi).
- **8 PAPER TRACK**: aktif semua; 4/6 melampaui target dgn denominator lama,
  2/6 dgn denominator baru jujur (REALWIDE +1.507%, TWOWAY-LONG +1.187%).

## STATUS PENCAPAIAN TARGET (denominator baru $139,37)
| Track | n | WR | ROI/trade | Target 0,7% |
|---|---|---|---|---|
| REALWIDE | 62 | 50.0% | +1.507% | ✅ |
| TWOWAY LONG | 108 | 54.6% | +1.187% | ✅ |
| SWING | 142 | 46.5% | +0.567% | ❌ dekat |
| SWING_PARTIAL | 137 | 56.9% | +0.564% | ❌ dekat |
| SPOT_V4 | 10 | 50.0% | +0.451% | ❌ |
| DONCHIAN | 48 | 37.5% | -0.289% | ❌ |

## AKAR MASALAH (terbukti audit 2026-09-05)
1. Sizing live $30 → $50 (sudah) — proyeksi +0,7537% LULUS.
2. Geometri TP6%/SL1,5% terbukti unggul (bootstrap CI95 [+0,40%,+0,99%]
   P=100%) — SUDAH di paper, menuai n≥30 sebelum promosi live.
3. TIME-exit drag: 32% trade exit TIME dengan median +0,16% — geometri baru
   mengurangi.
4. Hipotesis "local top entry" DIFALSIFIKASI (6 metrik p>0,13).

## GATE PROMOSI GEOMETRI BARU KE LIVE (maturation tracker)
- [ ] n≥30 trade forward paper (TP6/SL1.5) — saat ini 0/30 COLLECTING
- [ ] WR≥50%
- [ ] PF≥1.5
- [ ] ROI/trade ≥0.7%
- Verdict otomatis di data/sodex_maturation_status.json

## GO-LIVE CHECKLIST (sebelum live penuh)
- [ ] Watchdog 0 CRITICAL (berjalan tiap 3 menit)
- [ ] Sync realtime 0 error (tiap 2 menit)
- [ ] Preflight keduanya OK
- [ ] Kill switch file TIDAK ada
- [ ] Balance terverifikasi (perps $99.30 + spot $40.06 = $139.37)
- [ ] 39 test suite pass

## RISIKO TERPANTAU
- BTC < SMA50 → gate LONG blokir (sistem bekerja)
- Aster track -30.52 (n=14, multi-venue research)
- Hyperliquid track 0 trade (masih collect)