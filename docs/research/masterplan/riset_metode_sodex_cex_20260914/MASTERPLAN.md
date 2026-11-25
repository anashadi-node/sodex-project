# MASTERPLAN RISET 30 JAM — Metode/Mode/Data Terbaik untuk SoDEX & CEX-Binance
**Divisi RISET Anantara Sakti | Komisi Mas Anas 2026-09-14 | Window: ~30 jam | Status: AKTIF**

## 0-B. KOREKSI ACUAN TARGET (WAJIB — per sumber otoritatif CLAUDE.md & memory, 27–30 Sep 2026)
```
SODEX  : ≥ 0,8% dari TOTAL MODAL WALLET (spot+perps) per rentang 30 jam — KUMULATIF
         (bukan per-trade). 0,8% = BATAS MINIMAL, wajib mampu MELAMPAUI. HARGA MATI.
CEX-B  : ≥ 0,8% kumulatif / 30 jam, basis sama.
ATURAN  : SoDEX & CEX-Binance DIUKUR TERPISAH — sampel TIDAK digabung.
CONFIG  : paper_test_realwide.py TARGET_MIN_PCT=0.008 ; sodex_maturation_tracker ;
          cex_go_no_go_gate.py
IMPLIKASI RISET: mencari metode yang membawa sistem ke 0,8% KUMULATIF/30j pada basis
         wallet penuh — bukan 0,7% per window. Bar naik => seleksi harus lebih ketat.
STATUS LANE UANG NYATA: SoDEX stop+disabled (30-09); spot_liquidator LIQ_DRY=1.
         => Riset tetap paper/research-only sampai ada unfreeze + approval user.
```

## 0-C. STATUS KANAL RISET (terverifikasi 14 Sep 2026)
```
HIDUP  : arxiv.org/search (HTML, size ∈ {25,50,100,200} SAJA — nilai lain => HTTP 400)
         arxiv.org/abs/<id>            (abstract)
         api.crossref.org/works        (metadata + citation count)
         api.openalex.org              (polite pool, perlu mailto=)
MATI   : web_search + web_extract    -> Nous/Firecrawl billing 402 (insufficient funds)
         export.arxiv.org api/query  -> timeout total
         api.semanticscholar.org/v1  -> HTTP 429 rate-limited
         papers.ssrn.com             -> 403 Forbidden
         doi.org (SSRN/MDPI redirect)-> 403
TOOLS  : harvest.py (arxiv|abs|crossref|openalex|stats) -> hits.jsonl
         batch3.py / batch4.py (driver multi-query)
```

## 0. FUNGSI DOKUMEN
Dokumen kontak-centris: state riset, checkpoint batch, bibliografi, kriteria kualitas.
Lanjutkan dengan APPEND ke Bibliografi & Konsolidasi. Setiap batch selesai = update checkpoint.

## 1. MANDAT
- Riset global ilmiah: metode/mode/data yang PALING SESUAI dengan karakteristik
  empirical SoDEX dan CEX-Binance (bukan riset umum trading).
- Target keputusan: daftar metode-priority dari bukti tertimbul (ranked), dengan
  expected impact rehat angka, dsb. Falsification-first semua.
- Output akhir: dokumen riset PDF+HTML+MD (3 file) dengan protokol verifikasi.

## 2. KARAKTERISTIK EMPIRIS (basis data terverifikasi sesi 12-14 Sep 2026)

### SoDEX (DEX perps, swing 1-30 jam, target >=0.7%/window, SHORT-BEAR prioritas #1)
```
Trades      : n=544 (SWING 203 | TWOWAY 211 | REALWIDE 130)
WR          : 44.12% agg (40.39 | 45.02 | 48.46) — SEMUA <50% KECUALI REALWIDE nyaris
Mean/trade  : +0.18% agg (+0.08 | +0.19 | +0.34)
Median      : -0.40% agg (NEGATIF semua track) → distribusi loss-kecil-banyak/win-besar-sedikit
SHORT       : TWOWAY-SHORT n=42 WR 33.3% avg -0.45% → SHORT = sisi terlemah terukur
Instrumen   : perp DEX long+short; maker/taker; funding; OBI 317k snp; fill predictor AUC .79-.83
Risk engine : governor leverage inv-vol + SL in-liq-safety + asset scoring + prob-threshold n R:R
BUKTI AVE   : mean positif tapi tipis → edge kecil ada; exit geometry makan edge
```
**Root-cause hipotesis dominan: EXIT GEOMETRY RENDAH KUALITAS (median -0.40% substrat)**

