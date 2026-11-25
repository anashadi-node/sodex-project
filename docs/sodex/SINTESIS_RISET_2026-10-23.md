# SINTESIS RISET — Lima Lini Bukti, Satu Kesimpulan

**Tanggal:** 23 Oktober 2026 · **Ambang:** 9,57 bps gross/trade (target 0,8%/window pada biaya 6,49)
**Status:** semua lini independen, semuanya negatif. Dokumen ini merangkum mengapa.

---

## Ringkasan

| Lini bukti | Cakupan | Hasil | Yang membunuhnya |
|---|---|---|---|
| **1. Uji sendiri, 8 keluarga** | SoDEX 5m, 15 simbol, 30 hari | 0/8 lulus OOS | gross ≈ 0; F4 punya daya (MDE 6,2) dan tetap negatif |
| **2. Literatur intraday 15m–4j** | 12 studi, 2013–2026 | 0 layak | semua edge <9,57 bps atau gagal robust |
| **3. Microstructure L2** | 8 studi, resolusi 1–15 detik | 0 layak | R² kontemporer ≠ forecast; edge OOS <2 bps |
| **4. Funding carry** | HL/dYdX live, 60 hari | tidak layak | breakeven 4,3 hari; target butuh 3,1 bps/jam (≈0% jam) |
| **5. Session reversal (uji baru)** | Binance 30m, 6 simbol, 678 hari | 0/2 lulus | "edge" = drift pasar, alpha +1,5 bps |

---

## Lini 1 — Uji sendiri (PRAREG-SIG-01)

8 keluarga, split 70/30, biaya 6,49 bps: F1 −7,89 · F2 −0,86 · F3 −2,04 · F4 −6,50 ·
F5 −20,67 · F6 −2,24 · F8 −47,43 bps. Kontrol acak −8,61 bps (null benar, drift −2,44/2 jam).

Efek jam yang tampak kuat (jam 21 = +19,4 bps, 15/15 simbol) **gugur** di 2,8 tahun Binance:
korelasi profil antar-tahun 2025–2026 = **−0,15**.

## Lini 2 — Literatur intraday

| Keluarga | Effect size | Lolos 9,57? |
|---|---|---|
| Short-term reversal 15 menit | **1,3 bps** gross | tidak (13% ambang) |
| Boundary 15 menit (quarter-hour) | 0,5 bps | tidak (5%) |
| Turn-of-candle | 0,58 bps/menit | tidak (butuh 16 menit) |
| Opening range breakout | **−58%/tahun**, 0 dari 200 salinan acak | tidak |
| Post-liquidation rebound | mean +18 bps, **median −165 bps** | tidak (outlier) |
| Intraday TSM (½ jam pertama → ½ jam terakhir) | breakeven **10 bps** | marginal, tanpa OOS pasca-2020 |
| Session reversal 12 jam | gross 23,9–42,8 bps | **gagal SPA/bootstrap** di paper aslinya |
| Cross-sectional momentum mingguan | +57,3 bps/minggu gross | horizon di luar 4 jam; tidak signifikan |

**Pola:** semua yang gross-nya besar berada di **horizon lebih panjang** atau **gagal uji
robustness**. Semua yang horizon-nya cocok (15 menit–1 jam) berada **5–20× di bawah biaya**.

## Lini 3 — Microstructure L2

- OFI (Cont-Kukanov-Stoikov): R² **kontemporer** 65% — menjelaskan harga yang **sudah** terjadi.
- OFI 20-level BTC/USDT 100 ms: R² OOS 7,5% → **tidak ada keunggulan setelah 30 detik**.
- OFI multi-level pre-registered: edge bruto **0,2–0,3 bps**, dua orde di bawah ambang.
- TFI: CI95 melintasi nol di semua horizon 1–30 detik.
- OBI 5-level: rank-IC 0,050 pada 1 menit → decay 94%, half-life beberapa menit.
- Large-trade footprint: −2,0 bps/jam, **tidak robust** setelah koreksi (CI −4,3…+0,2).

**Batas resolusi 15 detik:** membuang 93% observasi 1 detik; pada BTC ~506 pesan/detik,
7.590 event dipadatkan jadi satu angka. OFI sejati **tidak bisa** dihitung dari snapshot
(hanya ΔQ net; add/cancel/eksekusi tidak terpisah).

