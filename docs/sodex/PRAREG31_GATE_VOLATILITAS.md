# PRAREG-31 — UJI FORWARD GATE VOLATILITAS PADA DEPLOY MESIN (SoDEX)

**Dibekukan:** 2026-10-25 ~08:20Z (sebelum window forward pertama) · **Sifat:** READ-ONLY, tanpa order, tanpa posisi, tanpa flag live
**Cakupan:** hanya **KAPAN mesin di-deploy** (on/off per window 30 jam). **Tidak** mengubah sinyal mesin, tidak mengarang trade, tidak menambah mesin.
**Hash dokumen:** `docs/sodex/PRAREG31_GATE_VOLATILITAS.md.sha256` (dibuat setelah teks beku).

---

## 1. Latar (terukur, 25-Okt-2026)

Audit kapasitas gross seluruh buku paper (`scripts/research/gross_capacity_audit.py`, 1.959 trade, kontrol RANDOM dikecualikan):

| Mesin | n | gross bps | net bps | biaya bps | hold (jam) |
|---|---:|---:|---:|---:|---:|
| twoway | 436 | **+20,18** | +12,59 | 7,59 | 13 |
| realwide | 268 | **+15,59** | +8,78 | 6,80 | 7 |
| donchian | 206 | **+14,98** | +7,82 | 7,16 | 5 |
| swing | 419 | +6,48 | +1,24 | 5,24 | 3 |
| shortbear | 41 | +39,98 | −48,41 | 88,40 | 5 |
| aster | 243 | −8,26 | −27,03 | 18,77 | 10 |
| hyperliquid | 214 | −17,54 | −37,76 | 20,22 | 10 |
| portfolio | 86 | −40,51 | −49,28 | 8,77 | 7 |
| pasar_anantara_trade | 46 | −96,98 | −102,06 | 5,08 | 9 |
| **Buku penuh** | **1.959** | **+3,43** | **−7,96** | **11,39** | 7 |

Dua fakta yang mengarahkan seluruh desain di bawah:

1. **Biaya riil rata-rata 11,39 bps/trade**, bukan 6,5 bps. Hanya 3 mesin yang gross-nya konsisten di atas biayanya.
2. **Edge 3 mesin itu berbalik tanda sekitar 2026-09-25** (`reports/sodex/ENGINE_TREND_WINDOW.json`, tren 7-harian):

| Minggu | twoway gross | realwide gross | donchian gross |
|---|---:|---:|---:|
| 09-12→09-19 | +119,5 | +44,9 | +28,4 |
| 09-19→09-26 | +24,9 | +40,3 | +88,1 |
| 09-26→10-03 | −39,1 | −50,7 | −42,3 |
| 10-03→10-10 | −73,1 | −77,3 | −37,1 |
| 10-17→10-24 | −70,9 | −42,9 | −110,7 |

3. **Kandidat penjelas ex-ante:** gross mingguan berkorelasi positif dengan **volatilitas BTC 7 hari sebelumnya** (`regime_conditioning.py`: r = 0,553 vol SoDEX, r = 0,593 vol Binance; median gross per kuartil vol: **−50,5 / +6,0 / +16,4 / +30,1 bps**). n efektif hanya ~9 minggu → ini **hipotesis**, bukan bukti.

**Simulasi in-sample** (`vol_gate_simulation.py`, 59 window 30 jam, gate dihitung dari 7 hari sebelum window):

| Varian | window | mean % | median % | hit % | CI95 blok mingguan |
|---|---:|---:|---:|---:|---|
| tanpa gate | 59 | 1,404 | −0,296 | 49,2 | [−5,75; +8,99] |
| vol ≥ 33% | 29 | 2,526 | +1,124 | 51,7 | [−7,43; +11,92] |
| vol ≥ 35% | 18 | 8,796 | +4,061 | 66,7 | [−0,64; +19,74] |
| **vol ≥ median 90d (parameter-free)** | 31 | **3,563** | **+1,851** | **54,8** | [−6,94; +11,70] |
| PRAREG-26 (14d net>0) | 59 | 1,411 | 0,000 | 32,2 | — |

**Semua CI95 memuat 0.** Karena itu gate ini **tidak boleh dipakai** berdasarkan data in-sample; satu-satunya jalan sah adalah uji forward dengan aturan beku.

**Matematika target** (0,8% modal/window): pada 9 trade/window dengan ukuran penuh dibutuhkan **8,9 bps net/trade**; pada 5 trade ukuran penuh **16,0 bps**; pada 15 trade setengah ukuran **10,7 bps**. Angka 8,9–16 bps ini yang harus dilampaui — dan itu hanya mungkin bila gross 15–20 bps bertahan.

## 2. Hipotesis

**H1:** Buku 3 mesin (`twoway, realwide, donchian`) yang **hanya di-deploy pada window dengan vol7 ≥ median vol7 12 window sebelumnya** mencapai **A DAN B** pada grid 30 jam, dan mengalahkan (a) buku tanpa gate dan (b) kontrol gate acak ber-duty sama.

**H0 (falsifikasi):** gate tidak mengubah distribusi (M4 tidak signifikan) atau kalah dari kontrol acak (M5 p ≥ 0,05).

## 3. Aturan beku (DILARANG diubah)

**Volatilitas (ex-ante, tanpa look-ahead):**
```
vol7(t) = pstdev( ln(close_i / close_{i-1}) ) × sqrt(8760) × 100
```
di mana `close_i` = candle 1 jam BTC-USD SoDEX (`data/sodex_klines/1h/BTC-USD.json`) dengan
**close_time ≤ t**, diambil 168 jam terakhir. Minimal 30 bar; bila < 30 → vol tidak tersedia.

