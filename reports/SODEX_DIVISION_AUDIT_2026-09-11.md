# Audit Divisi Project SoDEX — 2026-09-11

## 1. Kesimpulan eksekutif

**Target 0,7% dari total wallet per trade/window masih mungkin secara kondisional, tetapi belum terbukti stabil untuk seluruh Divisi SoDEX.**

Bottleneck utama bukan jumlah sinyal. Bottleneck utama adalah:

1. forward expectancy belum stabil;
2. SHORT-BEAR masih terlalu kecil untuk validasi;
3. aggregate PnL menyembunyikan rolling-window negatif;
4. sebelum audit ini, state paper dapat membuka pair yang sama berkali-kali;
5. denominator wallet berbeda antar runtime/report;
6. watchdog tidak memantau seluruh paper track walaupun mengklaim memantau semua.

Tidak ada bukti malware pada source aktif yang dipindai. Tidak ada posisi/order exchange pada snapshot terakhir. Ini **bukan** bukti profit live.

## 2. Scope dan metode

Scope hanya Divisi SoDEX: paper tracks, Realwide live, Spot live, watchdog, state integrity, wallet denominator, target reports, dan jalur data market.

Metode:

- RCA KT IS/IS NOT: pisahkan defect, lokasi, waktu, extent, dan perubahan pemicu.
- TOC bottleneck: cari constraint yang paling membatasi throughput profit, bukan mengoptimalkan komponen yang bukan constraint.
- Quantitative check: aggregate vs rolling-30, bootstrap CI95, target-hit rate, PnL net tercatat.
- Data triangulation: state JSON, service systemd, log, source code, test suite, dan snapshot exchange.
- Static security scan: suspicious execution, secret literals, `shuffle=True`, `dry_run=False`, withdrawal surface.

## 3. Snapshot exchange terbaru

Sumber: `data/sodex_real_sync_snapshot.json`

- Generated: `2026-09-11T00:07:37Z`
- Perps: `94.0253030809`
- Spot vUSDC: `14.0747905523`
- Total exact: `108.1000936332`
- Denominator operasional dibulatkan: `$108.10`
- Target 0,7% exact: `$0.7567006554`, dibulatkan `$0.76`
- Open perps positions: `0`
- Open perps orders: `0`

Snapshot ini menggantikan angka 107,70 yang sudah stale.

## 4. Metrik target terbaru

Semua PnL di bawah berasal dari state paper yang tercatat; bukan klaim live.

| Track | n | PnL | WR | Avg/trade | Bootstrap CI95 avg | Target-hit | Penilaian |
|---|---:|---:|---:|---:|---:|---:|---|
| REALWIDE | 128 | +$137,22 | 49,2% | +$1,07 | -$0,20…+$2,39 | 43,8% | aggregate positif, belum stabil |
| SHORT-BEAR | 4 | -$1,89 | 50,0% | -$0,47 | -$1,56…+$0,61 | 0,0% | belum valid, paper only |
| TWOWAY | 187 | +$166,32 | 48,1% | +$0,89 | -$0,07…+$1,88 | 46,5% | aggregate positif, recent negatif |
| SPOT v4 | 40 | -$4,92 | 27,5% | -$0,12 | -$0,64…+$0,42 | 22,5% | negatif |
| DONCHIAN | 84 | -$14,43 | 36,9% | -$0,17 | -$1,40…+$1,04 | 35,7% | belum edge |
| PORTFOLIO | 14 | -$17,49 | 21,4% | -$1,25 | -$2,06…-$0,11 | 7,1% | buruk |
| Hyperliquid | 25 | -$100,53 | — | -$4,02 | -$5,62…-$2,09 | 8,0% | buruk |
| Aster | 49 | -$45,88 | — | -$0,94 | -$3,19…+$1,58 | 30,6% | negatif/belum valid |

REALWIDE recent 30 trade: **avg -$2,56/trade**, CI95 **-$3,52…-$1,58**. Jadi aggregate +$137,22 tidak boleh dipresentasikan sebagai bukti edge yang sedang stabil.

Maturation Realwide forward setelah cutover/pair gate:

- `46/50` trade forward
- WR `54,4%`
- PF `1,711`
- avg net price return `+0,446%`
- wallet ROI berdasarkan recorded `pnl_usd`: `+1,237%`
- status: **COLLECTING**, belum memenuhi n≥50

## 5. RCA temuan utama

### RCA-1 — Duplicate paper positions per pair

**Deviasi:** state dapat memiliki beberapa posisi terbuka untuk symbol/pair yang sama walaupun desain mengasumsikan satu posisi per pair.

