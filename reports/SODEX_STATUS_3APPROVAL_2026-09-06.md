# SODEX — STATUS EKSEKUSI 3 APPROVAL (2026-09-06)

## TASK 1 ✅ Akselerasi maturasi — DONE
- paper_test_realwide.py: COOLDOWN_H 12→4, MAX_TOTAL 6→8 (riset replay 5-minggu:
  +34% throughput, PF 1,98→2,16, +54% net).
- realwide_micro_live.py: COOLDOWN_H **PIN 12** (live tetap konservatif, menunggu
  bukti forward; sudah di-unpin dari PT).
- Test update: cooldown_pinned_live. Commit 12eee11.

## TASK 2 ⚠️ Reaktivasi Twin E1 PEPE — DIBATALKAN SEMENTARA (blocker teknis)
- E1 readiness awalnya OK (ready_for_live=true setelah SAFETY_HALT dihapus).
- Jalankan run --live (CONFIRM_LIVE=YES): E1 mulai (heartbeat, equity $147) —
  TAPI 2 menit kemudian HARD STOP:
  `HARD STOP: loss-cap` → SAFETY_HALT written lagi.
- ROOT CAUSE: guard loss-cap memicu pada ledger/quote E1 (perlu audit formula
  loss E1: TE_LOSS_CAP_USD=0 tapi tetap halt = dari ledger/PNL_HALT lain).
- BAHAYA TEMUAN: twin mencoba cancel order ASTER-USD (order user manual!) —
  `cancel_all_perps: skip ... symbol='ASTER-USD'`. Interaksi dgn posisi user
  user = risiko tabrakan; harus dipisah SEBELUM reaktivasi.
- SAFETY_HALT dikembalikan (backup dipulihkan). E1 **tetap off** sampai:
  (a) formula loss-cap E1 diaudit, (b) twin dipastikan TIDAK menyentuh pair
  manual user (filter exclude ASTER/ETH di twin), (c) uji e1-trial paper dulu.

## TASK 3 ✅ S1 + P1 (pair science) — DONE
- S1 entry-hour: ditambahkan sebagai **cohort tag** `s1_ok` (13-20 UTC +
  Sunday 19-24) di signal — TAG bukan blok, agar maturasi tidak melambat.
  Dampak diukur 4 minggu sebelum jadi filter.
- P1 pair priority: PAIRS diurutkan ulang — top-7 (BTC/ETH/SOL/DOGE/UNI/AAVE/
  ENA) + PUMP/BNB duluan; slot MAX8 otomatis mengisi pair unggulan dulu
  (soft-priority, bukan hard drop; n kecil → hindari overfit). ASTER/LIT
  terakhir (konsisten dgn exclude live).

## STATUS SISTEM
- Paper realwide: CD4/MAX8/tier-prioritas aktif, 37 test pass.
- Live realwide: CD12 pinned, gate LONG masih tutup (tunggu BTC>MA50).
- Twin E1: OFF (SAFETY_HALT dipulihkan) — blocker teknis terdokumentasi.
- Posisi manual USER di exchange: ASTER-USD (168, lev5) + ETH-USD (0.0598, lev5)
  — sistem TIDAK menyentuh keduanya (watchdog skip ASTER; ETH belum di-skip,
  perlu ditambah utk hindari false alert).
- Maturation: 8/30 (WR 100%, ROI +8,5%).

## TODO
1. Audit formula loss-cap E1 (kenapa halt saat TE_LOSS_CAP_USD=0).
2. Exclude ASTER/ETH dari twin cancel logic (interaksi user).
3. Watchdog: tambah skip ETH-USD utk posisi manual user.
4. Kembali reaktivasi twin E1 setelah 1-3 beres → uji e1-trial paper dulu.