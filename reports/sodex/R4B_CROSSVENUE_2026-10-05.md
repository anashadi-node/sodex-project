# R4-B UJI SILANG VENUE — H6–H10 PADA TIGA TIER DATA (BINANCE · HYPERLIQUID 4j · HYPERLIQUID 1h)

> Spesifikasi **beku** (pra-registrasi `R4B_PROTOKOL_H6_H10_2026-10-05.md`, komit `b818502`).
> Satu-satunya yang berbeda antar tier: **grid data** (1 jam / 4 jam / 1 hari) dan rentang.
> Harness: `scripts/r4b_harness.py` (multi-tier). Mentah: `R4B_*_results.json`.
> Tujuan: memisahkan **"kelas hipotesis mati karena pasar"** vs **"mati karena struktur Binance"**.

## 1. Hasil lengkap (fase DEV, lockbox TERTUTUP)

| Tier | Rentang DEV | n bar | H6 | H7 | H8 | H9 | H10 | PBO |
|---|---|---|---|---|---|---|---|---|
| Binance 1j | 2022-10-01→2025-09-30 | ~26.300 | FAIL | FAIL | FAIL | FAIL | FAIL | 0,250 |
| HL 4j | 2024-06-23→2025-09-30 | 5.000 | FAIL | FAIL | FAIL | FAIL | FAIL | 0,353 |
| HL 1h | 2022-10-01→2025-09-30 | 2.239 (6,1 th) | FAIL | FAIL | FAIL | FAIL | FAIL | 0,881 |

**15/15 FAIL. PBO semua tier > 0,20. BH-FDR q=0,10: nol yang lulus di ketiga tier.**

| Tier | H | mean/48j | SR | p sign-flip | seg+ | trade | bruto/trade | perlu | kontrol p |
|---|---|---|---|---|---|---|---|---|---|
| Binance | H6 | +0,000% | 0,11 | 0,8457 | 2/3 | 304 | −0,18% | 6,00% | 0,214 |
| Binance | H7 | −0,090% | −0,37 | 0,5246 | 1/3 | 331 | −1,95% | 12,40% | 0,682 |
| Binance | H8 | +0,011% | 2,65 | 0,0000 | 2/3 | 136 | **+0,40%** | 6,00% | **0,0049** |
| Binance | H9 | −0,030% | −0,21 | 0,7208 | 0/3 | 177 | +1,10% | 6,00% | 0,980 |
| Binance | H10 | −0,006% | −1,65 | 0,0037 | 0/3 | 308 | −1,01% | 6,00% | 0,975 |
| HL 4j | H6 | +0,010% | 0,76 | 0,4111 | 1/3 | 124 | +0,15% | 6,00% | 0,119 |
| HL 4j | H7 | −0,020% | −0,08 | 0,9055 | 2/3 | 247 | −0,66% | 12,40% | 0,020 |
| HL 4j | H8 | +0,006% | 1,81 | 0,0067 | 2/3 | 201 | **+0,47%** | 6,00% | **0,0050** |
| HL 4j | H9 | +0,000% | 0,00 | 0,9961 | 1/3 | 52 | +2,29% | 6,00% | 0,552 |
| HL 4j | H10 | −0,024% | −1,76 | 0,0517 | 1/3 | 128 | −0,11% | 6,00% | 0,925 |
| HL 1h | H6 | −0,013% | −0,18 | 0,7598 | 1/3 | 304 | +0,21% | 6,00% | 0,423 |
| HL 1h | H7 | −0,011% | −0,04 | 0,9325 | 0/3 | 679 | +0,64% | 12,40% | 0,199 |
| HL 1h | H8 | +0,022% | **3,91** | 0,0000 | 2/3 | 201 | **+0,47%** | 6,00% | **0,0050** |
| HL 1h | H9 | −0,041% | −0,41 | 0,4146 | 1/3 | 170 | +1,81% | 6,00% | 0,960 |
| HL 1h | H10 | −0,108% | −1,33 | 0,0234 | 0/3 | 308 | +0,27% | 6,00% | 0,925 |

## 2. Temuan yang BERTAHAN di ketiga venue (replikasi)

### 2.1 H8 — informasi timing funding NYATA, tapi uangnya 13–15× terlalu kecil

| Tier | kontrol p | SR | bruto/trade | syarat §2 | rasio |
|---|---|---|---|---|---|
| Binance | **0,0049** | 2,65 | +0,40% | 6,00% | 0,067× |
| HL 4j | **0,0050** | 1,81 | +0,47% | 6,00% | 0,078× |
| HL 1h | **0,0050** | 3,91 | +0,47% | 6,00% | 0,078× |

**Tiga tier, tiga kali hasil yang sama**: filter "funding ≥ persentil-95 riwayat sendiri" memang
memilih waktu yang lebih baik dari acak (p ≈ 0,005 di **semua** venue — konsisten, bukan kebetulan).
Tetapi besarnya hasil **±0,4% per 14 hari**, sedangkan target menuntut **6,00% per 14 hari**.