| Dimensi | IS | IS NOT | Distinction/change |
|---|---|---|---|
| What | open key berbentuk `PAIR_timestamp` | guard membandingkan `PAIR in open` | key identity berubah menjadi timestamped ID |
| Where | Spot v4, Hyperliquid, Aster paper | exit loop tetap membaca seluruh open | bug entry guard, bukan exchange |
| When | state aktif 2026-09-11 | sebelumnya tidak tertangkap test | nambah posisi terjadi saat cooldown lewat |
| Extent | Spot 3× vTON, HL 2× TRX, Aster 3× TRX | bukan posisi live exchange | paper exposure/PnL terdistorsi |

**Root cause terverifikasi:** guard memeriksa key dictionary, bukan field `spot_sym`/`pair`.

**Fix:** helper `has_open_spot()` dan `has_open_pair()`; regression tests. State paper dibackup ke `/tmp/sodex-audit-20260911/`, lalu duplicate simulated positions dihapus dengan menyisakan posisi tertua. Tidak ada live state disentuh.

### RCA-2 — Denominator drift

**Deviasi:** script menggunakan 139,37 / 119,67 / 94,572 / 107,70, padahal snapshot exchange terbaru 108,100094.

**Dampak:** status target dapat berubah hanya karena analyzer memakai wallet berbeda; live/paper/report tidak apples-to-apples.

**Root cause:** literal wallet tersebar di script; tidak ada single runtime source yang diwajibkan semua analyzer.

**Fix:** active paper/report/research scripts membaca `SODEX_TOTAL_WALLET`, fallback local dry-run 108,10; `.env.swing` diset `SODEX_TOTAL_WALLET=108.10`. Dashboard memakai wallet dari snapshot data, bukan literal.

### RCA-3 — Pasar-Anantara symbol fallback

**Deviasi:** HYPE dan SILVER/XAG dilaporkan `fetch_err` setiap cycle.

**IS:** fungsi hanya Binance spot `/api/v3/klines`.

**IS NOT:** HYPE dan XAG/SILVER tersedia pada futures endpoint yang sudah dipakai Realwide.

**Root cause:** signal track mengimpor universe Realwide (termasuk perp-only symbols) tetapi fetch path tidak mengimpor fallback.

**Fix:** Pasar-Anantara memakai `paper_test_realwide.fetch_ohlcv()`, yang mencoba spot lalu futures; numpy array dikonversi ke list; pengecekan empty tidak memakai truth-value array.

**Verifikasi:** HYPEUSDT dan XAGUSDT masing-masing mengembalikan 5 candles pada read-only test; dry cycle Pasar-Anantara exit 0 tanpa fetch error.

### RCA-4 — Watchdog coverage tidak sesuai klaim

**Deviasi:** watchdog mengklaim seluruh paper-test, tetapi hanya memantau freshness tiga state dan mewajibkan lima service.

**Fix:** default service list sekarang mencakup 11 paper services SoDEX; TRACKS mencakup 11 state: Swing, Swing Partial, Realwide, Two-Way, Short-Bear, Donchian, Portfolio, Spot v4, Hyperliquid, Aster, Pasar-Trade.

**Verifikasi:** watchdog exit 0, semua service active, semua state parse/fresh.

### RCA-5 — Promotion gate terlalu longgar dan label terlalu kuat

**Deviasi:** maturation tracker memakai `MIN_N=30` dan verdict `LIVE PROMOTED`, walaupun data forward baru 46 dan standar audit n≥50.

**Fix:** `MIN_N=50`; verdict menjadi `COLLECTING 46/50`; label tidak lagi mengklaim promotion live. Tracker read-only; live service yang sudah disetujui tidak dihentikan oleh perubahan ini.

## 6. Bottleneck Analysis — TOC

### Constraint saat ini

**Forward, cost-adjusted, regime-specific expectancy yang cukup stabil.**

Bukan constraint utama:

- jumlah service;
- jumlah pair;
- cooldown yang lebih pendek;
- leverage;
- jumlah sinyal.

### Exploit

- Pertahankan fail-closed BTC gate.
- Biarkan Short-Bear menolak entry saat `chk4=0`; jangan turunkan gate untuk mengejar volume.
- Gunakan hanya PnL net tercatat untuk target.
- Monitor rolling windows, bukan aggregate saja.

### Subordinate

- Track negatif tetap paper/research, tidak menjadi sumber live PnL.
- Semua report memakai denominator yang sama.
- Watchdog wajib mengawasi seluruh state.
- Pair duplicate tidak boleh menambah simulated exposure.

### Elevate

Belum waktunya menaikkan notional/leverage. Elevation baru rasional setelah:

