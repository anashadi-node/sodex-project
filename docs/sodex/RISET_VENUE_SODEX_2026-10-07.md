# RISET VENUE SODEX — Laporan Riset Fundamental

**Divisi Riset Anantara Sakti · 7 Oktober 2026**
**Pertanyaan:** Cara, strategi, metode, atau mode apa yang **sangat cocok dan akurat** untuk Venue Market SoDEX, sesuai Target Utama divisi project SoDEX?

**Ringkasan satu baris:** Kami mengukur venue ini dari dalam (fee, spread, likuiditas, struktur korelasi, panjang data), menguji **60 hipotesis lintas-seksi** pada tiga panel (Binance 248 simbol ±6 tahun sebagai jaring daya uji; SoDEX 95 simbol × 361 hari; SoDEX 95 simbol × 8.533 jam untuk horizon yang benar-benar venue-matched), dan menemukan bahwa **penyumbat utama bukanlah ide strategi — melainkan panjang bukti, breadth venue, likuiditas, dan lantai biaya.** Tidak ada mesin yang lulus. Kami laporkan apa adanya.

> **ERRATUM 2026-10-07 — bug annualisasi panel 1 jam (ditemukan saat menyiapkan laporan ke divisi project SoDEX).**
> Skrip `scripts/research/xsec_mech_study.py` mengannualisasi Sharpe dengan `per_year = 365/hold`, padahal loop backtest
> melangkah **`hold` bar** — untuk panel **1 jam** ini men-understate S_ann sebesar **√24 = 4,899×**. Sudah diperbaiki
> (annualisasi kini ikut durasi bar: 1d → 365, 1h → 8760 periode/tahun) dan **ketiga panel dijalankan ulang**.
> Hasil verifikasi: panel **1 hari tidak berubah sama sekali** (rasio 1,000 pada seluruh 42 hasil); panel **1 jam naik tepat 4,899×**.
> **Verdict tidak berubah: 0 lulus** (24 Binance 1d · 18 SoDEX 1d · 18 SoDEX 1h). Registry trial tetap 40 — ini koreksi metrik,
> bukan trial baru. Artefak lama disimpan di `reports/sodex/archive_bug_annualisasi_20261007/`. Angka panel 1 jam di bawah sudah dikoreksi,
> dan Bab M.2 bertambah satu kandidat terukur yang sebelumnya tersembunyi oleh bug ini.

---

## A. Ringkasan Eksekutif

**Lima temuan, semuanya berangka:**

| # | Temuan | Angka |
|---|---|---|
| A1 | **Panjang bukti adalah penyumbat nomor satu.** Untuk membuktikan satu mesin kelas-target (Sharpe tahunan ≥ 2,3) di dalam keluarga 21 mesin seperti sensus D14, dibutuhkan **274 jendela = 549 hari**. SoDEX hanya punya **361 hari = 180 jendela**. Secara matematis terkunci. | 274 vs 180 window |
| A2 | **Plafon struktur venue:** 95 simbol SoDEX, tetapi korelasi antar-aset **0,33** dan faktor pasar pertama (PC1) menjelaskan **38,5%** varians. Jumlah taruhan independen (N_eff) hanya **6,1 dari 75 simbol**. | N_eff 6,1 |
| A3 | **Lantai biaya + plafon likuiditas:** biaya realistis sekali jalan-putar **9,71 bps**; **BTC+ETH = 87,8%** dari total volume **$204,7 juta/hari**; hanya **8 simbol** yang punya volume ≥ $1 juta/hari. N_eff likuiditas = **2,5 simbol**. | 9,71 bps · 87,8% |
| A4 | **Uji 60 hipotesis lintas-seksi → 0 lulus.** Panel panjang Binance (248 simbol, ±6 tahun, 24 uji): **nol** lulus, yang signifikan justru **8 bertanda terbalik** (range-position t = −5,10, p < 0,0001). SoDEX 1 hari (18 uji): **nol**. SoDEX 1 jam — horizon yang benar-benar venue-matched (18 uji): **nol**, meski tiga mekanisme signifikan secara mentah (t sampai 4,71). | 0/60 |
| A4b | **Bahkan yang terkuat tidak sampai.** Setelah semua koreksi biaya dan tanda: kandidat terkuat **≈+2,29** (reversal 21 jam, hold 48 jam, SoDEX 1 jam — *estimasi arah-balik, belum uji beku*) dan **+2,06** (Binance, momentum rentang, hold 5 hari) — dua-duanya **< 2,30** dan **gagal pada biaya 2×**. Di venue target sendiri, mekanisme ber-tanda-prarreg yang terbaik hanya **+1,62**. | +2,29 & +2,06 vs 2,30 |
| A5 | **Jarak ke target terdokumentasi secara kuantitatif.** IC yang dibutuhkan **0,069**; IC terbaik yang terukur **0,036** → kurang **1,91×**. Mesin venue-SoDEX terbaik yang terukur Sharpe **0,75**; syarat **2,30** → kurang **3,1×**. | 1,91× · 3,1× |

**Satu temuan yang kami kejar sampai akhir — dan hasilnya GAGAL.** Sinyal *range-position* 20 hari **berbalik arah** dari yang kami praregistrasikan: ia **momentum**, bukan reversal. Di Binance ia sangat kuat (t = 5,10; 3/3 segmen waktu sepakat, S_ann +1,51 pada H=2 hari dan +2,06 pada H=5 hari). Kami memperlakukannya sebagai hipotesis baru (PRAREG-2, dibekukan sebelum diuji) dan mengujinya dengan pemisahan waktu:

| Uji | Hasil | Ambang | Lulus? |
|---|---|---|---|
| Binance IS (60% periode) | S_ann 1,44 · t=2,54 | — | (pembentuk tanda) |
| **Binance OOS (40% periode)** | **S_ann 1,75** · t=2,80 · 3/3 segmen | **≥ 2,30** | **TIDAK** |
| OOS pada biaya 2× | S_ann 1,34 | ≥ 1,80 | TIDAK |
| **Replikasi SoDEX 1 jam (venue-matched)** | **S_ann −0,81 · t = −4,36** | tanda sama | **TIDAK — tanda BERLAWANAN** |
| Replikasi SoDEX 1 hari | S_ann +0,93 · t=0,96 | tanda sama | tanda sama, tapi tidak signifikan |

**Kesimpulan: kandidat ini ditolak.** Ia tidak mencapai Sharpe OOS, dan yang lebih penting, ia **berbalik tanda di horizon venue-matched** (pada bar jam, reversal yang menang, bukan momentum). Tidak ada yang masuk portofolio dari riset ini.

**Konsekuensi praktis:** menambah strategi, menambah model, atau menaikkan leverage **tidak akan menutup jarak ini**. Yang menutupnya adalah salah satu dari tiga hal: **(i)** memperbesar IC, **(ii)** memperlebar breadth efektif, atau **(iii)** memperpanjang jam bukti. Bab Q membahas ketiganya secara berurutan.

---

## B. Amanat, Target, dan Aturan Main

### B.1 Target (HARGA MATI — tidak boleh diubah)

| Parameter | Nilai |
|---|---|
| PnL bersih rata-rata | **0,8% dari TOTAL dana wallet per 48 jam** |
| Bentuk pencapaian | **6–8 mesin**, korelasi antar-mesin **ρ ≤ 0,10** |
| Syarat tiap mesin | Sharpe tahunan **≥ 2,3** |
| Leverage | **DILARANG** menaikkan leverage untuk mengejar target |
| Modal | TOTAL wallet (spot + perps), bukan ukuran per-trade |

### B.2 Dari target ke angka yang harus dibuktikan

Aritmetika ini kami hitung ulang dari nol, tidak kami warisi:

1. Sharpe portofolio yang dibutuhkan = `0,8% ÷ 2,35% × √182,5` = **4,60 /tahun**
   (dengan asumsi σ portofolio 2,35% per 48 jam dari D14).
2. Pengali diversifikasi dengan 6 mesin dan ρ = 0,10 = `√(6 ÷ (1 + 5×0,10))` = **2,00×**
3. Karena itu syarat tiap mesin = `4,60 ÷ 2,00` = **2,30 /tahun** = **0,170 per 48 jam**
4. Artinya rata-rata tiap mesin = `0,170 × 2,35%` = **0,400% bersih per 48 jam**

