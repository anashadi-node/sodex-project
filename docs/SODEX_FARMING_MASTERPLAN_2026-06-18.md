# SoDEX Farming — Masterplan Ilmiah Menuju Target Maksimal

> Disusun: 2026-06-18 · Penulis: Claude (Opus 4.8) · Berbasis bukti jujur (B13–B19)
> Anchor doktrin: [SODEX_FARMING_DOCTRINE.md](SODEX_FARMING_DOCTRINE.md)
> Prinsip: falsification-first, data riil, "tidak rugi", security-first.

---

## 1. Target resmi (dari doktrin) — yang harus dicapai maksimal

| # | Target | Nilai | Horizon |
|---|--------|-------|---------|
| T1 | Volume transaksi mingguan | **≥ $1.300.000** | 7 hari (Sabtu 07:00 WIB) |
| T2 | Rasio transaksi profit mingguan | **> 69%** | mingguan |
| T3 | Cost coverage — E1 profit cover E2 fees | **E1 profit ≥ E2 fees** | mingguan |
| T4 | Real Rasio (volume/fee) | **≥ 1:9.100** (min); **No-Loss** (max) | mingguan |
| T5 | Net mingguan | ≥ 0 (cenderung untung kecil) | mingguan |
| T6 | SoPoints | maksimalkan pangsa pool (∝ volume + konsistensi) | mingguan |

Semua diukur dengan **monitor jujur B16** (`monitor` / `data/twin_monitor_latest.json`) sebagai sumber kebenaran tunggal.

---

## 2. Keadaan jujur saat ini (bukti, bukan asumsi)

| Fakta | Nilai | Sumber |
|-------|-------|--------|
| Modal riil (equity) | ~$186 | balance() riil |
| Volume mingguan jujur | kecil (sisanya phantom pra-B13) | ledger B13 |
| E1 maker pasif net rate | **−0,0626%/RT, win 32%** (n=31) | RT jujur post-B13 |
| Status E1 | **PAUSED** oleh gate (rugi jujur) | B14/B17 |
| E2 (volume perps) | OFF (Fase 1) | watchdog |
| Spread PEPE / SHIB | 34,7 bps / 20,9 bps | B18 sampler |

**Kesimpulan ilmiah kunci:** maker pasif PEPE/SHIB **tidak ber-edge** (adverse selection ~17 bps menelan separuh-spread). Ini **mengarahkan kembali ke mandat doktrin**: profit harus datang dari **prediksi arah**, bukan market-making pasif. Volume adalah HASIL dari profitabilitas, bukan tujuan buta.

---

## 3. Dekomposisi masalah (5 faktor harus benar bersamaan)

Target hanya tercapai bila KELIMA faktor positif simultan:

```
SUKSES = EDGE (profit/RT > 0)  ×  VOLUME (≥$1,3M/mgg)
         ×  COST-COVERAGE (E1 profit ≥ E2 fees)  ×  REAL-RASIO (≥1:9.100)
         ×  SoPOINTS-EFISIENSI (poin/$ tinggi)
```

Bila satu faktor nol/negatif, target gagal. Prioritas ilmiah: **buktikan EDGE dulu** (faktor terlangka), baru skala VOLUME.

**Real Rasio diukur sebagai:** `official_credited_volume / max(0, fees − E1_realized_profit)`.
- **Minimum `1:9.100`**: volume ≥ 9.100 × net cost.
- **Maximum No-Loss**: `E1_realized_profit ≥ total_fees_E1 + total_fees_E2` — E1 profit menutupi SEMUA biaya, E2 loss diminimalisir via prediksi arah presisi.

---

## 4. Analisis kuantitatif feasibilitas $1,3M/minggu

**Biaya fee untuk $1,3M volume:**
| Rute | Fee maker 1-sisi | Fee bolak-balik | Biaya $1,3M/mgg |
|------|------------------|-----------------|------------------|
| PERPS | 0,0108% | 0,0216% | **~$280/mgg** |
| SPOT | 0,0315% | 0,0630% | ~$819/mgg |

→ **PERPS = rute volume termurah** (2,9× lebih murah). E2 (volume engine) wajib perps.

