# BAB DIVISI — SoDEX (Anantara Sakti)

> Bagian dari dokumen master **Ekosistem Anantara Sakti · 2026-09-26**
> Mode: **READ-ONLY dokumentasi**. Semua angka bersumber (path + baris/kunci, atau perintah + timestamp).
> Angka yang tidak dapat diverifikasi ditulis **NO-DATA** beserta cara memperolehnya.
> Kebijakan dokumen: seluruh isi keamanan/privacy (kredensial, isi `.env`, alamat dompet/akun,
> konfigurasi auth/izin, hasil audit keamanan, langkah pengerasan) **DIKECUALIKAN (kebijakan dokumen)**.

---

## 1. Identitas Entity

| Atribut | Nilai | Sumber |
|---|---|---|
| Nama divisi | **SoDEX** | `SODEX.md:1` |
| Venue operasi | sodex.com ("primary market: reliable (no VPN), full API") | `SODEX.md:3` |
| Tipe pasar | DEX (perp + spot) | `SODEX.md:60-92` |
| Peran dalam ekosistem | Divisi eksekusi pasar terdesentralisasi: swing trading profit-maksimal + eks-perps/spot volume farming | `SODEX.md:4-5`; `docs/SODEX_FARMING_DOCTRINE.md` |
| Dokumen kanonik utama | `SODEX.md`, `docs/SODEX_FARMING_DOCTRINE.md`, `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md`, `docs/SODEX_ARCHITECTURE_MAP.md`, `docs/SODEX_SWING_PHILOSOPHY_AND_MAP_20260802.md` | direktori `docs/` |
| Mesin eksekusi | PVE, E1, E2 (tiga arm/engine, satu basis kode `anantara/`) | `anantara/perps_volume_engine.py:176`; `anantara/sodex_twin_engine.py:541` |
| Basis data runtime | `twin_engine.db` (SQLite) | `twin_engine.db` |
| Status operasional (as-is) | **Paper/monitoring; live throughput nol** | `data/sodex_monitor_eval/latest.json` (ledger.fills.count=0) |
| Deadline target berikut | **2026-10-16 16:59:59 UTC** (20,29 hari dari 2026-09-26) | `reports/SODEX_RECOVERY_MONITOR_LATEST.md:5`; hitung ulang §12 |
| Tanggal cut-off dokumen | 2026-09-26 | konteks |

---

## 2. Latar Belakang

### 2.1 Mengapa divisi ini ada

Divisi SoDEX ada untuk **mengeksekusi strategi trading ber-arah (directional) pada venue DEX sodex.com**
— baik perps maupun spot — dengan tujuan akhir **profit PnL maksimal**, sambil memakai infrastruktur
guarded route selection (gate berlapis) yang sudah dibangun di repo `anantara-sakti`.

Ada dua motif historis yang tercatat dalam artefak dan keduanya tercermin di dokumen nyata:

1. **Motif awal (farming volume / SoPoints).** Doktrin pertama menyatakan target utamanya adalah
   volume transaksi mingguan: *"The minimum weekly transaction-volume target is: $1,300,000 weekly
   SoDEX transaction volume"* (`docs/SODEX_FARMING_DOCTRINE.md:7-13`). Motifnya: mengumpulkan SoPoints
   sebagai *airdrop reward*.
2. **Motif sekarang (profit swing).** Dokumen kanonik `SODEX.md` merevisi arah tersebut:
   *"REVISED 2026-08-01: Goal = profit maximal swing trading 1h–48h. Volume/SoPoints = byproduct,
   not objective."* (`SODEX.md:4-5`), dan menandai doktrin farming sebagai **superseded**
   (`SODEX.md:7-8`).

### 2.2 Sejarah dari artefak (tanggal commit / dokumen nyata)

| Tanggal | Artefak | Isi | Sumber |
|---|---|---|---|
| 2026-05-17 | commit `61670cf` | Data lake multi-exchange menyertakan integrasi SoDEX + tooling retry | `git log` |
| 2026-05-19 | commit `3487a04` | Fase 6 Day 11: multi-exchange dual instance LIVE | `git log` |
| 2026-05-20 | commit `c3e52fe` | Modul farming SoDEX SoPoints (maker loop berbasis CLI) | `git log` |
| 2026-05-20 | commit `8d659b0` | Skrip build CLI resmi SoDEX via Docker | `git log` |
| 2026-05-22 | commit `57f125e` | `SODEX.md` referensi komprehensif + mode scalp | `git log` |
| 2026-06-09 | `docs/SODEX_FARMING_DOCTRINE.md` | Doktrin farming (target $1,3 juta/minggu, >69% transaksi profit) | header dokumen |
| 2026-06-12 | commit `2296c8b` | FASE 0: stabilisasi pasca-audit | `git log` |
| 2026-06-18 | `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md` | Masterplan ilmiah menuju target (falsification-first) | header dokumen |
| 2026-06-27 | commit `8e17b60` | PVE-B39: aktivasi 4 pair + ledger volume tracking | `git log` |
| 2026-08-01 | `SODEX.md` revisi | Pivot: tujuan = profit swing maksimal, volume = byproduct | `SODEX.md:4-5` |
| 2026-08-02 | `docs/SODEX_SWING_PHILOSOPHY_AND_MAP_20260802.md` | Filosofi + peta swing; koreksi prinsip "hold-duration edge" | header + banner dokumen |
| 2026-09-02 | `docs/SODEX_ARCHITECTURE_MAP.md` v2.0 | North Star: Swing 1–30h, profit ≥0,7% wallet per trade | `docs/SODEX_ARCHITECTURE_MAP.md:1-11` |
| 2026-09-15 | commit terkait dust policy | `scripts/sodex_wallet_denominator.py` dust policy (audit 2026-09-15) | komentar sumber `:24-27` |
| 2026-09-21 | commit `3a71c4d`/`c5bc0dd`/`c92baa7` | Alarm palsu gateway, crash-loop daemon, sekring job | `git log` |
| 2026-09-25 | commit `efa0be6`…`12ccfd2`, `eabfa23`, `b12683e` | PEAK_TRAIL exit floor +2%, pair-gate BH-FDR, harmonisasi phantom, auto-resolve UNVERIFIED | `git log` |
| 2026-09-26 | commit `9961ad4`, `353ba2e` | Arm A1/A2 geometri ATR-adaptif; offload I/O veto job | `git log` |

### 2.3 Masalah yang dijawab divisi ini

- **M1 — Perps + spot DEX dengan fee/tier kompleks.** Fee perps maker 0,012%–0,000% bergantung tier volume
  14 hari; spot maker 0,035%; spot dihitung **2×** terhadap tier; rute volume termurah = perps
  (`SODEX.md:19-55`; `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md:52-58`).
- **M2 — Swing 1–48 jam dengan edge tipis.** Masterplan: *"maker pasif PEPE/SHIB tidak ber-edge (adverse
  selection ~17 bps)"* → kembali ke prediksi arah (`...MASTERPLAN...md:33-36`); peta arsitektur:
  *"Long-only (SHORT disabled — P(EV>0)=3%)"* (`docs/SODEX_ARCHITECTURE_MAP.md:14-19`).
- **M3 — Modal wallet kecil sebagai constraint mengikat.** Masterplan §2: modal riil saat itu **~$186**,
  `$1,3M/mgg` = **6.989× turnover mingguan**, dinyatakan *"kemungkinan besar tidak feasible"*
  (`docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md:20,72`). Masih hidup sampai hari ini (§6, §18).

---

## 3. Filosofi & Prinsip Dasar

> Prinsip di bawah **dikutip langsung dari dokumen nyata**. Bila satu prinsip tidak memiliki dokumen
> sumber, hal itu dinyatakan eksplisit.

### 3.1 Prinsip dari Doktrin Farming (`docs/SODEX_FARMING_DOCTRINE.md`)

Kutipan kunci:

- Target mingguan: *"the minimum weekly metrics are: Weekly volume: at least `$1,300,000`;
  Total Real Ratio: minimum `1:9,100`; … Weekly profitable transaction ratio: above `69%`"*
  (`:34-48`).
- *"E1 = profit engine … E2 = volume engine"* (`:56-59`).
- No-Loss Guarantee: *"`E1_realized_profit ≥ total_fees_E1 + total_fees_E2`"* (`:60-64`).
- Mandat metode: sinyal **Pre Top Gainer / Pre Top Loser** — menemukan aset *sebelum* lonjakan (`:117-138`).
- Obligasi perbaikan berkelanjutan (*"Belajar → Belajar → … → Ulangi"*) bersifat **mandat dan berkelanjutan** (`:145-168`).

### 3.2 Prinsip dari Masterplan (`docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md`)

- *"Prinsip: falsification-first, data riil, 'tidak rugi', security-first."* (`:1-4`).
- Dekomposisi masalah: `SUKSES = EDGE × VOLUME × COST-COVERAGE × REAL-RASIO × SoPOINTS-EFISIENSI`,
  *"Bila satu faktor nol/negatif, target gagal. Prioritas ilmiah: buktikan EDGE dulu"* (`:44-49`).
- *"Tidak ada fase berikut tanpa gate fase sebelumnya lulus (no skipping)."* (`:119`).
- *"Snapshot mingguan Sabtu 07:00 WIB = titik evaluasi & keputusan resmi."* (`:123`).

### 3.3 Prinsip dari Peta Arsitektur (`docs/SODEX_ARCHITECTURE_MAP.md`)

- *"Filosofi: EVIDENCE-FIRST arsitektur — setiap track punya peran ilmiah yang jelas, keputusan
  dinaikkan/turunkan berdasarkan bukti statistik."* (`:4-5`).
