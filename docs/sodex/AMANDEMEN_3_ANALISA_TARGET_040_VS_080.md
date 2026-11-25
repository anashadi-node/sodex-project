# AMANDEMEN-3 (DISETUJUI) — ANALISA TARGET 0,8% vs 0,4% per 48 JAM

**Status: DISETUJUI Mas Anas 2026-10-09 — OPSI A + C.** Target 0,80%/48 jam tetap berlaku dengan ambang terukur α ≥ 29,3 bps/48 jam; bila α lebih tipis, target mengikuti rumus kuadratik (§7). Saya tidak mengubah target/parameter fundamental tanpa GO eksplisit.
Tanggal: 2026-10-09 · Dasar: `reports/sodex/ANALISA_TARGET_LEVERAGE.json`, `reports/sodex/VENUE_DRIFT_CONTROL.json`, `scripts/research/lev_discipline.py` (21 tes PASS).

---

## TL;DR — VONIS: JANGAN TURUNKAN TARGET (dengan satu syarat terukur)

| # | Pertanyaan | Jawaban terukur |
|---|-----------|-----------------|
| 1 | Apakah turunkan target mempercepat sertifikasi? | **TIDAK. Nol.** `t = √n × (α/σ)` — invarian terhadap target & leverage. Leverage adalah skalar: mengalikan pembilang **dan** penyebut. |
| 2 | Berapa lama sertifikasi yang sebenarnya? | α=32 bps/48j → BTC **797 hari**, ETH **1.540 hari**, SOL **1.729 hari** untuk t≥1,96. **Ini penyumbat nyata proyek — bukan target.** |
| 3 | Apakah 0,8% bisa dicapai dengan aman? | **BISA.** 3 majors @half-Kelly, α=32 bps → **95,4 bps/48j = 0,95% = 1,19× target**, jarak likuidasi 65–143%. |
| 4 | Apakah 0,4% lebih aman secara *proses*? | **Tidak lebih mudah.** Sertifikasinya identik (797/1540/1729 hari). Yang berubah hanya jumlah mesin yang dibutuhkan untuk mencapai angka itu. |
| 5 | Kapan 0,4% jadi BENAR? | **Bila α terukur ≤20 bps/48j.** Di α=20, 3 majors hanya 37 bps; mencapai 0,8% menuntut L≥4 → bangkrut **~47%/tahun**. Maka turunkan — sebagai **konsekuensi pengukuran**, bukan pilihan selera. |

---

## 1. Kontrol wajib dulu: apakah data SoDEX bisa dipercaya?

Sapuan menemukan drift 48 jam SoDEX **negatif besar** (BTC −16, ETH −24, SOL −28 bps) sementara Binance **+13/+2/+2**. Sebelum menyimpulkan apa pun, saya uji: **apakah ini bias data, atau rezim pasar?**

Kontrol: potong Binance pada **jam yang persis sama** dengan SoDEX.

| Aset | SoDEX | Binance (jam sama) | Beda berpasangan | Korelasi 48j | Binance (penuh 24.276 bar) |
|------|-------|--------------------|------------------|--------------|---------------------------|
| BTC | −15,1 bps | **−15,1 bps** | −0,05 bps (t=−0,42) | **0,999** | +12,8 bps |
| ETH | −22,2 bps | **−22,9 bps** | +0,70 bps (t=+3,42) | **0,999** | +2,1 bps |
| SOL | −26,1 bps | **−26,1 bps** | +0,00 bps (t=+0,05) | **1,000** | +1,7 bps |

**Vonis: klines SoDEX BERSIH.** Tidak ada bias pengukuran (korelasi 0,999, beda ~0). Drift negatif itu **rezim pasar**: tahun data SoDEX (12-Okt-2025 → 09-Okt-2026) adalah **tahun turun**. Binance yang mencakup 2024–2025 (bull) menunjukkan +12,8.

Dua konsekuensi besar:
1. **Semua studi harga SoDEX yang lalu sah** (tidak perlu dibatalkan).
2. **Riwayat Binance 1h (24.276 bar ≈ 2,8 tahun) sah dipakai riset majors** — 2,8× lebih banyak bukti, korelasi 0,999 terhadap venue eksekusi. Ini akselerator riset terbesar yang kita temukan hari ini.