**Beban relatif modal:** $280/mgg pada modal $186 = **150%/minggu** fee burn. Ini MUSTAHIL ditutup profit kecuali salah satu:
1. **Edge direksional kuat** menghasilkan ≥ +$280/mgg (perlu ~150% return/mgg di $186 — tidak realistis pada modal sekecil ini), ATAU
2. **Maker rebate tier** — pada pangsa volume tinggi, maker DIBAYAR (fee negatif) → fee jadi pendapatan, ATAU
3. **Nilai SoPoints > biaya** — burn $280/mgg dibenarkan bila ekspektasi nilai airdrop > $280/mgg (perlu estimasi nilai SoPoint).

**Implikasi modal (jujur):** $1,3M/mgg pada $186 = **6.989× turnover mingguan** — secara mekanis perlu kecepatan ekstrem + leverage perps. Pada modal sekecil ini, target $1,3M **kemungkinan besar tidak feasible tanpa**: (a) maker-rebate tier, dan/atau (b) tambahan modal signifikan, dan/atau (c) leverage tinggi (naikkan risiko). Ini harus dihadapi jujur sebelum mengejar volume buta.

**Rekomendasi feasibilitas:** tetapkan target volume **bertahap & terkalibrasi pada modal**, bukan langsung $1,3M. Mis. mingguan: buktikan ekonomi positif pada $50K → $200K → $500K → $1,3M, naik HANYA bila per-faktor terbukti sehat. "Catch-up mode" doktrin = ramp terukur, bukan burn nekat.

---

## 5. Roadmap berfase (tiap fase: hipotesis → eksperimen → gate keputusan → metrik → budget)

### FASE 0 — Fondasi jujur ✅ SELESAI (B13–B19)
- Akunting balance-delta (B13), gate self-governing honest-aware (B14/B17), tracker net mingguan (B15), monitor otonom data-riil (B16), riset spread nol-risiko (B18), harness eksperimen ber-budget (B19).
- **Gate lulus:** semua metrik kini terukur jujur. Tanpa ini, semua keputusan berikutnya buta.

### FASE 1 — Falsifikasi/validasi maker pasif (SEKARANG)
- **Hipotesis H1:** maker profit bila quote hanya saat spread lebar (≥50bps).
- **Eksperimen:** B19 ber-budget ($3 maks, n=100), OFF sampai disetujui. Jalankan `e1research` (nol-risiko) dulu → bila spread JARANG ≥50bps, H1 gugur tanpa eksperimen.
- **Gate keputusan:** CI mean PnL/RT. SUPPORTED → jadikan E1 sumber profit; FALSIFIED → tinggalkan maker pasif, fokus direksional.
- **Metrik:** net rate jujur di spread lebar. **Budget:** ≤ $3.

### FASE 2 — Edge DIREKSIONAL di SoDEX (inti doktrin)
- **Hipotesis H2:** sistem prediksi arah proyek (Pre-Gain/Pre-Sentiment/intelligence) menghasilkan win-rate jujur > breakeven di eksekusi SoDEX.
- **Metode:** port sinyal direksional yang sudah ada → eksekusi SoDEX (spot/perps), ukuran kecil, instrumented (akunting B13).
- **Eksperimen:** paper/micro-live ber-budget; ukur WR jujur per sinyal/sesi/coin (seperti disiplin Pre-Gain di CEX).
- **Gate keputusan:** WR jujur > breakeven (≈ tergantung payoff; doktrin target >69%) dengan n cukup (bootstrap CI P(E>0) ≥ 90%).
- **Metrik:** WR jujur, E(R)/trade, profit mingguan. **Budget:** ber-cap, kill bila DD.

### FASE 3 — Volume engine (E2 perps) didanai edge
- **Hipotesis H3:** dengan sumber profit (Fase 1 atau 2) + perps maker murah, volume dapat di-skala sambil net mingguan ≥ 0.
- **Metode:** E2 churn perps maker (B1–B14 sudah hardened: crash-recovery, ghost-sweep, treasury G6). Treasury G6 batasi belanja E2 = max(0, profit E1) + sisa principal_fee_cap.
- **Eksperimen:** aktifkan E2 (TE_E2_ENABLED=1) HANYA setelah Fase 1/2 buktikan profit jujur > 0. Ramp volume bertahap ($50K→...).
- **Gate keputusan:** net mingguan ≥ 0 (monitor B16) DAN coverage E1/|E2| ≥ 1. **Metrik:** volume/mgg, coverage, net.

