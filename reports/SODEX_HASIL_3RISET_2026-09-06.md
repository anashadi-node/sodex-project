# SODEX — HASIL 3 RISET PARALEL & REKOMENDASI TERDAFTAR (2026-09-06)

## 1. Deep Learner Farming — MATI SEJAK 2026-08-02 (single point of failure)
- **Gejala**: sodex_deep_learning.jsonl & learned_params.json berhenti 02-Agu,
  bersamaan dgn matinya data twin-engine PEPE (WR 95,7% saat itu).
- **Root cause** (belum diverifikasi final): daemon restart/kfg job hilang ATAU
  collector feed putus ATAU exception tak tertangani.
- **Rekomendasi** (butuh aksi): cek log daemon tgl 02-Agu; verifikasi heartbeat
  collector OBI; tambah watchdog "jsonl tidak bertambah X menit" alert;
  backup state sebelum restart; resume dari iterasi 7617 jika ada checkpoint.

## 2. Audit 18 Modul — Harta Karun Twin Engine E1
- **Twin E1 PEPE**: 12.560 RT, WR 96,1%, **net +$87,47** (hanya tgl 2026-07-23).
- **Twin E2 perps**: WR 3,5%, -$35,90 — BUG GHOST perps (`TE_E2_ENABLED=0` benar).
- **Overlap kritis**: autofarm & twin E1 sama-sama maker spot PEPE/USDC — JANGAN
  aktifkan keduanya sekaligus (risiko nonce, lock hanya thread-level utk farming).
- **Modul terbaik utk diaktifkan** (bertahap, masing-masing ada syarat):
  1. Pengumpul E1 PEPE (setelah twin live & isi DB 1-2 minggu baru)
  2. sodex_autofarm (sudah aktif indirect; jaga lock)
  3. Deep learner farming (setelah root cause fix + watchdog baru)
- **Deprecated**: sodex_spot_farm, sodex_wide_farm (digantikan autofarm v3.1).

## 3. Akselerasi Maturasi TP6/SL1.5 — Data Replay 5-Minggu
- **Cooldown 12h memblok 40,3% episode tradable net-positif** (WR 44%,
  +0,37%/trade) = buang kapasitas, bukan saring sampah.
- **REKOMENDASI UTAMA (menunggu approval user — timeout, belum dieksekusi)**:
  `COOLDOWN_H 12→4` + `MAX_TOTAL 6→8` → trade +34% (238→320), PF 1,98→2,16,
  avg +0,66%/t, net +205,9% (+54%), forward WR 67%.
- **JANGAN ubah TP/SL/hold** sebelum n=30 forward (TP6 optimal; SL1% rapuh;
  TS24≈TS30; hold-SL 6h hanya naikkan PF 1,81→2,75 dgn hold lebih lama).
- 2× penuh TIDAK via satu track (supply ~407 episode/5 minggu) — perlu track
  paralel tak berkorelasi (short terpisah / universe baru 5-8 pair).
- Akselerasi (4h/8): **n=30 tercapai ±4 hari kerja** (vs ±6 hari sekarang).
- Tier unggulan utk prioritas pasca-n30: SOL/ETH/UNI/BNB/PUMP (WR 64-75%,
  PF 3,4-8,0). Drag: HYPE/ENA/ADA/AVAX/TRX/LIT/ASTER (PF<1,1).

## STATUS DEFAULT SAAT INI (tanpa perubahan — menunggu approval)
- Maturation: **8/30** (WR 100%, PF 999, ROI +8,5%) — gate selain n sudah LULUS.
- Service: 15 aktif, watchdog 0 CRITICAL, ASTER user aman.
- Live realwide: tunggu gate LONG (BTC>MA50), excl ASTER.

## KEPUTUSAN YANG MENUNGGU USER
1. **Akselerasi**: COOLDOWN 12→4 + MAX_TOTAL 6→8 (rekomendasi, replay kuat)?
   atau lebih agresif 12→0/MAX10? atau biarkan maturasi (opsi default dipakai
   krn user timeout — bukan keputusan).
2. **Reaktivasi twin E1 PEPE** (harta karun +$87,47 tapi overlap dgn autofarm)?
3. **T1/S1/P1** dari action plan 2× (partial-TP, entry-hour, pair prune)?