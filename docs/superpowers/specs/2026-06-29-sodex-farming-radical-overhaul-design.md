# SODEX FARMING — RADICAL OVERHAUL DESIGN

> **Tanggal:** 2026-06-29 · **Status:** DESIGN (menunggu approval user sebelum eksekusi)
> **Author:** ZCode (GLM-5.2) · **Brainstorming skill active**
> **Anchor:** `reports/SODEX_FARMING_AUDIT_ROOT_CAUSE_2026-06-29.md` (audit) + `docs/SODEX_FARMING_DOCTRINE.md` (doktrin)
> **Deadline keras:** 25 Juli 2026 (26 hari) — SoDEX S1 reward event berakhir
> **Constraint:** live trading real money, profile wash-trade risiko clawback, dry_run CEX tidak tersentuh

---

## 1. PROBLEM STATEMENT (riset-validated)

### 1.1 Kondisi saat ini (status quo = RUGI + BERISIKO)
| Metrik | Realitas (7d) | Target doktrin | Gap |
|--------|---------------|----------------|-----|
| NET mingguan | **−$59.79** (pnl +$18.68 − fee $78.47) | ≥ 0 | 🔴 GAGAL |
| Win-rate | 63.2% | >69% | 🔴 −6pp |
| Real Rasio | 1:5,020 | ≥1:9,100 | 🔴 55% |
| Volume | $110K | $1.3M | 🔴 8.5% |
| Profil trading | round-trip 12mnt same-wallet | — | 🔴 WASH-risk |

### 1.2 Root cause (6, dari audit + klarifikasi riset)
1. **RC-1 Taker fee burn** — PVE BUY@ask/SELL@bid. **Klarifikasi riset: taker fee 0.04%/side (BUKAN 0.02%)** = 3.3× maker. Biaya RT taker = 0.08% + spread.
2. **RC-2 Governor tidak ter-wire** ke eksekusi live.
3. **RC-3 Wash-trade profile** — round-trip deterministik same-wallet.
4. **RC-4 E1 SPOT dead-locked** (SELL block).
5. **RC-5 Data chaos 3-sumber.**
6. **RC-6 Modal $700 vs $1.3M** = infeasible tanpa rebate tier.

### 1.3 TROBOSAN RISET (mengubah lanskap solusi)
| Temuan | Bukti (verifikasi live 2026-06-29) | Implikasi |
|--------|-------------------------------------|-----------|
| **Taker fee = 0.04%/side** | `markets/symbols` REST: takerFee 0.0004 | RC-1 3.3× lebih buruk → maker path **jauh** lebih menguntungkan |
| **Post-only gtx DIDUKUNG** | `bin/sodex agent-help`: `--tif gtx`; test oid=0 saat crossing (reject bersih) | Maker path reliable (RC-1 solvable) |
| **GTC limit inside-spread = MAKER ACCEPTED** | Test live: BUY SPCX @154.40 < bid → orderID valid 10142259834, resting | Maker farming feasible |
| **Funding API accessible** | REST `/accounts/{addr}/fundings` per-posisi per-jam | Kolektor funding bisa dibangun (tutup gap G5) |
| **Spread pair right > maker fee** | CHZ 0.058%, SPCX 0.045%, WLD 0.023% > maker 0.012% | Maker capture **positif** di pair right |

---

## 2. TUJUAN & SUCCESS CRITERIA (deadline 25 Juli)

### 2.1 Tujuan doktrin (dipertahankan, kalibrasi-modal)
- **T1 Volume:** ≥ $1.3M/mgg (kalibrasi bertahap jika modal jadi binding — lihat §2.2)
- **T2 Win-rate:** > 69%
- **T3 Cost coverage:** E1/maker profit ≥ fee
- **T4 Real Rasio:** ≥ 1:9,100
- **T5 NET mingguan:** ≥ 0 (No-Loss)
- **T6 SoPoints/$ maksimal + anti-wash compliance**

