# ANALISIS KELAYAKAN TARGET 0,8% — Opsi A/B/C/D
**Divisi RISET Anantara Sakti · 1 Okt 2026 · Berdasarkan bukti terukur + literatur terverifikasi**

---

## 0. KOREKSI SAYA DULU (transparansi)

```text
Klaim saya sebelumnya: "0,8% per 30 jam = 1,6%/hari"
BENAR              : 0,8% x (24/30) = 0,64%/hari
Status             : SALAH (saya mengalikan 2, seharusnya x 0,8). Tafsir Mas Anas lebih tepat.
```

**Tafsir yang benar (dikonfirmasi Mas Anas):**
> Rata-rata PnL BERSIH per periode 30 jam = 0,8% dari TOTAL dana wallet saat itu (spot+future).
> Yaitu *average*, bukan "setiap window wajib". Basis compounding = wallet saat itu.

---

## 1. Setara tahunan

| Opsi | Periode | Per hari | Tanpa compounding | **Dengan compounding** |
|---|---|---:|---:|---:|
| **A** | 30 jam | 0,640% | +234%/th | **+924%/th** |
| **B** | 48 jam | 0,400% | +146%/th | **+328%/th** |
| **C** | 72 jam | 0,267% | +97%/th | **+164%/th** |
| **D** | 96 jam | 0,200% | +73%/th | **+107%/th** |

---

## 2. Sharpe ratio yang DIBUTUHKAN (ini penentu kelayakan)

| Opsi | vol 10% | vol 20% | vol 40% | vol 70% |
|---|---:|---:|---:|---:|
| A 30j | 92,4 | 46,2 | 23,1 | **13,2** |
| B 48j | 32,8 | 16,4 | 8,2 | **4,7** |
| C 72j | 16,4 | 8,2 | 4,1 | **2,3** |
| D 96j | 10,7 | 5,3 | 2,7 | **1,5** |

**Referensi Sharpe yang ADA BUKTINYA:**
```text
B0 Donchian — UKURAN KITA SENDIRI      : 1,05   (CAGR 16,06%, MaxDD −14,7%, 563 hari, 30 simbol)
Momentum kripto terbaik (Yang 2025)    : 1,42
Order flow (klaim paper Anastasopoulos): 3,68   ← TAPI digugurkan oleh C2 (IC+ / Sharpe net NEGATIF)
Hedge fund kelas atas (historis)       : 2,0–3,0
Medallion (kapasitas dibatasi keras)   : ~2,75
```
***Catatan kritis:*** C1 (Nefedov 2026) — pada 137 perp Binance 2020–2024 dengan walk-forward bersarang
+ biaya + Deflated Sharpe: **TIDAK ADA SATU PUN dari 6 faktor yang bertahan**; 4 negatif OOS.

---

## 3. Posisi sistem kita SEKARANG vs target (terukur, bukan opini)

| Sistem | per 30 jam | per 96 jam | vs target |
|---|---:|---:|---|
| Harvest funding (paper) | **0,0019%** | 0,0061% | **420× lebih kecil** dari A |
| B0 Donchian (benchmark kita) | **0,0550%** | 0,176% | **15× lebih kecil** dari A · 4,5× dari D |
| CEX Binance 90d | −0,0347% | RUGI | — |

---

## 4. TEMUAN PALING PENTING: target A = persis level skenario TERBAIK akademik

```text
Paper funding arbitrage (S2096720925000818): skenario TERBAIK dari 60 → 115,9% dalam 6 bulan
   = 0,794% per 30 jam   →   99% dari target A (0,8%)

Artinya: TARGET A dikalibrasi tepat pada kasus TERBAIK dari 60 skenario akademik —
         bukan pada rata-rata, bukan pada hasil live yang diaudit.
         Skor itu memakai leverage 7× pada Drift XRP.
```

Dan pembanding tandingannya:
```text
MDPI 2026 (26 bursa, 35,7 juta observasi): hanya 40% opportunity teratas tetap positif
   setelah biaya; forced exit di 95% opportunity.
C1: dengan protokol ketat, NIHIL yang bertahan.
C2: 23 run IC positif, Sharpe BERSIH negatif; 0 dari 460 sel fee-slippage positif.
```

---

## 5. Edge per round-trip yang dibutuhkan (praktis, fee 8 bps RT)

Rumus: `turnover T per periode × (gross − 0,08%) = target`

| Turnover / 30 jam | Gross perlu (A 30j) | = ×fee | Gross perlu (D 96j) | = ×fee |
|---:|---:|---:|---:|---:|
| T=1 | 0,880% | 11,0× | 0,330% | 4,1× |
| T=4 | 0,280% | 3,5× | 0,143% | 1,8× |
| T=8 | 0,180% | 2,2× | 0,111% | 1,4× |
| T=20 | 0,120% | 1,5× | 0,093% | 1,2× |

