# PRE-REGISTRASI — Uji Alternatif Top-4 FINAL (SODEX-ALT1)

**Tanggal pra-registrasi:** 2026-10-07 (SEBELUM hasil dihitung)
**Acuan:** `ANANTARA_SoDEX_Swing_Strategies_FINAL_V1.html` (Final V1, 5 Okt 2026) — Top-4.
**Pemicu:** permintaan user mencari strategi alternatif yang mampu melampaui Target Utama.
**Status:** ambang di dokumen ini **BEKU** setelah commit. Dilarang diubah setelah melihat hasil.

> Aturan yang diakui dari dokumen acuan sendiri: *"Hermes must not assume profitability. Tidak ada
> paper peer-reviewed yang membuktikan Top-4 ini profitable secara langsung di SoDEX. Evidence
> eksternal memberi alasan ilmiah untuk menguji; hanya replication pada data SoDEX terkini yang
> boleh menentukan apakah edge masih hidup dan executable."*

---

## 1. Data & keterbatasan yang diakui

| Aset | Isi | Status |
|---|---|---|
| Tape trade SoDEX | 136 hari (24 Mei–7 Okt 2026), 92 simbol, ~12,5 jt trade | ADA |
| Bar menit turunan | `scratch/sodex_minutes/day=*.parquet` | DIBANGUN dari tape |
| OBI (L2) | 133 hari | ADA |
| Funding | ~5 hari saja (sejak 2 Okt) | TERBATAS → tidak bisa diuji lintas-rezim |
| **Open Interest** | tidak tersedia | **TIDAK ADA** → overlay OI di dokumen acuan **di-drop** |
| Binance / Hyperliquid flow | belum diverifikasi di sesi ini | → varian #2 "global flow" (M2/M3) **ditunda**, bukan diklaim |