**Kesimpulan:** sinyal 15 detik berguna untuk **timing eksekusi**, bukan untuk arah.

## Lini 4 — Funding carry

| Metrik | Nilai terukur |
|---|---|
| Funding BTC Hyperliquid | 0,102 bps/jam (8,9% APR), 92,8% jam positif |
| Funding median semua aset HL | 0,125 bps/jam (lantai 11,6% APR) |
| Breakeven delta-neutral (RT 12,98 bps) | **4,3 hari** (rate lantai) – 5,3 hari (rata-rata) |
| Funding 30 jam di HL | **3,3 bps** (BTC) — di bawah biaya 12,98 |
| Yang dibutuhkan target 0,8%/30 jam | **3,10 bps/jam** → terjadi ≈0% jam pada aset besar |

**Verdict:** carry adalah strategi **multi-hari**, bukan 30 jam. Pada wallet $250, biaya
withdrawal ($1–2 = 40–80 bps) sudah lebih besar dari seluruh edge.

## Lini 5 — Session reversal/momentum (PRAREG-SIG-02, uji baru)

Data Binance 30m, 6 simbol, 678 hari (2024-01 → 2025-11), split latih 2024-01…2025-06 /
uji 2025-07…2025-11, biaya 10 bps.

| Hipotesis | Latih | OOS | t | Simbol + | Verdict |
|---|---|---|---|---|---|
| H1 **reversal** | −11,74 | **−45,14 bps** | −3,20 | **0/6** | DITOLAK |
| H2 **momentum** | −8,26 | **+25,14 bps** | +1,78 | 6/6 | DITOLAK |

**H2 tampak menjanjikan — dan itu jebakan.** Kontrol drift (beli-tahan sesi 2) menghasilkan
**+23,61 bps** pada periode OOS yang sama. Artinya:

> **alpha H2 = 25,14 − 23,61 = +1,53 bps** — hanya **16%** dari ambang 9,57 bps.

H2 bukan sinyal; ia **beta pasar** yang kebetulan searah. Tanpa kontrol drift, hasil ini akan
salah dilaporkan sebagai "edge +25 bps, 6/6 simbol". Ini contoh paling jelas mengapa kontrol
negatif wajib.

BH-FDR q=0,10: **0 dari 12 uji lolos**.

---

## Kesimpulan gabungan

**Tidak ada satu pun dari lima lini bukti yang menghasilkan edge ≥9,57 bps net pada horizon
15 menit–4 jam.** Yang konsisten muncul justru sebaliknya:

1. Sinyal jangka sangat pendek (15 menit–1 jam) punya edge **0,5–2 bps** — jauh di bawah biaya.
2. Sinyal yang gross-nya besar (session, cross-sectional, carry) berada di **horizon lebih
   panjang** dan **gagal uji robustness** saat diuji dengan benar.
3. Setiap kali hasil tampak bagus, penyebabnya **drift/beta**, bukan alpha.

**Implikasi untuk target 0,8%/30 jam:** target itu menuntut Sharpe 17 (risiko kecil) atau 3,4
(risiko 4%/window). Tidak ada bukti bahwa edge sebesar itu tersedia pada horizon ini — di
venue mana pun.

## Satu-satunya arah yang belum tertutup

Horizon **1–7 hari** (bukan 15 menit–4 jam):
- Cross-sectional momentum mingguan: +57,3 bps/minggu gross, tapi tidak signifikan.
- Data yang dibutuhkan: 2–3 tahun, bukan 30 hari — dan Binance menyediakannya.

Itu uji berikutnya yang layak, dan ia **tidak** akan menyelesaikan target 30 jam; ia
menyelesaikan pertanyaan "apakah ada edge sama sekali".

## Rekomendasi

| # | Tindakan |
|---|---|
| 1 | **Berhenti mencari sinyal 15 menit–4 jam.** Lima lini bukti sudah cukup. |
| 2 | Bila riset dilanjutkan: uji **cross-sectional momentum 1–7 hari** di Binance (2,8 th), pra-registrasi, kontrol drift wajib. |
| 3 | Jangan alokasikan modal ke keluarga mana pun yang diuji di sini. |
| 4 | Target 0,8%/30 jam perlu ditinjau ulang secara eksplisit bersama Mas Anas — bukan karena venue, tetapi karena tuntutan Sharpe-nya. |