- **North Star:** *"Swing 1-30h · Profit ≥0,7% wallet ($0,662) per trade"* (`:9-11`).
- Aturan gate: *"CI95 P(EV>0) < 5%: disable track"* (`:90`).

### 3.4 Prinsip dari Peta Swing (`docs/SODEX_SWING_PHILOSOPHY_AND_MAP_20260802.md`)

Dikutip verbatim (banner revisi + bagian Prinsip/ Konstitusi):

```
1. Profit adalah BUKTI, bukan target — setiap trade harus punya positive expectancy
2. Sederhana yang dijalankan > Canggih yang berhenti
3. Data adalah hakim — tidak ada klaim tanpa backtest, tidak ada live tanpa paper
4. Edge = kualitas sinyal ENTRY + geometri risiko yang DIHORMATI
5. SoDEX adalah venue — semua strategi harus compatible dengan thin books, maker-fee, spread aktual
F1 — Volume adalah HASIL profit, bukan tujuan
F2 — Security-first: no-withdraw flag MANDATORY, dry_run sebelum go-live
F3 — Edge-gated live: setiap strategi harus lolos Gate 1→2→3→4 sebelum live capital
```
(sumber: `docs/SODEX_SWING_PHILOSOPHY_AND_MAP_20260802.md`, bagian "Prinsip Dasar (WHY)" dan
"Konstitusi Proyek (HOW)").

### 3.5 Catatan ketidaksesuaian dokumen

**Temuan F-01:** `SODEX.md:7-8` menyatakan doktrin farming *"historical reference only — no longer
the operating target"*, namun file doktrin masih ada di repo dan masih dirujuk **sebagai "Anchor
doktrin"** oleh `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md:4`. Dua dokumen kanonik saling
menyatakan satu sama lain sebagai superseded/aktif → perlu keputusan tunggal di §11 (P1).

---

## 4. PRD (Product Requirement Document)

> PRD ini **dirumuskan dari artefak nyata** (dokumen + kode + state). Bagian yang tidak memiliki
> dokumen sumber ditandai. Tidak ada PRD formal bernama "PRD SoDEX" di repo — **temuan F-02**.

### 4.1 Pemangku kepentingan (stakeholders)

| Pemangku kepentingan | Peran | Sumber |
|---|---|---|
| Pengguna/operator (user Anantara) | Pemilik modal, penerima laporan Telegram, pemberi GO-LIVE eksplisit | `docs/SODEX_ARCHITECTURE_MAP.md:50-52` |
| Agent/daemon otomasi | Pelaksana sinyal→eksekusi→exit, tunduk gate | `scripts/sodex_safety_guardian.py:798` |
| Monitor/Governor | Penegak gate statistik & fail-closed | `scripts/sodex_monitor_eval.py`; `scripts/sodex_recovery_monitor.py` |
| Venue SoDEX | Penyedia pasar + data tier/SoPoints | `SODEX.md:17-58` |
| Divisi lain (CEX, Pre-Gain, Alpaca) | Sumber sinyal/intel lintas divisi | `docs/SODEX_FARMING_DOCTRINE.md:83-92` |

### 4.2 Kebutuhan fungsional

| ID | Kebutuhan | Implementasi (modul) | Bukti |
|---|---|---|---|
| FR-1 | **Sinyal** arah/entry per pair (swing 1–48h) | `anantara/sodex_signal.py` (`ofi_step:28`, `build_features:76`, `composite_signal:113`) | sumber |
| FR-2 | **Gate berlapis**: regime, smart-bps, pair-drag, coverage | `anantara/sodex_farming.py` (`_get_market_regime:484`, `_get_adaptive_smart_bps:541`, `_should_skip_regime:563`) | sumber |
| FR-3 | **Eksekusi** order (maker-biased, reduce-only close) | `anantara/perps_volume_engine.py:176`; `SODEX.md:62-71` | sumber |
| FR-4 | **Exit** (TP/SL/PEAK_TRAIL/partial) | commit `efa0be6` (PEAK_TRAIL floor +2%) | `git log` |
| FR-5 | **Pembelajaran** (deep loop, UCB1, params learnable) | `scripts/sodex_deep_learn.py`; `data/swing_deep_learning.json` (ts 2026-09-26T10:00:09Z) | file state |
| FR-6 | **Rekonsiliasi** ledger↔state↔venue | `scripts/sodex_reconciliation_audit.py`; `twin_engine.db` | sumber |
| FR-7 | **Pelaporan** harian/mingguan | `scripts/sodex_progress_report.py`; `scripts/sodex_recovery_monitor.py` | sumber |
| FR-8 | **Kontrol operator** (kill/resume, manual measure-farm) | `SODEX.md:99-101`; `data/ground_truth.json` (live_flags) | file state |

### 4.3 Kebutuhan non-fungsional

| ID | Kebutuhan | Bukti |
|---|---|---|
| NFR-1 | **Fail-closed**: denominator final ditolak bila ada holding material tanpa mark-to-market | `scripts/sodex_wallet_denominator.py:78-95` |
| NFR-2 | **Jejak bukti**: setiap claim bersumber; audit trail jsonl | `data/swing_deep_learning.jsonl`; `logs/` |
| NFR-3 | **Idempoten & crash-safe**: hard ceiling persisted, resume aman | `SODEX.md:144-147` |
| NFR-4 | **Security-first**: dry-run default, live butuh flag eksplisit | `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md:122`; `data/ground_truth.json` |
| NFR-5 | **No-skipping**: fase tidak boleh dilompati | `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md:119` |
| NFR-6 | **Konsistensi metrik = eksekusi**: trade yang di-block gate tidak masuk metrik | `scripts/sodex_maturation_tracker.py:55-61` |

### 4.4 Kriteria penerimaan (acceptance criteria)

| AC | Kriteria | Ambang | Sumber |
|---|---|---|---|
| AC-1 | n forward ≥ 50 | 50 | `scripts/sodex_maturation_tracker.py:23` |
| AC-2 | Win-rate ≥ 50% | 0,50 | `:24` |
| AC-3 | Profit factor ≥ 1,5 | 1,5 | `:25` |
| AC-4 | ROI wallet ≥ 0,7% per trade | 0,007 | `:26` |
| AC-5 | Semua gate lulus → verdict GO statistik | — | `:92-93` |
| AC-6 | Coverage E1 ≥ $300 fill/24h sebelum PVE jalan | 300 | `scripts/sodex_safety_guardian.py:805` |

### 4.5 Out-of-scope

- **Short di spot** (mekanis tak bisa) — spot long-only; SHORT hanya via perps (`docs/SODEX_ARCHITECTURE_MAP.md:16`).
- **SHORT mode relaxed** (tidak ada alpha entry — temuan commit `dcf43b8`).
- **Saham** pada universe swing (audit 0/28 lolos, buku tipis — `docs/SODEX_SWING_PHILOSOPHY_AND_MAP_20260802.md` banner).
- **Perubahan/penghapusan manual berkas state atau kode** oleh agent (bukan jalur sah; §11).
- **Mekanisme keamanan/rahasia** — DIKECUALIKAN (kebijakan dokumen).

---

## 5. Maksud & Tujuan

| Tingkat | Rumusan | Sumber |
|---|---|---|
| Maksud (WHAT) | *"Memperoleh keuntungan profit maksimal dari aktivitas Swing Trading di market sodex.com."* | `docs/SODEX_SWING_PHILOSOPHY_AND_MAP_20260802.md`, "Tujuan (WHAT)" |
| Tujuan (WHEN) | *"…di setiap time frame swing trading 1 jam – 48 jam."* | idem, "Target (WHEN)" |
| Arah kanonik | *"Goal = profit maximal swing trading 1h–48h. Volume/SoPoints = byproduct, not objective."* | `SODEX.md:4-5` |
| North Star metrik | Swing 1–30h, profit ≥ 0,7% wallet per trade | `docs/SODEX_ARCHITECTURE_MAP.md:9-11` |
| Tujuan historis (arsip) | Volume mingguan ≥ $1,3 juta + >69% transaksi profit | `docs/SODEX_FARMING_DOCTRINE.md:34-48` |

**Rumusan tunggal yang dipakai dokumen master ini:**
> Tujuan utama divisi SoDEX adalah **PROFIT PnL maksimal** pada swing trading 1–48 jam di DEX SoDEX
> (perps + spot). Angka **0,7% per window (per trade) adalah HARGA MATI / BATAS BAWAH**, bukan target
> ideal: gate promosi menolak live bila ROI wallet < 0,7% (`scripts/sodex_maturation_tracker.py:26,89`)
> dan monitor pemulihan memakai target/trade yang sama (`reports/SODEX_RECOVERY_MONITOR_LATEST.md:6`).

---

## 6. Target

### 6.1 Tabel target vs realisasi vs n-sampel vs bukti