### 2.2 Penutupan aritmetika carry (mengapa H8 tidak bisa diselamatkan)

Funding pada rezim ekstrem (persentil-95) menghasilkan ≈ **0,029%/hari ≈ 10,4%/tahun**.
Target menuntut **0,4%/hari ≈ 146%/tahun**. Kebutuhan vs kenyataan = **14×**.

Menahan lebih lama **tidak** menolong, karena biaya tumbuh linear terhadap hold:

| Hold | Funding terkumpul (rezim p95) | Syarat target | Selisih |
|---|---|---|---|
| 14 hari | ≈ 0,41% | 6,00% | 5,6% |
| 30 hari | ≈ 0,87% | 12,40% | 11,5% |
| 60 hari | ≈ 1,74% | 24,40% | 22,7% |

→ **Carry (keluarga ini) mati secara aritmetika sebagai mesin target.** Ia hanya bisa jadi
*komponen kecil* (net positif, SR tinggi) — dan itu pun butuh pra-registrasi baru.

### 2.3 Kelas "sinyal halus pada koin mayor likuid" DITUTUP

H6/H7/H9/H10 gagal di tiga tier dengan mean/48j ≈ 0 (±0,1%). Tidak ada bukti edge arah
(time-series maupun lintas-seksi) pada data harian/4-jaman koin mayor. Ini hasil **negatif yang
kuat** (bukan "belum cukup data"): n jendela 217–732, tiga venue, tiga grid waktu.

## 3. Constraint sesungguhnya (rekap kuantitatif)

| Klaim | Status |
|---|---|
| "Kurang mesin" | **SALAH** — mean portofolio = kombinasi konveks; menambah mesin hanya menaikkan Sharpe, tidak mean |
| "Kurang Sharpe" | **SALAH** — H8 punya SR 2,65–3,91 (lolos ambang SR 2,3) tapi mean-nya 0,011–0,022%/48j (target 0,8%) |
| "Kurang frekuensi" | **SALAH** — biaya 0,40%/trade; frekuensi tinggi = drag 69%/th (H1) |
| **"Kurang besar edge per trade"** | **BENAR** — terbaik 0,40–0,47% vs syarat 6,00% (14×) |

Target 0,8%/48 jam = **146%/tahun pada modal total tanpa leverage**. Edge terbaik yang
terepilkasi di 3 venue = **±10%/tahun**. Selisih ≈ **14×**. Ini bukan masalah optimasi; ini
masalah **jenis edge**.

## 4. Hanya dua jalur yang tersisa (keduanya perlu keputusan Mas Anas)

| Jalur | Mekanisme | Kenapa bisa menutup 14× | Yang dibutuhkan |
|---|---|---|---|
| **A. Biaya turun (maker, bukan taker)** | Asumsi biaya program 0,40%/trade adalah **taker**. Maker Binance 0,02%/sisi, HL 0,015%/sisi → biaya ≈ 0,03–0,04% (≈10× lebih murah). Frekuensi tinggi jadi hidup kembali | Beban biaya H1 (69%/th) → ≈ 7%/th; syarat edge per trade turun dari 6,00% ke ≈ 0,15–0,6% | **Model eksekusi + probabilitas fill** (limit order) — bukan asumsi. Harness wajib memodelkan fill, bukan menganggap selalu terisi |
| **B. Edge peristiwa besar** | Likuidasi besar, listing/delisting, funding flip pada koin kecil (bukan 11 mayor) | Edge per trade puluhan persen (bukan 0,4%), frekuensi sangat rendah | Data baru: tick/likuidasi/listing; universe koin diperluas di luar 11 mayor |

**Catatan penting**: jalur A **bukan** pelonggaran batas keamanan — tidak menyentuh leverage,
tidak mengubah target, tidak mengubah `SODEX_TOTAL_WALLET`, tidak menghidupkan arm A1. Yang berubah
hanya **asumsi biaya eksekusi**, dan hanya sah bila dibuktikan dengan model fill yang realistis
(limit order tidak selalu terisi). Sesuai aturan absolut: **butuh persetujuan Mas Anas sebelum
diuji**, dan harus lewat pra-registrasi baru.

## 5. Pagar yang tetap dipatuhi

- Lockbox **tetap tertutup** di ketiga tier (tidak ada yang lulus DEV).
- Tidak ada penyetelan parameter setelah melihat hasil; tidak ada promosi post-hoc (H8/H10 cermin
  hanya didokumentasikan).
- Tidak ada perubahan gate T1, leverage, target 0,8%/48j, `SODEX_TOTAL_WALLET`, E1, arm A1,
  `RW_MARGIN_UTIL_CAP`.
- Script tetap **READ-ONLY** terhadap lane live.

---
*Hermes Anantara v3 · 05-Okt-2026 · 15/15 FAIL · hasil negatif dilaporkan apa adanya.*