**Analogi:** target ini seperti meminta enam orang pelari, masing-masing harus lari 400 m dalam 48 detik, dan mereka tidak boleh saling menyeret. Permasalahannya bukan "apakah ada pelari" — tetapi bahwa **kita baru melatih mereka selama satu tahun**, sedangkan untuk yakin bahwa catatan waktunya bukan keberuntungan, kita butuh **satu setengah tahun** pengukuran.

### B.3 Sepuluh aturan keras yang kami patuhi (`PERINTAH_1_SoDEX.md`)

| # | Aturan | Kepatuhan dalam riset ini |
|---|---|---|
| 1 | Evaluasi PnL historis Wajib beta-netral | Return forward di-demean lintas-seksi (dollar-neutral + market-neutral) |
| 2 | Biaya diuji 1× DAN 2× | Dilaporkan **3 tingkat**: 8,00 · 9,71 (realistis) · 16,00 bps |
| 3 | Kontrol negatif wajib; kalau lolos → uji terlalu mudah | Kontrol diacak dalam baris; **dinilai pada bruto** (lihat Bab P.3) |
| 4 | Jendela < 6 bulan sah untuk eksekusi, tidak sah untuk alpha | Panel SoDEX 1 tahun; setiap penilaian alpha ditandai eksploratori |
| 5 | t-statistik gabungan lintas aset jangan dipakai | t dihitung pada **deret waktu portofolio** dengan Newey-West |
| 6 | Dilarang menaikkan leverage | Tidak ada usulan leverage di mana pun |
| 7 | Dilarang mengubah angka target | Target 0,8%/48 jam dipakai apa adanya sebagai pembanding |
| 8 | Dilarang menyembunyikan trial yang gagal | **Ke-42 uji dilaporkan**, termasuk yang memalukan (Bab P) |
| 9 | Modal nyata tetap FROZEN | Tidak ada order; seluruh riset read-only |
| 10 | LLM/agent tidak boleh mengalahkan Risk Engine | Tidak ada usulan bypass gate |

---

## C. Apa yang Sudah Dicoba Sebelum Riset Ini

Kami tidak memulai dari nol. Kami membaca ulang sensus D14 (`data/sodex_edge_census.json`, dijalankan 7-Okt-2026 02:07) — 21 mesin, verdict **`TIDAK-ADA-MESIN-LULUS`**.

| mesin | Sharpe tahunan | n jendela | p terburuk | seg+ | tanda asal |
|---|---|---|---|---|---|
| `mv_funding` | **7,76** | 16 | 0,036 | 3/3 | CARRY (lintas-venue) |
| `hl_replay` | 7,75 | 45 | 0,000 | 2/3 | REPLAY (Hyperliquid) |
| `spot_swing_cex` | 3,50 | 15 | 0,402 | 2/3 | — |
| `twoway` | 2,42 | 31 | 0,345 | 2/3 | — |
| `realwide` | 1,98 | 32 | 0,448 | 1/3 | — |
| `micro_live` (uang nyata) | −13,77 | 3 | — | 0/3 | UANG-NYATA |

**Tiga pembacaan yang mengubah arah riset kami:**

1. **Tiga mesin punya Sharpe titik di atas 2,3 — tak satu pun dapat dibedakan dari nol** (p = 0,036…0,448). Ini pola klasik kurang daya uji, bukan pola tanpa edge.
2. **n jendela maksimum di seluruh keluarga hanya 45, dari 180 yang tersedia.** Mesin-mesin itu memakai 25% daya yang ada.
3. **Dua mesin Sharpe tertinggi BUKAN bukti venue SoDEX.** `hl_replay` berasal dari jurnal replay Hyperliquid; `mv_funding` adalah carry lintas-venue (HL/Binance/Bybit/OKX/dYdX) — sekaligus berisiko berkorelasi dengan divisi HL-Harvest. Yang benar-benar venue SoDEX (realwide, twoway, spot_swing) semuanya p = 0,34–0,45.

Instrumentasi sensus juga terverifikasi sehat: `instrument_ok = true`, FPR instrumen 0,0525 (bersama 0,015), dan kedua kontrol negatifnya gagal dengan benar.

---

## D. Peta Venue SoDEX (Diukur Hari Ini)

Kami menarik dan mengukur ulang universe SoDEX dari `mainnet-gw.sodex.dev` — 95 simbol berdata, 84 di antaranya punya riwayat ≥ 120 hari.

| Metrik | Nilai |
|---|---|
| Jumlah simbol terdaftar | **95** (99 berkas; 4 kosong) |
| Komposisi | **75 kripto + 20 ekuitas/RWA** |
| Panjang riwayat maksimum | **361 hari** (BTC, mulai 12-Okt-2025) |
| Total notional | **$204,7 juta/hari** |
| Median volatilitas tahunan — kripto | **86,4%** |
| Median volatilitas tahunan — ekuitas/RWA | **61,6%** |

**Simbol paling likuid:**

| Simbol | Kelas | Vol tahunan | Notional/hari |
|---|---|---|---|
| BTC-USD | kripto | 44,8% | $109,8 juta |
| ETH-USD | kripto | 61,7% | $69,9 juta |
| ZEC-USD | kripto | 130,0% | $6,8 juta |
| SOL-USD | kripto | 64,7% | $3,5 juta |
| XAUT-USD | RWA (emas) | 30,0% | $2,3 juta |
| SUI-USD | kripto | 82,8% | $1,5 juta |

**Analogi:** venue ini seperti pasar malam besar dengan 95 kios. Tapi 88 dari 100 pembeli hanya mendatangi **dua kios pertama**. Sisa 93 kios kadang tidak dilewati siapa pun sepanjang hari — MSFT-USD hanya $5,2 ribu/hari, PLTR-USD $5,7 ribu/hari, bahkan ada yang $0.

---

## E. Ekonomi Venue: Fee, Spread, dan Mengapa LP Pasif Bukan Jalan

### E.1 Biaya terverifikasi (bukan asumsi)

| Komponen | Nilai | Sumber |
|---|---|---|
| Fee taker | **4,00 bps per sisi** | `scripts/sodex_harness_reeval.py` → `SODEX_FEE_BPS = 8.0`; di-assert di `tests/test_sodex_regime_gate_study.py` |
| Round-trip fee | **8,00 bps** | 2 × 4,00 |
| Spread median | **1,71 bps** | `AUDIT_BIAYA_AKUN_2026-10-05.md`, 77 simbol |
| Slippage (½ spread) | 0,86 bps per sisi | turunan |
| **Round-trip realistis** | **9,71 bps** | 8,00 + 2×0,86 |

### E.2 Sensus spread: mengapa market-making pasif bukan jalan

Dari 92 simbol yang bukunya tersampel:

- **67 dari 92 simbol punya spread < 2,4 bps** → LP pasif yang membayar maker 1,2 bps per sisi **rugi secara struktural**.
- Hanya **25 simbol ber-edge** (`spread − 2×1,2 bps > 0`).
- 25 simbol itu hanya menampung **0,83% dari total volume (≈ $1,64 juta/hari)**.

**Kesimpulan E:** jalur LP/market-making pasif **tidak dapat menampung alokasi** dan tidak boleh dijadikan mesin utama. Ini menutup satu dari sedikit jalur yang secara alami punya Sharpe tinggi di venue kecil.

---

## F. Empat Penyumbat — Peta Besar

```
        Sasaran: 0,8%/48 jam  →  Sharpe portofolio 4,60
                                  │
        ┌──────────────┬──────────┴─────────┬──────────────────┐
        │              │                    │                  │
   [G] PANJANG     [H] BREADTH         [I] LANTAI         [J] LIKUIDITAS
       BUKTI            VENUE              BIAYA              TERKONSENTRASI
   274 window        N_eff = 6,1        9,71 bps RT         top-2 = 87,8%
   vs 180 ada        dari 75 simbol      = 24% syarat      N_eff likuiditas
   → TERKUNCI        → IC harus 0,069    mean mesin         = 2,5 simbol
                                          → IC impas 0,019
```

