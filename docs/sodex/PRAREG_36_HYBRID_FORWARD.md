# PRAREG-36 — Paper-forward hybrid (B2 1,5× utama, A 2× pembanding)

Didaftarkan **sebelum jam pertama** paper-forward berjalan. Hash kode + parameter di `reports/sodex/PRAREG36_REGISTRY.jsonl`. DRY-RUN: tanpa order, tanpa kredensial, tanpa perubahan parameter live.

## Sel uji (beku, 2 sel)
| Peran | Arm | L | Konstruksi |
|---|---|---|---|
| Utama | B2 | 1,50 | spot 1,0× + perp 0,5× |
| Pembanding | A | 2,00 | spot 1,0× + perp 1,0× |

## Jendela
- Target pertama dicatat `asof = 2026-10-25` (bar tutup terakhir saat pendaftaran); dieksekusi pada penutupan berikutnya (26-Okt).
- Jendela evaluasi: **26-Okt-2026 → 24-Nov-2026 (30 hari return)**; evaluasi final 25-Nov-2026.
- Rekaman harian 00:35 UTC (setelah recorder Mode A 00:30). Append-only, idempoten per tanggal.

## Biaya & funding (beku)
- Fee: 10 bps per sisi **per lapisan** (spot dan perp), konservatif vs fee riil 6,5/4,5 bps.
- Funding: Binance USDM historis, dijumlahkan per tanggal UTC, dikenakan **hanya pada notional perp** = (L−1)×.
- Data harga: Binance BTCUSDT/ETHUSDT/XAUTUSDT harian (sama dengan backtest PRAREG-34/35).

## Gerbang (beku — tidak boleh diubah setelah hasil terlihat)
| Kode | Syarat |
|---|---|
| G1 | Data lengkap: tanpa tanggal hilang, backfill ≤ 3, hari GAGAL_DATA ≤ 2 |
| G2 | Target dihitung ulang dari **CSV forward** (riwayat penuh, ikut di-hash) **identik** dengan target di ledger |
| G3 | M_B2 ≥ 0,010 %/5 jam |
| G4 | MDD_B2 ≥ −35% |
| G5 | 0 hari likuidasi (berbasis penutupan, dengan stres ×1,5 gerak merugikan) |
| G6 | Bootstrap blok p(M≤0) untuk B2 lolos **BH q=0,05 atas 2 sel** → p ≤ 0,025 |
| G7 | M_A > 0 (pembanding tidak runtuh) |

## Pohon keputusan (beku)
- G1/G2 gagal → `DATA_INVALID` (perpanjang jendela, bukan vonis strategi).
- G3 atau G4 atau G5 gagal → `NO-GO`.
- G7 gagal → `TIDAK_KONSISTEN` (sel utama tidak boleh dipakai).
- Semua lulus kecuali G6 → `LANJUT_EKSEKUTOR_DRY_RUN` (bukan klaim terbukti).
- Semua lulus termasuk G6 → `LANJUT_EKSEKUTOR_DRY_RUN_TERBUKTI` — tetap **bukan** izin live; live butuh 3 kunci live + GO eksplisit pengguna.

## Status implementasi (26-Okt-2026)
- Recorder: `hybrid36.py record|refund|eval|status`. Rekaman pertama tertulis `asof 2026-10-25`.
- Timer: `sodex-hybrid36-record.timer`, harian **00:35 UTC**, `Persistent=true`, aktif.
- Eksekutor dua lapis: `hybrid_exec.py --plan|--apply`, **paper-only**, menolak berjalan bila ada penanda live (`LIVE_ARMED`, `PREGAIN_LIVE`, `SODEX_LIVE`, `HL_API_SECRET`, `BINANCE_API_SECRET`) — exit 3.
- Koreksi tercatat: rec pertama sempat menulis `funding_bps = null` karena bug tipe (Series vs DataFrame). Diperbaiki, lalu diisi lewat event `KOREKSI_FUNDING` append-only — ledger tidak ditimpa. Hari itu: BTC 2,34 / ETH 1,71 bps.

## Catatan metodologis
1. Jendela 30 hari tidak punya daya untuk membuktikan edge 0,010%/5j; G3/G4 adalah **uji kelangsungan**, G6 satu-satunya uji inferensial dan sengaja diketatkan dengan BH.
2. Likuidasi dihitung dari gerak penutupan (bukan low intraday) karena ledger hanya menyimpan penutupan — ini **lebih longgar** dari PRAREG-34/35 dan dicatat sebagai keterbatasan.
3. Target adalah rata-rata lintas jendela; 30 hari hanya satu sampel. Hasil positif tidak mengubah status "belum terbukti" di luar G6.
