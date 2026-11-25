# D14 — Protokol Sensus Edge (PRA-REGISTRASI)

**Status: DITETAPKAN SEBELUM MENGUJI.** Berkas ini ditulis dan di-commit **sebelum**
evaluasi dijalankan. Sesudah hasil keluar, isinya **tidak boleh** diubah.
Tanggal deklarasi: 05-Okt-2026 · Registry trial: akan menjadi **38** setelah dijalankan.

---

## 1. Pertanyaan yang dijawab

Bukan "apakah REAL-wide punya edge" (sudah dijawab R3: belum terbukti), melainkan:

> **Dari SELURUH mesin yang berjalan di ekosistem ini, berapa yang punya edge
> yang tervalidasi — dan apakah cukup untuk mencapai target?**

Ini pertanyaan yang benar karena jalur target yang ditetapkan adalah
**portofolio 6–8 mesin**, bukan satu mesin yang sempurna.

## 2. Aritmetika target — mengapa Sharpe-nya harus ~4,6

Target **0,8% per 48 jam** yang dimajemukkan:

```
0,8% / 48 jam  ->  0,4% / hari  ->  (1,004)^365 - 1  =  +328% / tahun
```

Sharpe tahunan = (mean per 48 jam / sigma per 48 jam) x sqrt(182,5).

| sigma 48 jam | Sharpe tahunan yang dibutuhkan untuk mean 0,8%/48 jam |
|---|---|
| 1,60% | 6,8 |
| 2,00% | 5,4 |
| **2,35%** (realistis utk portofolio kripto) | **4,6** |
| 3,00% | 3,6 |

Dengan **6 mesin** masing-masing Sharpe tahunan **2,3** dan korelasi **ρ = 0,10**:

```
S_portofolio = 2,3 x sqrt( 6 / (1 + 5 x 0,10) ) = 2,3 x 2,00 = 4,60
```

**Cocok.** Karena itu syarat yang ditetapkan:

> **Setiap mesin: Sharpe TAHUNAN >= 2,3** (setara **0,170 per 48 jam**) dengan
> **ρ antar-mesin <= 0,10**, dan **perlu 6–8 mesin** yang lulus.

## 3. Protokol — ditetapkan sebelum melihat hasil

| # | Aturan |
|---|--------|
| P1 | **Kandidat** = SEMUA mesin dengan >= 20 trade tertutup yang menyimpan return per-trade. Daftar dibekukan di Lampiran A **sebelum** menjalankan. |
| P2 | **Metrik** = return per-trade (fraksi). Sharpe **invarian skala**, jadi `pnl_pct` maupun `pnl_usd` sama-sama sah — asalkan **konsisten di dalam satu mesin**. |
| P3 | **Return jendela 48 jam** = jumlah return per-trade yang exit di dalam jendela itu, non-overlap, anchor = exit pertama. |
| P4 | **Sharpe tahunan** = (mean/σ dari deret jendela 48 jam) x sqrt(182,5). |
| P5 | **p cluster-honest** = bootstrap resample **per HARI**, >= 20.000 iterasi, seed tetap. |
| P6 | **p TERBURUK menentukan.** Bila ada kontrol acak, p berpasangan vs kontrol masuk hitungan; yang dipakai = **p terbesar**, bukan terkecil. |
| P7 | **Ketahanan** = 3 segmen kronologis, butuh **3/3 positif**. Segmen dengan n < 5 dilaporkan **`-`** (belum dapat dinilai), bukan `no`. |
| P8 | **Multiple testing** = **BH-FDR q = 0,10 atas SELURUH keluarga sekaligus** (bukan per mesin). |
| P9 | **LULUS** bila: n_windows >= 20 **DAN** Sharpe_48j >= 0,170 **DAN** 3/3 segmen positif **DAN** p_terburuk < 0,05 **DAN** lolos BH-FDR. Kelima-limanya. |
| P10 | **Korelasi** = ρ Pearson pada return jendela 48 jam, hanya antar mesin yang lulus (P9). |
| P11 | **Kontrol RANDOM dibuang** dari track sinyal (pelajaran R3: kalau tidak, uji alpha membandingkan sinyal dengan dirinya sendiri). |
| P12 | **Data-hygiene**: baris ledger yang identik-butir-per-butir (entry_time, exit_price, pnl sama persis) atau `close_rc` kosong pada mesin uang-nyata DIBUANG sebagai artefak audit-log (bukan trade). Ditemukan 05-Okt: 171 baris ETH KILL_FLATTEN palsu (semua exit_price=2486,22, close_rc=None) = dry-run pre-guard insiden 25-Sep mencemari ledger; baris valid = 7 dgn close_rc=0; sumber kebenaran = state JSON (+1 VENUE_RECONCILE). |

## 4. Yang TIDAK boleh dilakukan setelah berkas ini di-commit