### CEX-Binance (Freqtrade+FreqAI/HMM, dry-run, target 0.7%/window HARGAMATI)
```
90d       : n=94 WR 36.17% wallet total -2.4998% → FALSIFIED aggregate
30d       : n=49 WR 22.45% -1.8635% (regresi era v8.8)
7d        : n=8 WR 25% +0.2715% gap vs 0.7% = -0.4285pp
expectancy: gate FAIL (mean_e -0.000266, frac_above_0=5.1%)
SPRT      : REJECT_EDGE llr -7.551
Deep loop : r6_bear n=23 WR69.6% E+0.55 PF1.61 | r8_neutral n=32 WR40.6 E+0.32 PF1.28
            r8_freqai n=21 WR 9.5% E-1.96 PF0.14 | r8_trend n=14 WR14.3% E-1.78 PF0.12
            vetoed=[] KEMUNGKINAN BUG PROPAGASI + binom p = .00011/.00647 → veto SHOULD fire
Blocklist : LINK_SHORT hard n=6 WR16.7% | ONDO_SHORT soft n=3
```
**Root-cause: komposisi jalur (path portfolio) kosmetiknya são 2 jalur killer**

## 3. MATRIKS RUANG RISET (RQ → metode global → karakteristik cocok)

### LANE S = SoDEX-fitting (Karakteristik: DEX perps, swing, median-anker, SHORT-weak, OBI data, governor)
| # | Dimensi | RQ | Mode ilmiah | Source class |
|---|---|---|---|---|
| S1 | Exit geometry | MAE/MFE, triple-barrier (Lopez de Prado), stop placement empiris | EMA/tail/backtest | papers+books+audits |
| S2 | Order-flow | OFI (Kukanov-Stoikov/Cont), depth imbalance, queue estimate | microstructure | papers+data |
| S3 | Funding signal | Apakah funding rate mem pengarah arah/jatuh-waktu short | regresi/event-study | papers |
| S4 | Regime | HMM/MS-SV, vol-targeting (Moreira-Muir), ensemble regime | quant | papers |
| S5 | Sizing | Fractional Kelly dalam leverage inv-vol, vol-targeting per trade | quant | papers |
| S6 | DEX-tokenomik | Sliver liquidity, spread widening, oracle risk response | microstructure | papers |
| S7 | Multi-agent/LLM arb | Seperti LLM-MAS crypto + execution overhead | papers | 133.52%/yr paper |
| S8 | Deep-loop learning | Data-pipeline konsisten belajar → path boost berbasis flushing | internal infra | internals |

### LANE C = CEX-Binance (Freqtrade+FreqAI+HMM, 2x leverage cap, dry-run harus tetap)
| # | Dimensi | RQ | Mode |
|---|---|---|---|
| C1 | Path governance | Bagaimana systems alokasi path meta meminimakam r8-style bleed | portfolio |
| C2 | Meta-labeling | Lopez de Prado Primary+Meta ganda-layer (подсgraphs FreqAI) | ML |
| C3 | Vol targeting | Moreira-Muir vol-managed pada leveraged swing | quant |
| C4 | Funding signal | Binance funding 8h prior-post window pada swing entry | event |
| C5 | Actual market impl | Binance tick-size rebal, maker rebates vs takers | microstructure |
| C6 | ML ensembles | LightGBM+regime (hasil FreqAI buruk = under-n?), akurasi vs baseline | ML |
| C7 | Walk-forward | Puas dengan OOS split tajam tak cukup - sit dsb | methodology |

## 4. CRITERIA SIFAT SIAPA SUMBER YANG MASUK
```
CONFIRMED   : paper peer-reviewed / eksperimenIndependen-kolong / dataset terbuka
PROMISING   : preprint dgn methodology baik / internal backtest terverifikasi
FALSIFIED   : hipotesis gagal OOS / internal evidence contradicts
INCONCLUSIVE: sample size buruk / review di-speculative dsb.
```

## 5. BATCH STATE
```
Batch 0 (fondasi)        : DONE   — masterplan + char matrix (dokumen ini)
Batch 1 (literature S1-S3 + C2-C4) : IN PROGRESS
Batch 2-5                : KAT-UNTUK-SELESAI, tiap batch checkpoint di file ini
```

## 6. CHECKPOINT LOG
```
[14 Sep ~18:00 WIB] Batch 0 selesai: masterplan dibuat.
```