⚠️ **Peringatan metode**: karena tahun sampel turun, **strategi short-bias otomatis terlihat bagus**. Itu **bukan alpha** — itu drift. Setiap uji sinyal ke depan **wajib mengontrol drift pasar** (regresi terhadap return pasar; residual yang diuji, bukan return mentah).

## 2. Aritmetika yang membunuh ilusi: target tidak mempercepat sertifikasi

Klaim "return ≥ target" diuji dengan `t = √n × (α/σ)`. Leverage L mengubah return menjadi `L×α` **dan** volatilitas menjadi `L×σ` → **rasio tidak berubah**. Karena itu:

| S_ann | Hari untuk t≥1,96 | Window 48j |
|-------|-------------------|-----------|
| 0,50 | 5.609 | 2.804 |
| 1,00 | 1.402 | 701 |
| **1,33** (BTC @α=32) | **797** | 398 |
| 2,00 | 351 | 175 |
| 5,78 | 42 | 21 |

**Menurunkan target dari 0,8% ke 0,4% tidak memindahkan satu baris pun di tabel ini.** Angka 0,4% hanya berarti leverage lebih rendah (`L = target/α`), dan leverage lebih rendah = return lebih rendah **dengan bukti statistik yang identik**. Menurunkan target karena "ingin lebih mudah dibuktikan" adalah kekeliruan kategori.

## 3. Kelly: leverage yang benar berbeda per instrumen — inilah masalah sebenarnya

Pertumbuhan majemuk `E[log(1+L·r)] ≈ L·α − L²σ²/2` → optimum **L\* = α/σ²**. Di atas Kelly, menambah leverage **menurunkan** pertumbuhan **dan** menaikkan risiko bangkrut.

Pada α = 32 bps/48j (bar yang sama, §8 laporan sapuan):

| Instrumen | σ 48j | Kelly | Half-Kelly | Return @half-Kelly | Jarak likuidasi |
|-----------|-------|-------|-----------|-------------------|-----------------|
| BTC | 3,26% | 3,01× | **1,51×** | **48,2 bps** | 65,4% |
| ETH | 4,53% | 1,56× | **0,78×** | **25,0 bps** | 127,2% |
| SOL | 4,80% | 1,39× | **0,69×** | **22,2 bps** | 143,1% |
| **TOTAL** | | | | **95,4 bps = 0,95%** | **1,19× target 0,8%** |

**Temuan yang membalik intuisi**: target 0,8% yang datar **memaksa over-leverage pada ETH/SOL** (butuh L=2,5 = 1,6× dan 1,8× Kelly → pertumbuhan **negatif**). Yang salah bukan angkanya — **yang salah adalah menerapkan satu leverage datar untuk instrumen berlainan volatilitas.**

**Berapa mesin yang dibutuhkan (α=32, half-Kelly):**

| Target | Kombinasi | Total |
|--------|-----------|-------|
| **0,4%** | BTC saja | 48,2 bps ✓ (1,20×) |
| 0,8% | BTC + ETH | 73,2 bps ✗ (92% — **kurang**) |
| **0,8%** | **BTC + ETH + SOL** | **95,4 bps ✓ (1,19×)** |

## 4. Risiko ekor: dua koreksi yang saya temukan sendiri

**(a) "P(likuidasi) 0,00%" di sampel adalah artefak.** Dengan ~350 window dan **nol** kejadian, batas atas 95% Poisson = 3/350 = 0,86%/window → **79%/tahun**. Ekor sampel **tidak dapat** mengesampingkan kejadian langka. Karena itu disiplin wajib dilengkapi **anggaran bangkrut tahunan** (R2: ≤10% → p_window ≤ 0,058%), bukan hanya "p5 ≤ 1/3 jarak".

**(b) Plafon 2,5× akan mati di skenario stres.** BTC pernah **−55%** dalam 48 jam (Mar-2020); pada L=2,5 (jarak 39%) posisi **likuidasi**. Maka R5: `L ≤ 1/(mmr + |pergerakan 48 jam terburuk yang diketahui|)` → **BTC ≤1,79× · ETH ≤1,64× · SOL ≤1,52×**.

