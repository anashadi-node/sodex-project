# SoDEX Farming Latest Map, Structure, and Target Assessment

Tanggal audit: 16 Juli 2026, sekitar 21:22 WIB  
Mode audit: read-only, no order, no cancel, no leverage change, no service restart  
Sumber bukti lokal:

- `data/sodex_system_map/latest.json`
- `data/sodex_project_structure/latest.json`
- `data/sodex_quant_stat/latest.json`
- `data/sodex_monitor_eval/latest.json`
- `data/SAFETY_HALT`

## Executive Verdict

Jawaban langsung: **belum**. Struktur project SoDEX Farming terbaru sudah jauh lebih rapi dan secara arsitektur sudah lebih layak untuk mengejar target secara bertahap, tetapi **kondisi aktual sekarang belum bisa mencapai semua target PnL Profit, Rasio Real, dan Volume Transaksi**.

Alasan utama:

1. `SAFETY_HALT` aktif karena `ratio_breach_after_SPCX_improved_maker_trade`.
2. Sistem map berstatus `degraded`.
3. Blocker aktif: `micro_pilot_negative_edge_cooldown`.
4. Quant-stat engine membaca 10 kandidat dan hasilnya: `TRADE_READY=0`, `WAIT=0`, `BLOCK=10`.
5. Monitor mingguan status `FAIL`.
6. Realized PnL masih negatif.
7. Rasio real canonical masih di bawah target.
8. Volume mingguan masih sangat jauh dari target.

Kesimpulan ilmiah: **struktur sudah mendukung kontrol risiko dan seleksi probabilistik, tetapi edge trading yang terbukti belum ada. Sistem yang benar justru harus menahan scaling volume sampai probabilitas, biaya, dan rasio lolos gate.**

## Peta Sistem Terbaru

Canonical flow terbaru:

```text
data_collectors
-> market_scan
-> technical_probability_gate
-> quant_stat_decision_engine
-> autonomous_research
-> monitor_eval
-> deep_learning_loop
-> policy_and_gates
-> execution_guard
-> supervisor_reporting
-> operator_approval
-> micro_pilot_or_engine
-> experience_log_back_to_learning
```

Interpretasi:

- `data_collectors` mengumpulkan OBI, ticker, spot/perps, dan input monitor.
- `market_scan` memilih kandidat pasar SoDEX secara read-only.
- `technical_probability_gate` mengolah 7 sinyal teknikal sebelum kandidat masuk ke decision engine.
- `quant_stat_decision_engine` menggabungkan probabilitas TA, kalibrasi statistik, fill probability, cost model, dan budget rasio.
- `policy_and_gates` dan `execution_guard` menjadi lapisan penahan sebelum live exposure.
- `operator_approval` tetap wajib sebelum order-capable engine dipakai.
- `experience_log_back_to_learning` membuat hasil eksekusi/pilot menjadi data pembelajaran untuk iterasi berikutnya.

Status sistem map: **degraded**  
Blocker aktif: `micro_pilot_negative_edge_cooldown`

## Struktur Project Terbaru

Total item terindeks: **182**

| Domain | Jumlah | Fungsi |
|---|---:|---|
| `core_decision` | 10 | Policy, target, probability, system map, quant-stat decision. |
| `safety` | 10 | Safety halt, guardian, deadman, order surface audit, reconciliation. |
| `execution` | 6 | Engine yang order-capable atau historis order-capable; wajib di belakang guard dan approval. |
| `market_data` | 6 | Scanner, monitor eval, OBI, ticker, funding, data pasar. |
| `research` | 10 | Backtest, paper test, autonomous research, dokumen quant. |
| `services` | 12 | Systemd service/timer entry point. |
| `docs` | 30 | Peta, struktur, audit, doktrin, handover, status. |
| `data` | 27 | Latest report, JSONL history, safety flags, ledger lokal. |
| `tests` | 37 | Unit/regression tests untuk safety, decision, monitor, execution helper. |
| `legacy_or_archive` | 34 | Artefak lama/historis; sebaiknya read-only kecuali dimigrasi eksplisit. |

