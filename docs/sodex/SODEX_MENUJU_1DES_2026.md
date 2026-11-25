# SoDEX — Rencana Menuju Target & Live 1 Desember 2026

**Dibuat:** 2026-11-12 · **Status:** dokumen kerja divisi SoDEX (read-only terhadap sistem produksi)
**Sumber angka:** semua angka di bawah dihitung dari file state/venue nyata pada 2026-11-12,
bukan estimasi. Yang belum terverifikasi ditandai `[BELUM TERBUKTI]`.

---

## 1. Target, definisi, dan aritmetika wajib

| Item | Nilai | Sumber |
|---|---|---|
| Target | **≥0,8% dari TOTAL modal wallet per window (1–30 jam)**, akumulatif | North Star (pin 27-Sep-2026) |
| Denominator modal | `SODEX_TOTAL_WALLET` = **$234,17** (venue: perps $205,77 + spot $28,39, priced lower bound) | `scripts/sodex_wallet_denominator.py` |
| Nilai target per window | ≈ **1,87 USD** (0,8% × $234,17) | hitungan program |
| Exposure per trade (twoway) | `NOTIONAL=100` × `LEVERAGE=3` = **300 USD** | `scripts/paper_test_twoway.py:138,144` |

> **Koreksi 2026-11-13:** dokumen ini sebelumnya memakai 0,7% dan denominator $243,39
> (nilai `.env.swing` yang basi 3,8%). Denominator sudah diselaraskan ke angka venue
> $234,17 (`--min-delta 0.001 --apply`, backup `.env.swing.bak-*`), sehingga
> target/window berubah dari $1,947 → **$1,873**. Angka target tidak berubah: tetap 0,8%.

Konsekuensi aritmetika (dihitung, bukan opini):

| trade/window | net dibutuhkan / trade | = % notional | gross (fee 16 bps) |
|---:|---:|---:|---:|
| 1 | +1,873 USD | 0,62% | 0,78% |
| 2 | +0,937 USD | 0,31% | 0,47% |
| 3 | +0,625 USD | 0,21% | 0,37% |
| 5 | +0,375 USD | 0,12% | 0,28% |
| 10 | +0,187 USD | 0,06% | 0,22% |

**Kesimpulan #1 (paling penting):** target 0,8%/window **tidak menuntut trade besar**,
ia menuntut banyak trade kecil yang net-nya di atas biaya. Fee round-trip 16 bps
adalah lantai keras: gross move per trade harus > 16 bps dengan margin.

## 2. Kenapa lane sekarang tidak mencapai target (bottleneck terukur)

### 2a. Expectancy realisasi seluruh lane paper (dedup, dari file state)

| lane | n | total PnL | mean/trade | winrate | periode |
|---|---:|---:|---:|---:|---|
| swing_state | 957 | −617,66 | −0,645 USD (−0,13% notional) | 22,9% | 06 Agu–12 Nov |
| swing_state_partial | 1038 | −593,62 | −0,572 USD (−0,11%) | 29,3% | 14 Agu–12 Nov |
| swing_state_strict | 697 | −663,78 | −0,952 USD (−0,19%) | 15,2% | 25 Sep–12 Nov |
| twoway_state | 602 | −38,24 | −0,064 USD (−0,01%) | 39,2% | 07 Agu–06 Nov |
| twoway_p27 | 232 | −252,57 | −1,089 USD (−0,36%) | 25,9% | 21 Okt–12 Nov |
| swing_state_ab8atr | 27 | −214,69 | −7,951 USD (−1,59%) | 11,1% | 06–12 Nov |
| swing_state_ab8trail | 31 | −97,99 | −3,161 USD (−0,63%) | 12,9% | 06–12 Nov |

**Tidak ada satu lane pun dengan expectancy positif.** Target 0,8%/window tidak
bisa datang dari tuning mikro; harus dari lane dengan edge nyata atau berhenti.

### 2b. Audit edge-leak twoway (laporan resmi 2026-11-12 08:44)

- gross excess beta-neutral arm SIGNAL: **+2,91 bps**, CI95 [−22,98; +29,77], p(>0)=0,58
  → **tidak signifikan**; setelah fee 2× = **−13,09 bps**.