Kabar baiknya: pada α wajar (32 bps), **half-Kelly (1,51×) sudah di bawah batas stres (1,79×)** → disiplin half-Kelly **mengayomi diri** (terverifikasi tes `test_kelly_mengikat_sebelum_stres_pada_alpha_wajar`). R5 baru mengikat pada α=60 bps.

## 5. KONDISI PEMBATALAN: kapan 0,4% menjadi jawaban yang benar

Ini bagian yang membuat keputusan ini **bukan selera, tapi konsekuensi**:

| α terukur (bps/48j) | Kelly BTC | L aman (half-Kelly) | Return 3 majors | Target 0,8% tercapai? | Tindakan benar |
|---------------------|-----------|---------------------|-----------------|----------------------|----------------|
| ≥ 40 | 3,77× | 1,79× (stres) | 119 bps | ✓ (1,5×) | **0,8%** |
| **32** | 3,01× | 1,51× | **95 bps** | ✓ (1,19×) | **0,8%** |
| 20 | 1,88× | 0,94× | 37 bps | ✗ (46%) | **turunkan ke ~0,4%** (bukan karena menyerah, tapi karena itulah α kita) |
| 10 | 0,94× | 0,47× | 19 bps | ✗ (23%) | **tidak deploy** — bangkrut tahunan >50% pada L yang diperlukan |

