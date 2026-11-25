# AUDIT GANDA PROJECT SODEX — 2026-11-02

**Sifat**: read-only, dua lapis (audit definisi/metrik + audit data mentah), independen dari label tracker.
**Prinsip**: tidak ada angka tanpa sumber; setiap selisih direkonsiliasi, bukan diabaikan.
**Commit perbaikan hari ini**: `3ef5f5e`. **Tes**: 4866 passed, 38 skipped, 83 subtests.

---

## 0. VERDICT RINGKAS

| Pertanyaan | Jawaban berbukti |
|---|---|
| Apakah semua lane paper berjalan? | **Ya** — 33/33 lane OK (fleet report), 11/11 timer eksperimen active |
| Apakah ada gate yang lolos target? | **Tidak ada** — 0 PASS (Arena 5 strategi), REAL-WIDE/TWO-WAY negatif, PRAREG-36 negatif |
| Apakah ada edge per-pair terbukti? | **Tidak ada** — 0/15 (REAL-WIDE) dan 0/22 (TWO-WAY) lolos BH q<0,05 |
| Apakah sistem mengarah ke 0,8%/30 jam? | **Belum** — REAL-WIDE −0,77%/window; jarak ke target 1,57pp/window |
| Apakah siap live 01-Des? | **Belum terbukti** — PRAREG-36 −0,0366%/5j vs target +0,010%/5j; arming aman, tetapi tidak ada data positif |
| Apakah arsitektur aman untuk live? | **Sebagian** — 22 permukaan order ber-guard halt-file; 3 kunci di `mode_a_live.py` fail-closed; **deadman tidak terpasang** |

---

## 1. LAPIS 1 — INTEGRITAS DATA & ARTEFAK

### 1.1 Silent-zero PRAREG-36 (P0, DIPERBAIKI)
`hybrid36.py eval forward36` dari root repo → `n_rec: 0`, `BELUM_ADA_DATA`, padahal ledger berisi **8 baris `kind: rec`**. Penyebab: path relatif diselesaikan ke cwd, dan `_read()` mengembalikan `[]` bila file tidak ada.
**Dampak**: eksperimen yang berjalan terlihat "belum mulai" — tepat kegagalan yang ingin dicegah.
**Perbaikan**: `resolve_fdir()` + `GAGAL_DATA` eksplisit + 3 tes regresi. Output kini: `n_rec 8, vonis BERJALAN (7/30 hari)`.

### 1.2 Artefak 0-byte (P2, terbuka)
`data/twin_engine.db` berukuran **0 byte**; DB asli di root repo. Tidak ada pembaca aktif hari ini, tetapi merupakan jebakan untuk tool baru.
**Rekomendasi**: ganti dengan symlink atau hapus setelah audit pembaca (butuh persetujuan).

### 1.3 Nama file yang tidak pernah ada (P1, DIPERBAIKI)
Fleet report memantau `PRAREG40_REFLECT_OVERLAY.jsonl` (tidak ada). Penulis sebenarnya `scripts/reflect_gate.py` → `PRAREG40_AB_OVERLAY.jsonl` (4.724 byte, 06:45 WIB).
**Dampak**: lane reflect-40 dilaporkan OK tanpa data — "timer hidup, output mati" tidak terdeteksi.
**Perbaikan**: path dikoreksi + aturan `flag_missing_data()` (OK tanpa file → `NO_DATA`).

### 1.4 Klines (P1, terbuka)
- **5m: 16 file, seluruhnya basi 247 jam (10 hari)**.
- 1h: 106 file, median segar 6,1 jam, tetapi 5 file tanpa `newest` dan 1 file basi 2.757 jam.
- 1d: 106 file, 8 tanpa `newest`.
**Dampak**: lane yang butuh 5m buta; verdict berbasis 1h hanya valid untuk simbol yang segar.

---

## 2. LAPIS 2 — REKONSILIASI METRIK

### 2.1 Denominator (selesai, bukan bug)
Rekomputasi awal saya memakai penjumlahan `pnl_pct` → −1,148%. Tracker memakai **USD/total wallet** → −0,766%. **Tracker benar**; skrip audit saya yang salah metode dan sudah dikoreksi.

