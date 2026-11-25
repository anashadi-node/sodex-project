# Epoch E6 Paper Arena — batas, env efektif, cacat yang ditemukan (2026-11-15)

Status: BERJALAN. Dokumen ini mengunci definisi epoch supaya pembacaan hasil nanti
tidak ambigu (epoch mana, arm mana, env apa). Semua angka diambil dari proses hidup
(`/proc/<pid>/environ`), bukan dari isi file unit.

## 1. Batas epoch

| Arm | PID | Mulai (lokal WIB) | Mulai (UTC) | Catatan |
|-----|-----|-------------------|-------------|---------|
| ab9a | 2993589 | 2026-11-15 07:55:52 | 2026-11-15 00:55:52 | baseline geometri TP1,5/SL6,0 |
| ab9b | 2993591 | 2026-11-15 07:55:52 | 2026-11-15 00:55:52 | TP 3,0 |
| ab9c | 2993593 | 2026-11-15 07:55:52 | 2026-11-15 00:55:52 | pre24_min 3,0 |
| ab9d | 2993595 | 2026-11-15 07:55:52 | 2026-11-15 00:55:52 | kontrol: regime gate OFF |
| ab9e | 3015785 | 2026-11-15 08:06:50 | 2026-11-15 01:06:50 | geometri TP1,5/SL2,0 |

Gerbang restart dipenuhi lebih dulu: full suite `pytest tests/ -q` = **5071 passed,
42 skipped, 293 warnings, 83 subtests passed in 275,13 s (exit 0)** pada HEAD
`a96f095`.

## 2. Matrix env efektif (dibaca dari `/proc/<pid>/environ`)

Env identik di semua arm kecuali yang tercantum. Pembeda 9e vs 9a **hanya** `TW_SL_PCT`.

| Env | 9a | 9b | 9c | 9d | 9e |
|-----|----|----|----|----|----|
| `TW_INVERT_SIGNAL` | 0 | 0 | 0 | 0 | 0 |
| `TW_SHORT_LEG` | 1 | 1 | 1 | 1 | 1 |
| `TW_REGIME_GATE` | 1 | 1 | 1 | **0** | 1 |
| `PAPER_BTC_GATE_QUOTA` | 2 | 2 | 2 | — | 2 |
| `TW_TP_PCT` | 0,015 | **0,030** | 0,015 | 0,015 | 0,015 |
| `TW_SL_PCT` | 0,06 | 0,06 | 0,06 | 0,06 | **0,02** |
| `TW_PRE24_MIN` | — | — | **3,0** | — | — |
| `TW_FUNNEL` | 1 | 1 | 1 | 1 | 1 |

Regime BTC saat verifikasi: `btc_daily_regime() = BEAR`, `btc_momentum_ok() = True`,
`btc_gate_pass('signal') = True`. Jadi SHORT boleh entry di semua arm ber-gate.

## 3. Cacat yang ditemukan dan diperbaiki di epoch ini

### 3.1 Unit 9e v1 kehilangan dua env (ditemukan dari `/proc`, bukan dari log)
Versi pertama `anantara-paper-ab9e.service` tidak memuat `TW_SHORT_LEG=1` dan
`PAPER_BTC_GATE_QUOTA=2`. Akibatnya arm berlabel "SHORT-only BEAR" berjalan tanpa
kaki SHORT dan tanpa kuota gate → **0 entry** selama masa hidupnya. Bukti funnel
saat itu: `reason_no_signal` 44×, `skip_random_btc_gate` 2×.

Perbaikan: header unit ditulis ulang (daftar env wajib + pernyataan paritas env),
`ExecStart` memuat dua env tersebut, `daemon-reload` + `restart`.

Bukti pasca-perbaikan (entry pertama 9e, UTC 01:06:51–01:12:03): 6 posisi,
**semua SHORT** — 4 `SIGNAL` (ETH, SOL, LINK, SUI) + 2 `RANDOM` (ENA, BCH).
Sebelum perbaikan: 0 posisi. Ini bukti langsung, bukan inferensi.

### 3.2 Label funnel mencampur saturasi asli dengan sub-siklus exit-only
`run_cycle()` hanya melakukan entry tiap siklus ke-5 (`INTERVAL/EXIT_POLL = 300/60`),
tetapi keempat sub-siklus lain tetap mencatat `cycle_caps_full`, sehingga rasio
saturasi terbaca ~4:1 palsu. Perbaikan (`a96f095`): `cycle_caps_full` hanya saat
`do_entries=True`, sub-siklus lain → `cycle_exit_only`. Dikunci regression test
berbasis AST; kontrol negatif (salinan pre-fix) = 2 FAILED, pasca-fix 9 passed.

### 3.3 Klaim breakeven salah di komentar unit
`57,0%` → **64,0%** = (2,0 + 0,24)/(1,5 + 2,0). Komentar saja, tanpa dampak perilaku.

## 4. Posisi legacy yang masih terbuka (bukan cacat, tapi membatasi throughput)

Epoch boundary tidak menutup posisi — state dipertahankan utuh supaya tidak ada
exit sintetis. Konsekuensinya:

- `ab9a` dan `ab9b`: 6 slot SIGNAL terisi **LONG** legacy (entry 2026-11-14 17:30 –
  2026-11-15 00:16 UTC, yaitu pra-E6). Tidak ada LONG baru pasca-E6. Selama posisi ini
  hidup, slot SIGNAL arm tersebut tidak bisa menerima entry baru; mereka keluar
  paling lambat lewat `TW_TIME_STOP_H=24`, yaitu 2026-11-15 17:30 – 21:20 UTC.
- Semua entry pasca-E6 di seluruh arm = **SHORT** (subset: 9a 1 RANDOM, 9d 1 RANDOM,
  9e 6). Jadi klaim "SHORT-only" berlaku untuk entry baru, bukan untuk posisi warisan.

Keputusan: posisi legacy **dibiarkan** keluar secara alami (TP/SL/time-stop). Menutup
paksa akan menciptakan waktu-exit yang tidak dipilih strategi dan mengotori
perbandingan `closed_trades` antar arm.

## 5. Geometri dan kebutuhan sampel (9e)

- Biaya round-trip diasumsikan 24 bps; breakeven WR = (SL + biaya)/(TP + SL).
- TP1,5/SL6,0 → **83,2%**; TP1,5/SL2,0 → **64,0%**.
- Tail 6 SL serentak: −$43,34 (−18,5% wallet) vs −$14,05 (−6,0% wallet);
  wallet efektif $234,17, margin/slot $39,03, notional@3x $117,08.
- n untuk membuktikan WR > breakeven (α=0,05 satu sisi, power 80%):
  WR70% → 384 trade; WR75% → 110; WR80% → 50.

## 6. Aturan baca hasil

1. Hitung hanya trade dengan `exit_time` ≥ batas epoch arm masing-masing
   (a–d: 2026-11-15T00:55:52Z, e: 2026-11-15T01:06:50Z).
2. Dedup sebelum menghitung (telemetri loop rawan baris duplikat).
3. Laporkan CI95 + p-value; "WR di atas breakeven" tanpa CI bukan bukti.
4. Jangan menyimpulkan dari arm yang slot-nya masih tersandera posisi legacy.