| # | Target (dokumen) | Nilai target | Realisasi as-is | n-sampel | Bukti (path + kunci) |
|---|---|---|---|---|---|
| T1 | Volume mingguan farming | ≥ $1.300.000 | **$0** (window berjalan) | 0 fill/24h | `data/sodex_monitor_eval/latest.json` → `ledger.volume.raw_total_usd=0.0` |
| T2 | Rasio transaksi profit mingguan | > 69% | **NO-DATA** (denominator live nol) | 0 | idem, `ledger.fills.count=0` |
| T3 | Cost coverage E1 ≥ E2 fees | E1 profit ≥ E2 fees | **True secara artifisial** (keduanya $0) | 0 | idem, `verdict.progress.e1_covers_e2_fees=true`, `e1_fees_usd=0.0` |
| T4 | Real Rasio (volume/fee) | ≥ 1:9.100 | **null** (tak terdefinisi, fee=0) | 0 | idem, `volume_fee_ratio=null` |
| T5 | Net mingguan | ≥ 0 | **$0** (tak ada eksekusi) | 0 | idem, `realized_pnl_usd=0.0` |
| T6 | SoPoints | maksimalkan | **NO-DATA** (SoPoints di luar API) | — | `SODEX.md:13` ("tracked at sodex.com (not via API)") |
| T7 | ROI wallet per trade (swing) | ≥ 0,7% (**harga mati**) | +1,6163% (denominator usang $108,10) | n=97 | `data/sodex_maturation_status.json` → `wallet_roi_pct` |
| T7' | ROI wallet per trade (denominator nyata $276,58) | ≥ 0,7% | +0,635% (**di bawah harga mati**) | n=97 | hitung ulang §6.3 |
| T8 | Trade forward memenuhi ≥0,7% | maksimalkan | 47/97 (denominator usang) → **22/97** (denominator nyata) | 97 | `target_met_per_trade` vs rekalkulasi §6.3 |
| T9 | Win-rate forward | ≥ 50% | 61,86% | 97 | `data/sodex_maturation_status.json` → `wr` |
| T10 | Profit factor forward | ≥ 1,5 | 2,239 | 97 | idem → `pf` |
| T11 | PnL absolut forward | maksimalkan (**tujuan utama**) | +$169,48 | 97 | rekalkulasi dari `data/paper_test_realwide_state.json` |

### 6.2 Catatan "tujuan utama = PROFIT PnL maksimal; 0,7% = harga mati"

- Tujuan utama bukan "lulus gate", melainkan **PnL maksimal** (T11). Gate 0,7% adalah **lantai**
  (`MIN_AVG_ROI = 0.007  # >=0.7% wallet ROI/trade`, `scripts/sodex_maturation_tracker.py:26`).
- Lantai ini bersifat *hard*: kegagalan satu gate menghasilkan **NO-GO** (`:96-98`).
- Monitor pemulihan menyatakan lantai yang sama dalam dolar: *"Target/trade: $1.9361 (0.70% wallet)"*
  (`reports/SODEX_RECOVERY_MONITOR_LATEST.md:6`).

### 6.3 Rekalkulasi jujur (verifikasi independen)

Rekalkulasi ulang dari state mentah (`data/paper_test_realwide_state.json`, filter sama seperti
tracker: `exit_ts > 2026-09-05T02:20:00Z`, pair di-pause dibuang):

| Denominator wallet | Ambang/trade | Trade memenuhi | Sumber |
|---|---|---|---|
| $108,10 (default usang di kode) | $0,7567 | **47/97** | `scripts/sodex_maturation_tracker.py:27` |
| $276,58 (verified snapshot) | $1,9361 | **22/97** | `reports/SODEX_RECOVERY_MONITOR_LATEST.json` → `wallet.value` |
| $276,75 (nilai paket audit 06:12Z) | $1,9373 | 22/97 | paket audit (nilai historis, drift tipis) |

→ **Temuan F-03 (kritis):** verdict `GO` pada `data/sodex_maturation_status.json` (generated
2026-09-26T09:58:58Z) dihitung dengan denominator usang **$108,10** yang tidak pernah disinkronkan ke
wallet nyata **$276,58**. Dengan denominator nyata, `ROI≥0,7%` turun menjadi +0,635% → gate **gagal**.
Verdict GO bersifat **artifisial**.

---

## 7. Struktur

### 7.1 Struktur organisasi teknis (arm/engine)

```
SoDEX DIVISION
├── PVE  (Perps Volume Engine)      → volume perps (arsip farming)
├── E1   (spot / maker capture)     → profit engine (doktrin)
└── E2   (perps directional)        → volume engine / directional amplif. (doktrin + Fase 2)
```
Sumber: `anantara/perps_volume_engine.py:176` (`class PerpsVolumeEngine`); `docs/SODEX_FARMING_DOCTRINE.md:56-59`;
`twin_engine.db` (`select engine,count(*) from fills` → E1/E2/PVE).

### 7.2 Struktur berkas (ringkas)

```
SODEX.md · docs/SODEX_* (doctrine, masterplan, map, audit) · anantara/ (mesin & domain logic)
scripts/sodex_*.py (~80 runner/monitor/gate/laporan) · data/ (state JSON/JSONL + PVE_PAUSE + SELL_BLOCKED)
logs/ · reports/ · twin_engine.db (ledger fills/rts/state) · systemd/ (unit sodex-*.service/.timer)
```

### 7.3 Unit systemd kunci (SoDEX)

Bukti: `ls systemd/ | grep -i sodex`; `systemctl --user list-timers --all | grep -i sodex`.

| Kelas | Contoh unit | Catatan |
|---|---|---|
| Monitor/perbaikan | `anantara-sodex-recovery-monitor.timer`, `sodex-monitor-eval.timer`, `sodex-guardian.service` | timer aktif (terlihat di list-timers) |
| Sinkronisasi | `anantara-sodex-realsync.timer` | sinkron snapshot real |
| Laporan | `anantara-sodex-progress.timer`, `sodex-honest-ratio-report.timer`, `sodex-capital-report.timer` | mingguan/harian |
| Penjaga / watchdog | `sodex-twin-watchdog.service`, `anantara-sodex-watchdog.timer`, `sodex-sentinel.service` | fail-closed |
| Riset/lab | `sodex-quant-stat.timer`, `sodex-cameo-scalp-research.timer` | non-kapital |
| Pilot/kapal kecil | `sodex-qip-xaut-pilot.service`, `sodex-pin-maker.service` | — |

Catatan: daftar `systemd/` juga memuat unit non-SoDEX; hanya unit ber-prefix `sodex`/`anantara-sodex`
yang dihitung di sini. Hitungan pasti unit aktif = **NO-DATA** runtime-wide (hanya sebagian terlihat
di `list-timers`); cara memperoleh: `systemctl --user list-units 'sodex*' 'anantara-sodex*'`.

---

## 8. Arsitektur

### 8.1 Alur data (dari peta arsitektur kanonik)

```
Binance 1h OHLCV (sinyal) → 4 track perps → state JSON → sodex_progress_report.py (harian 08:00 WIB)
                          ↘ deep learner (swing_deep_learning.jsonl) → learned params
                             → sodex_paper_config.py (canonical, drift-check)
```
Sumber: `docs/SODEX_ARCHITECTURE_MAP.md:71-84`.

### 8.2 Layered gate (fail-closed)

```
Sinyal (composite_signal)
   → Gate-1 regime        (_get_market_regime, _should_skip_regime)
   → Gate-2 spread/bps    (_get_adaptive_smart_bps)
   → Gate-3 pair-drag     (edge_gate JSON; BH-FDR rolling window — commit c705029)
   → Gate-4 coverage      (check_e1_coverage: E1 fill_24h ≥ $300 → else PVE_PAUSE)
   → Gate-5 risk/treasury (governor: leverage, stop, prob-threshold, expectancy)
   → EKSEKUSI  →  EXIT (TP/SL/PEAK_TRAIL/partial)
```
Sumber: `anantara/sodex_farming.py:484,541,563`; `scripts/sodex_safety_guardian.py:798`;
`anantara/sodex_governor.py:39,88,128,140`; `git log` commit `efa0be6`, `c705029`.

### 8.3 Komponen mesin

| Komponen | Peran | Definisi | Bukti |
|---|---|---|---|
| `PerpsVolumeEngine` | Eksekusi perps (vol/directional) | `anantara/perps_volume_engine.py:176` | sumber |
| `create_engines()` | Pabrik arm (PVE/E1/E2) | `anantara/perps_volume_engine.py:1670` | sumber |
| `Ledger` | Akunting fills/rts, sumber tunggal volume internal | `anantara/sodex_twin_engine.py:541` | sumber |
| `e1_profit_since()` | Profit E1 sejak timestamp (coverage) | `anantara/sodex_twin_engine.py:580` | sumber |
| `e2_dir_open_signal(s)` | Sinyal arah E2 terbuka | `anantara/sodex_twin_engine.py:676,693` | sumber |
| `e1_spot_capability_block_reason()` | Alasan blok kapabilitas spot (incl. SELL) | `anantara/sodex_twin_engine.py:105` | sumber |
| Governor (4 mesin) | Leverage/stop/prob-threshold/expectancy | `anantara/sodex_governor.py:39,88,128,140` | sumber |
| Intel layer | Skor intel (F&G, regime) | `anantara/sodex_intel_layer.py:96,188` | sumber |

### 8.4 Kontrol & state runtime

| Kontrol | Isi (as-is) | Sumber |
|---|---|---|
| `data/PVE_PAUSE` | PVE dijeda oleh gate coverage E1 | `data/PVE_PAUSE` |
| `data/SODEX_SPOT_SELL_BLOCKED` | SELL spot diblokir (exit gagal) | `data/SODEX_SPOT_SELL_BLOCKED` |
| `data/ground_truth.json` | `live_flags` semua `"0"` | file state |
| `halt_status` | `active=false` (tak ada SAFETY_HALT) | `data/sodex_monitor_eval/latest.json` |

---

## 9. Peta Detail (Maps)

### 9.1 Modul → fungsi kunci → nomor baris