### 2.2 Daftar pause dinamis & diterapkan surut (P0, terbuka)
Tracker membaca `data/paper_test_edge_gate.json` untuk `pairs_pause["REAL-wide"]` yang **diregenerasi harian**, lalu mengecualikan pair tersebut dari **seluruh histori**. Hari ini daftarnya **8 pair** (ADA, ARB, DOGE, HYPE, LIT, ONDO, SILVER, SUI), bukan 4 seperti asumsi dokumen.
**Efek terukur**:
```
resmi (terfilter) : n_win=38 mean=-0,7665% med=-1,4638% hit0,8=12 worst=-20,213% t=-0,51
tanpa filter      : n_win=57 mean=-0,6130% med=-1,3061%
skip              : pra_cutover=52, pause=66, stale_exit=3
```
**Vonnis**: filter hari ini **tidak** menguntungkan (mean lebih buruk), tetapi sampel **tidak reprodusibel** — angka historis bisa berubah karena keputusan hari ini. Ini cacat metode, bukan cacat angka.
**Perbaikan (dibuat hari ini)**: `scripts/sodex_gate_sample_audit.py` merekam daftar pause + sha256 + kedua versi statistik ke `reports/sodex/GATE_SAMPLE_AUDIT.jsonl` (append-only), dan **exit 1 saat drift terdeteksi**. Rekaman pertama: digest `68cce424b75d80a3`.
**Keputusan yang masih diperlukan (user)**: bekukan daftar pause per tanggal keputusan (forward-only) vs tetap surut.

---

## 3. LAPIS 3 — EKONOMI TRADING (akar masalah sebenarnya)

### 3.1 REAL-WIDE (n=350 trade, 57 window, 3x, notional $300/trade)
```
total       = -$95,43      mean = -$0,273/trade
WR          = 43,4%        avgW = $5,44   avgL = -$4,66
payoff      = 1,17         PF   = 0,90
break-even  = 46,1%  ->  defisit 2,7pp (dengan biaya model)
```
Rincian per jenis exit (bukti bahwa masalahnya bukan "tidak ada TP"):
```
TP          n=34  mean +5,06%  +$516,05
SL          n=95  mean -2,09%  -$596,68   <-- kerugian terbesar
SL_PROTECT  n=62  mean +0,27%  +$50,01    (label SL, hasilnya positif = label menyesatkan)
SL_BEAR     n=59  mean -1,43%  -$253,00
TIME_30h    n=38  mean +0,97%  +$110,21
TIME_24h    n=31  mean +0,19%  +$17,30
PEAK_TRAIL  n=14  mean +1,66%  +$69,87
```

### 3.2 TWO-WAY (n=556)
```
WR 39,6% | payoff 1,53 | PF 1,00 | total -$0,73
BE_WR = 39,6% (persis sama dengan WR)
LONG +$55,86 (n=514) | SHORT -$56,60 (n=42)
```
**Vonnis**: sistem ini **terkalibrasi tepat di titik nol**. Bukan "hampir untung" — geometri TP/SL-nya membuat BE sama dengan WR aktual. SHORT menghapus seluruh keuntungan LONG dengan 7,6% jumlah trade.

### 3.3 Ukuran risiko vs target (P0)
```
SL murni: mean -$6,28/trade = 2,58% wallet
target  : 0,8% wallet / 30 jam
```
**Satu SL = 3,2× target window.** Dengan 6,1 trade/window, varians satu window didominasi 1–2 trade. Selama rasio ini tidak diubah, MDD −20,2% yang sudah terjadi akan berulang.

### 3.4 Model biaya & fill tidak konservatif (P1)
| Sumber | Biaya per sisi |
|---|---|
| Model paper REAL-WIDE (implisit) | **4,66 bps** |
| Dokumen `ARAH_BARU_BIAYA` | **8 bps** |
| PRAREG-36 (`cost=0.0010`) | **10 bps** |
Selisih 6,6 bps round-trip pada 350 trade = **−$69,3** → total menjadi −$164,7.
Tambahan: exit TP terealisasi **+0,24pp di atas** TP terkonfigurasi (maks +1,61pp) → model mengisi di harga yang lebih baik daripada limit.
**Gabungan**: optimisme ≈0,09pp/trade × 6,1 trade ≈ **0,55pp/window** — 69% dari target 0,8%.