Struktur ini sekarang lebih jelas karena memisahkan:

- observasi pasar,
- analisis teknikal,
- probabilitas/statistik,
- safety gate,
- execution surface,
- monitoring,
- dokumen,
- test coverage,
- arsip/legacy.

## Assessment Target

### 1. PnL Profit

Status: **FAIL**

Bukti:

- Realized net PnL: **-4.518557057860704 USD**
- `combined_pnl_negative`
- `realized_pnl_negative`
- `e1_profit_does_not_cover_e2_fees`
- `micro_pilot_negative_edge_cooldown`

Analisa:

Sistem belum membuktikan expectancy positif. Jika volume dinaikkan saat PnL negatif dan cooldown aktif, risiko yang terjadi bukan profit scaling, tetapi loss scaling. Secara kuantitatif, target profit belum layak dikejar dengan live scaling sampai model menunjukkan edge setelah fee, spread, fill risk, dan adverse selection.

### 2. Rasio Real

Status: **FAIL untuk canonical real ratio**

Bukti:

- Target `volume_fee_ratio_min`: **5100**
- `volume_to_fee`: **3589.8687544582604**
- `volume_to_realized_loss`: **1440.3810614434758**
- `weighted_volume_to_fee`: **6538.234781371469**

Analisa:

Ada satu metrik weighted yang terlihat melewati 5100, tetapi canonical `volume_to_fee` dan terutama `volume_to_realized_loss` masih gagal. Karena target pengguna adalah Rasio Real, maka metrik yang wajib dipakai harus konservatif, bukan hanya weighted. Dengan safety halt aktif karena ratio breach, sistem tidak boleh menganggap rasio sudah aman.

### 3. Volume Transaksi

Status: **FAIL berat**

Bukti:

- Target volume mingguan: **1,300,000 USD**
- Volume canonical/internal ledger: **6,508.44401119431 USD**
- Progress mingguan: **0.5006495393226392%**
- Sisa waktu ke snapshot: **33.6615 jam**
- Snapshot: **18 Juli 2026 07:00 WIB**

Analisa:

Volume belum naik signifikan karena gate yang benar sedang memblokir kandidat buruk. Ini bukan sekadar masalah struktur folder atau service; masalah inti adalah tidak ada kandidat live yang lolos probabilitas, kalibrasi, rasio, dan safety. Menaikkan volume secara paksa sekarang akan melanggar tujuan Rasio Real dan memperbesar risiko PnL negatif.

## Kondisi Quant-Stat Terbaru

Ringkasan engine:

```text
total candidates = 10
TRADE_READY      = 0
WAIT             = 0
BLOCK            = 10
min ratio        = 5100
notional test    = 12 USD
policy           = no orders, no cancels, no leverage change, no service restart
```

Blocker yang muncul pada kandidat:

- `safety_halt_active`
- `ta_probability_gate_not_passed`
- `direction_probability_below_minimum`
- `calibration_not_passed`
- `ratio_budget_not_passed` pada sebagian kandidat

Interpretasi:

Quant-stat engine sudah melakukan fungsi yang benar: menolak trade saat bukti belum cukup. Ini baik untuk keselamatan sistem, tetapi berarti sistem belum siap mengejar volume besar.

## Apakah Struktur Terbaru Bisa Mencapai Target?

Jawaban bertingkat:

| Target | Bisa dicapai dengan struktur terbaru? | Kondisi saat ini |
|---|---|---|
| PnL Profit | Bisa hanya jika edge terbukti positif setelah biaya. | Belum, PnL negatif. |
| Rasio Real minimal 1:5100 | Bisa hanya jika cost model, maker fill, dan adverse loss konsisten lolos. | Belum, canonical ratio gagal. |
| Volume Transaksi tinggi | Bisa hanya setelah ada banyak kandidat `TRADE_READY` dan safety halt cleared. | Belum, volume baru 0.5% dari target mingguan. |