| Modul | Fungsi/kelas kunci | Baris | Sumber |
|---|---|---|---|
| `anantara/sodex_farming.py` | `halt_active` | 58 | grep -n |
| `anantara/sodex_farming.py` | `_get_market_regime` | 484 | grep -n |
| `anantara/sodex_farming.py` | `_get_adaptive_smart_bps` | 541 | grep -n |
| `anantara/sodex_farming.py` | `_should_skip_regime` | 563 | grep -n |
| `anantara/perps_volume_engine.py` | `class PerpsVolumeEngine` | 176 | grep -n |
| `anantara/perps_volume_engine.py` | `create_engines` | 1670 | grep -n |
| `anantara/sodex_twin_engine.py` | `e1_spot_capability_block_reason` | 105 | grep -n |
| `anantara/sodex_twin_engine.py` | `class Ledger` | 541 | grep -n |
| `anantara/sodex_twin_engine.py` | `e1_profit_since` | 580 | grep -n |
| `anantara/sodex_twin_engine.py` | `e2_get_open_positions` | 639 | grep -n |
| `anantara/sodex_twin_engine.py` | `e2_dir_open_signal(s)` | 676 / 693 | grep -n |
| `anantara/sodex_signal.py` | `ofi_step` / `build_features` / `composite_signal` | 28 / 76 / 113 | grep -n |
| `anantara/sodex_governor.py` | `mesin1_leverage` / `mesin2_stop_loss` / `mesin4_prob_threshold` / `expectancy` | 39 / 88 / 128 / 140 | grep -n |
| `anantara/sodex_intel_layer.py` | `compute_intel_score` / `class IntelLayer` | 96 / 188 | grep -n |
| `scripts/sodex_safety_guardian.py` | `PVE_PAUSE_FILE` / `check_e1_coverage` / `main` | 119 / 798 / 910 | grep -n |
| `scripts/sodex_maturation_tracker.py` | `GEOMETRY_CUTOVER_UTC` / `MIN_AVG_ROI` / `WALLET` | 20 / 26 / 27 | grep -n |
| `scripts/sodex_wallet_denominator.py` | `SNAP` / `KEY` / `MIN_DELTA_PCT` / `read_priced_wallet` / `read_real_wallet` | 19 / 21 / 22 / 52 / 78 | grep -n |
| `scripts/sodex_recovery_monitor.py` | `bootstrap_ci` / `metrics` / `read_wallet` | 116 / 131 / 169 | grep -n |
| `scripts/sodex_spot_daemon.py` | `SPOT_SELL_BLOCK_FILE` | 26 | grep -n |

### 9.2 Berkas state (JSON/JSONL)

| Berkas | Isi | Nilai/kunci penting | Sumber |
|---|---|---|---|
| `data/paper_test_realwide_state.json` | state track REALWIDE (closed trades) | `closed[]`, `exit_ts`, `pnl_usd` | file |
| `data/sodex_maturation_status.json` | hasil tracker promosi | `n_forward=97`, `wr=0.6186`, `pf=2.239`, `verdict=GO` | file |
| `data/PVE_PAUSE` | freeze PVE | `source=e1_coverage_gate`, `e1_fill_24h=0.0`, `threshold=300.0` | file |
| `data/SODEX_SPOT_SELL_BLOCKED` | blok SELL spot | `reason=SELL_CANCELLED_TIMEOUT_EXIT_FAILED` | file |
| `data/e1_autopilot_heartbeat.json` | heartbeat E1 | `engine_alive=false`, ts 2026-07-23T07:39:33Z | file |
| `data/sodex_monitor_eval/latest.json` | evaluasi monitor window | `ledger.fills.count=0`, `volume.raw_total_usd=0.0` | file |
| `data/sodex_real_sync_snapshot.json` | snapshot balance/posisi | `perps_positions` (2 pos terbuka) | file |
| `data/ground_truth.json` | flag live | `live_flags.*="0"` | file |
| `data/swing_deep_learning.jsonl` | audit trail deep loop | ts 2026-09-26T10:00:09Z | file |
| `data/paper_test_edge_gate.json` | pair-gate | `pairs_pause['REAL-wide']` = ADA/ARB/DOGE/HYPE/ONDO/SILVER/SUI | file |
| `reports/SODEX_RECOVERY_MONITOR_LATEST.json` | monitor pemulihan | `wallet.value=276.5823398863654`, `days_to_deadline=20` | file |

### 9.3 Tabel & isi DB (`twin_engine.db`)

| Tabel | Kolom kunci | Jumlah baris | Sumber |
|---|---|---|---|
| `fills` | `id, ts, engine, bucket, pair, side, price, qty, notional, fee, maker, rt_id` | **69.260** | `pragma table_info`; `count(*)` |
| `rts` | `rt_id, ts_close, engine, pair, volume, net_pnl` | **15.291** | idem |
| `state` | key-value (`equity_high`, `b13_activated_ts`, …) | (KV) | idem |
| `weekly_points` | titik mingguan (KV) | — | idem |
| `e2_open_pos` | posisi E2 terbuka | — | idem |
| `e2_dir_signals` | `pair, side, grade, funding_rate, obi, entry_px, exit_px, qty, pnl, exit_reason, opened_ts, closed_ts` | **92** | idem |

**Agregat fills per engine (notional kumulatif seumur DB):**

| Engine | Jumlah fills | Σ notional | Fill terakhir (UTC) |
|---|---|---|---|
| E1 | 62.704 | $897.064,19 | 2026-07-23T06:24:30Z |
| E2 | 3.368 | $987.366,09 | 2026-06-20T05:57:40Z |
| PVE | 3.188 | $607.482,20 | 2026-07-23T07:35:41Z |

Sumber agregat: `twin_engine.db` (kueri `group by engine`). Catatan: notional ini **historis seumur DB**,
bukan volume window berjalan — volume window berjalan = 0 (lihat §6.1 T1).

---

## 10. Alur Kerja

### 10.1 Rantai sinyal → exit

1. **Ingest data pasar.** Binance 1h OHLCV menjadi sumber sinyal (`docs/SODEX_ARCHITECTURE_MAP.md:74`).
2. **Bangun fitur & sinyal.** `build_features` → `composite_signal` (OFI/OFI-step) di
   `anantara/sodex_signal.py:28,76,113`.
3. **Gate regime.** `_get_market_regime` / `_should_skip_regime` menyaring kondisi pasar
   (`anantara/sodex_farming.py:484,563`).
4. **Gate spread/bps adaptif.** `_get_adaptive_smart_bps` menentukan ambang spread per pair
   (`anantara/sodex_farming.py:541`).
5. **Gate pair-drag statistik.** Pair dengan drag buruk di-pause via BH-FDR rolling window; trade yang
   di-block gate **tidak** masuk metrik promosi (`scripts/sodex_maturation_tracker.py:55-61`; commit `c705029`).
6. **Gate coverage E1.** `check_e1_coverage`: bila E1 fill 24h < $300 → tulis `PVE_PAUSE`, PVE berhenti;
   auto-clear bila E1 pulih (`scripts/sodex_safety_guardian.py:798-847`).
7. **Keputusan risiko governor.** `mesin1_leverage`, `mesin2_stop_loss`, `mesin4_prob_threshold`,
   `expectancy` (`anantara/sodex_governor.py:39,88,128,140`).
8. **Eksekusi.** Order maker-biased via engine (`anantara/perps_volume_engine.py:176`); spot long-only,
   perps kedua arah sesuai keputusan arsitektur.
9. **Exit.** TP/SL, ditambah PEAK_TRAIL floor +2% (commit `efa0be6`) dan mode partial.
10. **Deep learning loop.** Hasil trade → `data/swing_deep_learning.jsonl` → learned params →
    `sodex_paper_config.py` (canonical, drift-check) (`docs/SODEX_ARCHITECTURE_MAP.md:80-83`).
11. **Rekonsiliasi & pelaporan.** `sodex_reconciliation_audit.py`, `sodex_progress_report.py`,
    `sodex_recovery_monitor.py` (harian 08:00 WIB / mingguan Sabtu 07:00 WIB).

### 10.2 Loop pembelajaran (deep loop)

```
trade closed → telemetry (jsonl) → outcome model + UCB1 weights → learned params
     ▲                                                              │
     └──────────────── drift-check vs sodex_paper_config.py ◄───────┘
```
Sumber: `scripts/sodex_deep_learn.py` (mode `--loop`/`--status`); `data/swing_deep_learning.json`
(ts 2026-09-26T10:00:09Z) memuat `ucb1_weights`, `outcome_model`, `lessons`,
`adaptive_suggestions`, `quality`.

### 10.3 Papan keputusan gate (dari peta arsitektur)

| Tier | Track | n | ROI | CI95 | Keputusan (dokumen) |
|------|-------|---|---|------|---------------------|
| 1 | REALWIDE / TWOWAY-LONG | 43 / 80 | +3,77% / +1,51% | [+1,26,+5,79] ✅ / [+0,05,+2,75] ✅ | n→50 lalu GO-LIVE proposal / qualified |
| 2 | SWING / SWING_PARTIAL | 124 / 117 | +1,79% / +1,57% | CI sentuh 0 | perlu ≥160 / menuju evaluasi |
| 2 | DONCHIAN / SPOT_SWING | 37 / 35 | −0,60% / −0,22% | P=28% / P=43% | arah KILL / baseline |
Sumber: `docs/SODEX_ARCHITECTURE_MAP.md:55-69`. **Catatan (temuan F-04):** n pada tabel dokumen (2026-09-02)
kini jauh tertinggal dari realisasi (REALWIDE n=197, `reports/SODEX_RECOVERY_MONITOR_LATEST.md:12`).

---

## 11. Rencana Kerja

> Prioritas disusun terhadap deadline **2026-10-16** dan mengikuti prinsip *no-skipping*.
> Setiap item memiliki **kriteria selesai** yang dapat diverifikasi (bukan narasi).

### P0 — Kritis (blocker terhadap kebenaran keputusan)