Empat penyumbat ini **independen**. Menutup salah satu saja tidak cukup; tiga di antaranya saling mengunci (Bab Q).

---

## G. Penyumbat 1 — Panjang Bukti (Power)

### G.1 Aritmetika

Karena syarat mesin = Sharpe 0,170 per 48 jam, jumlah jendela yang harus dikumpulkan agar t-statistik melewati ambang adalah:

| Skenario | t kritis | Jendela dibutuhkan | Hari dibutuhkan |
|---|---|---|---|
| 1 mesin, tanpa koreksi (p < 0,05) | 1,96 | **133** | 265 |
| 1 mesin, 2 sisi (p < 0,025) | 2,24 | 174 | 348 |
| Keluarga 5, BH q = 0,10 | 2,33 | 187 | 375 |
| Keluarga 10, BH q = 0,10 | 2,58 | 230 | 459 |
| **Keluarga 21 (seperti D14), BH q = 0,10** | **2,82** | **274** | **549** |

**Tersedia di SoDEX: 361 hari = 180 jendela.**

### G.2 Artinya apa

- **Keluarga 21 tidak mungkin dibuktikan hari ini** — butuh 549 hari, ada 361.
- Bahkan **satu mesin tanpa koreksi apa pun** butuh 265 hari, dan margin kita tipis (361 − 265 = 96 hari, ± 27%).
- Kita butuh **6–8 mesin**. Dengan 8 mesin tanpa koreksi pun (t = 1,96), kita butuh 8 × 133 = **1.064 jendela setara** — kecuali mesin-mesin itu diuji serentak dengan koreksi, yang justru memperbesar ambang.

**Analogi:** ini seperti menilai apakah seorang penembak jitu memang jitu, padahal ia baru menembak 45 kali dan kita butuh 274 tembakan untuk yakin. Bukan tembakannya yang salah — **kita kurang peluru waktu.**

### G.3 Pengecualian penting (jalan keluar yang sah)

Ada satu cara melegakan penyumbat ini **tanpa menunggu**: **jendela paralel lintas aset**. Satu portofolio lintas-seksi selalu berada di pasar, sehingga menghasilkan ± 182 jendela per tahun dari **satu** mesin, bukan 15–45 seperti mesin trade-diskrit. Inilah alasan kami memilih keluarga lintas-seksi untuk diuji (Bab K).

---

## H. Penyumbat 2 — Plafon Struktur Venue (Breadth & Korelasi)

### H.1 Hasil pengukuran

| Jendela | Simbol | ρ rata-rata | ρ median | PC1 | **N_eff** | Bagian idiosinkratik |
|---|---|---|---|---|---|---|
| 90 hari (95% tersedia) | 82 | 0,333 | 0,311 | 38,4% | **5,87** | 66,7% |
| 180 hari (95%) | 74 | 0,333 | 0,316 | 38,5% | **6,11** | 66,7% |
| 180 hari (60%) | 77 | 0,302 | 0,283 | 36,2% | 6,67 | 69,8% |
| 365 hari (95%) | 14 | 0,640 | 0,645 | 68,2% | 2,10 | 36,0% |
| 365 hari (60%) | 67 | 0,380 | 0,360 | 42,1% | 5,27 | 62,0% |

**Catatan penting:** baris 365 hari dengan N_eff 2,10 adalah **artefak**, bukan fakta venue — hanya 14 simbol tertua (para mayor) yang punya riwayat penuh, dan para mayor memang paling saling berkorelasi. Angka yang jujur untuk venue ini adalah **N_eff ≈ 6 pada jendela 3–6 bulan**.

### H.2 Anggaran IC — Hukum Fundamental

Hukum Fundamental: `Sharpe = IC × √breadth`, dengan `breadth = N_eff × frekuensi`.

| N_eff | breadth (H=48 jam) | **IC dibutuhkan untuk Sharpe 2,3** | vs IC terukur 0,036 |
|---|---|---|---|
| **6,1 (venue terukur)** | 1.113 | **0,0689** | **0,52×** |
| 20 | 3.650 | 0,0381 | 0,94× |
| 40 | 7.300 | 0,0270 | 1,34× |
| 76 | 13.870 | 0,0196 | 1,84× |

### H.3 Dua kesalahpahaman yang perlu dikoreksi

**(a) "Aset berkorelasi berarti mesin berkorelasi."** Tidak selalu. Untuk mesin **dollar-neutral**, korelasi antar-mesin ditentukan oleh **tumpang tindih bobot**, bukan korelasi asetnya — komponen pasar saling meniadakan di selisih long-short. Jadi syarat ρ ≤ 0,10 **bukan mustahil** secara matematis. Tetapi korelasi aset 0,33 tetap memangkas **kolam dispersi** yang bisa dipanen: hanya **67%** varians yang idiosinkratik — 33% adalah faktor pasar bersama yang tak bisa dipanen lintas-seksi tanpa menambah risiko arah.

**(b) "Tinggal tambah mesin."** Pengali diversifikasi punya **plafon**: dengan ρ = 0,10 plafonnya 3,16×; dengan ρ = 0,30 → 1,83×; dengan ρ = 0,61 → 1,29×. Mesin ke-7, ke-8, ke-20 tidak menambah apa pun begitu plafon tercapai.

| ρ antar-mesin | pengali n=6 | plafon (n→∞) | Sharpe mesin yang dibutuhkan untuk portofolio 4,60 |
|---|---|---|---|
| 0,10 | 2,00× | 3,16× | **2,30** |
| 0,30 | 1,55× | 1,83× | 2,97 |
| 0,61 | 1,22× | 1,29× | 3,77 |

**Inilah sebabnya syarat ρ ≤ 0,10 di dalam target bukan hiasan — ia yang menentukan apakah syarat Sharpe 2,3 cukup atau harus jauh lebih tinggi.**

---

## I. Penyumbat 3 — Lantai Biaya

Biaya tidak bisa dihilangkan, hanya bisa dilawan dengan edge yang lebih besar atau frekuensi yang lebih rendah. Dua angka yang tidak bisa ditawar:

| Ambang IC (break-even) di SoDEX 1d | H = 48 jam | H = 5 hari |
|---|---|---|
| Biaya 8,00 bps RT | 0,0159 | 0,0101 |
| **Biaya realistis 9,71 bps RT** | **0,0193** | 0,0123 |
| Biaya 16,00 bps RT (2×) | 0,0318 | 0,0203 |
| Setelah koreksi turnover 1,30 | 0,0125 | 0,0080 |

Dan untuk **mencapai target** (bukan sekadar impas), pada H = 48 jam dibutuhkan IC **0,0689**.

```
IC  0,0193 ──── impas (biaya realistis)
IC  0,0360 ──── terbaik yang terukur hari ini  → untung tipis, Sharpe ≈ 0,7
IC  0,0689 ──── syarat target Sharpe 2,3       → 1,91× di atas yang terukur
```

**Analogi:** bayangkan pedagang yang untung Rp 36.000 per putaran, sementara ongkos kirimnya Rp 19.300. Ia memang untung. Tetapi untuk membiayai target perusahaan ia perlu untung Rp 69.000 per putaran — dan itu bukan dicapai dengan mengirim lebih sering, karena setiap pengiriman tambahan menambah ongkos.

---

## J. Penyumbat 4 — Likuiditas Terkonsentrasi

| Ukuran konsentrasi | Nilai |
|---|---|
| Total notional | $204,7 juta/hari |
| Top-2 (BTC+ETH) | **87,8%** |
| Top-5 | 93,9% |
| Top-10 | 96,8% |
| Top-20 | 99,4% |
| HHI | 0,406 (merata = 0,011) |
| **N_eff likuiditas** | **2,5 simbol** dari 94 |
| Simbol ≥ $1 juta/hari | **8** |
| Simbol ≥ $100 ribu/hari | **20** |
| Simbol ≥ $10 ribu/hari | 63 |

**Benturan mematikan:** strategi lintas-seksi butuh **banyak nama** agar punya breadth. Tetapi nama-nama yang memberi diversifikasi justru **nama-nama yang tidak bisa ditransaksikan**. N_eff return (6,1) dan N_eff likuiditas (2,5) tidak bertempat di simbol yang sama.

