# SODEX ALT3 — HASIL STUDI CROSS-SECTIONAL (1 jam) — 2026-10-07

Status: **SELESAI. VERDICT: GAGAL (TIDAK ADA VARIAN LULUS).**
Data: `scratch/sodex_klines/` — 92 simbol, 511.254 bar 1 jam, 2025-10-12 → 2026-09-28.
Harness: `scripts/sodex_alt3_xsec_study.py` | Hasil JSON: `reports/sodex/sodex_alt3_xsec_20261007*.json`
Pra-registrasi: `docs/sodex/SODEX_ALT3_PRAREG_2026-10-07.md` (BEKU, `d55cc8d`).

---

## 1. Ringkasan satu paragraf

Cross-sectional reversal 8 jam (H7b) **lolos** gerbang formal pada seluruh universo
(+9,31 bp, p=0,001). Begitu pasar tipis dibuang dan hanya pasar likuid yang diuji,
angka itu **berbalik negatif** (−13,33 bp) dan **tidak ada satu pun varian yang lulus**.
Kesimpulan: hasil "lolos" itu **artefak likuiditas/peringkat pasar mati**, bukan edge.
ALT3 ditutup.

---

## 2. Tiga run pembanding (bukti pemutus)

| Varian | (1) Semua 92 pasar | (2) **Likuid saja** (≥$1rb/jam) | (3) breadth 6 | Verdict |
|---|---|---|---|---|
| H6a trend 24j | −99,07 bp | −76,29 bp | — | gagal |
| H6b trend 72j | −57,38 bp | −136,54 bp | — | gagal |
| H6c trend 168j | +6,43 bp (p .40) | +203,38 bp (n=**17**) | — | gagal |
| H7a reversal 4j | +7,79 bp (p .001) | **−6,62 bp** | −6,62 bp | gagal |
| **H7b reversal 8j** | **+9,31 bp (p .001) → LULUS** | **−13,33 bp (p .345)** | −13,33 bp | **gagal** |
| H8a risk-trend A | +26,78 bp (p .16) | −33,58 bp | −33,58 bp | gagal |
| H8b risk-trend B | +85,28 bp (p .17, n=17) | +164,17 bp (n=**17**) | +164,17 bp (n=17) | gagal |
| H8c risk-trend C | +113,62 bp (n=**8**) | +273,92 bp (n=**8**) | +273,92 bp (n=8) | gagal |

Run (3) IDENTIK dengan run (2) → masalahnya **bukan** breadth, murni **likuiditas**.

Catatan kritis H7b: pada run 1, share satu simbol (LIT-USD) ≈ 49% dari total net.
"Edge" itu pada dasarnya **satu pasar tipis**.

---

## 3. Penyebab teknis (root cause)

Di pasar tipis, harga 1-jam sering **tidak bergerak** (tidak ada transaksi) →
bar berulang / harga basi. Strategi peringkat-desil membaca "reversal" dari
harga basi ini, lalu diberi kredit profit yang **tidak bisa dieksekusi**
(tidak ada volume untuk masuk/keluar). Uji likuiditas menghapus ilusi itu.
Ini bukan kegagalan kalibrasi — ini kegagalan **asumsi pasar**.

---

## 4. Fakta likuiditas venue (medan perang yang sebenarnya)

Median notional per jam (OOS, USD) — 15 teratas:
BTC 1.074.400 · ETH 433.739 · SOL 111.530 · QNT 88.930 · XAUT 54.196 · SUI 36.459 ·
BNB 35.863 · UNI 24.037 · ZEC 22.875 · PONS 14.914 · CXMT 8.787 · SPCX 6.573 ·
HYPE 6.211 · DOGE 5.819 · XRP 5.318

| Ambang | Simbol lolos (median jendela IS ≥ ambang, dari 92) |
|---|---|
| ≥ $1rb/jam | 53 (IS) — **tetapi hanya 18 pada 3 bulan terakhir** |
| ≥ $10rb/jam | 11 |
| ≥ $100rb/jam | **3** |
| median seluruh pasar | **$328/jam** |