| ID | Tindakan | Kriteria selesai | Bukti saat ini |
|---|---|---|---|
| P0-A | **Sinkronkan denominator wallet** di tracker promosi ke snapshot nyata (ganti default `108.10`) | `scripts/sodex_maturation_tracker.py:27` membaca nilai terverifikasi; verdict dihitung ulang mencerminkan $276,58 | default masih `108.10`; wallet $276,58 (`reports/SODEX_RECOVERY_MONITOR_LATEST.json`) |
| P0-B | **Hentikan klaim GO artifisial** sampai P0-A selesai | Laporan/tracker tidak lagi mengeluarkan `GO` dengan denominator usang | `data/sodex_maturation_status.json` verdict GO |
| P0-C | **Pulihkan E1** (profit engine) — E1 fill 24h ≥ $300 | `check_e1_coverage` membaca E1 fill_24h ≥ 300 → auto-clear PVE_PAUSE | E1 fill 24h = 0 (`data/PVE_PAUSE`) |
| P0-D | **Angkat `PVE_PAUSE` secara SAH** (bukan hapus manual) | Berkas hilang **hanya** jalur auto-clear gate `source=e1_coverage_gate` (`scripts/sodex_safety_guardian.py:838-845`) — bukan `rm` manual | PVE_PAUSE ada, source e1_coverage_gate |
| P0-E | **Selesaikan blok SELL spot** | `data/SODEX_SPOT_SELL_BLOCKED` hilang setelah SELL spot kecil terverifikasi dapat tereksekusi | berkas ada, reason SELL_CANCELLED_TIMEOUT_EXIT_FAILED |

**Catatan penting (aturan P0-D):** Pengangkatan `PVE_PAUSE` yang SAH adalah melalui **jalur gate**
yang menulis berkas (`check_e1_coverage` → `PVE_PAUSE_FILE.unlink()` pada `:838-845`), atau melalui
prosedur operator yang terdokumentasi setelah E1 terbukti pulih. **Menghapus berkas dengan `rm`
adalah jalur tidak sah** — ia mem-bypass gate yang justru melindungi dari E1 dorman.

### P1 — Penting (kualitas keputusan & konsistensi)

| ID | Tindakan | Kriteria selesai |
|---|---|---|
| P1-A | Selaraskan dokumen kanonik (F-01): tetapkan satu target operasi (farming vs profit) | Hanya satu dokumen berstatus "operating target"; yang lain ditandai arsip |
| P1-B | Rekonsiliasi drift peta arsitektur (F-04): perbarui n/ROI/CI95 | Tabel `docs/SODEX_ARCHITECTURE_MAP.md` cocok dengan `reports/SODEX_RECOVERY_MONITOR_LATEST.md` |
| P1-C | Perbaiki throughput pembuktian: n forward ≥ 50 dengan denominator benar | Verdict dihitung ulang, gate `ROI≥0,7%` dievaluasi dengan wallet nyata |
| P1-D | Tutup celah "coverage artifisial" (T3 = true karena $0) | Monitor membedakan "tak ada eksekusi" dari "coverage lulus" |

### P2 — Bernilai (jangka menengah)

| ID | Tindakan | Kriteria selesai |
|---|---|---|
| P2-A | Kembalikan E2 (perps directional) **hanya setelah** P0-C lulus | E2 aktif dengan gate coverage, bukan manual |
| P2-B | Kalibrasi target volume bertahap (bukan $1,3M langsung) | Target bertingkat terkalibrasi-modal disepakati & dipantau |
| P2-C | Riset rebate tier & estimasi nilai SoPoint | Estimasi poin/$ tersedia → keputusan burn fee rasional |
| P2-D | Kandidat komersialisasi multi-venue (opsi, §17) | Brief kelayakan ditulis; **belum ada artefaknya** |

---

## 12. Timeline

### 12.1 Kejadian nyata bertanggal

| Tanggal | Kejadian | Sumber |
|---|---|---|
| 2026-05-17 | Integrasi SoDEX ke data lake multi-exchange | commit `61670cf` |
| 2026-05-20 | Modul farming SoPoints + build CLI resmi | commit `c3e52fe`, `8d659b0` |
| 2026-05-22 | `SODEX.md` referensi komprehensif (mode scalp) | commit `57f125e` |
| 2026-06-09 | Doktrin farming (target $1,3M/mgg, >69%) | `docs/SODEX_FARMING_DOCTRINE.md` |
| 2026-06-18 | Masterplan ilmiah (falsification-first) | `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md` |
| 2026-06-20 | Fill E2 terakhir | `twin_engine.db` (E2 max ts) |
| 2026-06-27 | PVE-B39: aktivasi 4 pair + ledger volume | commit `8e17b60` |
| 2026-07-23 | E1 fill terakhir (06:24:30Z); PVE fill terakhir (07:35:41Z); heartbeat E1 mati (07:39:33Z) | `twin_engine.db`; `data/e1_autopilot_heartbeat.json` |
| 2026-08-01 | Pivot tujuan: profit swing maksimal | `SODEX.md:4-5` |
| 2026-08-02 | Peta/profilosofi swing; koreksi prinsip hold-duration | `docs/SODEX_SWING_PHILOSOPHY_AND_MAP_20260802.md` |
| 2026-09-02 | Peta arsitektur v2.0 (North Star) | `docs/SODEX_ARCHITECTURE_MAP.md` |
| 2026-09-05 | Cut-over geometri baru (TP6/SL1.5) di paper | `scripts/sodex_maturation_tracker.py:20` |
| 2026-09-15 | Cut-off pemulihan + dust policy denominator | `reports/SODEX_RECOVERY_MONITOR_LATEST.md:4`; komentar sumber |
| 2026-09-19/21 | Insiden live halt / SELL spot diblokir | `data/SODEX_SPOT_SELL_BLOCKED` (2026-09-21T04:05:44Z) |
| 2026-09-25 | PVE_PAUSE ditulis gate coverage; perbaikan pair-gate, PEAK_TRAIL, harmonisasi phantom | `data/PVE_PAUSE` (2026-09-25T15:23:14Z); `git log` |
| 2026-09-26 | Arm ATR-adaptif; snapshot dokumen ini | commit `9961ad4`, `353ba2e`; konteks |

### 12.2 Deadline & sisa hari

| Item | Nilai | Sumber |
|---|---|---|
| Deadline | **2026-10-16 16:59:59 UTC** | `reports/SODEX_RECOVERY_MONITOR_LATEST.md:5` |
| Sisa hari (per 2026-09-26T10:01:26Z) | **20,29 hari** | hitung ulang Python |
| Blok SELL spot berjalan | 5,25 hari (sejak 2026-09-21T04:05:44Z) | hitung ulang |
| E1 zero-fill | 94,26 hari (135.735 menit) | `logs/e1_autopilot.log` 2026-09-26T06:15:18Z |
| Heartbeat E1 mati | 65,10 hari (sejak 2026-07-23T07:39:33Z) | `data/e1_autopilot_heartbeat.json` |

---

## 13. Metode

> Metode dipakai untuk memutuskan naik/turun track dan memvalidasi klaim. Semua ambang bersumber.

| Metode | Definisi operasional | Sumber |
|---|---|---|
| **Gate statistik 4-pintu** | n≥50 · WR≥50% · PF≥1,5 · ROI≥0,7% | `scripts/sodex_maturation_tracker.py:23-26,85-90` |
| **Wilson CI** | Interval keyakinan proporsi untuk WR/directional | `docs/SODEX_ARCHITECTURE_MAP.md` (gate CI95); modul statistik terkait |
| **Bootstrap CI95** | Interval keyakinan EV/mean PnL via resampling | `scripts/sodex_recovery_monitor.py:116` (`bootstrap_ci`, rounds=1000) |
| **WFE** | Walk-forward efficiency 0,5–0,7 sebagai ambang kesehatan | `docs/SODEX_ARCHITECTURE_MAP.md:39` |
| **P(EV>0)** | Probabilitas EV positif; <5% → disable track | `docs/SODEX_ARCHITECTURE_MAP.md:90` |
| **BH-FDR** | Benjamini–Hochberg FDR untuk uji multi-pair (pair-drag) | commit `c705029`; `scripts/sodex_maturation_tracker.py:55-61` |
| **Aturan n<20 = MONITOR** | Sampel < 20 → status MONITOR (belum layak keputusan; hanya observasi) | konvensi internal; lihat catatan di bawah |
| **Split-half & DSR** | Validasi stabilitas; DSR<0,95 = marginal | `docs/SODEX_SWING_PHILOSOPHY_AND_MAP_20260802.md` banner |

**Catatan kejujuran metode (temuan F-05):** Aturan **n<20 = MONITOR** dipakai sebagai konvensi
internal (track belum layak keputusan) namun **tidak ditemukan sebagai konstanta bernama** di kode
tracker/monitor yang diperiksa (`scripts/sodex_maturation_tracker.py` memakai `MIN_N=50`;
`docs/SODEX_ARCHITECTURE_MAP.md` memakai n≥50). Jadi: (a) n<20 praktis ≤ n<50 → tetap MONITOR;
(b) nilai ambang 20 sebagai konstanta eksplisit = **NO-DATA**; cara memperoleh: `grep -rn "n<20\|MIN_N"
scripts/ anantara/` dan menetapkan konstanta resmi bila diinginkan.

---

## 14. Prinsip Kerja Utama

> Prinsip di bawah adalah yang **benar-benar dioperasikan** SoDEX untuk mengejar target profit (§5, §6).
> Tiap prinsip dipasangkan dengan **konsekuensi terukur bila dilanggar** — bukan narasi.