**Perhitungan jujur:** kalau kita membatasi diri pada **20 simbol likuid** (≥ $100 ribu/hari), breadth = 20 × 182 = 3.640 → √breadth = 60,3 → IC yang dibutuhkan = **0,0381** — **hampir persis IC yang terukur (0,036).** Artinya: target ini **secara aritmetika berada di ambang jangkauan**, tetapi hanya jika (a) IC 0,036 itu nyata dan stabil, (b) kedalaman 20 nama itu nyata, (c) hold 48 jam, dan (d) eksekusi persis di spread median. **Keempatnya belum terbukti.**

---

## K. Uji 60 Hipotesis Lintas-Seksi — Metode

### K.1 Mengapa lintas-seksi

Mesin trade-diskrit mengumpulkan 15–45 jendela (Bab G). Portofolio lintas-seksi yang selalu berada di pasar mengumpulkan ± 182 jendela per tahun dari satu mesin. Ini satu-satunya tuas daya uji yang bisa dipakai **tanpa menunggu dan tanpa data baru**.

### K.2 Cara kerja (dibekukan sebelum dijalankan)

Berkas: `docs/sodex/PRAREG_PANEL_PANJANG_2026-10-07.md` (dibekukan sebelum satu angka pun dihitung).

```
sinyal   : 12 mekanisme (lihat tabel) — diranking lintas-seksi
bobot    : dollar-neutral, SUM|w| = 1
return   : forward return DI-DEMEAN lintas-seksi  → beta-netral
hold     : H = 2 hari (±48 jam) dan H = 5 hari
biaya    : 8,00 bps (1×) · 9,71 bps (realistis) · 16,00 bps (2×)
kontrol  : sinyal diacak dalam baris, konstruksi identik
statistik: t Newey-West pada deret waktu portofolio (bukan t gabungan lintas aset)
koreksi  : Benjamini-Hochberg q = 0,10 atas 24 trial
lulus    : S_ann ≥ 2,30 (1×) DAN ≥ 1,80 (2×) DAN BH lolos DAN 3/3 segmen positif
```

### K.3 Dua belas mekanisme

| # | Kode | Sinyal | Tanda prarreg | Dasar pemikiran |
|---|---|---|---|---|
| 1 | REV_L1 | return 1 periode | − (reversal) | reversal jangka pendek |
| 2 | REV_L3 | return 3 periode | − | reversal jangka pendek |
| 3 | REV_VOL | return ÷ vol 20p | − | reversal ternormalisasi |
| 4 | REV_IDIO | residual vs pasar (β 60p) | − | reversal idiosinkratik |
| 5 | MOM_L21 | return 21 periode | + | momentum menengah |
| 6 | MOM_L63 | return 63 periode | + | momentum menengah |
| 7 | LTREV_L180 | return 180 periode | − | reversal jangka panjang |
| 8 | RANGEPOS | posisi dalam rentang 20p | − | pembalikan posisi |
| 9 | VOLSHOCK | z(volume) × tanda(return) | − | guncangan volume |
| 10 | MAXFX | rata-rata 5 return terbesar | − | efek lotre (Bali dkk.) |
| 11 | CARRY_FR | funding 8 jam terakhir | − | long funding rendah |
| 12 | BASIS | premi mark−index | − | premi derivatif |

### K.4 Panel uji

| Panel | Simbol | Bar | Rentang | Peran |
|---|---|---|---|---|
| **Binance USDT-perp** | **248** | 371–2.587 | Sep-2019 → Okt-2026 | **jaring daya uji** — panjang riwayat, untuk membedakan "tidak ada edge" dari "kurang data" |
| **SoDEX 1d** | 95 | 361 | Okt-2025 → Okt-2026 | **venue target** — replikasi, bukan penemuan |
| **SoDEX 1h** | 95 | 8.533 | Okt-2025 → Okt-2026 | **venue target, horizon venue-matched** (hold 24 jam & 48 jam) |

**Peringatan metodologis yang kami patuhi:** Binance dipakai **hanya** untuk menguji *mekanisme*, bukan untuk mengklaim mesin SoDEX. Setiap mekanisme yang lolos di Binance **wajib** lolos replikasi di SoDEX (tanda sama, |IC| ≥ ½). Pelajaran H5 sebelumnya: efek breakout di SoDEX **berbalik arah** di Binance — efek lintas venue **tidak otomatis** bertahan.

---

## L. Hasil Uji — Panel Panjang Binance (248 simbol, ±6 tahun)

**Verdict: 0 dari 24 lulus.** Instrumentasi diverifikasi lebih dahulu dengan uji asap: sinyal reversal buatan sebesar 0,4%/hari **terdeteksi** (S_ann 5,33; t = 5,50; p < 0,0001; 3/3 segmen) dan kontrol acaknya bersih (t = −0,73).

**Delapan trial signifikan setelah koreksi BH — SEMUANYA BERNEGATIF (tanda terbalik dari yang kami praregistrasikan):**

| trial | neto (bps) | sd | S_ann | t_NW | p | BH | seg+ |
|---|---|---|---|---|---|---|---|
| **RANGEPOS_H2** | −23,62 | 150 | **−2,13** | **−5,10** | <0,0001 | ✓ | **0/3** |
| RANGEPOS_H5 | −45,10 | 235 | −1,64 | −3,98 | 0,0001 | ✓ | 1/3 |
| REV_L3_H5 | −41,72 | 241 | −1,48 | −3,71 | 0,0002 | ✓ | 0/3 |
| REV_L3_H2 | −17,01 | 159 | −1,44 | −3,49 | 0,0005 | ✓ | 0/3 |
| REV_VOL_H2 | −12,72 | 140 | −1,23 | −3,20 | 0,0014 | ✓ | 0/3 |
| REV_L1_H5 | −33,07 | 234 | −1,21 | −2,71 | 0,0068 | ✓ | 0/3 |
| REV_VOL_H5 | −28,99 | 220 | −1,13 | −2,59 | 0,0095 | ✓ | 0/3 |
| REV_IDIO_H5 | −26,09 | 211 | −1,06 | −2,35 | 0,0186 | ✓ | 1/3 |
| MAXFX_H2 | −11,08 | 169 | −0,88 | −2,17 | 0,0297 | ✓ | 0/3 |

**Tidak ada satu pun trial yang signifikan POSITIF.**

### L.1 Apa artinya — dan apa yang BUKAN artinya

**Yang bukan artinya:** kita tidak boleh sekadar membalik tanda lalu mengklaim edge. Sebagian nilai negatif itu murni biaya, bukan arah. Kami uraikan bruto dari neto untuk memisahkannya:

| trial | bruto (bps) | biaya (bps) | bruto negatif? | tafsir |
|---|---|---|---|---|
| REV_L1_H2 | **+0,02** | 6,52 | tidak | edge bruto **nol**; rugi murni biaya |
| REV_VOL_H2 | −6,12 | 6,60 | hampir | ≈ biaya |
| MAXFX_H2 | −9,83 | 1,25 | ya | arah terbalik lemah |
| **RANGEPOS_H2** | **−20,22** | 3,40 | **ya, 6× biaya** | **arah terbalik kuat** |
| REV_L3_H5 | −35,21 | 6,51 | ya, 5× biaya | arah terbalik kuat |

**Kesimpulan L yang jujur:** pada perps Binance, keluarga **reversal lintas-seksi jangka pendek TIDAK bertahan setelah biaya**. Dua yang benar-benar bertahan berbalik arah adalah **range-position** dan **reversal 3 hari pada hold 5 hari** — dan keduanya, setelah dikoreksi biaya dengan benar, tetap di bawah ambang 2,30.

---

## M. Hasil Uji — Replikasi SoDEX 1 Hari (95 simbol, 361 hari)

**Verdict: 0 dari 18 lulus** (4 trial dilewati karena datanya tidak ada di venue: VOLSHOCK 1d, CARRY_FR, BASIS — SoDEX tidak menyediakan histori funding/basis, hanya prediksi 5 hari ke depan).

