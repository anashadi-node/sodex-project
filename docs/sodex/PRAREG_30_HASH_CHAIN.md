# RANTAI HASH PRAREG-30

Dokumen tidak dihapus; setiap versi tercatat berurutan.

| Versi | Waktu (WIB) | Perubahan | SHA-256 |
|---|---|---|---|
| v1 | 2026-10-22 09:56:52 | Pembekuan awal — 2 arm (P/C), 12 bps primer, gerbang a–g, n_trials 140 | `ddac7c1157c5c590532170f14ebf126c8da4eee969428e6bb50de042a1b87281` |
| A1 | 2026-10-22 10:30 | Amandemen celah data (2022 ratio 13%) + replikasi 2021+2023 + guard gap>24h. Aturan sinyal/gerbang tidak berubah | `31eaa8eaeffe32aea49677686357938a3451fe5d32d72752682f63b0ac8f21f6` |

## Verifikasi

```bash
cd ~/anantara-sakti/docs/sodex
sha256sum -c PRAREG_30_OI_CROWDING_REVERSAL.md.sha256
```

## Catatan anti look-ahead

- Dokumen dibekukan **sebelum** satu sinyal PRAREG-30 dihitung.
- Pada saat beku, yang tersedia hanya: (a) data mentah metrics (belum dianalisis di level sinyal),
  (b) kline 1h lokal, (c) hasil diagnostik buku hidup arm A (dokumen terpisah).
- Tidak ada nilai WR/expectancy/p-value PRAREG-30 yang diketahui saat hash dibuat.
- OOS (2026-01-01 → 2026-10-08) belum pernah dievaluasi dengan aturan ini.
- Bila dokumen perlu diubah setelah melihat hasil → amandemen terpisah + hash baru + alasan tertulis;
  perubahan arah gerbang hanya boleh **memperketat**, tidak melonggarkan.
