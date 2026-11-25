# MM — VERIFIKASI TIGA METODE (KOREKSI)

**Tanggal:** 25 Okt 2026 · **Data:** 817.000 record BBO+trade, jendela ~25 menit
**Status:** **TIDAK KONKLUSIF.** Angka "+0,787 bps" pada dokumen 20 menit **DITARIK.**

---

## 1. Tiga analisis, tiga jawaban

| Metode | Binance BTC | Binance ETH | Binance DOGE |
|---|---|---|---|
| Subagent (markout) | **−0,376** (t=−49,0) | **−0,843** (t=−82,0) | **−0,435** (t=−18,5) |
| Saya v1 (baseline mid +1s) | −0,154 | +0,128 | +0,444 |
| Saya v2 (baseline mid pra-trade) | −0,154 | +0,128 | +0,444 |

Untuk simbol yang sama, dalam data yang sama: **−0,38 sampai +0,44 bps**. Rentangnya
lebih besar dari efeknya. Artinya **efek tidak terpisah dari noise pengukuran.**

**Penyebab utama:** baseline mid. Jika mid diambil setelah fill (mid +1s), pergerakan
yang justru merupakan adverse selection sudah "hilang" sebelum diukur → hasil terlalu optimis.

## 2. Kesalahan statistik yang lebih besar: t membengkak karena overlap

Window drift 10 detik pada trade yang berurutan **saling bertumpuk**. Ribuan trade
dalam 25 menit bukan ribuan observasi independen — maksimum ≈ **150 blok independen**
(1500 s / 10 s).

Hasil agregasi blok 10 detik:

| Venue | Simbol | Mean net | t naif | **t blok** | Putusan |
|---|---|---|---|---|---|
| Binance | BTC | −0,078 | −12,81 | **−2,62** | negatif, lemah |
| Binance | DOGE | +0,473 | +13,02 | **+7,06** | positif |
| Binance | ETH | −0,005 | **+8,16** | **−0,13** | **tanda berbalik** |
| Binance | SOL | +0,253 | +3,89 | **+4,33** | positif |
| Hyperliquid | BTC | +0,055 | +3,58 | +1,40 | tidak signifikan |
| Hyperliquid | ETH | +0,193 | +1,96 | +2,61 | lemah |
| Hyperliquid | SOL | +0,380 | +1,50 | +4,74 | positif |
| Aster | BTC | −0,026 | −0,98 | −0,29 | tidak signifikan |
| Aster | ETH | +0,104 | +1,68 | +0,68 | tidak signifikan |

**Contoh paling instruktif: Binance ETH.** t naif **+8,16** ("sangat signifikan positif")
menjadi **−0,13** setelah clustering. Pelajaran: jangan pernah memakai t naif pada
data microstructure bertumpuk.

## 3. Mengapa tetap tidak layak meski positif

Ambil kasus terbaik yang lolos (Binance DOGE, +0,473 bps/RT):

| Kebutuhan target 0,8% / 72 jam | Nilai |
|---|---|
| Round-trip | **170** (1 tiap 25 menit) |
| Fill (2 leg) | **340 fill** |
| Volume notional ($243) | **$41.300** |
| sd inventory 1 jam (DOGE ~6,3%/30j) | **≈110 bps** |
| **Rasio risiko : capture** | **≈230 : 1** |

Satu gerakan adverse 110 bps menghapus **230 round-trip**. Tanpa kontrol inventory
sub-detik, satu posisi yang tertahan beberapa menit membalik seluruh keuntungan.

## 4. Bukti eksternal — penentu

**Daru Finance 2026** (9.983 coin-days, 125,8 juta fill simulasi): net pre-fee
Bybit **−0,839**, Binance **−0,391**, Hyperliquid **−0,458** bps. Break-even
rebate 0,29 bps → domain MM institusional, bukan retail.

**Albers dkk. 2025 (arXiv 2502.18625)** — sudah saya verifikasi langsung: eksperimen
trading live di Binance BTC perp, menyimpulkan strategi maker umum
*"highly unprofitable"*; antrean belakang 13× lebih buruk dari depan
(−0,775 vs −0,058 bps menurut pembacaan subagent).

Keduanya konsisten dengan pengukuran subagent (12/12 negatif) dan **bertentangan
dengan estimasi trade-level saya**. Penyebab bias saya: mid BBO bisa basi hingga
~1 detik, sehingga capture terdorong ke atas.

## 5. Putusan (final)

1. **Klaim "+0,787 bps" DITARIK** — artefak baseline.
2. **MM retail TIDAK LAYAK.** Tiga sumber independen: pengukuran 25 menit (12/12
   negatif), Daru (9.983 coin-days), Albers (eksperimen live). Estimasi saya yang
   positif tidak terdukung bukti luar.
3. **Nol alokasi modal.**
4. Bahkan bila net +0,5 bps: butuh **170 RT/72 jam** dengan rasio risiko
   inventory **230 : 1**.

## 6. Program insentif — tidak ada yang mendekati target

Target 0,8% per 30 jam = **233,6% APR**.

| Program | APR terukur | bps/30 jam | Layak |
|---|---|---|---|
| Funding carry delta-neutral | ~9,7% | **3,32** | satu-satunya riil |
| HLP vault | 4,5% | 1,54 | parkir kas saja |
| SoPoints / Aster points | tak dapat dihitung | n/a | spekulasi murni |
| Binance VIP1 | butuh 5 BNB + $5 jt/30 hari | — | mustahil |
| Aster/HL/SoDEX rebate | 0 untuk retail | — | tidak terjangkau |

**Implikasi:** jalur non-directional maksimal **≈3,3 bps/30 jam = 4% dari target**.
Sisa 96% harus datang dari alpha directional — yang sudah diuji 1.080 kali tanpa
satu pun lolos BH.

## 7. Yang saya pertahankan dari dokumen lama

Satu hal masih benar: **adverse selection SoDEX (111 bps) jauh lebih ekstrem**
daripada venue besar — masalahnya spesifik venue, bukan universal.