| trial | neto (bps) | sd | S_ann | t_NW | p | seg+ |
|---|---|---|---|---|---|---|
| REV_L1_H2 | +7,58 | 137 | **0,75** | 0,82 | 0,415 | 3 |
| REV_IDIO_H2 | +6,32 | 113 | 0,75 | 0,66 | 0,506 | 2 |
| LTREV_L180_H2 | +4,43 | 113 | 0,53 | 0,32 | 0,745 | — |
| MOM_L63_H2 | +2,74 | 132 | 0,28 | 0,26 | 0,797 | 2 |
| REV_VOL_H2 | +2,98 | 107 | 0,38 | 0,36 | 0,718 | 2 |
| LTREV_L180_H5 | +20,51 | 219 | 0,80 | 0,71 | 0,479 | — |
| RANGEPOS_H2 | −12,96 | 115 | −1,53 | −1,58 | 0,114 | 0 |
| MOM_L21_H5 | −20,75 | 252 | −0,70 | −0,57 | 0,567 | — |

**Terbaik yang benar-benar venue SoDEX: REV_L1_H2, Sharpe tahunan 0,75** — **3,1× di bawah syarat 2,30**, dan tidak signifikan (p = 0,415).

**Yang perlu diperhatikan:** RANGEPOS di SoDEX juga **negatif** (−12,96 bps, t = −1,58) — **tanda yang sama** dengan Binance. Signifikansinya lemah karena datanya hanya 1 tahun (n = 138 jendela), tetapi **arahnya konsisten lintas venue**. Ini satu-satunya benang yang layak ditarik (Bab N).

**Empat trial tidak bisa dijalankan di SoDEX, dan itu sendiri sebuah temuan:** collector funding SoDEX menyimpan **prediksi 5 hari ke depan**, bukan histori. Venue ini secara data belum bisa menguji strategi carry — padahal justru carry yang paling menjanjikan di sensus D14.

### M.2 SoDEX 1 jam — horizon yang benar-benar venue-matched

Uji ini yang paling relevan: jendela swing project SoDEX adalah **1–30 jam**, sementara bar harian hanyalah proksi kasar. Panel 1 jam baru selesai ditarik riset ini: **95 simbol × 8.533 bar** (± 356 hari jam-jaman, 12-Okt-2025 → 7-Okt-2026).

**Verdict: 0 dari 18 lulus** (4 dilewati karena data venue tidak ada).

| trial | neto (bps) | sd | S_ann | t_NW | p | BH | seg+ |
|---|---|---|---|---|---|---|---|
| **MOM_L21_H24** | −18,77 | 106 | **−3,38** | **−4,59** | <0,0001 | ✓ | 0/3 |
| **MOM_L21_H48** | −25,94 | 130 | **−2,70** | **−4,71** | <0,0001 | ✓ | 0/3 |
| **RANGEPOS_H48** | **+11,70** | 98 | **1,62** | **+2,31** | 0,021 | ✗ | **3/3** |
| RANGEPOS_H24 | +6,41 | 81 | 1,51 | +1,65 | 0,099 | ✗ | **3/3** |
| REV_IDIO_H48 | +6,77 | 108 | 0,85 | +1,39 | 0,165 | ✗ | 2/3 |
| MAXFX_H48 | −12,83 | 176 | −0,98 | −1,06 | 0,291 | ✗ | 1/3 |
| REV_L1_H48 | +3,46 | 128 | 0,37 | +0,44 | 0,657 | ✗ | 2/3 |

**Tiga hal yang berubah setelah uji ini:**

1. **Dua mekanisme signifikan sangat kuat (t = −4,59 dan −4,71, p < 0,0001)** — tetapi **bertanda terbalik** dari yang kami praregistrasikan. Artinya pada horizon 21 jam di SoDEX, sinyalnya adalah **reversal**, bukan momentum. Besar efeknya (biaya 1×): **S_ann −3,38 (H24)** dan **−2,70 (H48)**.
2. **`RANGEPOS_H48` justru SEPAKAT dengan prareg** di sini: tanda reversal positif, t = +2,31, dan **3/3 segmen waktu positif**. Tetapi ia **gagal koreksi BH** (ambangnya 0,0167 saat peringkat ke-3 dari 18; p-nya 0,021) dan Sharpe-nya **1,62** — 70% dari syarat. Ia juga **gagal kontrol negatif** (kontrol acak memberi t = −2,13, di atas ambang 2,0 yang kami tetapkan).
3. **Kesimpulan horizon:** tanda efek lintas-seksi **berbalik menurut horizon** — pada bar **jam** (20–21 bar ≈ 1 hari) arahnya **reversal**; pada bar **hari** (20 bar ≈ 20 hari) arahnya **momentum**. Ini pola yang dikenal di literatur dan konsisten di seluruh hasil kami.

**Satu kandidat terukur baru — estimasi arah-balik (REVERSAL 21 jam), BELUM uji beku:**

| varian (arah reversal) | neto 1× (bps) | S_ann 1× | neto 2× (bps) | S_ann 2× | t_NW | seg+ |
|---|---|---|---|---|---|---|
| **Reversal 21 jam · hold 48 jam** | **+15,58** | **≈ +2,29** | +10,40 | ≈ +1,53 | **+4,71** | **3/3** |
| Reversal 21 jam · hold 24 jam | +8,22 | ≈ +1,48 | +2,94 | ≈ +0,53 | +4,59 | **3/3** |

Tabel ini **estimasi aritmetik** dari hasil yang sudah ada (`neto_balik = −neto − 2×biaya`), **bukan** backtest beku yang baru dijalankan — simpangan baku belum tentu identik karena korelasi bruto↔biaya berubah saat tanda dibalik. Karena arah ini **dipilih setelah melihat data**, ia wajib masuk **prarreg baru yang dibekukan sebelum diuji** (PRAREG-3) dengan pemisahan IS/OOS. Bacaannya: kandidat terkuat **≈2,29 dari 2,30 pada biaya 1×, tetapi jatuh ke ≈1,53 pada biaya 2× (syarat 1,80)** — persis penyumbat "lantai biaya". Turnover 1,29 membuat tiap jendela 48 jam membayar ≈5,2 bps biaya (5,2 dari 20,8 bps bruto = 25%).

**Belum ada satu pun yang lulus penuh.** Mekanisme ber-tanda-prarreg di venue target hanya **0,93–1,62** (40–70% dari syarat 2,30); kandidat arah-balik terkuat ≈2,29 tetapi **gagal pada biaya 2×** dan belum diuji pemisahan waktu.

---

## N. Temuan Terkuat: Range-Position Berbalik Arah

### N.1 Apa yang terjadi

Kami praregistrasi `RANGEPOS` sebagai **reversal**: beli yang dekat dasar rentang 20 hari, jual yang dekat puncak. Data menolak tanda itu dengan sangat kuat:

- Binance H=2: t = **−5,10**, p < 0,0001, **0/3 segmen** positif (artinya arah sebaliknya positif di ketiga periode waktu).
- Binance H=5: t = −3,98, p = 0,0001.
- SoDEX H=2: t = −1,58 (tanda sama).

**Terjemahan:** posisi dalam rentang harga 20 hari adalah sinyal **momentum/kontinuasi** — nama yang mendekati puncaknya cenderung lanjut, bukan berbalik.

### N.2 Besarnya setelah biaya dihitung dengan benar

Kesalahan yang mudah dibuat: membalik tanda sinyal **tidak** membalik biaya. Turnover tetap sama. Jadi:

```
neto_dibalik = −(neto_asli + 2 × biaya)
```

| trial | neto asli | biaya | **neto dibalik** | sd | **S_ann dibalik** |
|---|---|---|---|---|---|
| RANGEPOS_H2 | −23,62 | 3,40 | **+16,82** | 150 | **+1,51** |
| RANGEPOS_H5 | −45,10 | 4,62 | **+35,86** | 235 | **+2,06** |
| REV_L3_H5 | −41,72 | 6,51 | +28,70 | 241 | +1,61 |
| REV_VOL_H2 | −12,72 | 6,60 | −0,48 | 140 | −0,04 |