Kesimpulan: **struktur terbaru adalah fondasi, bukan bukti keberhasilan. Target bisa menjadi realistis setelah gate menghasilkan kandidat yang valid, tetapi tidak realistis untuk dipaksa saat semua kandidat masih BLOCK.**

## Syarat Minimum Sebelum Scaling Volume

Scaling volume baru layak dipertimbangkan jika semua kondisi ini terpenuhi:

1. `SAFETY_HALT` sudah diselesaikan berdasarkan root-cause ratio breach dan disetujui operator.
2. `sodex_quant_stat_engine` menghasilkan `TRADE_READY > 0`, bukan semua `BLOCK`.
3. 7-signal TA gate lolos dengan probability minimal **0.80**.
4. Kalibrasi statistik memiliki sampel cukup dan tidak kalah dari baseline.
5. Cost model menunjukkan expected edge positif setelah maker fee, spread, fill risk, dan adverse selection.
6. Canonical `volume_to_fee` dan `volume_to_realized_loss` melewati target rasio secara konservatif.
7. Micro-pilot keluar dari negative-edge cooldown.
8. Forward paper atau micro-live menunjukkan PnL positif, bukan hanya backtest.
9. Official/dashboard reconciliation tidak bertentangan dengan ledger lokal.
10. Eksekusi tetap di bawah operator approval dan guard.

## Roadmap Pemulihan yang Aman

### Fase 1: Research Only

Selama `SAFETY_HALT` aktif:

- tidak scale volume,
- tidak restart order-capable service,
- tidak ubah leverage,
- tidak paksa entry,
- hanya harvest data, paper decision, audit ratio breach.

### Fase 2: Calibration Harvest

Target:

- kumpulkan sampel kandidat,
- ukur hit-rate arah,
- ukur fill probability,
- ukur adverse selection,
- validasi Brier/ECE,
- pisahkan kandidat yang profit after fee dari yang hanya menghasilkan volume.

### Fase 3: Micro Pilot Terkontrol

Syarat:

- `TRADE_READY > 0`,
- ratio budget pass,
- expected edge positif,
- max loss kecil dan eksplisit,
- no open hidden exposure,
- operator approval.

### Fase 4: Volume Expansion

Volume baru dinaikkan bertahap jika:

- PnL realized sudah positif,
- ratio real stabil di atas target,
- win-rate dan expectancy stabil,
- halt tidak berulang,
- perbedaan official dashboard vs internal ledger sudah direkonsiliasi.

## Rekomendasi Operasional

Rekomendasi sekarang: **RESEARCH ONLY / NO SCALE VOLUME**.

Alasan:

- safety halt aktif,
- quant-stat tidak punya kandidat trade-ready,
- PnL negatif,
- rasio canonical gagal,
- volume jauh dari target,
- micro-pilot sedang negative-edge cooldown.

Tindakan terbaik bukan memaksa volume, tetapi memperbaiki kualitas kandidat:

- tambah kualitas data OBI dan market history,
- perbaiki kalibrasi probabilitas,
- audit ratio breach SPCX,
- validasi 7 sinyal TA terhadap hasil aktual,
- gunakan quant-stat sebagai gate wajib,
- hanya izinkan micro-pilot ketika edge positif dan rasio aman.

## Final Answer

Dengan struktur terbaru, project SoDEX Farming **lebih siap secara arsitektur** dibanding sebelumnya karena sudah memiliki pemisahan map, struktur, safety, technical gate, quant-stat engine, monitor, dan test layer.

Namun secara kondisi aktual 16 Juli 2026, struktur ini **belum bisa mencapai target PnL Profit, Rasio Real, dan Volume Transaksi secara bersamaan**. Target belum gagal karena kurang map; target gagal karena sistem belum punya live edge yang terbukti, rasio real masih di bawah target konservatif, dan semua kandidat quant-stat masih diblokir.

Keputusan ilmiah: **jangan scale volume sekarang**. Gunakan struktur baru untuk membuktikan edge dulu, lalu naikkan volume hanya ketika PnL, rasio, dan quant-stat gate sudah sama-sama hijau.