### 2.2 Success criteria terukur per fase (gate ilmiah)
| Fase | Gate lulus jika (snapshot mingguan jujur B16) | Budget risiko |
|------|-----------------------------------------------|---------------|
| F0 Stop-bleed | NET harian ≥ 0 selama 48 jam setelah switch taker→maker | $0 (config) |
| F1 Maker path | Fill-rate maker ≥ 40%, NET/RT maker > NET/RT taker pada ≥3 pair | $3 (paper→micro live) |
| F2 Funding harvest | Funding kolektor sehat, paper NET ≥ 0 setelah fee | $5 (paper) |
| F3 Governor wire | 0 trade dieksekusi saat EV<0 (audit log), WR honest ≥ baseline | $0 (kode) |
| F4 Anti-wash | Self-trade-ratio <50%, hold-time std-dev tinggi (non-deterministik) | $0 (monitor) |
| F5 Scale target | Volume ramp $50K→$200K→$500K, tiap tier NET≥0 sebelum naik | per-tier cap |

---

## 3. APPROACH (terpilih: HYBRID BERTAHAP)

User mendelegasikan ke rekomendasi terbaik dengan deadline 25 Juli. **Hybrid dipilih** karena:
- Pure directional (Approach B) terlalu lambat untuk 26 hari (validation mingguan, risiko edge tidak proven)
- Aggressive taker (Approach C) melanggar doktrin + risiko clawback
- Pure maker+funding (Approach A) kurang agresif capai $1.3M sendiri
- **Hybrid = hentikan bleeding dulu (maker), validasi edge paralel (funding/LightGBM), scale terukur** = seimbang speed + safety + doktrin

### 3.1 Arsitektur target
```
┌─────────────────────────────────────────────────────────────────┐
│              SODEX FARMING v4 (MAKER + FUNDING + GOVERNED)       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  E1-MAKER (perps, BARU) — sodex_twin_engine.py modifikasi       │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Post-only GTC inside-spread (BUY@bid-x, SELL@ask+x)    │     │
│  │ Pairs: SPCX, CHZ, WLD (spread > maker fee)             │     │
│  │ Hold: hingga fill ATAU funding-target (anti-wash)       │     │
│  │ Fee: maker 0.012% + rebate tier potential               │     │
│  │ Inventory mgmt: skew, cap, flush (reuse B14 logic)      │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  FUNDING-HARVEST-SoDEX (BARU) — sodex_funding_harvest.py        │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Kolektor funding REST /fundings (tutup gap G5)          │     │
│  │ Sinyal: pair over-funded → SHORT (receive funding)      │     │
│  │ Delta-neutral hedge bila perlu (1-leg funding dominant) │     │
│  │ Paper-first → micro-live gate WR n≥100                  │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  GOVERNOR (WIRE, BARU) — sodex_governor.py integrate ke live    │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ evaluate_roundtrip() sebelum setiap order               │     │
│  │ EV gate (Mesin 1-4 + expectancy) = master               │     │
│  │ Skip pair NET-negatif secara matematis                  │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  ANTI-WASH MONITOR (BARU) — sodex_wash_audit.py                 │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Self-trade ratio, hold-time regularity, notional var    │     │
│  │ Alert + auto-pause bila profil wash meningkat           │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                  │
│  INFRA YANG DIPERTAHANKAN (jangan ubah):                         │
│  G4 breaker, monitoring 5-layer, B13 akunting, B16 monitor,     │
│  weekly snapshot, PVE fill-recon, dry_run CEX, .env hygiene     │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Komponen & tanggung jawab
| Komponen | Status | Tanggung jawab | Dependency |
|----------|--------|----------------|------------|
| `perps_volume_engine.py` | **MODIFIKASI** | Tambah maker path (`--tif gtx` inside-spread) sebagai opsi; taker jadi fallback | adapter place_limit_gtx |
| `sodex_twin_engine.py` adapter | **MODIFIKASI** | Tambah `place_limit_gtx_perp()` method (GTC post-only) | bin/sodex orders place --tif gtx |
| `sodex_funding_harvest.py` | **BARU** | Kolektor funding REST + sinyal over-funded + paper execution | httpx, ledger |
| `sodex_governor.py` | **WIRE** | Dipanggil di PVE tick sebelum order | model_prob (sodex-model:8001) |
| `sodex_wash_audit.py` | **BARU** | Monitor profil wash harian | ledger fills/rts |
| `.env` | **MODIFIKASI** | Tambah TE_PVE_MAKER_PATH, TE_PVE_PAIRS (filter), TE_FUNDING_* | — |

---

## 4. DATA FLOW (maker path)

```
1. tick() → governor.evaluate_roundtrip(ATR, spread, depth, RR, model_prob, WR, fee, funding)
   ├─ EV < 0 → SKIP (log reason)
   └─ EV ≥ 0 → lanjut