**Kandidat terbaik: range-position momentum pada hold 5 hari, Sharpe +2,06** — 90% dari syarat 2,30, tetapi **belum lulus**.

### N.3 Perlakuan yang benar (dan yang kami lakukan)

Karena tanda ini **dipilih setelah melihat data**, ia **tidak sah** diklaim sebagai temuan prarreg. Kami memperlakukannya sebagai hipotesis baru:

- **Amandemen dibekukan lebih dahulu** — `docs/sodex/PRAREG_2_RANGE_POSITION_2026-10-07.md`, ditulis **sebelum** uji validasi dijalankan.
- Uji sahnya: **pemisahan waktu** — ukur tanda di 60% periode terawal (IS), uji di 40% terakhir (OOS), **tanpa menyetel ulang** N, hold, atau ambang.
- Sensitivitas N ∈ {10, 20, 40, 60} dilaporkan **sebagai stabilitas, bukan pemilihan**.
- Replikasi SoDEX wajib: tanda harus sama.

**Status: DITOLAK.** Lihat Bab N.4.

### N.4 Hasil uji — kandidat ditolak

PRAREG-2 dibekukan sebelum uji dijalankan. Hasilnya:

| Panel / segmen | n | neto | S_ann | t_NW | seg+ | S pada 2× biaya |
|---|---|---|---|---|---|---|
| Binance IS (60% terawal) | 634 | +18,59 bps | 1,44 | 2,54 | 2 | 1,17 |
| **Binance OOS (40% terakhir)** | 507 | +14,43 bps | **1,75** | 2,80 | **3** | 1,34 |
| SoDEX 1 hari | 138 | +7,91 bps | +0,93 | 0,96 | 2 | 0,63 |
| **SoDEX 1 jam (venue-matched, hold 24 jam)** | 293 | −16,95 bps | **−0,81** | **−4,36** | **0/3** | −1,06 |

**Ambang yang dibekukan:** S_ann OOS ≥ 2,30 (1×) **DAN** ≥ 1,80 (2×) **DAN** t ≥ 2,0 **DAN** tanda konsisten **DAN** replikasi venue bertanda sama.

| Syarat | Hasil | Putusan |
|---|---|---|
| S_ann OOS ≥ 2,30 | **1,75** | ✗ |
| S_ann OOS pada 2× biaya ≥ 1,80 | **1,34** | ✗ |
| t_NW ≥ 2,0 | 2,80 | ✓ |
| 3/3 segmen positif | 3/3 | ✓ |
| Kontrol negatif tidak lulus | ctrl bruto +4,66 / −2,22 bps (tidak signifikan) | ✓ |
| **Replikasi SoDEX bertanda sama** | **1 jam: t = −4,36 (tanda BERLAWANAN)** | **✗** |

**Sensitivitas N (stabilitas, bukan pemilihan):**

| N | Binance OOS S_ann | SoDEX 1d S_ann | SoDEX 1h S_ann |
|---|---|---|---|
| 10 | 0,86 | +0,07 | −4,14 |
| **20 (utama)** | **1,75** | **+0,93** | **−3,98** |
| 40 | 1,75 | +0,62 | −3,47 |
| 60 | 1,55 | −0,13 | −2,69 |

**Tiga kesimpulan dari uji ini:**

1. **Di Binance, momentum rentang itu nyata tetapi terlalu lemah.** t = 2,80 (signifikan) tetapi S_ann 1,75 — 76% dari syarat. Tidak cukup.
2. **Di venue target, arahnya BERBALIK di horizon yang justru paling relevan.** Pada bar jam (venue-matched, jendela 1–30 jam), momentum rentang **kalah signifikan** (t = −4,36, 0/3 segmen) — yang menang di sana adalah **reversal**.
3. **Tidak ada overfitting** (IS 1,44 < OOS 1,75), jadi angka ini bukan ilusi pemilihan periode — memang **efeknya tidak cukup besar**.

Ini persis pelajaran yang pernah muncul di divisi ini (H5: efek breakout di SoDEX berbalik arah di Binance). **Efek lintas venue tidak otomatis bertahan, dan efek lintas horizon juga tidak.**

---

## O. Jarak ke Target — Empat Dimensi dengan Angka

Berkas: `reports/sodex/JARAK_KE_TARGET_SODEX.json`

### Dimensi 1 — Sharpe

| | Nilai |
|---|---|
| Target bersih | 0,80% per 48 jam |
| σ portofolio diasumsikan | 2,35% per 48 jam |
| **Sharpe portofolio wajib** | **4,60 /tahun** |
| Pengali diversifikasi (n=6, ρ=0,10) | 2,00× |
| **Sharpe tiap mesin wajib** | **2,30 /tahun** (0,170 per 48 jam) |
| Rata-rata tiap mesin | 0,400% bersih per 48 jam |
| Mesin venue-SoDEX terbaik terukur | **0,75** |
| **Jarak** | **3,1×** |

### Dimensi 2 — Panjang bukti

| | Nilai |
|---|---|
| Jendela dibutuhkan (keluarga 21, BH q=0,10) | **274** |
| Jendela tersedia | **180** |
| **Status** | **TERKUNCI — mustahil dibuktikan dengan data hari ini** |

### Dimensi 3 — IC

| | Nilai |
|---|---|
| N_eff venue (terukur) | 6,1 dari 75 simbol |
| Breadth (H=48 jam) | 1.113 taruhan independen/tahun |
| **IC wajib** | **0,0689** |
| IC terbaik terukur | **0,0360** |
| **Jarak** | **1,91×** |
| IC impas (biaya realistis) | 0,0193 |

### Dimensi 4 — Biaya

| | Nilai |
|---|---|
| Round-trip realistis | **9,71 bps** |
| Sebagai % target 48 jam | 12,1% |
| **Sebagai % rata-rata mesin yang dibutuhkan** | **24,3%** |

**Kesimpulan O:** dari empat dimensi, **satu terkunci secara matematis (panjang bukti)**, **dua membutuhkan perbaikan kinerja nyata (IC ~2×, Sharpe ~3×)**, dan **satu adalah ongkos tetap yang bisa dikelola (24% dari rata-rata mesin)**.

---

## P. Yang Gagal — Tanpa Disembunyikan

Aturan #8 `PERINTAH_1_SoDEX.md`: dilarang menyembunyikan trial yang gagal. Berikut daftar lengkapnya.

### P.1 Daftar kegagalan

| Kelompok | Jumlah | Hasil |
|---|---|---|
| Sensus D14 (21 mesin) | 21 | **0 lulus**; 1 lolos BH tetapi bertanda REPLAY (Hyperliquid, bukan SoDEX) sehingga dikecualikan |
| Panel panjang Binance 1d (12 mekanisme × 2 hold) | 24 | **0 lulus**; 8 signifikan negatif; **0 signifikan positif** |
| Replikasi SoDEX 1d | 18 berjalan (6 dilewati — data venue tidak ada) | **0 lulus**; terbaik S_ann 0,75 |
| Replikasi SoDEX 1h (horizon venue-matched) | 18 berjalan (6 dilewati) | **0 lulus**; terbaik **1,62** (RANGEPOS_H48) · efek terkuat justru **berlawanan arah** (MOM_L21, \|S_ann\| 3,38 → kandidat reversal ≈2,29) |
| Uji OOS range-position (PRAREG-2) | 4 segmen | **kandidat DITOLAK** — OOS 1,75 < 2,30, dan tanda berbalik di horizon venue-matched |
| LP pasif / market-making | 1 | **ditolak** — 67/92 simbol spread < 2,4 bps |
| **TOTAL dievaluasi** | **81 backtest + 5 uji tambahan = 86** | **0 lulus** |

### P.2 Yang kami batalkan sendiri di tengah jalan