### 3.5 Disiplin exit (P1, terbuka)
```
exit TIME_* = 86; melanggar batas >1 jam = 15 (17,4%)
terburuk: TRX TIME_24h pada hold 189,7 jam (kelebihan 165,7 jam)
          XAUT TIME_24h 184,4 jam; ENA SL 179,9 jam
hold > 30 jam = 20/350 (5,7%)
```
Batas waktu **tidak ditegakkan** saat engine tidak melangkah. Di live ini berarti posisi bisa menginap 8 hari melewati stop.

---

## 4. LAPIS 4 — DAYA STATISTIK & FALSIFIKASI

### 4.1 Tidak ada edge per-pair
Uji t per pair + Benjamini–Hochberg: **0/15** (REAL-WIDE) dan **0/22** (TWO-WAY) lolos q<0,05. Pair "terbaik" pun t≈1,5 (p≈0,13). HYPE terburuk t=−1,99 tetapi q=0,64.

### 4.2 Ambang t proyek tidak terjangkau horizon verifikasi
Window 30 jam yang tersedia 38 (REAL-WIDE). Untuk mendeteksi +0,8%/window:
```
t=2,0  -> butuh 581 window  (~2,0 tahun pada 1 window/30 jam dengan gap)
t=4,11 -> butuh 2.452 window (~8,4 tahun)
```
**Konsekuensi**: verdict 25-Nov dengan n≈12–40 **tidak berdaya**. "GAGAL" tidak informatif; "LOLOS" hampir pasti kebetulan. Ini alasan metodologis untuk tidak mengubah gate setelah melihat data (anti p-hacking) — dan alasan untuk memperpanjang horizon, bukan menurunkan ambang.

---

## 5. LAPIS 5 — KESIAPAN LIVE

### 5.1 Yang sudah benar (bukti)
- `mode_a_live.py`: fail-closed penuh — `KILL`, `LIVE_ARMED` dengan `not_before ≥ 2026-12-01`, `engine_sha256` (kode terkunci saat GO), `max_equity/order/total_buy > 0` wajib, `CONFIRM_LIVE=YES`, circuit breaker drawdown menulis KILL.
- `sodex_order_surface_audit.py`: **22 permukaan order, 0 tanpa guard** (mekanisme halt-file `SAFETY_HALT`/`PNL_HALT`).
- `secrets/`: tidak ada `LIVE_ARMED.json`, tidak ada `KILL`, tidak ada `sodex.env` → **status belum armed (benar)**.

### 5.2 Celah (P0)
1. **Deadman/guardian tidak terpasang**: `systemd/sodex-guardian.service` ada sebagai file, tetapi 0 unit terinstal, tidak ada proses. ExecStart-nya menunjuk `--db twin_engine.db` (DB legacy) → mengaktifkannya apa adanya **salah sasaran**.
2. **`PNL_HALT` tidak punya penulis di kode produksi** (hanya dibaca; penulis hanya di tes/deadman). Artinya batas rugi harian **tidak otomatis**.
3. Guard halt-file bersifat *fail-open saat file tidak ada* (desain normal), sehingga bila penulis halt mati, tidak ada yang memblokir.

---

## 6. LAPIS 6 — KONTINUITAS & OBSERVABILITAS

- Fleet: **33/33 OK** setelah koreksi; `needs_action=0`.
- `paper-learning-watchdog` tetap `ExecMainStatus=1` tiap 15 menit karena `paper_trades.jsonl` legacy basi 792 jam → alarm palsu permanen (risiko *alarm fatigue*).
- Timer eksperimen: **11/11 active**.
- PRAREG-36: 8 rec / 7 hari dari 30 (23 hari tersisa sampai 25-Nov).

---

## 7. TEMUAN BERPeringKAT