**Dua fakta yang mengubah arsitektur:**
1. 90% "92 pasar" adalah pasar mati. Yang benar-benar bisa ditradingkan: **3–11 nama**.
2. Likuiditas **menyusut**: 53 simbol likuid (IS) → 18 simbol (3 bulan terakhir).

---

## 5. Yang dibuang karena studi ini (dan itu bagus)

- H7b 8-jam reversal → **DIBUANG**. Breakeven slippage hanya 2,3 bp/sisi; setelah
  filter likuiditas malah negatif. Kalau ini di-deploy, kita akan menaruh uang
  di pasar yang tidak punya kedalaman untuk keluar.
- Kelas arsitektur "cross-sectional desil" untuk SoDEX → **DIBUANG** (lihat §6).

---

## 6. Diagnosis ARSITEKTURAL (bukan strategi)

Tiga putaran hipotesis (Top-4, H5, ALT3) semuanya **gagal dengan pola yang sama**:

| Putaran | Kelas arsitektur | Hasil |
|---|---|---|
| Top-4 (Binance 3 thn) | event single-name | 0/17 lulus |
| H5 fade (SoDEX) | event single-name | arah BERLAWANAN |
| ALT3 (92 pasar) | cross-sectional desil | lulus semu → gugur saat difilter likuiditas |

Pola: **setiap arsitektur yang saya bangun mengasumsikan pasar DEEP & BROAD.**
SoDEX bukan Binance kecil. SoDEX = venue tipis, 3 nama likuid, retail-heavy.

**Asumsi yang salah (2 buah):**
1. Bahwa 92 pasar = 92 kesempatan. Kenyataannya ~10.
2. Bahwa ada "alpha arah" bersih setelah biaya di pasar tipis. Kenyataannya
   biaya + slippage memakan seluruh edge pada horizon ≤8 jam.

---

## 7. Arsitektur apa yang SECARA STRUKTURAL cocok untuk venue tipis?

Bukan "cari strategi lebih pintar", tapi **pindah kelas masalah**:

| Kelas | Kenapa cocok untuk SoDEX | Data yang kita miliki |
|---|---|---|
| **(A) Order-flow imbalance native** | Di pasar tipis, arus order RETAIL itu sendiri adalah sinyal (bukan noise seperti di Binance). Kita punya tape sendiri: `buy_n/sell_n`, `big_n/big_qty`, vwap per MENIT. | ✅ 92 simbol, 2026-05-24 → 2026-10-07, 131 hari |
| **(B) Lead-lag lintas venue** | Kalau harga SoDEX tertinggal dari Binance (oracle/perp lebih lambat), itu edge yang **hanya ada di venue lambat**. Tidak butuh breadth. | ✅ paralel: beli klines Binance menit periode sama |
| **(C) Entry pasif (maker)** | Fee taker SoDEX 4 bp/leg vs maker 1,2 bp/leg → arsitektur hemat biaya 3,3×. Bisa disimulasikan dengan OHLC menit yang kita punya (limit terisi bila masuk [low,high]). | ✅ tape menit OHLC |

Ketiganya **tidak** memerlukan cross-section lebar, dan (A),(B) memakai data yang
**hanya kita punya** (tape mikro-struktur SoDEX sendiri).

---

## 8. Batas jujur

- Dokumen ini **tidak** mengklaim ada kandidat yang akan mencapai target 0,8%/48 jam.
  Ia mengklaim: satu jalur sudah **ditutup dengan bukti**, dan tiga kelas arsitektur
  baru **layak diuji** — belum berarti akan berhasil.
- Target utama tetap **harga mati** dan **belum terbukti terlampaui**.
- Putaran berikutnya WAJIB pra-registrasi sebelum satu hasil dihitung.

— Hermes Anantara v3 — 2026-10-07