| Klaim awal kami | Mengapa dibatalkan |
|---|---|
| "Reversal lintas-seksi 1 hari menjanjikan — IC −0,0358 (t = −2,34)" | Setelah portofolio yang benar dibentuk (bobot peringkat, biaya, kontrol), hasilnya **+8,1 bps bruto dengan t = 0,43** — di dalam noise kontrol. IC mentah **bukan** PnL. |
| "Mesin mv_funding dan hl_replay hampir lulus (Sharpe 7,76 / 7,75)" | Keduanya **bukan venue SoDEX**: satu replay Hyperliquid, satu carry lintas-venue. Tidak boleh dihitung sebagai bukti venue. |
| "Data funding SoDEX bisa dipakai backtest carry" | **Salah** — collector menyimpan prediksi 5 hari ke depan, bukan histori. 2 dari 12 mekanisme gugur karena ini. |
| "N_eff venue rendah, sekitar 2,3" | **Artefak sampel** — hanya simbol mayor lama yang punya riwayat 365 hari. Nilai jujur: **6,1**. |
| "Range-position momentum adalah kandidat mesin (S_ann +2,06)" | **Ditolak setelah uji OOS**: OOS 1,75 < 2,30 dan tanda berbalik di SoDEX 1 jam (t = −4,36). |

### P.3 Cacat desain yang kami temukan pada instrumen kami sendiri

**Kontrol negatif dinilai pada neto → selalu terlihat gagal.** Portofolio dengan bobot acak punya turnover ≈ 1,33 (selalu berbalik penuh), sedangkan sinyal nyata punya turnover 0,15–1,33. Akibatnya kontrol **selalu membayar biaya ≈ 6,7 bps** lebih banyak, sehingga t kontrol selalu negatif (terukur: −0,6 sampai −3,6).

Setelah kami pisahkan **bruto** kontrol, seluruhnya kembali ke dalam noise (|t| ≈ 0,3–1,5). Jadi: **instrumennya sehat; metrik kontrolnya yang salah.** Kami mencatat ini dan mengoreksinya di PRAREG-2 (kontrol dinilai pada bruto).

**Dampak pada verdict: tidak ada.** Tidak satu pun trial gagal *hanya* karena kriteria kontrol — semuanya sudah gugur di ambang Sharpe.

---

## Q. Rekomendasi — Tiga Jalur, Urut Prioritas

### Jalur 1 (dampak tertinggi, bisa dimulai besok) — Perbesar IC, bukan jumlah strategi

Jarak IC adalah **1,91×**, dan itu jarak yang paling mungkin ditutup dengan kerja, bukan dengan menunggu. Konkretnya:

1. **Kejar HORIZON, bukan mekanisme baru.** Hasil kami menunjukkan tanda efek **berbalik menurut horizon**: **reversal** pada bar jam (20–21 jam), **momentum** pada bar hari (20 hari). Karena jendela swing SoDEX adalah **1–30 jam**, keluarga yang paling masuk akal untuk dikejar berikutnya adalah **reversal jam-jaman** — bukan menambah mekanisme baru di bar harian. Di SoDEX 1h, dua variannya sudah signifikan sangat kuat (t = −4,59 dan −4,71; \|S_ann\| = 3,38 dan 2,70) dan estimasi arah-baliknya **≈2,29 pada biaya 1× (hold 48 jam) — tetapi hanya ≈1,53 pada biaya 2× (syarat 1,80)**. Jadi langkah berikutnya bukan "cari sinyal", melainkan **uji beku reversal jam-jaman dengan pemisahan IS/OOS** (PRAREG-3) sambil menjawab pertanyaan biaya: bisa tidak turnover diturunkan dari 1,29 tanpa membunuh sinyalnya.
2. **Naikkan resolusi sinyal dengan data 1 jam** yang baru selesai ditarik (99 simbol, ±8.000 bar/simbol). Ini membuka uji horizon yang benar-benar venue-matched (target 1–30 jam) dan memungkinkan sinyal turunan yang tidak ada di bar harian.
3. **Tambahkan dimensi yang belum tersentuh**: order-book imbalance (data tape/OBI historis sudah ada untuk 3 simbol), decomposisi overnight vs intraday pada perps ekuitas/RWA (venue ini memperdagangkan NVDA/TSLA 24 jam sementara pasar AS tutup — ini **khas venue** dan belum kami uji).

### Jalur 2 (struktural, tidak bisa ditawar) — Perpanjang jam bukti sambil jalan

Panjang bukti **tidak bisa dipercepat**, tetapi bisa **diparkir dengan benar**:

1. **Kurangi ukuran keluarga.** BH q=0,10 atas 21 trial butuh 274 jendela; atas 5 trial hanya butuh 187, dan 1 mesin tanpa koreksi 133. **Preregistrasi 3–5 hipotesis terbaik dan setop menguji yang lain** adalah cara sah untuk mendapatkan verdict lebih cepat.
2. **Mulai pencatatan 1 jam berjalan sekarang** dan jangan diubah-ubah. Setiap bulan yang lewat menambah ± 15 jendela.
3. **Siapkan verdict HARD_STOP 20-Nov-2026 dengan jujur**: pada tanggal itu, **paling cepat** kita bisa punya verdict sah untuk **satu** mesin tanpa koreksi (butuh 265 hari, tersedia 361). Untuk sebuah portofolio keluarga, **belum**.

### Jalur 3 (pengelolaan, bukan pencarian) — Kelola biaya & kedalaman

1. **Batasi universe ke 20 simbol likuid** (≥ $100 ribu/hari). Ini justru **menaikkan** IC yang bisa dicapai per unit risiko karena menghapus nama yang biaya eksekusinya jauh di atas asumsi.
2. **Hold ≥ 48 jam.** Setiap percepatan rebalance menambah biaya linear sementara edge hanya tumbuh dengan akar waktu.
3. **Jangan pernah pakai leverage untuk menutup jarak Sharpe.** Sharpe bersifat bebas skala — leverage tidak mengubahnya sedikit pun. Ini dinyatakan eksplisit dalam larangan #6.

### Yang **tidak** direkomendasikan

| Usulan | Mengapa ditolak |
|---|---|
| Menambah mesin ke-7, ke-8, dst. sebelum ada yang lulus | Plafon diversifikasi (Bab H.3): tanpa mesin yang lulus, menambah mesin hanya menambah biaya |
| Meniru `mv_funding` (Sharpe 7,76) | Bukan venue SoDEX, dan berisiko berkorelasi dengan divisi HL-Harvest |
| LP/market-making pasif | Sudah ditolak (Bab E.2) |
| Menaikkan leverage | Dilarang aturan #6 dan tidak mengubah Sharpe |
| Melonggarkan ambang agar terlihat lulus | Dilarang aturan #7 |

---

## R. Batasan dan Apa yang **TIDAK** Boleh Disimpulkan

| Jangan simpulkan | Alasannya |
|---|---|
| "Tidak ada strategi yang bisa bekerja di SoDEX" | Yang terbukti: 60 hipotesis lintas-seksi **tertentu** tidak lulus **pada data yang ada**. Ini bukan bukti ketiadaan peluang. |
| "Range-position momentum adalah mesin" | Sudah **diuji dan ditolak**: S_ann OOS 1,75 < 2,30, dan tanda berbalik di horizon venue-matched (t = −4,36). |
| "Binance membuktikan SoDEX" | Tidak. Binance hanya menguji **mekanisme**. Bukti H5: efek bisa berbalik arah antar-venue. |
| "Sharpe 7,76 berarti kita hampir sampai" | Angka itu milik mesin **lintas-venue**, bukan venue SoDEX. |
| "N_eff 2,3 berarti venue ini miskin" | Itu artefak sampel. Angka jujur 6,1. |
| "Jendela < 6 bulan cukup untuk menilai alpha" | Aturan #4: sah untuk verifikasi eksekusi, **tidak sah** untuk menilai alpha. |
| "Kontrol negatif kami gagal, jadi harnessnya rusak" | Setelah dinilai pada bruto, kontrol bersih. Yang salah metriknya, bukan instrumennya (Bab P.3). |

**Batasan data yang harus diingat:**

- Histori SoDEX maksimum **361 hari** — di bawah satu siklus pasar penuh.
- Funding/basis SoDEX **tidak tersedia historis** → 2 mekanisme tidak dapat diuji di venue.
- Data order-book historis hanya **3 simbol, 22-Mei → 4-Okt** (< 6 bulan) → sah untuk eksekusi, tidak sah untuk alpha.
- Panel Binance punya **bias kelangsungan hidup** (yang terdaftar hari ini, bukan yang delisting) — arah biasnya biasanya **menguntungkan** strategi momentum, jadi hasil negatif kita tetap aman.