- pecahan **side**: SHORT n=42 **+60,94 bps** vs LONG n=470 **−2,27 bps**
  → sejalan dengan keputusan 2026-11-07 (sinyal LONG mati).

### 2c. Geometri exit sekarang secara matematis tidak bisa menang

Arm 9a/9b/9c/9d: TP 1,5% / SL 6% (lev 3).
- TP hit = +4,50 USD · SL hit = **−18,00 USD** = **7,4% dari modal wallet** per SL.
- **Winrate breakeven = 80,0%** (82,1% setelah fee). Winrate realisasi lane twoway = 41,4%.

**Kesimpulan #2:** dengan TP 1,5%/SL 6%, lane ini butuh winrate 80% — mustahil.
Satu SL (7,4% modal) menghapus 10 window target. Geometri ini harus dinilai ulang
sebelum 1 Des.

### 2d. Gate memblokir 100% kandidat (bukti funnel 34 siklus, 9a)

| tahap | jumlah |
|---|---:|
| pairs_scanned | 782 |
| tanpa sinyal aktif (`reason_no_signal` 548 + `reason_15m_below_sma20` 38) | 586 |
| gagal fetch (blackout) | 161 |
| kandidat aktif diblokir gate (`skip_btc_gate` 6 + `skip_chop_gate` 9 + `skip_random_btc_gate` 20) | 35 |
| **entry** | **0** |

Aritmetika tertutup rapi (586+161+35 = 782) → tidak ada entry "hilang secara misterius".
Kandidat track SIGNAL = **15 dari 782 scan (1,9%)**.

## 3. Data quality: blackout feed Binance (temuan baru 2026-11-12)

- 1127 baris `Signal error` di log ab9a terbagi **49 burst**, dan **setiap burst panjangnya tepat 23 baris = 23/23 pair gagal bersamaan**.
- Tidak ada satu pun kegagalan sebagian (1–22 pair) dan tidak ada noise acak →
  ini **blackout total per siklus**, bukan rate-limit per simbol.
- Sebaran indeks siklus mod 5 merata → blackout **bukan** efek siklus entry (hipotesis diuji, gugur).
- Laju: 49 dari 6470 siklus (0,8%) secara historis, tetapi **7 di antaranya di 51 siklus terakhir**.
- Perbaikan terpasang: pesan galat menyebut sebab (`sebab=HTTP <kode> …`), retry 2× + backoff,
  **anggaran retry per siklus** (`TW_RETRY_BUDGET`, default 4) agar retry tidak menggandakan
  beban saat endpoint membatasi, plus baris ringkas `[WARN] feed blackout: 23/23 pair gagal`.
- `[BELUM TERBUKTI]` penyebab blackout (429/418/timeout/lokal). Bukti akan tertangkap otomatis
  pada blackout berikutnya karena `sebab=` sudah dicatat.
- Dampak ke A/B: 20,6% scan hilang di arm a/b/c vs 0% di 9d (9d lahir 09:01) → sampel tidak
  seimbang; readout wajib melaporkan laju ini berdampingan dengan hasil.

## 4. Eksperimen yang sedang berjalan

| arm | gate BTC | sinyal | geometri | mulai | n trade tertutup |
|---|---|---|---|---|---:|
| 9a | ON | dibalik | TP 1,5%/SL 6%/24j | – | 0 |
| 9b | ON | dibalik | sama | – | 0 |
| 9c | ON | dibalik | sama | – | 0 |
| 9d | **OFF** | dibalik | sama | 2026-11-12 09:01 | 0 (2 posisi RANDOM) |

Aturan baca hasil dibekukan di `docs/sodex/SODEX_AB9D_PREREG.md` (n≥20, bootstrap CI95,
INSUFFICIENT/EFEK NYATA/TIDAK TERBUKTI). Alat baca: `scripts/research/ab9_readout.py`.

## 5. Jadwal menuju 1 Desember 2026 (H-19)

