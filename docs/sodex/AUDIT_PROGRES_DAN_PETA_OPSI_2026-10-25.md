# AUDIT PROGRES & PETA OPSI PROYEK SODEX

**Tanggal:** 25 Oktober 2026 · **Commit acuan:** `99c0459` · **Verdict:** 25 Nov 2026
**Sifat:** audit read-only. Tidak ada order, tidak ada modal dialokasikan.

---

## 1. Ringkasan eksekutif (scoreboard jujur)

| Pertanyaan | Jawaban terukur |
|---|---|
| Modal on-chain sebenarnya | **$7,93** (primary $3,17 + harvest $4,76), 0 posisi, semua flag live = 0 |
| Wallet yang dipakai menghitung target | **$243,23** (simulasi, bukan saldo on-chain) |
| Mesin terbaik (REAL-WIDE) | n=192, WR 49,48%, PF 1,03, **+$13,18** |
| Window 30 jam terbaik | mean **+0,169%**, median **−0,362%**, hit 37,5% |
| Target | **0,80%** per window → mesin terbaik mencapai **21%** target |
| Sharpe tahunan mesin terbaik | **0,886** (p = 0,695 → tidak berbeda dari nol) |
| Keluarga sinyal diuji | **20+**, **0** lulus |
| Trial tercatat | **162** |
| Hasil positif yang terbukti | **tidak ada** |

**Kesimpulan satu kalimat:** proyek ini sudah selesai secara metodologis — 20+ keluarga
diuji dengan pra-registrasi, semuanya gagal; yang tersisa bukan "cari sinyal lagi", tetapi
**keputusan** apakah target dipertahankan atau diubah.

---

## 2. Audit state

### 2.1 Modal

| Sumber | Nilai | Catatan |
|---|---|---|
| `ground_truth.json` (2026-10-25 09:08 WIB) | **$7,93** | primary $3,17 + harvest $4,76 |
| `sodex_maturation_status.json` | $243,23 | "onchain_snapshot" — **label menyesatkan** |
| Posisi terbuka | 0 | — |
| Flag live | AUTOTRADE 0, PREGAIN 0, SODEX_SPOT_FARM 0, FUNDING 0 | semua paper |

> **Defect audit #1:** file maturation menyebut `wallet_source: onchain_snapshot` tetapi
> nilainya $243,23 sementara saldo on-chain $7,93. Salah satu dari dua hal ini benar; sampai
> direkonsiliasi, **semua persentase target dihitung dari basis yang salah 30×**.

### 2.2 Dua ledger yang bertentangan

| Ledger | Periode | n | Hasil |
|---|---|---|---|
| `BUKU_FORWARD_LEDGER.json` TWOWAY | 6 Agu – 8 Okt | 418 | **+$182,43** (+75% wallet) |
| `BUKU_FORWARD_LEDGER.json` REALWIDE | 6 Agu – 9 Okt | 268 | **+$90,66** (+37%) |
| Snapshot 9 buku (RCA 23 Okt) | s.d. 22 Okt | 1.984 | **−$375,18** (−154%) |

> **Defect audit #2:** selisih **$557** antara ledger forward dan snapshot RCA. Penjelasan
> paling mungkin: ledger forward berhenti 9 Okt (sebelum kolaps), sedangkan RCA mencakup
> 1–22 Okt ketika WR jatuh 41,0% → 26,9%. **Tetap harus direkonsiliasi sebelum keputusan
> modal apa pun.**

### 2.3 Infrastruktur

| Komponen | Status |
|---|---|
| `sodex-l2-collector` | **active (running)**, mulai 24 Okt 18:04 WIB, `Restart=always`, 10 simbol |
| Data L2 | 85 MB, 0 pelanggaran bid<ask (diverifikasi) |
| Klines SoDEX | 5m: 15 simbol × 8.640 · 1m: 15 × ~10.000 · 1h/1d tersedia |
| Klines Binance | 1h ~2,8 th · 1d 245 simbol × 2.587 hari · **30m 6 × 32.568 bar** |
| Registry trial | 162 entri |
| Dokumen | 100+ file di `docs/sodex/` |