| # | Prinsip | Pernyataan operasional | Cara diukur | Bukti di kode/data | Konsekuensi bila dilanggar (terukur) |
|---|---|---|---|---|---|
| P-1 | **Profit-first (PnL maksimal; 0,7%/window = harga mati/batas bawah)** | Tujuan utama = profit PnL maksimal; ambang ≥0,7% wallet/trade adalah **batas bawah**, bukan aspirasi | konstanta target + gate `ROI>=0.7%` di tracker | `scripts/sodex_paper_config.py:15` (`TARGET_MIN_PCT = 0.007`); `scripts/sodex_maturation_tracker.py:23-26,85-90`; `docs/SODEX_ARCHITECTURE_MAP.md` (North Star); §6.2 | Rekalkulasi jujur dgn wallet $276,58 → `wallet_roi_pct` = **+0,635%** (< 0,7%) → gate **GAGAL**, `target_met` = **22/97** (`data/sodex_maturation_status.json`, lampiran A.3). Bila dipaksa GO → yang dikejar volume, bukan profit |
| P-2 | **Disiplin gate fail-closed (PVE_PAUSE, HALT, kill-switch)** | Bila coverage/risiko tak terpenuhi → sistem **berhenti**, bukan lanjut dengan asumsi | keberadaan berkas gate & jalur auto-clear | `data/PVE_PAUSE` (`source=e1_coverage_gate`, `e1_fill_24h=0.0` < `threshold=300.0`); `scripts/sodex_safety_guardian.py:798-847`; `data/SAFETY_HALT`/`PNL_HALT` (`scripts/sodex_deadman_switch.py:32,138`); `REALWIDE_LIVE_KILL`/`SPOT_LIVE_KILL` (`reports/SODEX_RECOVERY_MONITOR_LATEST.json`) | Menghapus PVE_PAUSE manual = bypass gate → arm volume jalan di atas E1 dorman (E1 zero-fill **94,26 hari**). Jalur SAH hanya auto-clear gate atau prosedur operator terdokumentasi (§11 P0-D) |
| P-3 | **Sumber kebenaran tunggal (ground truth & rekonsiliasi)** | Satu sumber internal kanonik; state JSON/DB direkonsiliasi ke venue sebelum dipercaya | `canonical_volume_source`; flag live di ground truth | `data/ground_truth.json` (`live_flags.*="0"`, `git_sha=353ba2e`); `data/sodex_monitor_eval/latest.json`; `scripts/sodex_paper_config.py:1-8` ("single source of truth"); commit `2b27351`, `39cb1e7` | Klaim ganda → **phantom/ghost** (insiden reverse-phantom 2026-09-25; harmonisasi BTC/AAVE/SOL/UNI). Volume window berjalan = 0 (§18.1) |
| P-4 | **Sizing & risiko per posisi (ceiling, bukan target)** | Notional default $100 · leverage 3x · risiko **≤2,1% wallet**/posisi · maks **6** posisi koncurrent | konstanta sizing & cap | `scripts/sodex_paper_config.py:102-105` (`NOTIONAL_DEFAULT=100.0`, `LEVERAGE_DEFAULT=3`, `RISK_PCT_WALLET=0.021`, `MAX_POSITIONS=6`) | Naikkan sizing di luar ceiling → $100×3x @SL2% = $2 risiko = **2,1% wallet**, di puncak rentang aman half-Kelly (komentar sumber: "JANGAN naikkan") |
| P-5 | **Geometri exit (TP/SL/trailing/time-stop)** | Tiap track punya geometri eksplisit; SL aktif dari t=0; exit punya lantai trailing + time-stop | `GEOMETRY` dict per track; cut-over bertanggal | `scripts/sodex_paper_config.py:74-93`; PEAK_TRAIL floor **+2%** (commit `efa0be6`); time-stop **30h** | Min-hold 12h tanpa SL (pra-fix 2026-09-04) → **37/132 (28%)** trade SWING kena EMERGENCY_SL. REALWIDE (SL t=0) = **0%** emergency SL (role model) |
| P-6 | **Ritme belajar (deep loop)** | Tiap trade → telemetry → model/UCB1 → learned params → drift-check ke config kanonik | loop harian/mingguan + audit trail | `scripts/sodex_deep_learn.py` (`--loop`/`--status`); `data/swing_deep_learning.jsonl` (ts 2026-09-26T10:00:09Z); §10.2 | Tanpa drift-check → parameter track menyimpang dari kanonik; peta arsitektur tertinggal (n=43 vs realisasi 197, F-04) |
| P-7 | **Jaminan jejak bukti (evidence-first)** | Setiap angka bersumber (path+baris); klaim tanpa bukti ditulis **NO-DATA** + cara memperoleh | audit ulang verbatim | `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md` (falsification-first); Lampiran A (kutipan verbatim); §13 catatan F-05 | Klaim tanpa bukti → verdict **"GO artifisial"** (F-03: denominator usang $108,10 vs wallet $276,58) |

---

## 15. Metode Kerja (Mode Operasi)

> Daftar **mode yang benar-benar ada di kode/config** SoDEX (bukan usulan). Status jujur: mode yang
> sedang **PAUSE/REJECT** atau **belum pernah dijalankan** ditandai eksplisit di kolom Kekurangan.

| Mode | Cara kerja | Kondisi aktivasi (flag/env/unit) | Kelebihan | Kekurangan | Bukti (file/baris/state) |
|---|---|---|---|---|---|
| **SCALP / volume (PVE)** | Patient-maker open→close (`patient_mm_round`), volume ≈ 2×margin×leverage, ~99% maker | env `SODEX_SCALP_MODE=1`; job `job_sodex_scalp` tiap 10 mnt; gate enable+kill+cap volume | Volume murah untuk SoPoints/tier; spread capture | **SEDANG PAUSE** (`PVE_PAUSE`, source `e1_coverage_gate`); anti-wash membatasi; ekonomi farming tak layak di modal kecil (R-5) | `SODEX.md:60-70`; `data/PVE_PAUSE`; `scripts/sodex_safety_guardian.py:798-847` |
| **E1 spot (flywheel profit)** | Maker-biased spot round-trip (subsidi fee) | engine twin E1; gate coverage E1 fill ≥$300/24h | Bila spread-capture positif dapat menutup fee | **DORMAN ~94 hari** zero-fill; heartbeat mati 65 hari; `e1_spot_capability_block_reason` aktif | `anantara/sodex_twin_engine.py:105,580`; `logs/e1_autopilot.log`; `data/e1_autopilot_heartbeat.json` |
| **E2 twin (directional)** | Engine perps arah (funding + OBI) | env/flag `TE_E2_DIR_*` & policy; gate WR/posisi | Seed edge positif terdokumentasi (funding squeeze + OBI) | **PAUSE sejak 2026-06-20** (fill terakhir); perlu gate pemulihan sebelum skala | `anantara/sodex_twin_engine.py` (`Engine2Directional`); `twin_engine.db` (E2 max ts); `scripts/sodex_mode_audit.py` |
| **REALWIDE** | SL-2% t=0 · TP-4% · 3x · time-stop 30h | unit paper REALWIDE (`anantara-paper-realwide.service`) | **TERBUKTI** CI95 EV>0; ROI +3,77% (n=43 → realisasi 197) | Sampel dokumen tertinggal dari realisasi (F-04) | `scripts/sodex_paper_config.py:75`; `docs/SODEX_ARCHITECTURE_MAP.md:59`; `reports/SODEX_RECOVERY_MONITOR_LATEST.md:12` |
| **TWOWAY-LONG** | Sama REALWIDE, SHORT dimatikan | track TWOWAY | CI95 EV>0 ✅ (n=80) | Konflik nama: kode `TWOWAY_LONG` = long-only, state `paper_test_twoway` historis dua arah | `scripts/sodex_paper_config.py:76`; `docs/SODEX_ARCHITECTURE_MAP.md:59` |
| **SWING** | SL-1% t=0 · TP-2,5% · 5x · time-stop 30h | unit paper SWING | Lebih selektif dari REALWIDE | Edge marginal (CI sentuh 0); **pra-fix 28% emergency SL** | `scripts/sodex_paper_config.py:79`; `data/paper_test_swing_state.json` |
| **SWING_PARTIAL** | SWING + ambil 50% profit di +1,2%, sisa TP2,5/SL-protect | track PARTIAL | Realisasi profit lebih awal | Kompleksitas exit; CI95 ≈ 0 | `scripts/sodex_paper_config.py:77-78` |
| **DONCHIAN** | Breakout SL-2/TP-4 | track DONCHIAN | Diversifikasi breakout | **KILL-candidate** P(EV>0)=28% 🔴 | `scripts/sodex_paper_config.py:80`; `docs/SODEX_ARCHITECTURE_MAP.md:61` |
| **SPOT_SWING_v4** | CEX momentum+ADX+regime, long-only, mode adaptif | filter likuiditas `min_volume` $3.000/24h, size $100 | SL aktif dari t=0 (fix jendela gempa −$32,91) | v3 RETIRED; bergantung pair ber-prefix `v` | `scripts/sodex_paper_config.py:83-93` |
| **STRICT vs RELAXED** | STRICT: ADX≥25, ≥4 check, wajib golden-cross · RELAXED: ADX≥15, ≥3 check, golden opsional | env `PAPER_RELAXED` (1=relaxed default, 0=strict v3) | RELAXED percepat pengumpulan data | Temuan commit: **tidak ada alpha entry di mode relaxed** | `scripts/paper_test_swing.py:273-277`; `scripts/paper_test_realwide.py:273-281`; commit `dcf43b8` |
| **ATR-adaptif (arm A1/A2) vs SL tetap** | SL = k×ATR% (arm ATR-adaptif) vs pembanding SL tetap 1% (buta volatilitas) | arm riset di jalur promosi SoDEX | Menyesuaikan stop ke volatilitas | SL tetap 1% = "buta volatilitas"; hasil arm **belum dipromosikan** | `anantara/sodex_governor.py:27,91` (`SL_ATR_K=1.2`); commit `9961ad4`, `b12683e` |
| **LONG-only vs SHORT-BEAR** | Keputusan: long-only (SHORT disabled) · track paper SHORT_BEAR + micro-pilot BEAR | gate regime (`regime==BEAR`) untuk SHORT | SHORT-BEAR = probe edge pasar turun, loss cap | SHORT generik **dibuang** (WR 29,7%, n=37, P(EV>0)=3%); varian shortbear kini **blocked_signal=1704/24h**, 0 closed | `scripts/sodex_paper_config.py` (`LESSONS["short_disable"]`); `scripts/sodex_auto_trader.py:204-206`; `reports/SODEX_RECOVERY_MONITOR_LATEST.json` |
| **Paper vs live mikro** | Paper = track utama; live mikro = eksposur kecil reduce-only | `data/realwide_micro_live_state.json`; resume via `live_resume_approved` | Uji eksekusi nyata tanpa risiko besar | Skala terlalu kecil memenuhi target event; **inkonsistensi label** (state "live" mikro ada, namun `ground_truth.live_flags` semua "0") | `data/realwide_micro_live_state.json` (session_pnl +$0,3479, trades_today 2); `data/ground_truth.json` |
| **Maker (post-only) vs taker** | Default maker `--tif gtx`; close darurat tanpa gtx → boleh taker agar tak macet | flag order `--tif gtx` | Maker fee 0,0114% (≈⅓ taker); anti-wash | Maker fill tidak pasti (stale-book); close tanpa gtx kena taker 0,038% | `anantara/sodex_farming.py:13,669,826,1265`; `SODEX.md:14` |
| **MM modes (4/5/6/7/8/10)** | Mode4 static gate · Mode5 OBI dynamic · Mode6 hybrid dual-side · Mode7 intel maker · Mode8 delta-neutral · Mode10 dual-side spread | riset/paper; sebagian `PAPER_FIRST`/`AFTER_GATE_ONLY` | Mode5/7 lebih pintar dari gate statis | Mode6 `RESEARCH_ONLY`; Mode8 butuh gate dulu; fill-rate belum terbukti | `scripts/sodex_mode_audit.py:38-158`; `anantara/sodex_farming.py:744,928,1117,1544` |
| **Mode jam / dead-zone & gate sesi** | Perp saham/komoditas hanya di sesi AS; kripto 24/7 | `13 ≤ now.hour < 21` UTC untuk `_is_stock_commodity` | Menghindari eksekusi di buku tipis | Kandidat saham di luar jam → "no candidates pass filter" | `scripts/sodex_trend_rider.py:344-374` |