| tanggal | milestone | kriteria lulus |
|---|---|---|
| 12 Nov | perbaikan data-quality + pra-registrasi + readout | selesai (commit `3b9f11b`, `9ca7a55`) |
| 14 Nov | ukur ulang laju blackout ≥24 jam pasca-fix | blackout cycle ≤2% siklus, sebab tercatat |
| 19 Nov | baca antara A/B 9 | kalau n<20 → lanjut tanpa klaim (sesuai pra-reg) |
| 22 Nov | uji falsifikasi geometri (TP/SL kecil vs besar) di lane riset | ada geometri dengan net>0 di luar sampel |
| 25 Nov | keputusan lane kandidat live | net expectancy CI95 tidak memuat 0 **dan** ≥2× fee |
| 29 Nov | baca final A/B 9 + laporan ke Owner | keputusan tulis: mana lane yang di-live-kan / tetap paper |
| 30 Nov | freeze konfigurasi + readiness check live sodex.com | test suite PASS, governor selfcheck OK, checklist live lengkap |
| 1 Des | live spot + futures | hanya bila GO-LIVE eksplisit Owner |

## 6. Syarat minimum sebelum uang nyata (usulan, butuh approval Owner)

1. Net expectancy per trade CI95 **tidak memuat 0** dan > **2× fee** (16 bps).
2. Risiko per trade ≤ **1% dari modal wallet** (sekarang 7,4% per SL → tidak lulus).
3. Winrate realisasi ≥ winrate breakeven geometri terpasang + margin 3 pp.
4. Laju blackout feed ≤ 2% siklus (kalau tidak, entry bergantung keberuntungan API).
5. Lane yang di-live-kan harus punya bukti dari **data di luar sampel** (bukan in-sample).

## 7. Yang tidak boleh dilakukan

- Mengubah TP/SL/leverage/ukuran posisi/gate tanpa approval Owner + backtest yang membuktikan perbaikan.
- Mengubah `dry_run`/mengeksekusi order nyata tanpa GO-LIVE eksplisit.
- Restart lane hanya untuk "menyegarkan" hasil; menyentuh state saat ada posisi terbuka.
- Menyimpulkan arah dari n<20 (aturan pra-registrasi).

---

## 7. Koreksi akar masalah 0-entry arm AB9 (2026-11-13 22:20–22:26 UTC)

Dugaan awal: "gate BTC momentum memblokir semua entry". **Dugaan itu SALAH.**
Funnel JSON (`data/paper_test_twoway_ab9{a,b,c,d}_funnel.json`) menunjukkan
`reason_no_signal` 20–22 dari 23 pair, `skip_signal_inactive` sama besar.

Akar masalah sebenarnya (terukur, bukan opini):

1. Kaki LONG menuntut `close > SMA50`. Di regime BEAR syarat ini hampir tak pernah benar.
2. Kaki SHORT **hardcoded `short_ok = False`** sejak 2026-09-02 (n=37, WR 29,7%).
3. Akibatnya tidak ada jalur entry tersisa → 0 entry 6 hari. Gate BTC hanya
   memblokir arm RANDOM (yang masih punya jalur), bukan SIGNAL.

Perbaikan (semua opt-in, default produksi tidak berubah):

| Env | Default | Fungsi |
|---|---|---|
| `TW_SHORT_LEG=1` | 0 | menyalakan kaki SHORT untuk arm riset |
| `PAPER_BTC_GATE_QUOTA=N` | 0 | izinkan N entry/label/siklus melewati gate BTC |

Bukti sesudah perbaikan (satu siklus, 22:26 UTC):

| Arm | entry_signal | quota_pass_signal | open | SIGNAL open |
|---|---:|---:|---:|---:|
| ab9a | 2 | 2 | 4 | 2 (BTC, ETH) |
| ab9b | 2 | 2 | 4 | 2 (BTC, ETH) |
| ab9c | 0 | 2 | 2 | 0 (diblok `skip_pre24` arm sendiri) |
| ab9d | 0 | — | 3 | 1 (tidak berubah, SHORT leg tetap off) |

Uji: `tests/test_twoway_btc_gate_quota.py` (6 test) + 20 test gate/funnel lain PASS.

### 7.1 Keputusan Owner 2026-11-13: `TW_PRE24_MIN` ab9c DIPERTAHANKAN