> **Defect audit #3:** registry berisi **12 entri `passed=true`**. Setelah diperiksa, semuanya
> adalah **studi metodologi/audit** (R2C, R2D, R3A, R3C) dan studi filter entry — "passed"
> berarti *studi berhasil direplikasi*, **bukan** *strategi profitable*. Catatan internalnya
> sendiri menyebut "mean capture −1R NEGATIF" dan "holdout WR 27,8%". Kamus data ini harus
> diperbaiki agar tidak terbaca sebagai 12 strategi yang lulus.

### 2.4 Riwayat uji (semua yang sudah dicoba)

| # | Keluarga | Hasil | Alasan gagal |
|---|---|---|---|
| 1 | Momentum TS | gagal | gross ≈ 0 |
| 2 | Momentum CS (5m) | gagal | OOS negatif |
| 3 | Reversal jangka pendek | gagal | di bawah biaya |
| 4 | Vol breakout | gagal | MDE 6,2 bps, tetap negatif |
| 5 | Time-of-day / sesi | gagal | tidak replikasi di 2,8 th |
| 6 | Funding carry (1 venue) | gagal | 3,3 bps/30j < biaya 12,98 |
| 7 | Post-liquidation rebound | gagal | median −165 bps |
| 8 | Lead-lag BTC→alt | gagal | tidak terukur biaya |
| 9 | OI crowding reversal (PRAREG-30) | gagal | tidak ada edge |
| 10 | Maker entry (X=0) | gagal | seleksi 111 bps |
| 11 | Maker pullback (X=20) | gagal | net −20,7 bps |
| 12 | Market-making | gagal | spread 0,08–1,03 < fee 2,28 |
| 13 | Session reversal 12 jam | gagal | −45,14 bps, 0/6 |
| 14 | Session momentum 12 jam | gagal | alpha +1,53 bps (drift +23,61) |
| 15 | CS momentum 1–7 hari | gagal | t=2,416 < 2,5 |

---

## 3. Peta opsi lengkap — dengan expected value per 30 jam

Semua angka dalam **bps per window 30 jam**, setelah biaya. Ambang target: **80 bps**.

| # | Opsi | EV / 30 jam | Status | Bukti |
|---|---|---|---|---|
| 1 | Sinyal arah (momentum/reversal/dll) | **negatif s.d. 0** | 20+ keluarga ditutup | pra-registrasi |
| 2 | Maker entry | **−20,7** | ditutup | 861 trade |
| 3 | Market-making SoDEX | **−5 s/d −7,4** | mustahil | spread < fee |
| 4 | Funding carry 1 venue (HL) | **−9,7** | ditutup | funding 3,3 vs biaya 12,98 |
| 5 | **Funding differential lintas venue** | **+5,0 s/d +6,2 gross** | **belum layak di 30j** | breakeven 2,6–3,3 hari |
| 6 | Basis spot-perp (cash & carry) | **−3 s/d −5** (basis negatif) | tidak ada carry | Binance live |
| 7 | HLP vault (market-making profesional) | **+0,13** | terlalu kecil | APR **3,79%** |
| 8 | Program insentif/points | belum terukur | riset berjalan | — |
| 9 | Leverage untuk menutup gap | **0** (menggandakan varian) | bukan edge | Sharpe tetap 0,886 |
| 10 | Ubah target/denominator | — | **keputusan Anda** | — |

### 3.1 Rincian opsi 5 — satu-satunya yang positif secara struktural

Diukur 25 Okt dari API (60 hari):

| Aset | Funding HL | Funding Binance | Selisih | 30 jam | 48 jam | Breakeven |
|---|---|---|---|---|---|---|
| BTC | 0,097 bps/j | 0,263 bps/j | **+0,166** | +4,96 | +7,94 | 3,3 hari |
| ETH | 0,109 | 0,314 | **+0,205** | +6,15 | +9,85 | 2,6 hari |
| SOL | 0,070 | 0,005 | −0,065 | −1,94 | −3,10 | tidak |

