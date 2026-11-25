# SoDEX Perps-Short Live — DIMATIKAN PERMANEN (2026-09-04)

## Alasan
1. `sodex_perps_short_live_test.py` (live) memakai signal dari
   `research_short_bear.py` — skrip RISET EKSPLORATIF ("does SHORT-in-bear
   add tradeable edge?"), BUKAN strategi yang pernah melalui proses maturasi
   paper->live resmi.
2. `research_short_bear.py` TIDAK MUNCUL di `sodex_progress_report.py` atau
   tracker resmi manapun — 0 evidence n/WR/PF pernah divalidasi.
3. Skrip riset tersebut bahkan TIDAK BISA DIJALANKAN saat ini — bergantung
   file `.feather` lokal yang sudah tidak ada di repo sama sekali
   (`find . -name '*.feather'` -> 0 hasil).
4. Insiden 2026-09-04: live short berjalan otonom sejak Agustus dengan
   4 "closed trade" yang semuanya phantom (order rc=1, gagal total) —
   baru terdeteksi & fixed hari ini, TAPI root masalah (signal tak
   tervalidasi) tetap ada meski bug phantom-fill sudah diperbaiki.

## Tindakan
- Service `anantara-perps-short-livetest.service` di-stop, di-disable.
- File unit systemd DIPINDAH ke
  `anantara-perps-short-livetest.service.DISABLED_2026-09-04_belum_tervalidasi`
  (bukan cuma disable — dipindah supaya `daemon-reload` tidak mengenalinya
  sama sekali; systemctl mask gagal krn file asli masih ada saat itu).
- KILL switch `data/PERPS_SHORT_KILL` TETAP terpasang sbg lapis kedua.

## Syarat reaktivasi (approved user 2026-09-04)
1. Bangun infrastruktur PAPER TEST otonom (bukan riset one-shot) utk
   strategi short-bear ini — reuse `_regime_gate_ok`/`_confirm_15m` dari
   `paper_test_realwide.py` sbg pola, sinyal dari `research_short_bear.py`
   (setelah source data 1h klines direstore — pakai Binance API live,
   BUKAN feather lokal yg hilang).
2. Jalankan paper minimal n>=30 closed trade (Bagian 10.1 SOUL: syarat
   minimum utk klaim "signal profitable").
3. WR>=55%, PF>1.2, OOS-consistent (bukan cuma in-sample).
4. User approval eksplisit sebelum live lagi (aturan §absolute: tidak
   ubah parameter/aktivasi fundamental tanpa approval).

## Status track lain (tidak terpengaruh)
- REALWIDE live: DIPERBAIKI (v2, 100% sinkron paper, 23 pair) — lihat commit.
- SPOT live: DALAM PERBAIKAN (sinkronisasi ke paper_test_spot_swing_v2.py).
- Semua 8 paper track: TETAP JALAN, tidak terganggu.
