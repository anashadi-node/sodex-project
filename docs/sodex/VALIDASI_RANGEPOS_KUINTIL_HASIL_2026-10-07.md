# VALIDASI RANGEPOS KUINTIL (PRAREG-3) — HASIL DESKRIPTIF — 2026-10-07

**⚠️ STATUS: DESKRIPTIF SAJA. BUKAN VERDICT.** Jendela historis Binance & SoDEX sudah
terpakai untuk memilih hipotesis ini (lihat protokol §0). Verdict yang sah hanya dari
data **forward**. Dokumen ini melaporkan apa yang terukur, tanpa menaikkannya jadi klaim.

Protokol beku: `docs/sodex/SODEX_PRAREG3_RANGEPOS_QUINTILE_2026-10-07.md`
Skrip: `scripts/research/rangepos_quintile_validation.py`
Output: `reports/sodex/VALIDASI_RANGEPOS_KUINTIL.json`

---

## 1. Hasil (4 sel keluarga, konfigurasi beku)

**Binance 1d — 245 nama × 2.587 bar (2019-09-08 → 2026-10-07):**

| Sel | n | bruto | net 1× | net real | net 2× | turnover | fee | S_ann | t_NW | p | seg+ | BH q=0,10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **kuintil H1** | 2305 | +14,64 | +11,37 | **+10,67** | +8,09 | 0,66 | 3,28 | 1,22 | **3,75** | **0,0002** | 3/3 | **PASS** |
| **kuintil H2** | 1152 | +24,53 | +20,22 | **+19,30** | +15,91 | 0,86 | 4,31 | 1,11 | **3,31** | **0,0009** | 2/3 | **PASS** |
| desil H1 | 2305 | +20,30 | +16,10 | +15,20 | +11,90 | 0,84 | 4,20 | 1,15 | 3,51 | 0,0005 | 2/3 | **PASS** |
| desil H2 | 1152 | +26,77 | +21,44 | +20,30 | +16,11 | 1,07 | 5,33 | 0,78 | 2,30 | 0,0213 | 2/3 | **PASS** |

**SoDEX 1d — 84 nama × 361 bar (2025-10-12 → 2026-10-07):**

| Sel | n | bruto | net 1× | net real | net 2× | turnover | fee | S_ann | t_NW | p | seg+ | BH q=0,10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| kuintil H1 | 276 | +9,19 | +6,69 | +6,15 | +4,18 | 0,63 | 2,51 | 0,98 | 1,06 | 0,2895 | 1/3 | gagal |
| kuintil H2 | 138 | +19,05 | +15,73 | +15,02 | +12,42 | 0,83 | 3,32 | 1,25 | 1,46 | 0,1441 | 3/3 | gagal |
| desil H1 | 276 | +5,52 | +1,90 | +1,13 | −1,72 | 0,90 | 3,62 | 0,20 | 0,21 | 0,8355 | 2/3 | gagal |
| desil H2 | 138 | +21,90 | +17,38 | +16,42 | +12,86 | 1,13 | 4,52 | 0,92 | 1,05 | 0,2952 | 2/3 | gagal |

## 2. Kontrol negatif (dinilai pada BRUTO) — dan satu bendera merah

| Panel | H | acak-dalam-baris | kuintil-acak murni |
|---|---:|---:|---:|
| Binance | 1 | +2,08 bps | +0,84 bps |
| Binance | 2 | +5,37 bps | +3,46 bps |
| **SoDEX** | **1** | −5,44 bps | **+7,61 bps** ← ⚠️ |
| SoDEX | 2 | −5,47 bps | −0,88 bps |

- Binance: kontrol kecil relatif terhadap bruto (+14…+27 bps) dan berada dalam ±1,2 SE → **OK**.
- **SoDEX H1: kontrol "kuintil-acak" = +7,61 bps sedangkan sinyal asli hanya +9,19 bps bruto.**
  Artinya pada sel itu **sinyal tidak bisa dibedakan dari portofolio kuintil acak** — "edge"-nya
  sebagian besar adalah efek konstruksi (equal-weight dollar-neutral pada n kecil), bukan
  informasi. Ini alasan kuat untuk **tidak** memakai sel H1 SoDEX sebagai bukti apa pun.

## 3. Aritmetika ke target (memakai angka NET, bukan bruto)

Target 0,8% = **80 bps per 48 jam**.

| Sumber | net per 48 jam | % dari target |
|---|---:|---:|
| Binance kuintil H2 (BH PASS) | +20,22 bps | **25%** |
| Binance kuintil H1 (BH PASS, ×2 hari) | +22,74 bps | **28%** |
| SoDEX kuintil H2 (BH gagal) | +15,73 bps | 20% |
| SoDEX kuintil H1 (BH gagal, kontrol bocor) | +13,38 bps | 17% |

**Bahkan mekanisme terbaik yang lolos BH-FDR (Binance kuintil, t=3,75, 7 tahun, 245 nama)
hanya memberi ±25–28% dari target.**

## 4. Mengapa ini penting: celahnya sekarang terukur, bukan spekulatif

| Komponen | Nilai terukur | Yang dibutuhkan |
|---|---:|---:|
| Mekanisme terbaik (lolos BH) | 20–23 bps/48 jam | 80 bps/48 jam → **celah ≈ 4×** |
| n periode SoDEX 1d | 138 | ≈ 203 untuk t=2,0 |
| t SoDEX kuintil H2 | 1,46 | ≥ 2,0 → **belum signifikan** |
| Korelasi pasangan antar-nama | 0,595 | — |
| n_effective_bets (6 mesin) | 2,32 | — |
| Pengganda Sharpe dari diversifikasi | **1,49×** (bukan √6 = 2,45×) | ≥ 2,0× untuk menambal 4× |

Jadi: **tambal-kekurangan-lewat-diversifikasi tidak bisa menutup celah 4×**, karena
diversifikasi nyata hanya memberi 1,49× (sensus korelasi), sedangkan menaikkan gross
= leverage = dilarang oleh aturan proyek.

## 5. Kesimpulan jujur

1. **Binance**: efek momentum ekor (rangepos kuintil) **kuat, signifikan, lolos BH-FDR**
   di 4/4 sel, t sampai 3,75, atas 7 tahun dan 245 nama. Ini mekanisme pertama di sesi ini
   yang lolos uji multiplisitas dengan bersih.
2. **SoDEX**: tanda sama (+), besaran 65–78% dari Binance (konsisten dengan replikasi),
   **tetapi belum signifikan** (t ≤ 1,46) dan **sel H1 gagal kontrol**.
3. **Besaran terbaik = 25–28% dari target.** Celah ±4×.
4. **Tidak ada jalan menutup celah lewat diversifikasi** (1,49×) atau leverage (dilarang).
5. Karena itu verdict sah menunggu **data forward** (PRAREG-3 §4), dan **tenggat 20-Nov
   tidak cukup** untuk sertifikasi horizon harian (~22 periode vs ~203 dibutuhkan).

— Hermes Anantara v3 — 2026-10-07
