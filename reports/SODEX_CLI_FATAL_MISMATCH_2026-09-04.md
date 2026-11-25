# SODEX — TEMUAN KRITIS: CLI TIDAK VALID, DASHBOARD ADALAH SUMBER KEBENARAN
# 2026-09-04 20:15 WIB — INSIDEN P0

## MASALAH FATAL

CLI `bin/sodex` (build 20 Mei 2026) **TIDAK BISA membaca posisi perps yang sebenarnya**.
`sodex positions` selalu return `null` meski ada posisi NYATA terbuka di exchange.

**BUKTI**: Dashboard SoDEX (screenshot user, 2026-09-04 20:04 WIB) menunjukkan:
```
Posisi NYATA: ETH-USD LONG 10x
  Amount:        0.0356 ETH
  Entry Price:   $2,524.8
  Mark Price:    $2,447.7
  Unrealized PnL: -$2.74 (-30.53%)
  Position Value: 87.14 USDC
  Margin:        $8.99 (isolated)
  Liq Price:     $2,301.1
```

Ini **PERSIS SAMA** dengan order live pertama yang dieksekusi via `realwide_micro_live.py`
pada 2026-09-04 10:49 WIB (qty=0.0356, entry=$2525.2). Order itu SAYA KIRA "tidak fill"
karena CLI `positions` melapor `null` — KESIMPULAN ITU SALAH. Order tersebut TEREKSEKUSI
NYATA dan sudah OPEN sejak ~9.5 jam yang lalu, merugi -$2.74 (leverage 10x, bukan 3x
seperti yang di-set script — kemungkinan default akun sudah 10x sebelum order).

## KENAPA CLI SALAH

1. CLI dibuild 20 Mei 2026 (>3 bulan lalu)
2. Dashboard menunjukkan banner "SoDEX Layer 1 Season is Live" — indikasi migrasi
   platform/infrastruktur besar setelah tanggal build CLI
3. Kemungkinan: endpoint positions berubah, format response berubah, atau CLI
   query ke gateway/environment yang sudah deprecated

## KESALAHAN SAYA (diakui penuh)

1. Order pertama dieksekusi (10:49 WIB), CLI melapor `positions: null`
2. Saya SIMPULKAN "order tidak fill" — TIDAK saya verifikasi silang ke dashboard
3. Saya bersihkan "state phantom" — padahal posisi itu NYATA
4. Saya deploy service otonom `realwide-livetest` TANPA menyadari sudah ada posisi
   terbuka nyata sejak 9.5 jam sebelumnya — RISIKO OVER-EXPOSURE jika loop jalan
   lama tanpa saya sadar posisi asli sudah ada

## TINDAKAN SEGERA (dieksekusi)

1. ✅ STOP `anantara-realwide-livetest.service` (cegah entry tambahan di atas posisi
   yang sudah nyata ada — cegah pelanggaran MAX_POSITIONS_TOTAL=2 tanpa sadar)
2. ⏳ JANGAN percaya CLI `positions`/`balance` sampai divalidasi ulang terhadap
   dashboard resmi sodex.com
3. ⏳ User harus konfirmasi manual dari dashboard: posisi apa saja yang benar-benar
   terbuka SEKARANG (screenshot terbaru)
4. ⏳ Keputusan: tutup posisi ETH manual via dashboard (rugi -$2.74 dikunci) ATAU
   biarkan (SL script di -2% = -$0.60 kalkulasi lama, TIDAK BERLAKU karena leverage
   asli 10x bukan 3x — worst case sebenarnya jauh lebih besar dari yang direncanakan)

## RISIKO YANG BELUM DIKETAHUI

- Leverage aktual 10x (dashboard) vs 3x (asumsi script) — margin/liq price sangat
  berbeda dari kalkulasi safety envelope yang saya buat
- Liq price $2,301.1 — ETH turun lagi ~6% dari mark price ($2,447.7) bisa liquidation
- TIDAK ADA cara terpercaya bagi saya untuk memonitor posisi ini via CLI saat ini