### FASE 4 — Optimasi SoPoints
- **Hipotesis H4:** poin/$ dimaksimalkan via (a) maker-rebate tier (fee negatif), (b) konsistensi harian (anti-wash compliant), (c) rute & pair efisien.
- **Metode:** riset tier rebate sodex.com (volume share → rebate), distribusikan volume agar konsisten harian, hindari pola wash.
- **Gate keputusan:** poin/$ terukur naik; rebate tier tercapai → fee jadi pendapatan (mengubah ekonomi Fase 4 §4 poin 2).
- **Metrik:** SoPoints/minggu, poin per $1K volume, $ cost per 1K poin.

### FASE 5 — Governance mingguan & skala modal
- **Mode adaptif** (doktrin): STRICT (edge belum terbukti → paper), BALANCED (edge tipis → ukuran kecil), FARMING (edge sehat → ramp volume), CATCH-UP (di bawah target + edge sehat → percepat terukur).
- **Keputusan modal:** tambah modal HANYA setelah ekonomi per-dollar terbukti positif jujur (poin/$ + net mingguan ≥ 0). Skala linear pada edge terbukti, bukan harapan.
- **Gate keputusan:** keputusan modal/skala mingguan pada snapshot Sabtu 07:00 WIB, berbasis monitor jujur.

---

## 6. Aturan keputusan & disiplin risiko (lintas fase)

- **Setiap fase ber-budget kerugian eksplisit** (cap keras, auto-halt — pola B19).
- **Tidak ada fase berikut tanpa gate fase sebelumnya lulus** (no skipping).
- **Monitor jujur B16 = sumber kebenaran tunggal**; verdict berbasis data jujur (post-B13), bukan phantom.
- **Self-governing gates** (B14/B17) tetap aktif: auto-pause pada EV negatif.
- **Security-first**: tidak ada secret di CLI/log; dry-run/paper default; live butuh flag eksplisit.
- **Snapshot mingguan Sabtu 07:00 WIB** = titik evaluasi & keputusan resmi.

---

## 7. Metrik sukses akhir (definisi "maksimal tercapai")

Target tercapai maksimal bila, pada snapshot mingguan jujur:
1. Volume ≥ $1,3M (T1) — ATAU target bertahap terkalibrasi-modal yang disepakati.
2. Win-rate direksional jujur > 69% (T2).
3. E1 profit ≥ E2 fees — cost coverage engine model (T3).
4. Real Rasio ≥ 1:9.100 DAN No-Loss (E1 profit ≥ total fees) (T4).
5. Net mingguan ≥ 0 (T5).
6. SoPoints/$ termaksimalkan + rebate tier tercapai (T6).
7. Semua dicapai dalam budget risiko, tanpa stuck/ghost/phantom (B1–B17 menjamin).

---

## 8. Tindakan langsung berikutnya (prioritas)

1. **Jalankan `e1research`** setelah daemon kumpulkan sampel spread beberapa jam → putuskan apakah Fase 1 (eksperimen B19) layak atau langsung gugur.
2. **Bila maker pasif gugur** → mulai Fase 2: rancang port sinyal direksional Pre-Gain → SoDEX (paper dulu, instrumented).
3. **Riset tier rebate sodex.com** (Fase 4 prasyarat ekonomi) — apakah volume tinggi → fee negatif? Ini mengubah seluruh kalkulus feasibilitas.
4. **Estimasi nilai SoPoint** (bila tersedia data) → tentukan apakah burn fee dibenarkan oleh nilai airdrop.

> Catatan jujur: pada modal $186, target $1,3M/mgg yang "cost-covered murni dari profit" kemungkinan TIDAK feasible tanpa rebate tier dan/atau modal tambahan. Plan ini mengejar target secara bertahap & jujur, bukan dengan burn nekat yang melanggar prinsip "tidak rugi".
