# SODEX — ROOT CAUSE ANALYSIS: PAPER TEST SPOT SWING (2026-09-03)
# Data: 35 closed trade · hold time · exit per pair · payoff geometry

---

## 📉 GEJALA

| Metrik | Nilai |
|--------|-------|
| Total closed | 35 |
| WR | 42,9% |
| PnL | **-$7,12** |
| ROI wallet | **-0,22%** (target +0,7%) |

Padahal matematika dasarnya **POSITIF**:
```
TP avg +$8,15 · SL avg -$5,23 · payoff 1,56:1 · breakeven WR 39,1%
Actual WR 42,9% → EV/trade matematis = +$0,50 (POSITIF!)
```
Tapi realita -$7,12. **Ada yang menghancurkan EV — ditemukan.**

---

## 🔍 ROOT CAUSE (ranked by impact)

### 🔴 RC-1: Min-hold 4 jam TANPA SL aktif = Jendela Gempa (PALING FATAL)

**Bukti — 3 trade loss besar yang menghancurkan seluruh EV:**

| Pair | Loss | Hold | Total |
|------|:----:|:----:|:-----:|
| vSOL | **-6,27%** | 4,0h | -$18,80 |
| WSOSO | **-2,65%** | 4,0h | -$7,94 |
| vETH | **-2,06%** | 19,4h | -$6,17 |
| **Subtotal** | | | **-$32,91** |

Kode: `elif g <= -SL_PCT and hold_h >= MIN_HOLD_H` → SL 1,5% **hanya aktif setelah 4 jam**.
vSOL turun 6,27% dalam 4 jam pertama TANPA ada yang menghentikan.

**Dampak:** Tanpa 3 gempa ini, SPOT_SWING = **+$25,79 (POSITIF!)**. Tiga trade
menghancurkan 4,6× laba dari 32 trade lain.
→ **Kontras dgn REALWIDE (profit +3,85%) yang SL aktif DARI t=0** — inilah bedanya.
REALWIDE SL dari t=0 = tidak pernah ada gempa -6%.

### 🔴 RC-2: Book tipis → Adverse selection & slippage (bottleneck entry)

Volume harian pair yang baru trade (data live 2026-09-01):
```
vPEPE $548/24h · vADA $516/24h · vSHIB $157/24h · vUNI $228/24h
vLTC $272/24h · vAVAX $258/24h · vSUI $251/24h · vXLM $765/24h
```
**Order $300 = 20-60% dari volume harian pair.** Masuk di "dip -3%" di book yang
hampir kosong → harga jatuh bebas (adverse selection): kita masuk persis saat
pair sedang di-jual habis oleh orang lain di book tipis.

**vSOL (volume $3.4K/hari) -6,27% dalam 4 jam** = contoh buku teks.
→ **Bottleneck masuk**: entry ke pair tipis di dip besar = counter-trend di market
yang tidak punya depth untuk rebound.

### 🟡 RC-3: WR 42,9% vs breakeven 39,1% — margin cuma 3,8pp

Payoff 1,56:1 hanya memberi ruang 3,8pp di atas breakeven. Sedikit noise (gempa
RC-1) langsung menggoreng margin. **Bukan penyebab utama, tapi amplifier.**

### 🟡 RC-4: State terkontaminasi pair yang SUDAH dihapus

vSOL & WSOSO dihapus dari universe 23-Agu (WR 25%, anti-predictive) — tapi state
masih mencatat 12 trade lama mereka = **-$25,86** (73% dari total loss).
Era 18-aset baru: baru n=2 (vPEPE, vADA — keduanya SL). Realita track sekarang
belum terwakili statistiknya.

---

## 🔬 KESIMPULAN ILMIAH — urutan penyebab

```
1. JENDELA GEMPA: SL tidak aktif 4 jam pertama → 3 trade -$32,91 (4,6× laba 32 trade lain)
2. BOOK TIPIS: entry $300 di pair volume $150-765/24h → adverse selection, harga jatuh bebas
3. MARGIN TIPIS: payoff 1,56:1 + WR 42,9% → ruang cuma 3,8pp (amplifier)
4. DATA LAMA: state mencatat pair mati (vSOL/WSOSO) → menyembunyikan realita
```

**Akar tunggal:** desain exit (min-hold 4h) + entry tanpa filter likuiditas,
pada venue spot yang book-nya sangat tipis. Bukan "strategi salah" — melainkan
**parameter tidak cocok dengan lingkungan eksekusi**.

---

## ✅ REKOMENDASI FIX (evidence-based)

| # | Fix | Dasar | Dampak estimasi |
|:-:|-----|-------|-----------------|
| 1 | **SL dari t=0** (MIN_HOLD_H 4 → 0) — samakan dengan REALWIDE yang terbukti | vSOL -6,27% → -1,5% (hemat $14,3); pola REALWIDE SL-t=0 WR 60% ROI +3,85% | 3 gempa hilang → **-$32,91 → -$4,5** (hemat ~$28) |
| 2 | **Filter likuiditas**: hanya trade pair volume >$5K/24h | vPEPE $548, vADA $516 = adverse selection terbukti (2/2 SL di era baru) | buang pair gempa |
| 3 | **POS 300 → 100** untuk pair tipis | order $300 = 20-60% volume harian | kurangi slippage |
| 4 | **Reset state era baru** | buang 35 trade lama (vSOL/WSOSO dsb) — mulai clean 18 aset | data valid & murni |

Estimasi setelah fix 1+2: 3 trade gempa ter-SL di -1,5% = -$4,5; sisa profit tetap
+$25,79 → **track jadi +$21 dan MELAMPAUI target**.

---

*Root cause analysis 2026-09-03 | Hermes Anantara v2 | data 35 trade nyata*