**Implikasi:** target A menuntut edge gross 1,5×–11× biaya di SETIAP round-trip, terus-menerus.
Untuk konteks: median MFE kita terukur +1,087R, tetapi **excess alpha setelah beta dinetralkan = −0,133R**
(H1b v4, n=812). Jadi kita belum punya edge positif sama sekali, apalagi 2–11× biaya.

---

## 6. Draw-down yang "wajar" pada setiap target

| Opsi | Return | Sharpe | Vol tahunan | MaxDD kasar |
|---|---:|---:|---:|---:|
| D 96j | 107% | 2,0 | 54% | ~13% |
| D 96j | 107% | 1,5 | 71% | ~24% |
| C 72j | 164% | 2,5 | 65% | ~13% |
| B 48j | 328% | 5,0 | 66% | ~7% |
| A 30j | 924% | 13,0 | 71% | ~3% |

**Bacaan:** angka MaxDD kecil pada B dan A muncul KARENA Sharpe-nya tidak realistis
(Sharpe 5 dan 13 tidak ada presedennya). Target dengan Sharpe rasional (D pada 1,5–2,0)
membawa MaxDD 13–24% — itu konsekuensi yang harus diterima, bukan dihindari.

---

## 7. VERDICT per opsi

| Opsi | Sharpe dibutuhkan | Ada preseden? | Verdict |
|---|---:|---|---|
| **A (30j)** | 13,2–23 | Hanya di skenario TERBAIK dari 60 (paper, 7× lev, bukan live) | ❌ **TIDAK LAYAK** — tidak ada satu pun jalur bukti |
| **B (48j)** | 4,7–8,2 | **Tidak ada** | ❌ **TIDAK LAYAK** dengan basis bukti sekarang |
| **C (72j)** | 2,3–4,1 | Di ambang batas terbaik yang terdokumentasi | ⚠️ **SANGAT SULIT** — perlu edge kelas atas yang belum kita punya |
| **D (96j)** | 1,5–2,7 | **Ada**: hedge fund atas 2,0–3,0; momentum kripto 1,42 | ✅ **SATU-SATUNYA YANG MASUK AKAL** — tetapi masih 4,5× di atas B0 kita |

---

## 8. Rekomendasi RISET (falsifiable)

```text
R1. Jadikan Opsi D (0,8% net per 96 jam) sebagai target antara yang RESMI diuji.
    Alasan: satu-satunya dengan preseden Sharpe yang terdokumentasi.

R2. Tangga bukti menuju D (jangan lompat):
      Tahap 1: alpha net POSITIF pada paper, 30 hari, universe likuid, beta-netral
      Tahap 2: Sharpe rolling 90 hari >= 1,5 (setara B0+)
      Tahap 3: implementasi shortfall < 25% dari model
      Tahap 4: BARU bicara 0,8%/96 jam

R3. Ukur "jarak ke target" setiap bulan, jangan ukur "apakah target tercapai".
    Metrik tunggal: (net PnL bulanan) / (target bulanan). Sekarang ≈ 0,2–2%.

R4. JANGAN menaikkan leverage untuk mengejar A atau B.
    Leverage menaikkan Sharpe yang DIBUTUHKAN, bukan menurunkannya — target jadi makin jauh.

R5. Lompatan yang mungkin (jalur berbeda, bukan lebih cepat di jalur yang sama):
      a) Jalur market-neutral funding (varians rendah) — menaikkan Sharpe, bukan return mentah
      b) Jalur alpha nyata (S1/S2) — wajib lulus C1/C2 lebih dulu
      c) Kombinasi keduanya = satu-satunya cara menuju Sharpe 2+
```

## 9. Jawaban singkat atas pertanyaan Mas Anas

```text
"Apakah 0,8% per 30 jam mungkin?"
  → Secara matematis: mungkin (924%/th).
  → Secara bukti: TIDAK. Tidak ada strategi live-teraudit mana pun yang menunjukkan
    Sharpe 13+. Angka itu hanya muncul sebagai skenario TERBAIK dari 60 di satu paper.

"Opsi B?"
  → Sharpe 4,7–8,2. Tidak ada preseden. Praktis tidak layak.

"Opsi C?"
  → Sharpe 2,3–4,1. Di ambang teratas yang pernah terdokumentasi. Sangat sulit.

"Opsi D?"
  → Sharpe 1,5–2,7. PRESEDEN ADA (hedge fund kelas atas). Ini jalur yang masuk akal.
    Tetapi jujur: B0 kita = Sharpe 1,05 dan CAPAI 0,176%/96 jam — masih 4,5× di bawah D.
```

**Kesimpulan:** target yang layak diperjuangkan adalah **D (0,8% net per 96 jam)**, dengan C sebagai
ambisi jangka panjang. A dan B bukan target — keduanya adalah angka yang tidak punya dasar bukti
dan, jika dijadikan patokan, akan mendorong pengambilan risiko yang justru merusak modal.
