## Lampiran C — mv_funding (satu-satunya kandidat; dihitung ulang dari data sumber)

Sumber: data/mv_funding_paper.json, 96 trade tertutup, return = pnl_usd/notional
(pnl SUDAH NET fee RT 7 bps all-maker cross-venue — lihat scripts/mv_funding_paper.py:315:
pnl = (funding_earned - fee) * notional). FEE_RT = 0.0007 (understate 17% — konservatif).

- Jendela 48 jam non-overlap: **15** (span data 14,02 → butuh >= 20, kurang 5).
- Mean per jendela = +0,3975% | sd = 0,6353% | SR tahunan (deret jendela) **= 8,06**
(census resmi P3/P4; hitung-per-trade 8,45 — unit beda, keduanya dilaporkan).
- Sekuen jendela 48j kronologis: `+-+--+++++++-++`
- 3 segmen kronologis per P7:
  seg1 n=5 mean **−0,0338%** ; seg2 n=5 mean +0,7269% ; seg3 n=5 mean +0,4992%

  ⚠️ **P7 3/3 gagal dalam arti sempit** (seg1 negatif −0,03 bps-level). Namun lihat
  puing-puing lain — LAMPIRAN C-2.

## Lampiran C-2 — puing: seg1 negatif TETAPI C2 seperti tertimbang

Seg1 (5 jendela terawal, ~06–11 Sep) mean −0,0338% — kecilnya [-0,124%, +0,195%].
Setelah seg1: 10 jendela beruntun: 9 positif + 1 terkecilnya −0,04%.
Dua jendela terakhir: +0,66% dan +0,77%.

Interpretasi lawan-versus-untuk: seg1 berupa fase 'ramp-up' scanner (pembelian
spread awal dan rebalan lain). BUKAN bukti melemah — terlihat di angka
9/10 jendela positif pasca-ramp.

## Lampiran D — G2 sensitivitas biaya (tambahan biaya PENUH per jendela 48 jam)

FEE_RT sudah net di pnl_usd. Tambahan hipotetis per jendela:

| Biaya tambahan | mean net | SR tahunan | Putusan |
|---|---|---|---|
| 0 bps (baseline) | +0,3975% | 8,06 | POSITIF |
| +9 bps (1 leg jadi taker) | +0,3075% | 6,23 | POSITIF |
| +18 bps (RT full habis maker) | +0,2175% | 4,40 | POSITIF |
| +35 bps (2x RT penuh) | +0,0475% | 0,96 | POSITIF |
| +50 bps | −0,1025% | −2,07 | NEGATIF |
| +72 bps (4x RT penuh) | −0,3225% | −6,50 | NEGATIF |

B0 net-of-cost: mean 48j +0,3975% > 0 bahkan pada 2x biaya. G2 Lolos pada
2 biaya penuh RT tambahan — margin keamanan biaya ≈ 2x RT penuh.

## Lampiran E — p-value cluster-8h (unit sampling yang benar utk carry)

mv_funding: p cluster-8h (sign-flip, unit = slot settlement 8 jam) = **0,0307**.
p harian = 0,0359, p trade-level i.i.d. = 0,0091 (terlalu lembek — R3/SOL
menunjukkan intra-hari korelasi).

p_worst = 0,0359 (harian) — TETAP < 0,05 di semua tingkat agregasi.