- ❌ Mengubah ambang P9 setelah melihat hasil.
- ❌ Menambahkan mesin ke keluarga setelah melihat hasil (kecuali dicatat sebagai trial baru yang terpisah).
- ❌ Memilih jendela waktu, simbol, atau periode yang menguntungkan.
- ❌ Menghapus mesin yang hasilnya jelek dari laporan.
- ❌ Mengganti statistik uji setelah melihat mana yang lolos.

## 5. Batasan yang DIAKUI di muka (sebelum ada hasil)

| # | Batasan | Konsekuensi yang diterima |
|---|---------|---------------------------|
| B1 | Banyak mesin berbagi data pasar yang sama (alt-vs-BTC). | Korelasi **struktural** > 0. **ρ <= 0,10 mungkin MUSTAHIL dicapai** — dan itu temuan yang sah, bukan kegagalan analisis. |
| B2 | Sebagian mesin menyimpan return **gross-of-fee**. | Ditandai `GROSS`. Mesin yang tandanya berbalik setelah biaya **tidak dianggap lulus**. |
| B3 | Mesin ber-n kecil menghasilkan CI lebar. | Dilaporkan `-`, bukan `no`. Tidak diklaim apa pun. |
| B4 | Beberapa mesin berjalan di jendela waktu yang berbeda. | Perbandingan lintas-mesin sah untuk **Sharpe** (invarian skala), **tidak** sah untuk PnL absolut. |
| B5 | Return jendela menjumlahkan return per-trade dengan asumsi notional seragam. | Ini **mengabaikan plafon margin** (temuan R2: paper 8,6x live). Sharpe tetap sah (skala konstan), tetapi **tingkat return absolut TIDAK boleh dibaca sebagai hasil wallet**. |

## 6. Lampiran A — daftar mesin yang dibekukan (SEBELUM menjalankan)

| # | Mesin | Berkas | n | Satuan |
|---|-------|--------|---|--------|
| 1 | realwide | `data/paper_test_realwide_state.json` | 246 | pnl_pct |
| 2 | realwide_atrvolopen (A2) | `data/paper_test_realwide_state_atrvolopen.json` | 63 | pnl_pct |
| 3 | realwide_atrvol (A1, mati) | `data/paper_test_realwide_state_atrvol.json` | 25 | pnl_pct |
| 4 | donchian | `data/paper_test_donchian_state.json` | 195 | pnl_pct |
| 5 | portfolio | `data/paper_test_portfolio_state.json` | 65 | pnl_pct |
| 6 | pasar_anantara_trade | `data/paper_test_pasar_anantara_trade_state.json` | 47 | pnl_pct |
| 7 | shortbear | `data/paper_test_shortbear_state.json` | 26 | pnl_pct |
| 8 | twoway | `data/paper_test_twoway.jsonl` | 383 | pnl_pct |
| 9 | swing | `data/paper_test_swing.jsonl` | 453 | pnl_pct |
| 10 | swing_partial | `data/paper_test_swing_partial.jsonl` | 480 | pnl_pct |
| 11 | swing_strict | `data/paper_test_swing_strict.jsonl` | 112 | pnl_pct |
| 12 | swing_atrvol | `data/paper_test_swing_atrvol.jsonl` | 47 | pnl_pct |
| 13 | spot_swing_cex | `data/paper_test_spot_swing_cex_trades.jsonl` | 464 | pnl_pct |
| 14 | spot_swing_cex_spot | `data/paper_test_spot_swing_cex_spot_trades.jsonl` | 156 | pnl_pct |
| 15 | e2_momentum | `data/e2_momentum_paper.jsonl` | 433 | pnl_pct |
| 16 | hl_replay | `data/hl_paper_replay_journal.jsonl` | 2185 | net_pct |
| 17 | aster | `data/paper_test_aster_state.json` | 200 | net_pct |
| 18 | hyperliquid | `data/paper_test_hyperliquid_state.json` | 169 | net_pct |
| 19 | spot_swing_v2 | `data/paper_test_spot_swing_v2_state.json` | 212 | gross_pct **GROSS** |
| 20 | mv_funding | `data/mv_funding_paper.json` | 96 | pnl_usd/notional |
| 21 | micro_live (uang nyata) | `data/realwide_micro_live.jsonl` | 8 | net_pct |

Keluarga = **21 mesin**. n_trials naik **37 -> 38** (satu uji keluarga, dengan
penalti multiple-testing BH-FDR atas 21 hipotesis).

## 7. Lampiran B — kontrol negatif

Kontrol = track `RANDOM` di `paper_test_realwide` & `..._atrvolopen` (dibuang dari
track sinyal, diuji terpisah). Harapan: kontrol **TIDAK** lulus P9. Bila kontrol
lulus, alat ukurnya rusak dan **seluruh** hasil dibatalkan (aturan langkah 7
skill `signal-gate-falsification`).

---

*D14 · pra-registrasi · 05-Okt-2026 · Hermes Anantara v3*
*Berkas ini di-commit SEBELUM evaluasi dijalankan. Hasil ada di D14 (bagian hasil).*