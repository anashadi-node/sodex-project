# KEPUTUSAN LIVE 01-DES-2026 (dibekukan 26-Okt-2026)

Keputusan Mas Anas: kriteria **anggaran risiko**, target **0,010%/5j tetap**, **live nyata di SoDEX 01-Des-2026**.

## 1. Apa yang live pada 01-Des
| Item | Nilai |
|---|---|
| Strategi | Mode A arm A, **spot 1×**, tanpa short, tanpa leverage |
| Eksekutor | `mode_a_live.py` (limit-IOC, slip ≤30 bps, tanpa retry) |
| Modal | usulan ≤ $300 (akun terpisah) |
| Cap | ekuitas 300 · per-order 100 · total-beli 200 |
| **Henti otomatis** | drawdown dari puncak ≥ `max_drawdown_pct` (template 15%, batas keras 20%) → `secrets/KILL` ditulis |
| Jam | 00:50 UTC (07:50 WIB), setelah recorder 00:30 UTC |

## 2. Kenapa BUKAN leverage pada 01-Des
- Eksekutor perp live belum ada; yang ada hanya `hybrid_exec.py` paper (menolak live).
- Format respons CLI SoDEX belum pernah divalidasi kunci nyata — celah terbesar, bahkan untuk spot.
- Likuidasi/margin SoDEX belum dimodelkan (MMR generik).
- Leverage = **Fase 2**, syarat: verdict PRAREG-36 (25-Nov) bukan NO-GO/DATA_INVALID + eksekutor perp + model margin + selftest testnet.

## 3. Ekspektasi jujur arm A spot
M ≈ 0,0061%/5j (**di bawah** target 0,010), MDD historis −13,8%, hari terburuk −4,6%, P(31 hari < 0) 54%. Live 01-Des = **uji eksekusi nyata + data**, bukan bukti edge, dan belum mencapai target secara rata-rata. Jalur ke target = Fase 2 (B2 hybrid 1,5×, M historis 0,0124) dan varian vol-target (PRAREG-37, M 0,0157) setelah terbukti operasional.

## 4. Syarat GO (semua harus terpenuhi)
1. `preflight.py` 0 FAIL.
2. Selftest TESTNET sukses (**user**).
3. PRAREG-23b/36 tidak `DATA_INVALID`; 0 error eksekusi paper.
4. `LIVE_ARMED.json` ditandatangani **user** (hash engine cocok).
5. `CONFIRM_LIVE=YES` ditambah **user**.

## 5. Stop & evaluasi
- Otomatis: drawdown ≥ batas arm → KILL. Eksekusi gagal → berhenti tanpa retry.
- Manual (aturan): MDD live ≤ −20% atau 2 error eksekusi → berhenti, review.
- Evaluasi 90 hari: **24-Jan-2027** — hit90, M, MDD (PRAREG-37 shadow + live kecil).

## 6. Garis waktu
| Tanggal | Tugas | Siapa |
|---|---|---|
| ≤ 05-Nov | Akun/kunci khusus bot + `secrets/sodex.env` (chmod 600) | **user** |
| ≤ 10-Nov | Selftest TESTNET | **user** |
| 25-Nov | Verdict PRAREG-36 | agen |
| 26-Nov | Evaluasi PRAREG-23b | agen |
| 27–29-Nov | Preflight harian, perbaiki FAIL | agen |
| 30-Nov | Tanda tangan `LIVE_ARMED.json` | **user** |
| 01-Des 07:50 WIB | Aktifkan timer live | **user** |

Agen tidak pernah mengetik/menyimpan kunci pribadi dan tidak membalik live sendiri (Red Line + Prinsip #1).


---

## 7. Amandemen 26-Okt-2026 — perps + leverage DISETUJUI untuk 01-Des
Mas Anas menyetujui: leverage, trading perps SoDEX 01-Des, paper perps, dan riset perps.

| Item | Nilai |
|---|---|
| Sel | **P1** (S 0,75 / M 0,25 / Lp 3) — gross 1,5× total, perp 3× pada akun perp |
| Modal perp | ≤ $60 dari total ≤ $240 (spot $180 + perp $60) |
| Eksekutor | `perp_exec.py` — paper default; live terkunci 3 kunci + receipt selftest |
| Paper mulai | 26-Okt-2026, timer 00:45 UTC (3 fill paper tercatat) |
| Live perps | 01-Des-2026, **hanya** setelah selftest testnet + reconciliation nyata |
| Pengaman | taker 4 bps, Lp 3, likuidasi ≥40% jauh saat entry, breaker −15% dari puncak |

**Vonis ilmiah PRAREG-38:** `LAYAK_PAPER_BUKAN_BUKTI` — p(M≤0)=0,0197 (edge positif tipis), p(M≤target)=0,3215 (target belum terbukti). P2 dan P4 gugur karena MDD menembus −35%.