ab9c tetap 0 entry selama filter `TW_PRE24_MIN=3.0` (range 24 jam ≥ 3%) tidak
terpenuhi. **Ini disengaja**, bukan bug: ab9c adalah arm pembeda hipotesis
"entry hanya saat volatilitas 24 jam sudah cukup besar". Jangan dimatikan
tanpa keputusan Owner baru.

Konfigurasi pembeda (diverifikasi via `systemctl --user cat`):

| Arm | `TW_PRE24_MIN` | `TW_INVERT_SIGNAL` | `TW_REGIME_GATE` |
|---|---|---|---|
| ab9a | — | 1 | 1 |
| ab9b | — | 1 | 1 |
| ab9c | **3.0** | 1 | 1 |
| ab9d | — | 1 | **0** |

**Temuan tambahan (belum ditindak):** ab9a dan ab9b **identik secara fungsional**
— beda hanya nama unit/state/log. Tidak ada variabel bebas yang membedakan.
Konsekuensi metodologis: data ab9a dan ab9b **bukan** dua arm independen, jadi
tidak boleh digabung seolah n bertambah (pseudo-replikasi). Pilihan: (a) hapus
ab9b, atau (b) beri ab9b satu variabel bebas yang berbeda (mis. `TW_SL_PCT`
atau `TW_TP_PCT`). Menunggu keputusan Owner.

### 7.2 Keputusan Owner 2026-11-13: ab9b diberi variabel bebas TUNGGAL

Sebelumnya ab9a dan ab9b **identik secara fungsional** (hanya beda nama unit,
state, dan log) sehingga datanya bukan dua arm independen. Owner memilih opsi 2:
beri ab9b satu variabel bebas.

**Yang diubah: `TW_TP_PCT` 1,5% → 3,0% (hanya itu).** SL −6% dan time-stop 24 jam tetap.

| Arm | `TW_TP_PCT` | `TW_SL_PCT` | R:R | Break-even WR |
|---|---:|---:|---:|---:|
| ab9a (kontrol) | 0,015 | 0,06 | 1:4 | **80,0%** |
| **ab9b (treatment)** | **0,030** | 0,06 | 1:2 | **66,7%** |

Alasan memilih TP, bukan SL:

1. WR paper twoway terukur **39,2% (n=602)**. Dengan R:R 1:4, lane butuh WR 80%
   agar impas — mustahil. Geometri adalah batasan (constraint), bukan sinyalnya.
2. TP 3% menurunkan break-even WR ke 66,7% tanpa mengubah risiko per trade.
3. Kelayakan TP 3% didukung data: analisis path-ordered 13 exit `early_loss_cutoff`
   (klines 1h) → MFE rata-rata **+3,27% harga dalam 24 jam**; 9/13 mencapai ≥ +2%.
4. Hanya satu variabel → atribusi bersih ke TP. Bila TP 3% kalah, SL yang diuji berikutnya.

Verifikasi runtime (dibaca dari `/proc/<pid>/environ`, bukan asumsi):
`TW_TP_PCT=0.030`, `TW_SL_PCT=0.06`, `TW_TIME_STOP_H=24`, `TW_FUNNEL=1`, `TW_SHORT_LEG=1`, `PAPER_BTC_GATE_QUOTA=2`;
banner log: `TP+3%/SL-6% @3x | time-stop 24.0h`.

**Kriteria readout (pra-registrasi):** ≥ 40 trade tertutup per arm; Welch t dua sisi
α=0,05 pada PnL%; bila ab9b tidak lebih baik dengan p<0,05, TP 1,5% dipertahankan.

### 7.3 Perbaikan telemetri: funnel kini tetap ditulis saat cap penuh

Ditemukan saat verifikasi 7.2: `funnel_flush` hanya dipanggil **di dalam** blok
entry. Ketika 6 SIGNAL + 2 RANDOM penuh, blok dilewati → file funnel berhenti
diperbarui (arm ab9b: 265 siklus, lalu diam) padahal justru saat itulah bukti
paling dibutuhkan. Sekarang ada cabang `else` yang menulis `cycle_caps_full` +
konteks penuh.