> **Catatan jujur (lihat §18.1):** (a) arm volume PVE **dijeda** dan **belum pernah jalan di window
> berjalan**; (b) E1 **dorman**, E2 **pause**; (c) spot SELL **terblokir** (`data/SODEX_SPOT_SELL_BLOCKED`)
> sehingga mode spot keluar SELL belum dapat dieksekusi; (d) mode SHORT-BEAR berjalan tetapi **hanya
> menghasilkan `blocked_signal`** (0 closed/24h). Basis empiris saat ini = mode **paper long-only**
> (REALWIDE/SWING).

---

## 16. Segmen Value Market

> Di **value/market** mana SoDEX berjalan, dan konsekuensinya bagi target. Semua angka bersumber; yang
> tidak ada ditandai **NO-DATA** + cara memperoleh.

| Dimensi | Nilai (as-is) | Konsekuensi bagi target | Sumber |
|---|---|---|---|
| **Kelas aset** | Kripto di DEX (perp + spot); ekuitas/komoditas hanya sebagai instrumen turunan di venue | Horizon operasi 1h–48h (§10.1); tunduk aturan anti-wash venue | `SODEX.md:3-5`; `docs/SODEX_ARCHITECTURE_MAP.md` |
| **Segmen — perp** | Perp likuid: BTC, ETH, SOL, HYPE, BNB, XRP, DOGE, BCH, ONDO, LINK, AAVE, SUI, UNI, ADA, TRX, ENA, ASTER, PUMP, LIT (+ARB/AVAX/SILVER/XAUT/ZEC ekstensi per track) | Likuiditas cukup untuk maker; pair thin-book kena spread besar | `scripts/sodex_paper_config.py:20-43` |
| **Segmen — spot** | Pair spot ber-prefix **`v`**: vBTC, vETH, vSOL, vTON, vHYPE, vXRP, vLINK, vUNI (vUSDC = kuotasi) | Spot long-only; saat ini SELL terblokir | `scripts/sodex_paper_config.py:93`; `scripts/sodex_downloader.py:42-45`; `scripts/sodex_live_watchdog.py:34-35` |
| **Tipe instrumen** | Perp DEX (leverage; dua arah secara desain) & Spot DEX (long-only) | Perp: bisa short (namun SHORT dibuang); Spot: tak bisa short → bias long struktural | `SODEX.md:60`; `docs/SODEX_ARCHITECTURE_MAP.md` (Long-only) |
| **Venue** | **SoDEX** (sodex.com) — tetap dipilih; switch venue dinilai **−$17 EV** | Migrasi venue ditolak atas dasar bukti biaya | `scripts/sodex_paper_config.py` (`LESSONS["venue_switch"]`); `docs/SODEX_ARCHITECTURE_MAP.md` |
| **Biaya (fee) perp** | maker **0,0114%** · taker **0,038%** (Tier 0 + diskon staking 5%) | Maker ≈ ⅓ taker → mode maker-biased; `MAKER_FEE_RT` 0,024% round-trip | `SODEX.md:14`; `scripts/sodex_paper_config.py:58` |
| **Biaya (fee) spot** | Tier 0: maker **0,035%** · taker **0,065%**; volume spot dihitung **2×** ke tier | Spot ~3× lebih mahal dari perp maker → penghambat flywheel E1 | `SODEX.md:30-38` |
| **Spread** | Model live-measured: BTC 1,3 bps … HYPE/SUI/SILVER/LIT 8 bps; **thin-book (<$550/sisi) → 8 bps** | Spread lebar menggerus edge 0,7%; pair thin-book dihindari/di-pause | `scripts/sodex_paper_config.py:48-58` |
| **Kedalaman (depth)** | Buku tipis bila top-of-book **<$550/sisi** → dikenai 8 bps | Order besar tak dapat maker; sizing dibatasi | `scripts/sodex_paper_config.py:48-58` |
| **Minimum notional** | **$5** per order (kanonik twin engine); konstanta lain $10 (`sodex_autofarm.py:122`) | Batas bawah ukuran order; modal kecil tak bisa memecah posisi lebih halus | `anantara/sodex_twin_engine.py:2058`; `anantara/sodex_autofarm.py:122` |
| **Filter volume minimum** | Spot v4: **$3.000/24h**; queue validator: **$100/jam** (pilot $150/jam); scanner: $50.000 | Menyaring pair tak layak → peluang berkurang namun kualitas naik | `scripts/sodex_paper_config.py:92`; `scripts/sodex_queue_trade_validator.py:35,39`; `anantara/sodex_farming.py:3330,3354` |
| **Modal wallet** | **$276,5823398863654** (perp+spot terkonsolidasi) | Ambang 0,7% = **$1,9361/trade**; ROI jujur window = **+0,635%** (< 0,7%) | `reports/SODEX_RECOVERY_MONITOR_LATEST.json`; §6.3; lampiran A.3 |
| **Efek modal kecil** | Target farming $1,3M/mgg **tidak layak** pada modal ini | Volume-churn = burn fee tak tertutup (R-5) | `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md:72`; §18.2 |
| **Venue non-SoDEX (HL)** | Saldo HL terpantau ~**$7,93** (2 akun) — bukan venue operasi SoDEX | Modal terpisah; bukan denominator SoDEX | `data/ground_truth.json` (`hl_total.observed_account_value_usd=7.9289`) |
| **Pasar multi-venue/CEX** | **NO-DATA** untuk model bisnis/pasar (usulan §17.3) | Tidak ada dasar keputusan | §17.3 (opsi komersialisasi — belum ada artefaknya) |

**Ringkas:** SoDEX berjalan di **ceruk perp DEX likuid + spot DEX pair `v`**, dengan maker jauh lebih
murah dari taker, tetapi **dibatasi** oleh minimum notional $5, buku tipis (<$550/sisi → 8 bps), filter
volume, dan **modal $276,58** yang menjadikan target volume besar tidak layak — sehingga satu-satunya
jalur rasional adalah **profit per trade ≥0,7% wallet ($1,9361)**, bukan volume-churn.

---

## 17. Rencana Jangka Panjang

> Arah 3–12 bulan. **Opsi komersialisasi multi-venue adalah USULAN yang belum memiliki artefak di
> repo — dinyatakan eksplisit sebagai usulan, bukan realisasi.**

### 17.1 Horizon 3 bulan (Okt–Des 2026)

1. **Tutup semua P0** (§11): denominator benar, E1 pulih, blok SELL spot selesai, PVE_PAUSE diangkat
   secara sah. Kriterianya terukur (state JSON + gate).
2. **Buktikan edge dengan denominator jujur**: verdict promosi dihitung dengan wallet nyata; bila gagal
   gate, tetap di paper (no-skipping).
3. **Selaraskan dokumen (F-01/F-04)**: satu target operasi, peta arsitektur sinkron dengan realisasi.

### 17.2 Horizon 6 bulan (2027 Q1)

4. **Skala modal berbasis bukti**: tambah modal **hanya** setelah ekonomi per-dollar positif jujur
   (prinsip masterplan `:111`), skala linear pada edge terbukti.
5. **E2 volume engine dihidupkan didanai edge E1** (Fase 3 masterplan `:97-101`), dengan treasury cap.
6. **SoPoints efisiensi** (Fase 4 masterplan `:103-107`) bila target farming kembali dipertimbangkan.

### 17.3 Horizon 12 bulan (2027)

