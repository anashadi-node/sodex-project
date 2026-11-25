# RANTAI HASH PRAREG-26

Setiap perubahan tercatat berurutan. Dokumen asli tidak dihapus; v1 tetap dapat diverifikasi
dari catatan ini.

| Versi | Waktu (WIB) | Perubahan | SHA-256 |
|---|---|---|---|
| v1 | 10-Okt-2026 (pembekuan) | Dokumen awal — verdict 2-Nov-2026, t ≥ 3,60 | `e06fcb265a25caa24c880949c7cb112b9945d36abad204bfb2d1c368c9cc46d0` |
| v2 | 19-Okt-2026 09:55 | Tambah §10 + penanda DICABUT pada §6 (tanggal & ambang t) — verdict **25-Nov-2026**, t ≥ **3,80**, give-up tetap 30-Nov | `b71fc29338a4034738a43513c11f833f4aeb1c271c47a8d20a7e7e0f0732e7ad` |
| Amandemen-1 | 19-Okt-2026 09:55 | Dokumen amandemen lengkap (alasan, aritmetika Bonferroni, klarifikasi verdict, filter `stale_exit`) | `b1c55b858c8aff30b2647fbf9592a701b17fe4547e8010fb176163a25298039c` |

## Verifikasi

```bash
cd ~/anantara-sakti/docs/sodex
sha256sum -c PRAREG_26_MESIN_SELEKSI.md.sha256
sha256sum -c AMANDEMEN_PRAREG26_JADWAL_2026-10-19.md.sha256
```

Tes otomatis: `tests/test_prereg26_jadwal.py` memeriksa kedua hash, tanggal verdict, dan ambang t.

## Catatan

- v1 dibuat **sebelum** data forward 11-Okt ada (bukti anti look-ahead).
- v2 dibuat karena keputusan jadwal diambil setelah melihat 2/12 window — karena itu ambang t
  dinaikkan dari 3,60 ke 3,80 (Bonferroni 4 look), sesuai §6 protokol induk.
- Target 0,8%, definisi A/B, aturan seleksi, universe, dan minimum 12 window tidak berubah.