| # | Temuan | Kelas | Bukti | Dampak ke target |
|---|---|---|---|---|
| P0-1 | Sampel gate tidak reprodusibel (pause list surut) | Metode | 38 vs 57 window; 8 pair | Verdict bisa digeser tanpa mengubah aturan |
| P0-2 | Risiko/trade 2,58% wallet vs target 0,8%/30j | Sizing | SL −$6,28 | Satu loss = 3,2 window; MDD −20,2% |
| P0-3 | Deadman tak terpasang + PNL_HALT tanpa penulis | Ops | 0 unit, 0 penulis | Tidak ada rem otomatis saat live |
| P0-4 | Silent-zero evaluator PRAREG-36 | Data | 0 vs 8 rec | Eksperimen terlihat mati |
| P1-5 | Model biaya 4,66 vs 8 bps/sisi | Model | −$69,3 | −0,28pp/window |
| P1-6 | Fill TP +0,24pp di atas limit | Model | 34 TP | Edge overstated |
| P1-7 | Time-stop tidak ditegakkan (17,4%) | Eksekusi | TRX 189,7j | Risiko live |
| P1-8 | 5m klines basi 247j | Data | 16 file | Lane 5m buta |
| P1-9 | Path PRAREG-40 salah → lane OK tanpa data | Observability | DIPERBAIKI | Alarm palsu senyap |
| P2-10 | `data/twin_engine.db` 0 byte | Higiene | 0 byte | Jebakan tool baru |
| P2-11 | Label `SL_PROTECT` menghasilkan profit | Semantik | +$50,01 | Analisis exit menyesatkan |
| P2-12 | Target live 0,010%/5j = 0,060%/30j < lantai 0,10% | Kebijakan | aritmetika | Promosi di bawah lantai sendiri |

---

## 8. VERDICT PER TARGET

| Target | Ambang | Realisasi | Status |
|---|---|---|---|
| North Star 0,8%/30 jam (A+B) | mean ≥0,8%, med>0, hit≥50% | REAL-WIDE −0,7665%, med −1,4638%, hit 31,6% | **GAGAL jauh** |
| Arena 0,8% + t≥4,11 | — | 0/5 strategi PASS | **GAGAL** |
| PRAREG-31 | A/B/C/D + p_perm | 5 window usable | **DATA KURANG** |
| PRAREG-32 | EW ≥0,8% | 3 window / 6 trade | **GAGAL DATA** |
| PRAREG-36 | M_B2 ≥0,010%/5j | **−0,0366%/5j**, cum −1,231%, p(M≤0)=1,0 | **GAGAL (7/30 hari)** |
| PRAREG-23b | M ≥0,010%/5j | historis 0,0061%/5j (61% target) | **DI BAWAH TARGET** |
| Gate live awal (REV2) | M_kum ≥0,010%/5j, MDD ≥−15% | belum ada data live | **DATA KURANG** |

---

## 9. YANG SUDAH DIPERBAIKI HARI INI (`3ef5f5e`)

1. `hybrid36.resolve_fdir()` + `GAGAL_DATA` eksplisit → tidak ada lagi silent-zero. 3 tes.
2. Fleet report: path PRAREG-40 benar, `NO_DATA` untuk lane tanpa file, lane klines dipetakan. 1 tes.
3. `sodex_gate_sample_audit.py`: rekaman harian daftar pause + hash + statistik ganda, exit 1 saat drift. 5 tes.
4. Rekaman pertama `reports/sodex/GATE_SAMPLE_AUDIT.jsonl`.
5. Full suite **4866 passed, 38 skipped, 83 subtests** — tidak ada regresi.

---

## 10. KEPUTUSAN YANG DIPERLUKAN (tidak diambil sendiri)

1. **Pause list**: bekukan per tanggal (forward-only) atau tetap surut dengan rekaman harian? *(default rekomendasi: forward-only + rekaman)*
2. **Ukuran risiko**: turunkan notional per trade agar 1 SL ≤ 0,4% wallet (≈$100 notional pada SL 2%)? Ini mengubah ekspektasi dan perlu persetujuan karena menyentuh parameter fundamental.
3. **Biaya**: samakan model paper ke 8 bps/sisi (konservatif) sebelum verdict 25-Nov?
4. **Deadman**: retarget guardian ke lane swing (`data/paper_test_*`) + penulis `PNL_HALT` otomatis, atau tunda?
5. **Klines 5m**: lanjutkan refresh 5m atau pensiunkan lane 5m?
6. **Watchdog legacy**: pensiunkan `paper_trades.jsonl` dari cek (alarm palsu 15 menit).

---

*Audit ganda 2026-11-02 · semua angka dari state/ledger di disk, dapat direproduksi dengan `scripts/sodex_gate_sample_audit.py`, `hybrid36.py eval`, dan `scripts/paper_fleet_report.py`.*