Posisi: **long HL + short Binance**, delta-neutral. Biaya 4 leg ≈ 13 bps.
- Pada 30 jam: **net −7 s/d −8 bps** → gagal.
- Pada 7 hari: BTC +27,8 bps gross − 13 = **+14,8 bps/minggu** ≈ 7,7%/tahun.
- Modal minimum realistis: dua venue, margin buffer → **≥$5.000** agar biaya withdrawal
  ($1–2) tidak mendominasi.

**Ini positif, tetapi 100× di bawah target.**

### 3.2 Rincian opsi 7 — pembanding paling jujur

HLP adalah vault market-making **profesional** Hyperliquid: APR saat ini **3,79%**.
Per 30 jam = **0,13 bps**. Artinya: pelaku MM terbaik di venue terbaik pun tidak memperoleh
80 bps per 30 jam. Ini bukti eksternal, bukan opini, bahwa target tersebut berada 600×
di atas hasil MM profesional.

---

## 4. Aritmetika: apa yang harus benar agar 0,8% tercapai

| Jalur | Syarat | Kondisi sekarang |
|---|---|---|
| Sharpe sangat tinggi | Sharpe **17,1** dengan sd 0,8%/window | 0,886 |
| Sharpe elit + risiko | Sharpe **3,4** dengan sd 4%/window | 0,886 |
| Leverage pada mesin sekarang | **4,7×** untuk mean 0,169% → 0,8% | sd ikut 4,7× → worst window −77% |
| Edge per trade | **≥9,57 bps** gross | tidak ditemukan di 20+ keluarga |

**Tidak ada jalur yang lolos.** Leverage bukan solusi: ia mengalikan mean dan sd dengan
angka yang sama, sehingga Sharpe tetap 0,886 — dan drawdown menjadi fatal.

---

## 5. Tiga hal yang belum tertutup (dan nilainya)

| # | Yang belum diuji | Nilai potensial | Biaya |
|---|---|---|---|
| 1 | Insentif/points exchange | unknown, mungkin 5–30%/th | riset berjalan |
| 2 | MM Aster (maker 0) dengan data L2 penuh | mungkin, tapi adverse selection 111 bps | butuh data ≥2 minggu |
| 3 | Cross-venue funding 7–30 hari | **+7,7%/tahun** terukur | butuh modal ≥$5k di 2 venue |

Ketiganya **tidak** mencapai 80 bps/30 jam. Nilai tertinggi ada pada #3 karena sudah terukur.

---

## 6. Rekomendasi

| Prioritas | Tindakan | Alasan |
|---|---|---|
| **P0** | Rekonsiliasi dua ledger + perbaiki label `wallet_source` | selisih $557 dan basis 30× — semua angka target sekarang tidak dapat dipercaya |
| **P1** | Perbaiki kamus registry (`passed` ≠ profitable) | mencegah salah baca 12 entri |
| **P2** | Putuskan target: 0,8%/30 jam vs 0,8%/bulan vs hentikan | 0,8%/30 jam = 10,2×/tahun; 0,8%/bulan = 10%/tahun (konsisten dengan carry) |
| **P3** | Jika riset dilanjutkan: hanya opsi 5 (funding differential) dengan modal ≥$5k | satu-satunya EV positif terukur |
| **P4** | Pertahankan kolektor L2 sampai 25 Nov | biaya nol, optionality |

**Tidak ada rekomendasi untuk mengalokasikan modal ke strategi arah mana pun.**

---

## 7. Keterbatasan audit ini

1. Ledger belum direkonsiliasi — angka PnL bisa berubah setelah perbaikan.
2. APR HLP adalah snapshot, bukan rata-rata jangka panjang.
3. Basis spot-perp diukur satu titik waktu (bisa berubah jam-jaman).
4. Insentif exchange belum selesai diriset (2 subagent berjalan).
5. Analisis ini tidak menguji hipotesis baru; ia mengukur apa yang sudah ada.