- Short-Bear n≥50;
- PF dan avg net positif setelah biaya;
- rolling subperiod tidak runtuh;
- CI tidak konsisten negatif;
- exchange reconciliation bersih;
- tidak ada data gap/error aktif.

### Repeat

Setelah Short-Bear matang, constraint kemungkinan berpindah ke execution slippage, fill quality, atau market regime. Itu harus diukur, bukan diasumsikan.

## 7. Short-Bear — keputusan operasional

Status:

- service active;
- `SCAN ok=6 err=0` pada cycle terakhir sebelum audit;
- n closed `4`;
- PnL `-$1,89`;
- open paper `1` pada report terakhir;
- funnel pernah menunjukkan `bear_stack=5`, `r1neg=6`, tetapi `chk4=0`, `candidate=0`.

Keputusan:

- tetap **paper-only**;
- jangan longgarkan check gate;
- jangan promosi live pada n=4;
- evaluasi awal n≥20, kandidat live minimum n≥50;
- target per trade saat wallet sekarang sekitar `$0,76` net.

## 8. Safety dan malware scan

Yang diverifikasi:

- 3.435 test pass, 8 skipped, 0 fail, 30 subtests pass;
- 38 scoped regression tests pass sebelum full-suite final;
- py_compile seluruh file scope pass;
- scoped secret/API key literal scan bersih;
- tidak ditemukan `shuffle=True` pada scope;
- tidak ditemukan penambahan `dry_run=False`;
- scan pola `eval`, `exec`, `os.system`, `shell=True`, encoded execution pada active SoDEX entrypoints: tidak ditemukan;
- snapshot exchange: 0 open positions, 0 open orders;
- live watchdog: rekonsiliasi 0 posisi lokal vs 0 posisi exchange, 0 alert;
- `SODEX_NO_WITHDRAW=1` tetap menjadi constraint proyek; tidak ada withdrawal path pada source active yang diaudit.

Log stale yang masih ada tidak saya hapus karena berguna untuk RCA. Log lama bukan bukti error aktif:

- numpy/requests: mtime Agustus;
- Realwide ValueError: mtime 2 September;
- Donchian KeyError HYPE: mtime 2 September.

## 9. Kelemahan yang belum selesai

1. Forward sample Short-Bear terlalu kecil.
2. Realwide recent-30 negatif walau aggregate positif.
3. Target stability belum terbukti untuk semua regime.
4. Banyak script research/untracked di working tree; provenance dan review boundary perlu dibersihkan pada task terpisah.
5. Learning high-edge summary masih menampilkan track retired; ini dapat menjadi noise dashboard, walaupun bukan execution path.
6. Error log hanya mencatat symbol generik pada beberapa track; idealnya menyimpan exception class/status HTTP tanpa credential.
7. Denominator masih memiliki fallback literal karena belum ada library single-source yang dipakai semua script; env/snapshot harus tetap diprioritaskan.

## 10. Acceptance criteria berikutnya

### Short-Bear

- [ ] n≥50 closed forward
- [ ] PnL net setelah fee/spread/funding
- [ ] PF ≥1,5
- [ ] avg wallet ROI ≥0,7%
- [ ] rolling subperiod tidak menunjukkan collapse
- [ ] fetch error rate rendah dan tidak ada data-blind period
- [ ] paper state dan exchange reconciliation konsisten

### Divisi SoDEX

- [ ] setiap track punya status role: live / paper / research / retired
- [ ] satu canonical wallet source untuk seluruh analyzer
- [ ] watchdog memonitor service + state + freshness seluruh track
- [ ] pair uniqueness invariant diuji di semua paper engine
- [ ] tidak ada promotion label sebelum n≥50
- [ ] live size tidak dinaikkan selama recent expectancy negatif

## 11. Verdict akhir

**SoDEX belum terbukti sebagai tulang punggung profit yang stabil.**

Yang terbukti saat ini hanya:

- jalur Realwide memiliki historical/aggregate edge positif;
- jalur TWOWAY LONG-only aggregate positif;
- safety/live reconciliation berjalan bersih;
- beberapa bug observability, denominator, duplicate state, watchdog coverage, dan symbol fallback telah diperbaiki.

Yang belum terbukti:

- target 0,7% stabil setiap window;
- Short-Bear profitable;
- aggregate edge bertahan pada rolling forward period;
- seluruh track layak live.

Keputusan profesional saat ini: **pertahankan Realwide live dengan envelope yang ada dan fail-closed gate; jadikan Short-Bear prioritas paper #1; jangan tambah leverage/throughput; jangan promosikan Short-Bear sebelum n≥50 dan gate net-risk lulus.**