2. book() REST orderbook → bid/ask/spread
3. spread < maker_fee → SKIP (capture negatif)
4. qty = notional/mid, round ke stepSize
5. INV/QTY decision:
   ├─ flat → open maker: BUY@bid−offset (post-only GTC, resting)
   │        ├─ oid valid → tunggu fill (poll position delta, PVE fill-recon)
   │        └─ oid=0 (crossing) → skip, retry next tick dengan offset beda
   └─ have inv → close maker: SELL@ask+offset (reduce-only post-only)
6. Hold policy (anti-wash): posisi dipegang ≥ min_hold_s (variabel, bukan fixed 12mnt)
   exit saat: fill target funding interval ATAU SL/TP ATAU max_age
7. ledger.fill() + ledger.rt_close() (B39 pattern, reuse)
8. wash_audit.update() tiap RT
```

---

## 5. ERROR HANDLING & EDGE CASES

| Kasus | Handling |
|-------|----------|
| Post-only oid=0 (crossing) | Log, skip, retry offset berbeda tick berikutnya. Tidak phantom (verified: open orders 0) |
| Orderbook stale | PVE fill-recon `_real_pos()` delta check; if unverifiable → no volume minted |
| Funding API down | Funding-harvest pause, maker tetap jalan (funding = bonus, bukan dependency) |
| sodex-model:8001 down | Governor fallback prob_min tinggi (konservatif), skip high-conviction trades |
| G4 drawdown 15% | Hard stop (tidak diubah) |
| Wash-profile spike | Auto-pause PVE + alert telegram |
| Pair spread collapse < maker fee | Skip pair (governor gate) |
| Inventory stuck | Flush via maker reduce-only (perps buy+sell OK, tidak kena E1 spot block) |

---

## 6. TESTING STRATEGY (TDD per komponen)

| Komponen | Test | Gate |
|----------|------|------|
| Maker path | unit: offset calc, oid=0 handling, qty rounding | make test-pve |
| Governor wire | unit: skip saat EV<0, execute saat EV>0 | make test-governor |
| Funding collector | unit: parse REST, signal over-funded threshold | make test-funding |
| Wash audit | unit: self-trade ratio calc, alert trigger | make test-wash |
| Integration | paper mode 24h, NET≥0 | snapshot B16 |
| Full suite | `make audit` (1761 tests, ≤2 pre-existing astronacci errors) | green |

---

## 7. RISIKO & MITIGASI

| Risiko | Dampak | Mitigasi |
|--------|--------|----------|
| Deadline 25 Juli terlewat | volume/SoPoints suboptimal | Fase paralel, gate cepat, scale setelah NET≥0 |
| Maker fill-rate rendah | volume drop | fallback taker di pair dengan spread sangat tipis (BTC), tapi capping fee |
| Edge funding/LightGBM tidak proven | directional tidak scalable | Maker path tetap jalan (fee saving 70%), funding = bonus |
| Wash classification tetap terjadi | clawback | Anti-wash monitor + hold-time variabel + bukan self-round-trip |
| Modal kecil binding | $1.3M mustahil | Kalibrasi target bertahap (§2.2 F5), honest ke user |
| Bug kode live trading | loss modal | TDD + paper-first + G4 + dry_run + backup sebelum deploy |

---

## 8. ROLLBACK PLAN

Setiap fase:
1. **Backup** config + DB sebelum (`backups/pre_overhaul_20260629/`)
2. **Git branch** isolation (jika enable git worktree skill)
3. **Feature flag** per komponen (TE_PVE_MAKER_PATH=0 default → taker lama)
4. **Kill switch**: TE_PVE_ENABLED=0 + SODEX_FARMING_ENABLED=0
5. **Rollback**: restore backup + restart daemon

---

## 9. YANG TIDAK DIUBAH (invariants)

dry_run CEX, `.env` chmod 600 + no secret commit, G4 breaker, monitoring 5-layer, B13 akunting, B16 monitor, weekly snapshot, governor kode (self-test pass), PVE fill-recon, fill=0 fix, SAFETY_HALT, project lain (CEX/Astronacci/HL/Pre-Gain).

---

## 10. EXECUTION SEQUENCE (5 fase, TDD + gate per fase)

```
F0 — STOP THE BLEEDING (priority: hari ini)
  ├─ Backup config + DB
  ├─ Konsolidasi TE_PVE_PAIRS ke pair NET-positif (SPCX + CHZ)
  ├─ Matikan E1 spot quote noise (TE_E1_ENABLED=0 confirmed, skip _place_two_sided)
  └─ Gate: 48h NET harian ≥ 0