---

## S. Lampiran — Berkas, Skrip, Cara Reproduksi

### S.1 Skrip baru yang dibuat riset ini

| Berkas | Fungsi |
|---|---|
| `scripts/research/sodex_xsec_study.py` | Studi lintas-seksi eksploratori (pembentuk hipotesis) |
| `scripts/research/binance_pull_klines.py` | Penarik klines perp Binance, 248 simbol, paginasi penuh |
| `scripts/research/binance_pull_funding.py` | Penarik funding + basis, 248 simbol, full history |
| `scripts/research/xsec_mech_study.py` | **Mesin uji utama**: 12 mekanisme × 2 hold, BH, kontrol, 3 tingkat biaya |
| `scripts/research/sodex_diversification_census.py` | Sensus korelasi & N_eff venue |
| `scripts/research/sodex_breadth_budget.py` | Anggaran IC (Hukum Fundamental) |
| `scripts/research/sodex_distance_to_target.py` | Konsolidasi jarak ke target, 4 dimensi |
| `scripts/research/range_pos_validation.py` | Uji OOS range-position (PRAREG-2) |

### S.2 Berkas hasil (JSON)

| Berkas | Isi |
|---|---|
| `reports/sodex/PRAREG_PANEL_PANJANG_binance_1d.json` | 24 trial Binance + BH + kontrol |
| `reports/sodex/PRAREG_PANEL_PANJANG_sodex_1d.json` | 18 trial SoDEX 1d |
| `reports/sodex/SENSUS_DIVERSIFIKASI_SODEX.json` | Korelasi, N_eff, PC1 |
| `reports/sodex/ANGGARAN_BREADTH_SODEX.json` | Anggaran IC per N_eff |
| `reports/sodex/JARAK_KE_TARGET_SODEX.json` | 4 dimensi jarak ke target |
| `reports/sodex/UNIVERSE_SODEX_1D.json` | Universe 95 simbol + volume + volatilitas |
| `data/sodex_edge_census.json` | Sensus D14 (21 mesin) — masukan |
| `data/binance_klines/1d/` | Panel panjang 248 simbol |
| `data/binance_funding/` · `data/binance_basis/1d/` | Funding & basis 248 simbol |

### S.3 Protokol yang dibekukan

| Berkas | Status |
|---|---|
| `docs/sodex/PRAREG_PANEL_PANJANG_2026-10-07.md` | Dibekukan **sebelum** uji dijalankan |
| `docs/sodex/PRAREG_2_RANGE_POSITION_2026-10-07.md` | Dibekukan **sebelum** uji validasi dijalankan |

### S.4 Cara menjalankan ulang

```bash
cd ~/anantara-sakti
/usr/bin/python3 scripts/research/binance_pull_klines.py 1d 250     # panel panjang
/usr/bin/python3 scripts/research/binance_pull_funding.py 250       # funding + basis
/usr/bin/python3 scripts/research/xsec_mech_study.py binance 1d 2,5 # 24 trial Binance
/usr/bin/python3 scripts/research/xsec_mech_study.py sodex 1d 2,5   # replikasi SoDEX
/usr/bin/python3 scripts/research/sodex_breadth_budget.py
/usr/bin/python3 scripts/research/sodex_distance_to_target.py
/usr/bin/python3 scripts/research/range_pos_validation.py
```

Interpreter **wajib** `/usr/bin/python3` (punya pandas/numpy/scipy). Python default tidak.

---

## T. Glosarium dengan Analogi

| Istilah | Arti sederhana | Analogi |
|---|---|---|
| **Lintas-seksi (cross-sectional)** | Meranking semua aset pada satu waktu, lalu beli yang teratas dan jual yang terbawah | Memilih 5 pelari tercepat dan 5 terlambat **pada hari yang sama**, bukan menebak arah seluruh arena |
| **Dollar-neutral** | Total nilai beli = total nilai jual, jadi tidak peduli pasar naik atau turun | Taruhan seimbang: menang kalau pilihan kita lebih baik dari rata-rata, bukan kalau pasar naik |
| **IC (Information Coefficient)** | Seberapa akurat peringkat sinyal kita menebak peringkat hasil sebenarnya | Nilai ujian seorang peramal cuaca: 0 = menebak, 0,05 = sedikit lebih baik dari menebak |
| **Breadth** | Berapa banyak taruhan independen yang kita buat per tahun | Jumlah lemparan koin. Makin banyak, makin cepat tahu koinnya adil atau tidak |
| **N_eff (taruhan efektif)** | Berapa taruhan *benar-benar* independen dari sekian banyak aset | 75 siswa tapi semuanya menyontek dari 6 orang → hanya 6 jawaban mandiri |
| **PC1** | Bagian gerakan yang dijelaskan "pasar secara keseluruhan" | Cuaca: 38% hari hujan atau cerah untuk **semua** kota sekaligus |
| **Sharpe** | Return dibagi risiko | Bukan "berapa cepat", tapi "berapa rapi" — 2,3 artinya sangat rapi |
| **Drawdown** | Penurunan terdalam dari puncak | Turun sedalam apa sebelum naik lagi |
| **BH-FDR** | Koreksi saat menguji banyak hipotesis sekaligus | Kalau membidik 21 target, kadang kena tanpa sengaja. Koreksi ini mempersempit toleransi |
| **BH q = 0,10** | Toleransi 10% penemuan palsu di antara yang dinyatakan lulus | Dari 10 klaim "ini berhasil", paling banyak 1 boleh salah |
| **Jendela (window)** | Satu periode pengamatan independen | Satu lembar rapor. Tiga jendela = tiga rapor, bukan satu rapor tiga kali |
| **Turnover** | Seberapa besar portofolio diganti tiap rebalance | Berapa sering ganti seluruh isi gudang |
| **bps (basis poin)** | 1 bps = 0,01% | 100 bps = 1% |
| **Beta-netral** | Tidak punya paparan arah pasar | Tidak ikut naik-turun lift, hanya ikut langkah kaki kita sendiri |
| **OOS (out-of-sample)** | Masa yang tidak dipakai saat menyusun aturan | Ujian akhir dengan soal yang tidak pernah dibocorkan |
| **Preregistrasi** | Menuliskan aturan main sebelum melihat hasil | Menulis taruhan sebelum pertandingan mulai |

---

## U. Laporan Verifikasi

| Item | Hasil |
|---|---|
| Total dievaluasi | **81 backtest + 5 uji tambahan = 86** (21 sensus D14 + 24 Binance + 18 SoDEX 1d + 18 SoDEX 1h + 4 segmen OOS + 1 sensus LP) |
| Hipotesis lulus | **0** |
| Trial gagal yang dilaporkan | **semua** (tidak ada yang disembunyikan) |
| Skrip baru | 8 |
| Berkas hasil JSON | 7 baru + 1 masukan |
| Protokol dibekukan | 2 (PRAREG-1, PRAREG-2) |
| Uji asap instrumen | Lulus — edge sintetis 0,4%/hari terdeteksi (S_ann 5,33; t = 5,50; p < 0,0001), kontrol bersih |
| Kontrol negatif | Seluruhnya dalam noise setelah dinilai pada bruto (|t| ≈ 0,1–1,6; beberapa |t| > 2 sesuai ekspektasi statistik dari 72 kontrol) |
| Frekuensi positif palsu instrumen D14 | 0,0525 (individual) · 0,015 (gabungan) — terkontrol |
| Kandidat yang diuji OOS | 1 (range-position) — **ditolak** |
| Order nyata dikirim | **0** — seluruh riset read-only |
| Modal nyata | Tetap **FROZEN** |
| Aturan keras dilanggar | **0 dari 10** |

**Diperiksa dan direproduksi dengan:** `/usr/bin/python3` (pandas, numpy, scipy), seluruh keluaran berasal dari eksekusi nyata — bukan perkiraan.

---

*Divisi Riset Anantara Sakti · 7 Oktober 2026*
*Dokumen ini tidak mengubah target, tidak menaikkan leverage, dan tidak menyembunyikan kegagalan.*