7. **Opsi komersialisasi — USULAN (belum ada artefaknya).** Fleksibilitas **multi-venue**: generalisasi
   lapisan sinyal/gate/eksekusi agar dapat berjalan di venue DEX lain dan/atau CEX, dengan pemilihan
   venue per-trade (biaya, kedalaman buku, latensi). Ini **belum ada artefaknya** di repo saat dokumen
   ini ditulis — statusnya murni usulan. Cara memvalidasi bila diambil: tulis brief kelayakan + gate
   statistik lintas-venue, lalu bandingkan EV bersih lintas venue pada periode OOS.
8. **Produk/layanan**(turunan komersialisasi) — juga **USULAN**, tanpa artefak. **NO-DATA** untuk
   model bisnis/pasar; cara memperoleh: riset pasar + studi kelayakan terpisah.

---

## 18. Risiko, Asumsi & Status Jujur

### 18.1 Status jujur (as-is)

| Klaim status | Nilai | Bukti |
|---|---|---|
| Throughput live (window berjalan) | **NOL** — 0 fill, $0 volume, $0 PnL | `data/sodex_monitor_eval/latest.json` (`ledger.fills.count=0`, `volume.raw_total_usd=0.0`, `realized_pnl_usd=0.0`), ts 2026-09-26T10:00:16Z |
| Flag live | Semua `"0"` (AUTOTRADE_LIVE, PREGAIN_LIVE, SODEX_SPOT_FARM_LIVE, FUNDING_LIVE) | `data/ground_truth.json` |
| E1 dorman | **~94 hari** zero-fill (135.735 menit); heartbeat mati 65 hari | `logs/e1_autopilot.log`; `data/e1_autopilot_heartbeat.json` |
| PVE (volume arm) | **Dijeda** oleh gate coverage E1 | `data/PVE_PAUSE` (`source=e1_coverage_gate`, `e1_fill_24h=0.0`, `threshold=300.0`) |
| Spot SELL | **Terblokir** | `data/SODEX_SPOT_SELL_BLOCKED` (`reason=SELL_CANCELLED_TIMEOUT_EXIT_FAILED`) |
| Verdict promosi | **GO artifisial** | `data/sodex_maturation_status.json` `verdict="GO…"` dengan denominator usang **$108,10** vs wallet nyata **$276,58** (§6.3) |
| Volume window | **NO-DATA** untuk denominator resmi venue (SoPoints di luar API) | `SODEX.md:13` |
| Rekonsiliasi resmi volume | Sumber kanonik internal = `internal_ledger` (bukan dashboard resmi) | `data/sodex_monitor_eval/latest.json` → `verdict.progress.canonical_volume_source` |

### 18.2 Risiko

| ID | Risiko | Dampak | Mitigasi (ada di artefak?) |
|---|---|---|---|
| R-1 | Denominator usang → keputusan promosi salah (GO palsu) | Keputusan live berbasis angka salah | Perlu P0-A; belum ada mitigasi |
| R-2 | E1 dorman berkepanjangan → PVE tak pernah jalan | Arm volume lumpuh | Gate auto-clear `check_e1_coverage:838-845` (ada) |
| R-3 | SELL spot terblokir → posisi spot tak bisa keluar | Risiko posisi macet | `data/SODEX_SPOT_SELL_BLOCKED` + prosedur operator (ada, belum selesai) |
| R-4 | Coverage "artifisial true" saat $0 → rasa aman palsu | Gate lolos tanpa makna | Perlu P1-D |
| R-5 | Volume farming pada modal kecil tak layak ($1,3M vs modal) | Burn fee tak tertutup | Masterplan §4 jujur (`:72`) sudah mengakui |
| R-6 | Edge tipis & marginal (DSR<0,95) | Overfit/berhenti saat live | Gate statistik CP95/bootstrap (ada) |

### 18.3 Asumsi

| ID | Asumsi | Bila salah |
|---|---|---|
| A-1 | Data state JSON/DB dapat dipercaya sebagai sumber tunggal internal | Keputusan berbasis data salah → perlu rekonsiliasi venue |
| A-2 | Filter pair-gate membuat metrik konsisten dengan eksekusi | Metrik bias → promosi terlalu optimistis |
| A-3 | Snapshot wallet $276,58 mencerminkan realitas akun | Denominator salah arah (bisa lebih besar/kecil) |
| A-4 | `1h–48h` swing tetap horizon operasi | Perlu desain ulang sinyal/exit |
| A-5 | Opsi multi-venue (§17) belum dibutuhkan sekarang | Prioritas bergeser, sumber daya terbagi |

### 18.4 Ketidaksesuaian dokumen-vs-kenyataan (kumpulan temuan)

| ID | Temuan | Bukti |
|---|---|---|
| F-01 | Dua dokumen kanonik saling menyatakan superseded/aktif | `SODEX.md:7-8` vs `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md:4` |
| F-02 | Tidak ada dokumen berjudul/nama "PRD" formal untuk SoDEX | `ls docs/ \| grep -i SODEX` (tidak ada) |
| F-03 | Verdict GO memakai denominator usang $108,10 (nyata $276,58) | `scripts/sodex_maturation_tracker.py:27`; `reports/SODEX_RECOVERY_MONITOR_LATEST.json` |
| F-04 | Peta arsitektur n/ROI/CI95 tertinggal dari realisasi (REALWIDE 43 vs 197) | `docs/SODEX_ARCHITECTURE_MAP.md:59` vs `reports/SODEX_RECOVERY_MONITOR_LATEST.md:12` |
| F-05 | Konstanta "n<20 = MONITOR" tidak eksplisit di kode yang diperiksa | `scripts/sodex_maturation_tracker.py` (MIN_N=50) |
| F-06 | Masterplan §2 (Jun) modal ~$186 vs realisasi $276,58 (+48,7%) | `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md:20` vs monitor |
| F-07 | Masterplan menyatakan E2 OFF Fase 1, tetapi DB menunjukkan E2 pernah berjalan (3.368 fill) | `docs/SODEX_FARMING_MASTERPLAN_2026-06-18.md:31` vs `twin_engine.db` |
| F-08 | Monitor menyatakan coverage E1/E2 "true" padahal fee/PnL = $0 (keduanya nol) | `data/sodex_monitor_eval/latest.json` |
| F-09 | **Mode volume (PVE/scalp) belum pernah dijalankan** pada window berjalan — arm volume dijeda oleh gate coverage E1 (diturunkan dari §18) | `data/PVE_PAUSE`; `data/sodex_monitor_eval/latest.json` (`ledger.fills.count=0`); `SODEX.md:60-70` |
| F-10 | **Label paper vs live mikro tidak konsisten:** state "live" mikro beraktivitas (trades_today 2, session_pnl +$0,3479), sementara `ground_truth.live_flags` semua `"0"` | `data/realwide_micro_live_state.json` vs `data/ground_truth.json` |
| F-11 | **Dua konstanta minimum notional berbeda:** $5 (kanonik twin engine) vs $10 (`sodex_autofarm.py`) | `anantara/sodex_twin_engine.py:2058` vs `anantara/sodex_autofarm.py:122` |

---

## Lampiran A — Kutipan Bukti Mentah

> Empat kutipan berikut diambil verbatim dari sumber, sebagai jejak bukti yang dapat diaudit ulang.

**A.1 — `data/PVE_PAUSE` (freeze PVE oleh gate coverage E1):**
```json
{
  "ts": "2026-09-25T15:23:14.766000+00:00",
  "source": "e1_coverage_gate",
  "e1_fill_24h": 0.0,
  "e1_profit_24h": 0.0,
  "threshold": 300.0,
  "reason": "E1 dormant: fill $0 < threshold $300/24h"
}
```

**A.2 — `data/SODEX_SPOT_SELL_BLOCKED` (SELL spot diblokir):**
```json
{
  "ts": "2026-09-21T04:05:44.020415+00:00",
  "source": "sodex_spot_daemon",
  "reason": "SELL_CANCELLED_TIMEOUT_EXIT_FAILED",
  "operator_action": "Verify a tiny spot SELL manually in SoDEX UI, then remove this file if the account can sell."
}
```

**A.3 — `data/sodex_maturation_status.json` (verdict GO dengan denominator usang):**
```json
{'generated_utc': '2026-09-26T09:58:58.634073+00:00', 'n_forward': 97, 'target_n': 50,
 'wr': 0.6186, 'pf': 2.239, 'avg_net_pct': 0.5824, 'wallet_roi_pct': 1.6163,
 'target_met_per_trade': 47,
 'gates': {'n>=50': True, 'WR>=50%': True, 'PF>=1.5': True, 'ROI>=0.7%': True},
 'verdict': 'GO — statistical gates pass (live status is controlled separately)'}
```
Rekalkulasi dengan wallet nyata $276,58 → ambang/trade $1,9361 → `target_met` = **22/97**,
`wallet_roi_pct` = **+0,635%** (gagal gate 0,7%).

**A.4 — `data/sodex_monitor_eval/latest.json` (throughput live nol):**
```
ts = 2026-09-26T10:00:16.885895+00:00
ledger.fills.count = 0
ledger.volume.raw_total_usd = 0.0
verdict.progress.realized_pnl_usd = 0.0
canonical_volume_source = internal_ledger
```

**A.5 — `logs/e1_autopilot.log` (E1 zero-fill ~94 hari):**
```
[2026-09-26 06:15:18Z] 🟡 ZERO-FILL 135735 menit tetapi target policy sedang block/no-trade. Tidak restart; pantau heartbeat dan policy.
```
135.735 menit ÷ 1.440 = **94,26 hari**.

*BAB SoDEX — selesai. Seluruh proses READ-ONLY; satu-satunya berkas yang ditulis adalah dokumen ini.*