**Konsekuensi jujur:** yang diuji di sini adalah versi **#1, #2-lokal (M1), #4** pada data SoDEX.
Varian global (#2 M2/M3) dan #3 ProSP (butuh pipeline ML cross-sectional penuh + OI) **belum** diuji
dan **tidak boleh** diklaim berhasil/gagal oleh dokumen ini.

## 2. Protokol statistik (BEKU)

- **Split:** IS = 2026-05-24 .. 2026-08-25 (≈70%). OOS = 2026-08-26 .. 2026-10-07 (≈30%). Tidak digeser.
- **Biaya:** taker SoDEX 4 bp/leg → **round trip 8 bp**; maker 1,2 bp/leg → 2,4 bp. Funding diabaikan
  (data <5 hari) → **dinyatakan sebagai sumber optimism residual**.
- **Uji ketahanan biaya:** 1,5× biaya. Bila edge **hilang** saat biaya 1,5× → **DITOLAK**
  (kondisi penolakan eksplisit dari dokumen acuan §6.8).
- **Kontrol negatif WAJIB:** permutasi label blok-harian 1000×; edge harus berada di luar
  distribusi permutasi (p < 0,05). Bila kontrol ikut "lolos", uji **dinyatakan tidak sah**.
- **Multiple testing:** BH-FDR q = 0,10 lintas hipotesis & varian yang diuji.
- **Dedup:** hitung sinyal sebagai pasangan unik (simbol × hari), bukan baris mentah (skill #12).
- **Universum:** hanya simbol likuid. Ambang objektif: quoteVolume 24 jam ≥ 50.000 USD
  (aturan pemilihan yang sudah dipakai 5-Okt), dan harga tersedia. Simbol tipis **dikeluarkan**.

### Bar pass (SEMUA harus terpenuhi agar sebuah hipotesis disebut "LAYAK DIUJI LEBIH LANJUT")

1. n OOS ≥ 100 sinyal unik; dan
2. rata-rata net return OOS > 0 **setelah 8 bp**; dan
3. tetap > 0 setelah **1,5× biaya**; dan
4. p_permutasi < 0,05 (BH-FDR q=0,10); dan
5. tidak bergantung pada **satu** simbol (kontribusi simbol tunggal ≤ 30% dari total net OOS).

Bila salah satu gagal → status **GAGAL/TIDAK LAYAK**, dilaporkan apa adanya.

## 3. Hipotesis konkret (definisi presisi)

Bar 4H (UTC-aligned, 6 bar/hari) dibentuk dari bar menit. Bar harian dari bar menit.

**H1 — External-Regime Adaptive Breakout (#1)**
- Regime global: slope log-return **BTC 4H** atas 6 bar terakhir (24 jam). TREND_UP bila > 0.
- Sinyal LONG bila: `close_4H > max(high 4H, 30 bar sebelumnya)` **dan** `relvol ≥ 1,5`
  (relvol = volume bar ÷ median volume 30 bar sebelumnya) **dan** regime BTC = TREND_UP.
- Sinyal SHORT = cermin (lowest low + regime TREND_DOWN).
- Entry: `open` bar berikutnya. Horizon keluar: 6 bar (24 jam). Tanpa SL/TP (agar falsifiable bersih).
- Grid horizon yang diuji (kecil, sesuai §5.6): 4H, 8H, 24H, 48H.

**H2 — SoDEX Local Order Flow (#2, ladder M1)**
- `OFI_4H = (AggBuyVol − AggSellVol)/(AggBuyVol + AggSellVol)` dari tape (field `side`).
- Sinyal LONG bila OFI_4H berada di **desil teratas** lintas-simbol-hari; SHORT bila desil terbawah.
- Horizon 24H (prioritas 1 per §6.5). Diuji juga 8H, 12H.
- **Ablasi wajib (§6.7):** M0 = harga/volume saja vs M1 = + arus lokal. M1 harus menambah nilai net.
- ⚠ **Catatan kejujuran:** arti field `side` (agresor vs maker) **belum terverifikasi** di sumber data.
  Bila salah, OFI bisa terbalik tanda. Karena itu **tanda kedua arah diuji** dan hasilnya dilaporkan;
  tanda yang dipilih setelah melihat hasil **wajib** dicatat sebagai pasca-hoc, bukan konfirmatori.

**H4 — Risk-Managed Regime Momentum (#4)**
- Formasi 14 hari, holding 7 hari, cross-sectional: long kuartil atas, short kuartil bawah.
- Varian risk-scaled: Exposure = Base × min(MaxScale, TargetVol/RealizedVol).
- Gate UP→UP (Hsieh dkk.): hanya saat state transisi UP→UP.
- Catatan: kombinasi risk-managed + gate UP→UP adalah **sintesis** (bukan hasil publikasi tunggal) →
  diperlakukan sebagai hipotesis baru, sesuai peringatan dokumen acuan §8.1.

## 4. Yang TIDAK dilakukan (batas etis)

- Tidak mengubah ambang F1/F3 atau pra-registrasi mana pun yang sudah ada.
- Tidak mengoptimalkan parameter di OOS. Bila parameter terbaik IS berbeda dari default, **keduanya
  dilaporkan** dan hanya default yang dihitung sebagai konfirmatori.
- Tidak menaikkan leverage/LOCKBOX/mengaktifkan jalur order nyata.
- Tidak menyimpulkan "target 0,8%/48 jam tercapai" dari hasil apa pun di sini. Uji ini hanya
  menjawab: **apakah sebuah edge bersih masih hidup dan layak diuji lebih lanjut.**

## 6. AMENDEMEN CAKUPAN — 2026-10-07 (SEBELUM hasil Binance dihitung)

**Temuan yang memaksa amendemen (dari pengukuran, bukan asumsi):**

Tape trade & OBI SoDEX historis **hanya memantau 3 simbol** dan baru diperluas belakangan.

| Periode | Simbol tape | Simbol OBI |
|---|---|---|
| 22 Mei – 4 Okt (126–128 hari) | **3** (BTC, ETH, SOL) | **3** (BTC, ETH, SOL) |
| 30–31 Mei | 5 | 5 |
| 5 Okt | 20 | 20 |
| 6–7 Okt | 92 | 92 |

**Konsekuensi (terukur):**
- Strategi **cross-sectional** (#3 ProSP, #4 momentum) **tidak dapat** diuji pada histori SoDEX —
  hanya ada 3 aset.
- Uji **time-series** pun tidak bertenaga: uji H1 pada SoDEX memberi **n OOS = 12** (jauh di bawah
  syarat n ≥ 100). Karena itu hasil SoDEX **tidak boleh** dipakai untuk menyimpulkan apa pun.

**Perubahan yang ditetapkan (di-commit sebelum hasil Binance dilihat):**

1. **Venue uji primer = Binance USDT-perp 1-menit**, `data/1m_binance`: 11 simbol
   (ADA, AVAX, BNB, BTC, DOGE, DOT, ETH, LINK, LTC, SOL, XRP) × 36 bulan (Okt 2022 – Sep 2025),
   dengan `taker_buy_volume` → arus order agresor tersedia untuk #2.
2. **Venue sekunder = SoDEX** (replikasi), dijalankan setelah cakupan 92 simbol cukup umur.
3. Alasan memakai Binance: dokumen acuan sendiri memakai Binance/HL sebagai sumber evidence;
   hasil Binance **tidak membuktikan** profitabilitas SoDEX — hanya menentukan **kelayakan
   direplikasi**. Klaim profitabilitas SoDEX hanya boleh datang dari replikasi SoDEX.
4. Seluruh ambang lain di §2–§3 **tidak berubah** (biaya 8 bp + uji 1,5×, kontrol random-entry,
   BH-FDR q=0,10, n ≥ 100, syarat simbol tunggal ≤ 30%).
5. Biaya Binance ≠ biaya SoDEX. Untuk uji Binance dipakai biaya **taker Binance 4,5 bp/leg**
   (round trip 9 bp) yang lebih ketat daripada SoDEX 4 bp → konservatif, bukan menguntungkan.

**Batasan tetap diakui:** Open Interest tidak tersedia; funding SoDEX < 5 hari; varian global #2
M2/M3 (Binance/HL flow lintas-venue) belum disiapkan. Hasil apa pun dari §6 ini berstatus
**"layak diuji lebih lanjut"**, BUKAN "target 0,8%/48 jam tercapai".

## 7. Cara verifikasi ulang

### §6b — Tanggal split venue Binance (ditetapkan SEBELUM hasil dihitung, 2026-10-07)

Rentang data Binance: 2022-10-01 .. 2025-09-30 (36 bulan). Pembagian 70/30 sesuai §2:

- **IS** = 2022-10-01 .. 2024-11-30 (26 bulan)
- **OOS** = 2024-12-01 .. 2025-09-30 (10 bulan)

Biaya uji Binance: **taker 4,5 bp/leg → round trip 9 bp** (§6 butir 5). Uji ketahanan tetap 1,5×.

**Catatan metode #2 di Binance:** OFI dihitung dari `taker_buy_volume` arsip Binance →
`OFI = 2·taker_buy_volume/volume − 1`. Ini **arus agresor sebenarnya** (tidak ambigu), berbeda dari
data SoDEX yang semantik field `side`-nya belum terverifikasi. Karena itu H2 di Binance bersih dari
ambiguitas tanda, dan hasilnya **tidak otomatis berlaku** untuk SoDEX sampai direplikasi.


```
.venv-research/bin/python3 scripts/sodex_alt_top4_study.py --hyp H1
```
Hasil ditulis ke `reports/sodex/sodex_alt_top4_<tanggal>.json` + ringkasan MARKDOWN.
