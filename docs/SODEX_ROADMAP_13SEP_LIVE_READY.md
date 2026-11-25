# 🚀 ROADMAP 13 SEPTEMBER — SoDEX 100% LIVE-READY
## Target user: Full sistem siap Real Live Trading uang nyata di SoDEX maksimal 13 September 2026

> Dibuat: 2026-08-26 · Sisa waktu: **18 hari**
> Kandidat: **REAL-wide** (satu-satunya track yang lolos Gate-2 formal: n=29, SPRT Λ=+3.179 > +2.944, PF 6.67, WR 72%)

---

## STATUS AWAL (26 Agu) — apa yang SUDAH siap

| Komponen | Status |
|---|---|
| Strategi terbukti (Gate-2 lolos) | ✅ REAL-wide: TP+4%/SL−2%/time-stop, LONG-only, BTC/SOL/ETH |
| Infra eksekusi live | ✅ `bin/sodex` CLI (EIP-712) + `validate-signing` terbukti |
| Template live-test | ✅ spot_live ($3) + perps_short ($10) berjalan dengan safety envelope |
| Safety layer | ✅ guardian + sentinel service, kill-switch file pattern, no-withdraw flag |
| Proteksi baru | ✅ macro-BTC SHORT gate + edge gate agregat (LONG=KEEP) |
| Deep loop learning | ✅ iterasi 3.400+, autonomous 24/7 |

## YANG BELUM ADA (gap menuju live)

1. **Skrip micro-live REAL-wide** — mengeksekusi sinyal REAL-wide dengan uang nyata kecil (belum ada; yang ada hanya template intel-gated).
2. **Modal micro-live** — perps butuh margin ≥$6 per posisi; rekomendasi $150–300.
3. **Checklist go-live otomatis** — preflight harian (balance, signing, kill-switch, gate status).
4. **Evaluasi Gate-3 otomatis** — pengukuran slippage nyata vs paper.

---

## ROADMAP HARIAN (18 hari)

### FASE A — PERSIAPAN MICRO-LIVE (26–30 Agu, 5 hari)
| Hari | Tugas | Output |
|---|---|---|
| D1 (26) | ✅ Roadmap dibuat. Tulis `scripts/realwide_micro_live.py` (adaptasi template safety envelope: SIZE $10/trade, MAX_POS=1, SESSION_LOSS_CAP −$2, DAILY_CAP 3, kill switch `data/REALWIDE_LIVE_KILL`, DRY default) | Skrip + demo self-check |
| D2 (27) | Preflight: `validate-signing` + balance check + dry-cycle 24 jam | Bukti eksekusi bersih |
| D3 (28) | User top-up margin perps ±$150–300 (keputusan user) | Saldo cukup |
| D4 (29) | Live pertama: 1 trade manual-supervised (`--live --once`) | Trade #1 nyata |
| D5 (30) | Review trade #1: slippage vs paper, fee aktual | Laporan deviasi |

### FASE B — GATE-3 MICRO-LIVE BERJALAN (31 Agu – 9 Sep, 10 hari)
| Hari | Tugas |
|---|---|
| D6–D14 | `realwide_micro_live.py --live --loop` autonomous; target akumulasi ~1.9 trade/hari → ±18 trade |
| Harian | Watchdog cek: session loss cap, daily cap, kill switch, slippage log |
| D11 (5 Sep) | Checkpoint tengah: WR live vs paper (toleransi −10pp), PF live ≥1.2 |

### FASE C — EVALUASI & GO/NO-GO FULL LIVE (10–13 Sep, 4 hari)
| Hari | Tugas |
|---|---|
| D16 (10 Sep) | Evaluasi Gate-3: n≥15-20 live trades, slippage ≤ model, WR turun ≤10pp, zero margin call |
| D17 (11 Sep) | Jika lolos → naikkan size bertahap (10→25→50% dari target notional). Jika tidak → perpanjang micro-live (KEPUTUSAN ILMAH, bukan kalender) |
| D18 (13 Sep) | **GO/NO-GO FINAL**: sistem dinyatakan 100% live-ready dengan bukti lengkap |

---

## KRITERIA "100% SIAP" 13 SEPTEMBER (semua harus ✅)

1. ✅ Gate-2 lolos (REAL-wide SPRT +3.179) — SELESAI
2. ⬜ Micro-live ≥15 transaksi nyata tanpa incident
3. ⬜ Slippage rata-rata ≤ model (spread + fee 0.16% RT)
4. ⬜ WR live ≥ paper WR − 10pp (≥62%)
5. ⬜ Zero margin call / stuck position
6. ⬜ Kill-switch & loss-cap teruji minimal 1× (drill)
7. ⬜ Modal live tersedia & alokasi posisi final disetujui user

## ATURAN KEAMANAN (tidak bisa dinegosiasi)
- No-withdraw flag tetap ON.
- Loss cap sesi harian hard-coded; pelanggaran = halt otomatis.
- Naikkan size HANYA setelah evaluasi lolos — bukan karena tanggal.
- Semua keputusan GO/NO-GO memakai angka, bukan harapan.