F1 — MAKER PATH (menghemat fee 70%)
  ├─ TDD: test maker path (offset, oid=0, qty round)
  ├─ Implement place_limit_gtx_perp() di adapter
  ├─ PVE: TE_PVE_MAKER_PATH=1 (post-only GTC inside-spread)
  ├─ Paper verify fill-rate, lalu micro-live
  └─ Gate: NET/RT maker > taker pada ≥3 pair

F2 — FUNDING HARVEST SoDEX (edge baru, tutup gap G5)
  ├─ TDD: test funding collector + signal
  ├─ Implement sodex_funding_harvest.py (REST /fundings)
  ├─ Paper mode: track funding earned vs fee
  └─ Gate: funding NET ≥ 0 setelah fee

F3 — GOVERNOR WIRE (disiplin EV)
  ├─ TDD: test governor integration
  ├─ Wire evaluate_roundtrip() ke PVE tick
  ├─ Anti-wash monitor deploy
  └─ Gate: 0 trade EV<0, wash-ratio <50%

F4 — SCALE TO TARGET (ramp terukur)
  ├─ Per-tier: $50K → $200K → $500K → $1.3M
  ├─ Tiap tier: NET≥0 + WR≥69% + rasio≥1:9,100 sebelum naik
  └─ Gate: snapshot Sabtu jujur B16
```

**Approval per fase.** User bisa stop kapan saja.

---

## 11. SPEC SELF-REVIEW (brainstorming checklist)

- [x] Placeholder scan: tidak ada TBD/TODO, semua gate konkret
- [x] Internal consistency: arsitektur §3.1 match komponen §3.2 match data flow §4
- [x] Scope check: 5 fase fokus, tiap fase gate tunggal, no scope creep
- [x] Ambiguity check: maker path = post-only GTC inside-spread (explicit), bukan limit-IOC same-side (phantom)
- [x] Deadline-aware: fase paralel F1+F2, gate cepat

---

*Design ini READ-ONLY. Menunggu review + approval user sebelum eksekusi F0.*
*Tidak ada file/kode/config diubah saat penulisan design ini. Project lain tidak tersentuh.*