**Ambang:** `median_12(t)` = median `vol7` pada **12 window 30 jam sebelumnya** (grid jangkar
2026-08-03Z) yang punya vol valid. Bila < 12 window historis valid → gate FLAT (lihat 4).

**Keputusan per window:** window **ON** bila `vol7(window_start) ≥ median_12(window_start)`;
selain itu **OFF**.

**Buku yang diukur:** trade dari `twoway, realwide, donchian` dengan `exit_ts` di dalam window
(bucket exit). Kontrol RANDOM dikecualikan. Universe beku — mesin baru tidak masuk tanpa amandemen.

**Data stale:** bila bar terakhir BTC SoDEX lebih tua dari **6 jam** pada window_start → window
**FLAT** (0,0%), dicatat `data_stale=true`. Tidak boleh diisi dengan Binance sebagai pengganti
(Binance adalah venue lain; itu amandemen, bukan implementasi).

**Grid:** window 30 jam, jangkar **2026-08-03T00:00Z**, bucket berdasarkan `exit_ts`. Window tanpa
trade = **0,0%** (tidak dilewati) — konsisten dengan `AMANDEMEN_TARGET_AB_2026-10-10.md`.

**Wallet:** `wallet_usd` dari `reports/sodex/PRAREG26_MESIN_SELEKSI_STATUS.json` (fail-closed;
bila snapshot spot gagal → label `SPOT_UNMARKED`, tetap dipakai, dicatat).

## 4. Periode & ukuran sampel

- **In-sample (dilarang dipakai untuk verdict):** seluruh data sebelum 2026-10-26T00:00Z.
- **Forward (verdict):** window dengan **start ≥ 2026-10-26T00:00Z** dan **end ≤ 2026-11-25T00:00Z**
  (30 hari = 24 window teoretis).
- **Syarat data:** minimal **12 window** dengan data (ON atau OFF yang tercatat, bukan FLAT karena
  data stale). Bila < 12 → verdict **DATA KURANG** (bukan lolos, bukan gagal).
- **Stop rule:** bila setelah 12 window terisi M1 < 0 **dan** M4 t < 0 → uji dihentikan lebih awal,
  verdict GAGAL (menghentikan kerugian informasi, bukan mengubah aturan).

## 5. Metrik

| Kode | Metrik | Definisi |
|---|---|---|
| M1 | mean window | rata-rata PnL buku per window ÷ wallet × 100 |
| M2 | median window | — |
| M3 | hit rate | persentase window dengan PnL > 0 |
| M4 | t paired | uji-t berpasangan M1(gate) − M1(tanpa gate) per window, df = n−1 |
| M5 | gate vs kontrol acak | 10.000 permutasi: pilih acak himpunan window ON dengan **jumlah ON sama**, hitung mean; p = fraksi mean_acak ≥ mean_gate |
| M6 | total USD | jumlah PnL buku selama forward |
| M7 | window terburuk | min PnL per window (%)

## 6. Kriteria lolos (SEMUA wajib)

- **A:** M1 ≥ **0,8%** per window.
- **B:** M2 > **0** DAN M3 ≥ **50%**.
- **C:** M4 t ≥ **2,0** (gate lebih baik dari tanpa gate, berpasangan).
- **D:** M5 **p < 0,05** (gate mengalahkan kontrol acak ber-duty sama).
- **E:** Tidak ada pelanggaran aturan beku (vol dihitung ex-ante, tidak ada window ON yang
  memakai data setelah window_start).

Gagal salah satu → **TIDAK LOLOS**, dengan catatan metrik mana yang gagal.

## 7. Yang TIDAK diuji di sini (dilarang diklaim)

- Menambah/mengurangi mesin, mengubah TP/SL/hold, atau mengubah sinyal — di luar cakupan.
- Venue lain (Binance/Hyperliquid) sebagai sumber sinyal — di luar cakupan.
- Sizing lebih dari 1× wallet atau leverage > 1 — di luar cakupan.
- Klaim "0,8% tercapai" dari data in-sample — dilarang; in-sample hanya untuk desain.

## 8. Alasan aturan ini (bukan opini)

- Ambang **parameter-free** (median rolling) dipilih agar tidak ada knob yang bisa di-tuning
  setelah melihat forward; ambang absolut (30/33/35) hanya dilaporkan sebagai deskriptif.
- Gate acak ber-duty sama (M5) adalah **kontrol negatif wajib** (Rule 9): kalau gate acak sama
  baiknya, yang bekerja bukan volatilitas — melainkan sekadar "tidak selalu di pasar".
- Stop rule melindungi dari menghabiskan 30 hari pada hipotesis yang jelas salah arah.

## 9. Berkas terkait

```
scripts/research/gross_capacity_audit.py      audit kapasitas gross (n, gross, net, biaya)
scripts/research/engine_trend_window.py       tren 7-harian + agregasi window 30 jam
scripts/research/regime_conditioning.py       fitur vol/ret ex-ante vs gross mingguan
scripts/research/vol_gate_simulation.py       simulasi gate + matematika target
reports/sodex/GROSS_CAPACITY_AUDIT.json
reports/sodex/ENGINE_TREND_WINDOW.json
reports/sodex/REGIME_CONDITIONING.json
reports/sodex/VOL_GATE_SIMULATION.json
docs/sodex/RISET_KAPASITAS_DAN_GATE_VOLATILITAS_2026-10-25.md   laporan riset lengkap
```

---
*PRAREG-31 — dibekukan 2026-10-25. Verdict: 2026-11-25. Tidak ada parameter yang boleh diubah setelah hash.*
