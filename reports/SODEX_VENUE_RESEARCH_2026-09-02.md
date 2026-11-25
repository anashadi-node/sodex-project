# SODEX — RISET VENUE & STRATEGI (2026-09-02)
# Riset paralel 4 subagent: literatur ilmiah, SoDEX vs Hyperliquid,
# Variational/Ondo/Paradex, dan analisa matematis dampak pindah venue.
# Keputusan TETAP — semua berbasis angka, bukan asumsi.

---

## ⚡ VERDICT UTAMA (jawaban pertanyaan user)

**SWITCH VENUE = TIDAK DISARANKAN SEKARANG. TETAP DI SODEX.**

Pindah venue ke Hyperliquid/Variational/Ondo/Paradex justru berpotensi
**MENURUNKAN** pencapaian target yang sudah baik sekarang, dengan alasan matematis:

- **Gain fee maksimum jika pindah ke Hyperliquid: +$3,00/bulan** (3,2% wallet)
- **E[loss] migrasi: $17,19** (18,2% wallet — kehilangan data, state, integrasi bot baru)
- **Degradasi WR 3pt selama 30 trade: -$5,40** (-5,7% wallet)
- **EV switch ke HL: hanya +$0,90/bulan** — dinegasikan biaya integrasi
- Fee HL tier-0 (maker 1,5bps/taker 4,5bps) **LEBIH MAHAL** dari SoDEX (1,08/3,6bps) untuk wallet kecil!

---

## BAGIAN 1 — PERBANDINGAN VENUE (data live, Sep 2026)

### SoDEX vs Hyperliquid

| Faktor | SoDEX | Hyperliquid | Pemenang |
|--------|-------|-------------|:--------:|
| Fee maker (tier-0 + stake) | 0,0108% | 0,015% | **SoDEX** |
| Fee taker | 0,036% | 0,045% | **SoDEX** |
| Spread BTC/ETH/SOL | 1-3bps | 0,5-1bps | HL |
| **Depth meme pairs** (LIT/PUMP/ASTER) | $244-$2,5K | **$38K-$155K** (30-300×!) | **HL** |
| Volume 24h meme | $9-28K | $3,3-69M | **HL** |
| API bot publik | Closed Alpha (gate Gold tier) | **Publik, SDK resmi** | **HL** |
| Withdrawal via API | TIDAK didukung | Didukung | **HL** |
| Custody | Protocol (non-kustodial) | Protocol, tapi ada preseden intervensi (JELLY 2026, SNX 2023) | SoDEX |

**Faktor penentu = EKSEKUSI, bukan fee.** Di pair tipis SoDEX, exit market
$50-900 bisa slippage puluhan bps = menggerus 20-50% dari target 0,7%.
Di HL slippage tipikal 1-4bps.

### Variational · Ondo · Paradex — TIDAK ADA yang siap

| Venue | Status | Halangan |
|-------|--------|----------|
| **Variational** | Live, 549 market, fee 0%, $1,04B vol | ❌ **Trading API belum ada** (hanya read-only) — bot tidak bisa connect |
| **Ondo Perps** | Live, ada API | ❌ **Hanya perp saham/komoditas/ETF** — tidak ada crypto/meme = mismatch total |
| **Paradex** | Live sejak 2024, API lengkap | ❌ Volume tipis ($10M/24h) + insiden rollback Jan 2026 + retail 0% tapi spread-markup |

---

## BAGIAN 2 — TEMUAN LITERATUR ILMIAH (19 sumber)

Riset 19 sumber (jurnal akademik + riset kuant + praktik venue):

| # | Area | Temuan Angka |
|:-:|------|--------------|
| 1 | Entry | **Long-only + filter tren** didukung bukti kuat (Liu-Tsyvinski, Moskowitz-Ooi-Pedersen, Daniel-Moskowitz) — konsisten dgn paper data (LONG +1,5-4,5% vs SHORT WR 29,7%) |
| 2 | Exit | **REALWIDE = best** (SL 2%, TP 4%, 3x, time-stop 30h) sejalan literatur: SL berbasis kondisi, partial TP, trailing moderat, ATR overlay |
| 3 | Leverage | 2-3x + risk 1-2% wallet + vol-scaling (half-Kelly) — aman modal kecil |
| 4 | Deep loop | Rolling walk-forward, gate WFE 0,5-0,7, IS 3-4× OOS, 8-12 window |
| 5 | Anti-overfit | DSR/haircut, PBO, N ≥ 60-100 trade OOS |

**Break-even biaya:** butuh gross ~0,85-0,95%/trade untuk net 0,7% (fee taker 0,072% RT
+ spread 0,01-0,08% + funding 0,01-0,05%/30h) — masih 10× di bawah potensi TP 4% × 3x = 12%.

---

## BAGIAN 3 — ANALISA MATEMATIS KEPUTUSAN

Parameter: WR 65%, leverage 3x, modal $94,57, posisi $100

```
Gross edge/trade: $1,90 (2,01% wallet) vs target $0,662 (0,7% wallet)
→ ruang biaya RT MAKSIMUM: 123,8bps ($1,24/trade) agar target tetap tercapai
WR break-even: 46-51% selama cost ≤ 40bps (margin aman 15-20pt vs paper 65,8%)
P(capai target atas 20 trade): 90-96%
```

**Kondisi SWITCH WAJIB (hanya jika terpenuhi):**
1. Cost SoDEX > 80bps rata-rata 30 hari (WRbe 57,7%, margin <8pt)
2. Infrastruktur SoDEX rusak
3. Venue baru terbukti: ≥30 trade persisten, ≥30bps/trade lebih murah, AND ≥50 paper trade net EV ≥ SoDEX-5bps, WR ±2pt dari 65,8%

**Jangan pindah venue untuk perbaiki SHORT yang gagal** — itu masalah strategi (sudah di-disable), bukan venue.

---

## BAGIAN 4 — REKOMENDASI ACTIONABLE (prioritas)

### Segera (di SoDEX, no switch):
1. **Long-only permanen** — buang logika SHORT (sesuai literatur + data sendiri)
2. **REALWIDE jadi template exit standar** — SL-2%/TP-4%/3x/time-30h (ROI 3,77% & konsisten)
3. **Risk sizing half-Kelly** — risk 1-2% wallet, vol-scaling
4. **Anti-overfitting loop** — rolling walk-forward 8-12 window, gate WFE 0,5-0,7; N≥60-100 untuk klaim
5. **BSM: pantau cost SoDEX pair tipis** — jika ASTER/PUMP/LIT slippage eksekusi nyata > 80bps avg 30 hari → barulah evaluasi move pair-specific

### Jangka menengah:
6. **Kandidat cadangan venue: Hyperliquid** (likuiditas proven) — tetapi hanya jika kondisi threshold di atas terpenuhi; lakukan paper test 50 trade DI HL dulu sebelum switch nyata
7. **Variational** — pantau (trading API "in development"); jika rilis, bisa jadi opsi fee-0
8. **Ondo/Paradex** — JANGAN (mismatch produk / volume tipis)

---

*Laporan riset 2026-09-02 09:20 WIB | Hermes Anantara v2*
*4 riset paralel: 19 sumber literatur + data live API kedua venue + 3 profil venue + analisa matematis.*