**Kesimpulan:** 0,4% bukan pilihan untuk "merasa lebih aman". Ia adalah **angka yang benar ketika α ≈ 20 bps**. Hari ini α **belum terukur sama sekali** (0 mesin tersertifikasi) — artinya yang menentukan bukan keputusan target sekarang, tapi **seberapa cepat kita mengukur α`.

## 6. Yang saya minta Mas Anas putuskan (satu baris saja)

| Opsi | Isi | Konsekuensi |
|------|-----|-------------|
| **A (REKOMENDASI)** | Target tetap **0,80%/48j**; leverage **half-Kelly per instrumen** + plafon stres R5 + anggaran bangkrut ≤10%/thn; portofolio **≥3 majors** | 0,95%/48j pada α=32; tidak ada perubahan target; disiplin leverage jadi kode (sudah jalan) |
| **B** | Turunkan target ke **0,40%** sekarang | Menolak: 0 manfaat sertifikasi, memangkas pertumbuhan, konsentrasi 1 mesin |
| **C (paling radikal & paling jujur)** | Target tetap **0,80%** tetapi didefinisikan **sebagai fungsi α**: 0,8% bila α≥32 bps; 0,4% bila α≈20 bps | Target menjadi besaran **terukur**, bukan aspirasi. Mengubah definisi North Star → butuh GO eksplisit |

**Rekomendasi saya: A** (jika ingin paling jujur secara ilmiah: **A + C** sebagai kerangka).

---

*Artefak: `ANALISA_TARGET_LEVERAGE.json`, `VENUE_DRIFT_CONTROL.json`, `lev_discipline.py`, `tests/test_lev_discipline.py` (21 PASS), `target_leverage_analysis.py`, `venue_drift_control.py`.*

---

## 7. KEPUTUSAN MAS ANAS (2026-10-09): OPSI **A + C** DISETUJUI — ambang dibekukan

**A** — Target tetap 0,80%/48 jam; leverage half-Kelly per instrumen + R1–R5; portofolio ≥3 majors.
**C** — Target didefinisikan **sebagai fungsi α yang terukur** (bukan aspirasi yang dipaksakan).

> ### ⚠️ KOREKSI 2026-10-09 (ditemukan sendiri sebelum angka dipakai untuk keputusan uang)
> Versi pertama §7 memakai `0,5·Σ(1/σᵢ²)·α²` = 95,4 bps. **Rumus itu salah**: ia menjumlahkan
> Kelly tiap instrumen seolah risikonya **terpisah (ρ=0)** *dan* tiap mesin memakai **seluruh wallet**.
> Majors berkorelasi **ρ ≈ 0,7** — keunggulan yang sama tidak boleh dihitung tiga kali.
> Rumus benar: **`w = 0,5 · Σ⁻¹ · α`** (Σ dari σᵢσⱼρ). Efeknya: **95,4 → 48,3 bps** pada α=32.
> Kode: `lev_discipline.portofolio_half_kelly()` + `alpha_minimum_untuk_target()` (28 tes PASS).

**Rumus resmi (terverifikasi, DIKOREKSI):**

```
bobot portofolio half-Kelly   w = 0,5 · Σ⁻¹ · α      ,  Σᵢⱼ = σᵢ σⱼ ρ
return(laporan)              = wᵀ α                  (return atas TOTAL wallet)
```

| Ambang **FINAL** (ρ=0,7, half-Kelly **+ plafon stres R5**) | Nilai | Arti |
|--------|-------|------|
| α untuk target **0,80%** | **≥ 43,4 bps/48j** | plafon stres mengikat (L=1,79× BTC) |
| α untuk target **0,40%** | **≥ 29,1 bps/48j** | half-Kelly mengikat (L=1,37×, plafon belum) |
| α minimum untuk deploy | **> 10 bps/48j** | di bawah ini: **tidak deploy** |
| (pembanding) bila ρ bisa ditekan ke 0,3 | 36,4 bps | butuh edge yang **berbeda**, bukan nama lebih banyak |
| (pembanding, **DITOLAK**) full-Kelly | 26,6 bps | tidak dipakai: jarak likuidasi 33%, R3 melarang |

**Temuan struktural (lebih penting dari angkanya):** dengan α **sama** di ketiga majors, bobot optimal
jatuh ke **BTC saja (1,51×)** — ETH dan SOL dapat ≈ 0. Menambah nama **tanpa edge baru = sia-sia**;
yang menaikkan hasil bukan jumlah mesin, melainkan **jumlah edge yang benar-benar berbeda**.
Ini yang menurunkan ambang dari **43,4 → 36,4 bps** bila ρ bisa ditekan ke 0,3.

**Kurva C (FINAL: ρ=0,7, half-Kelly **+ plafon stres R5**) — di atas α≈38 bps kurva menjadi
LINEAR, bukan kuadratik, karena leverage sudah mentok plafon:**

| α (bps/48j) | Return portofolio | Setara setahun | L | Status |
|-------------|-------------------|----------------|---|--------|
| 20 | 0,19% | 34% | 0,94× | — |
| **29,1** | **0,40%** | 72% | 1,37× | **target 0,4% mulai berlaku** |
| 32 | 0,48% | 88% | 1,51× | 0,4% aman (1,20× target) |
| 38 | 0,68% | 124% | 1,79× | plafon stres **mulai** mengikat |
| **43,4** | **0,80%** | 146% | 1,84× | **target 0,8% mulai berlaku** |
| 50 | 0,93% | 169% | 1,85× | 0,8% aman (1,16× target) |
| 60 | 1,12% | 204% | 1,86× | ambang praduga batas realistis |

**Catatan jujur soal full-Kelly:** pada α=26,6 bps, target 0,8% **bisa** dicapai di **full Kelly**
(BTC 3,01×) — tetapi R3 melarangnya: jarak likuidasi turun dari 65% ke 33%. Saya **tidak**
merekomendasikan jalan itu, dan angkanya hanya dicatat sebagai pembanding.

**Aturan mengikat (tidak dapat dilanggar agen):**
1. Selisih antara target dan hasil aman **selalu** ditutup dengan **menambah mesin** atau **menerima target lebih rendah** — **tidak pernah** dengan menaikkan leverage atau menurunkan ambang.
2. Ambang 41,2 / 29,1 / 10 bps tidak boleh diubah tanpa amandemen baru yang disetujui Mas Anas.
3. Karena `t = √n·(α/σ)` invarian terhadap target, penurunan target **tidak** mempercepat sertifikasi — alasan menurunkan target **hanya** boleh berasal dari α terukur (§5 tabel), bukan dari keinginan "lebih mudah dibuktikan".
4. Ukuran keberhasilan proyek **bergeser** dari "mencapai 0,8%" menjadi **"mengukur α dengan benar, secepat mungkin"** — sebab α-lah yang menentukan target, leverage, dan kelayakan deploy sekaligus.
