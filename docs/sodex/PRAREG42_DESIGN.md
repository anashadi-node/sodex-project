# PRAREG-42 — Night-short cell (SHORT 00–05h UTC) — DIBEKUKAN SEBELUM JENDELA

Status: **BEKU 31-Okt-2026**, sebelum trade pertama jendela (01-Nov). GO-42.

## Keputusan desain (dan kenapa bukan dua sel)
Usulan awal: long 12–17h + short 00–05h. Data 30 hari terakhir menolak penggabungan:

| Sel | n (30h terakhir) | mean alpha | t | sd | status |
|---|---|---|---|---|---|
| SHORT 00–05h | 81 | **+0,296%** | **+4,48** | 0,59% | stabil (all-time t=4,10) |
| LONG 12–17h | 150 | +0,135% | +0,89 | 1,86% | **meluruh** (all-time t=2,79) |

Menambahkan sel yang meluruh hanya menaikkan varians dan menurunkan daya uji.
Karena itu PRAREG-42 **hanya SHORT 00–05h**. Long 12–17h dicatat sebagai
**observasi eksploratif tanpa gerbang** — tidak boleh diklaim lolos.

## Daya uji (dihitung sebelum jendela)
Laju 2,7 trade/hari → ±81 trade/30 hari. Dengan sd 0,59%, SE = 0,066%,
**MDES (80% power) = 0,185%**. Gerbang t ≥ 2,5 dapat dicapai bila efek nyata
≥ 0,19% — dan efek teramati 0,296%. Desain ini punya daya, bukan harapan.

## Aturan beku
- Arm E: `side == S` dan `0 ≤ hour(entry_utc) < 6`.
- Pembanding arm A: semua trade pada jendela sama.
- Jendela: **01-Nov .. 30-Nov-2026**, evaluasi **01-Des-2026**.
- Biaya 8 bps (stress 12 bps dilaporkan), unlevered, benchmark BTC 1h.

## Gerbang
- G1 cakupan ≥ 25 hari, gap ≤ 2 hari.
- G2 n_E ≥ 60.
- G3 mean alpha_net(E) ≥ 0 pada fee 8 bps.
- G4 t ≥ 2,5.
- G5 delta(E − A) ≥ +10 bps.
- G6 stress: mean alpha_net(E) pada fee **12 bps** ≥ 0.
- G7 kontrol: 200 sel acak (sisi acak × jendela 6 jam acak) harus **≥95% gagal G3**.
- G8 rezim dicatat per trade (BTC vs MA50h) sebagai **diagnostik**, bukan gerbang.

## Pohon keputusan
`DATA_INVALID` (G1/G2) | `GAGAL` | `LOLOS` → masih butuh OOS 30 hari + GO live terpisah.

## Catatan kejujuran
Sel ditemukan in-sample (8 sel diuji, BH lolos marginal untuk long; short lolos jelas).
Verdict hanya sah pada jendela forward, dan G7 wajib gagal. Pasar sedang lemah
(BTC −2,54% di bawah MA50h); bila rezim berbalik kuat, G8 akan menunjukkan apakah
efeknya bertahan — tanpa mengubah gerbang.
