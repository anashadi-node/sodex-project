# Riset Mendalam: Metode & Mode Trading HOLD 30 / 48 / 72 Jam untuk Venue SoDEX

**Divisi Riset & Penelitian — Anantara Sakti**
Tanggal: 25 Oktober 2026 · Versi 1.0 · Status: **DESKRIPTIF** (bukan pra-registrasi, bukan izin live)
Standar: `riset-penelitian` v1.0.0 (12 aturan) · Falsification-first · Fail-closed

---

## 1. Ringkasan eksekutif

**Pertanyaan:** metode/mode trading apa yang paling cocok untuk HOLD 30/48/72 jam di venue SoDEX?

**Jawaban jujur:** **tidak ada** dari metode yang bisa diuji di venue ini yang lolos gerbang
statistik pada horizon tersebut. Total **202 trial baru** dijalankan hari ini (150
gelombang-1: 120 cross-sectional + 30 time-series; 52 gelombang-2: 5 mekanisme literatur
baru × 4 hold × 3 tag), ditambah **8 verifikasi ulang kandidat** dengan 200 permutasi per
kandidat. Hasil: **0 lolos**.

Lima temuan yang mengubah keputusan:

| # | Temuan | Angka |
|---|---|---|
| 1 | Panel CS + 5 mekanisme literatur baru pada H24–72: nol lolos gate | 172 trial CS (120 + 52), 0 pass di semua tag |
| 2 | Time-series momentum **kalah dari beli-tahan** di kedua venue | SoDEX real: TSMOM −41,05 bps/72j vs bench +38,44; Binance: 28,45 vs 34,82 |
| 3 | "Signifikan" H72 di panel adalah **artefak bandwidth Newey-West** | RANGEPOS_H72: t=5,42 (lag=hold) → t=1,61 (lag=1); CI95 [−2,0; +42,9] memuat nol |
| 4 | Data SoDEX sebelum 12-Jun-2026 adalah **mirror Binance sintetis** | n=0 di semua simbol, harga corr 1,0000, volume fabrikasi; 67% bar panel lama |
| 5 | Gap ke target tetap **4–5×** | target 80 bps/30j; kandidat terbaik real-era 6,6–17,6 bps dan tidak signifikan |

**Konsekuensi:** jangan tambah mesin sinyal baru ke H30/48/72. Tuas yang tersisa bukan
"cari sinyal lain", melainkan **seleksi mesin (meta/ensemble)** dan **gate rezim** — dua-
satunya keluarga yang literatur beri ★★★★★ dan yang menyerang constraint WR/konsistensi.

---

## 2. Pertanyaan riset & definisi target yang mengikat

Hipotesis yang diuji (falsifiable):

> **H1:** Terdapat mekanisme sinyal (cross-sectional atau directional) yang, setelah biaya
> taker SoDEX, menghasilkan mean bersih ≥ 80 bps per window 30 jam dengan t ≥ 2,0,
> CI95 tak memuat nol, dan bertahan di ≥ 3 segmen waktu.

Kriteria gagal (harus bisa gagal — kalau tidak, bukan sains):
mean < 80 bps **atau** t < 2,0 **atau** CI memuat nol **atau** segmen tidak konsisten **atau**
kontrol negatif ikut signifikan.

Ekonomi yang mengikat:

| Item | Nilai | Sumber |
|---|---|---|
| Target | 0,8% dari TOTAL modal per window 30 jam (akumulasi) | Memory + amandemen target A/B |
| Fee taker SoDEX | 4,0 bps/sisi (≈6,5–6,7 bps round-trip) | docs/sodex/AUDIT_BIAYA_AKUN |
| Gross wajib | ≥ **9,57 bps**/trade untuk BEP | turunan fee + slip |
| Turnover rata-rata mekanisme panel | 1,29–1,36 × gross | hasil uji hari ini |
| **Funding-drag (Hold 30j)** | **3,75–11,25 bps** per window | peta literatur gel.-1 (analisis Binance) |
| **Funding-drag (Hold 72j)** | **9–27 bps** — bisa 2–5× fee | peta literatur gel.-1 |

Artinya: bukan hanya butuh *arah* benar — butuh edge kotor **≥ 10 bps** hanya untuk impas.
Dan di horizon panjang, **funding mengambil porsi biaya terbesar**: pada H72, funding-drag
sendirian bisa melewati ambang 9,57 bps. Semua hasil "net" di dokumen ini = net-of-fee
TANPA funding — sehingga hasil H48/H72 di sini adalah **batas atas**; kondisi riil bisa
lebih buruk. (Data funding SoDEX baru ada sejak 2-Okt: 22,7 hari — belum cukup untuk
menyejarahi-kan drag.)

---

## 3. Data: temuan forensik era "mirror" SoDEX

Ini temuan paling penting hari ini karena **mengubah cara membaca semua panel lama**.

**Bukti 1 — tidak ada trade.** Semua bar 1h SoDEX sebelum 2026-06-12 memiliki `n = 0`
(jumlah trade nol) di **semua** simbol, sementara `v` dan `q` (volume) tetap > 0.

**Bukti 2 — harga bukan karangan.** Setelah koreksi bug threshold epoch (1748736000000 =
Jun-2025, bukan 2026), harga bar era itu **sejajar timestamp** dan **mengikuti Binance**
dalam ±0,1% (korelasi close ≈ 1,0000 pada sampel berpasangan).

**Bukti 3 — volume fabrikasi.** Volume bar era mirror berskala tetap (~$1–2 juta/jam untuk
BTC) dan **tidak** mengikuti pola volume Binance; ini bukan volume venue.

**Kesimpulan forensik:**

| Era | Rentang | Bar (95 simbol) | Sifat |
|---|---|---|---|
| Mirror/phantom | 2025-10-12 → 2026-06-12 | 5 713 | Harga = mirror Binance, n=0, volume sintetis |
| **Real** | **2026-06-12 → 2026-10-25** | **3 244** | Perdagangan venue sungguhan |

**Implikasi langsung:**
1. Semua hasil panel yang dihitung pada `sodex_full` adalah **campuran 64% data proxy Binance
   + 36% data venue**. Verdict "SoDEX" dari panel lama harus dibaca sebagai "proxy Binance".
2. PRAREG-3 (reversal 21 jam) membagi IS/OOS pada bar ke-5120 — IS-nya (Okt-25→Mei-26)
   **seluruhnya era mirror**. Jadi "IS t=4,25 → OOS t=0,38" bukan semata overfit; itu
   **pergantian jenis data**. Falsifikasinya tetap sah, interpretasinya berubah.
3. Untuk verdict venue, satu-satunya bukti sah adalah `sodex_real` — 4,4 bulan, 3 244 bar.

---

## 4. Taksonomi 7 keluarga metode dunia + status uji

Sintesis dari 26 sumber primer (jurnal JF/JFE/RFS/JFQA/FAJ, SSRN, arXiv, Quantpedia,
Alpha Architect, Robot Wealth, Concretum) — peta lengkap: `/home/USER/peta-literatur-perps-hold-30-72-jam.md`.

| # | Keluarga | Kecocokan 30–72j | Bukti literatur | Status di Anantara |
|---|---|---|---|---|
| 1 | Trend / time-series momentum | ★★★★ | Kuat (1–4 minggu) | **DIUJI hari ini → kalah dari beli-tahan** |
| 2 | Mean-reversion / fade | ★★ | Sedang, meluruh cepat | Diuji (REV_L1/L3, REV_VOL, REV_IDIO, LTREV, RANGEPOS) → negatif/tidak stabil |
| 3 | Breakout / vol-expansion | ★★★ | Hanya kuat bila di-ensemble | Diuji hari ini → **n terlalu kecil, INVALID** (bukan terbukti salah) |
| 4 | Carry / funding | ★★ (overlay) | Kuat tapi butuh 2 leg | Ditutup: plafon ekonomi 3,6× di bawah lantai; data funding 22 hari |
| 5 | Vol-regime / kalender | ★★★★ (gate) | Paling konsisten | Sudah dipakai sebagai gate di CEX; belum diuji di SoDEX |
| 6 | OI / forced-flow | ★★★ | Mekanisme nyata, bukti kuantitatif tipis | Diuji (PRAREG-30) → gagal; collector OI 15s baru jalan |
| 7 | Meta / ensemble / seleksi mesin | ★★★★★ | Kuat (Zarattini; López de Prado; Robot Wealth) | **BELUM diuji** — dan ini tuas utama yang tersisa |

Catatan: peringkat ★ = kekuatan bukti × kesesuaian horizon × biaya implementasi di venue
ber-fee 4 bps/sisi, bukan skor akademik.

---

## 5. Uji #1 — Panel cross-sectional diperluas ke H24/30/48/72

**Motivasi:** panel beku 7-Okt hanya menguji H2/H5 (bar harian) dan H24/H48 (bar 1 jam).
Hold **30 jam** tidak pernah diuji di mana pun; hold **72 jam** hanya diuji sebagai sinyal
single-name (grid 1.080), bukan cross-sectional.

**Alat:** `scripts/research/panel_extend_h30h72_descriptive.py` — memakai harness beku
`xsec_mech_study.run_mech` **tanpa modifikasi** (fee 4 bps, kontrol negatif shuffle-per-bar,
t Newey-West, 3 segmen, BH-FDR q=0,10).

**Hasil:**

| Tag | Bar | Simbol | Trial | BH-pass | Gate-pass |
|---|---|---|---|---|---|
| `sodex_full` | 8 957 | 95 | 36 | 4 (semua negatif) | **0** |
| `sodex_real` | 3 244 | 95 | 36 | 4 | **0** |
| `binance_full` | 24 276 | 54 | 48 | 30 (mayoritas negatif) | **0** |

Kandidat positif teratas (dan mengapa gugur):

| Key | Tag | mean (bps) | t | n | S | WR | Gugur karena |
|---|---|---|---|---|---|---|---|
| RANGEPOS_H72 | sodex_real | +17,56 | 4,20 | 44 | 2,00 | 0,57 | n < 100; segmen tak bisa dihitung; **t artefak** (lihat §7) |
| RANGEPOS_H48 | sodex_full | +10,17 | 1,95 | 155 | — | 0,55 | t < 2,0 |
| RANGEPOS_H24 | sodex_real | +5,15 | 0,84 | 134 | — | 0,53 | jauh dari target |
| LTREV_L180_H72 | sodex_real | +22,99 | 2,27 | 42 | — | 0,57 | n=42, t artefak, CI memuat nol |
| MOM_L63_H30 | binance_full | +10,89 | 1,92 | 806 | — | 0,52 | t < 2,0; seg+ hanya 2/3 |

**Bukti bahwa angka negatif besar di panel bukan "temuan" melainkan artefak konstruksi:**
`MOM_L21_H24` di `sodex_real` = −24,15 (t = −2,94) **tetapi kontrol acaknya** = t = −4,85.
Kontrol yang lebih negatif dari sinyal berarti kerugian berasal dari **konstruksi long-short
pada dispersi cross-sectional yang miring** — bukan dari informasi momentum. Aturan 9 bekerja
sebagaimana mestinya: sinyal yang tidak bisa mengalahkan kontrolnya = nol.

**Kesimpulan Uji #1:** H30 dan H72 cross-sectional tidak menghasilkan apa pun yang lolos.
Tidak ada alasan menambah mesin CS ke horizon ini.

### 5b. Uji #1b — Gelombang 2: 5 mekanisme literatur baru (25-Okt, siang)

Sumber: peta literatur gelombang-2 (`docs/sodex/PETA_LITERATUR_METODE_BARU_2026-10-25.md`,
12 metode; 5 yang bisa jalan dengan data OHLCV venue langsung diuji). Harness beku tanpa
modifikasi, BH-FDR dalam keluarga sendiri (16–20 key per tag).

| Mekanisme | Sumber | Definisi sinyal |
|---|---|---|
| RESMOM_L168 | Blitz/Huij/Martens JEF 2011 | momentum residu vs BTC (rolling beta 168j) |
| RAMOM_L168 | Daniel-Moskowitz JFE 2016 (versi rank) | momentum 168j / vol 168j |
| ANCHOR_720 | George-Hwang JF 2004 | px / max-rolling 720j (proksi 52w — era real 4,4 bln) |
| BVDOWN_L168 | IFR-A 2023 | downside semivariance 168j (long RV- tinggi) |
| VOLPREM_L168 | Gervais JF 2001 | dollar-volume 168j (long volume tinggi) |

**Hasil: 52 trial, 0 lolos gate.** Poin penting:

| Tag | BH-pass | Terkuat | Keterangan |
|---|---|---|---|
| sodex_real | TIDAK ADA | — | semua mean −7,0..+5,5 bps, t −1,61..+0,73; 9 dari 20 tanda NEGATIF |
| sodex_full | TIDAK ADA | RAMOM_H48 +11,06 t=2,19 (S 1,19) | di bawah gate |
| binance_full | 7 key | RAMOM_H72 +22,22 t=3,10 S=1,39; BVDOWN_H72 +30,60 t=3,02 S=1,32 | lihat bawah |

**Kasus RAMOM_L168_H72 (Binance, t=3,10, BH-pass, kontrol bersih t=0,53, n=334, seg+ 3):**
satu-satunya kandidat yang melewati mayoritas gate pada horizon 72 jam — tapi S=1,39 < 2,3,
mean 22,2 bps ≪ 80 bps target, dan **gagal bereplikasi di SoDEX real** (H72: −4,88 t=−0,38,
n=42; H48: +4,16 t=0,42). Di BVDOWN, kontrol acak Binance H72 (t=−2,44) dan sodex_real H30
(t=−7,11) lebih negatif dari sinyal → sinyal tidak mengalahkan konstruksinya di venue target.
Anchoring 52w harus dibaca dengan caveat: anchor dipendekkan ke 720j karena era real hanya
4,4 bulan — bukan uji George-Hwang yang sesungguhnya. VOLPREM mati konsisten (t 0,34–0,38).

**Kesimpulan Uji #1b:** tidak ada yang lolos; satu pola momentum-risk-adjusted di Binance
72j dicatat sebagai petunjuk forward (PETA #2), bukan dasar alokasi modal. Konfirmasi
replikasi di SoDEX real adalah syarat mutlak sebelum uji lanjutan.

---

## 6. Uji #2 — Time-series momentum & breakout

**Celah yang ditemukan:** `run_mech` **selalu** market-neutral (`excess = fwd − fwd.mean()`)
dan rank-weight. Artinya keluarga dengan bukti literatur **terkuat** untuk 30–72 jam —
time-series momentum directional (Dobrynskaya 2026; Han/Kang/Ryu RAPS; Zarattini 2026) —
**secara arsitektur tidak bisa diuji** oleh harness beku. Ini bukan asumsi: sudah
diverifikasi di kode (baris 209–215 `xsec_mech_study.py`).

**Alat baru:** `scripts/research/ts_mech_h30h72.py` — TSMOM (sign return L=168j/336j) dan
Donchian breakout, gross exposure 1,0, **benchmark beli-tahan wajib** sebagai pembanding.

**Hasil SoDEX real era (3 244 bar, 95 simbol):**

| Mekanisme | H | mean (bps) | t | S | Bench mean | Bench S | Verdict |
|---|---|---|---|---|---|---|---|
| TSMOM_L168 | 24 | −5,45 | −0,77 | −0,66 | +13,05 | 1,09 | kalah |
| TSMOM_L168 | 30 | +1,69 | 0,16 | 0,18 | +16,63 | 1,15 | kalah |
| TSMOM_L168 | 48 | −15,82 | −2,90 | −1,09 | +26,95 | 1,14 | kalah (signifikan negatif) |
| TSMOM_L168 | 72 | −41,05 | −5,50 | −1,56 | +38,44 | 1,06 | kalah (signifikan negatif) |
| TSMOM_L336 | 72 | +40,44 | 2,62 | 1,94 | +38,44 | 1,06 | **= beta**, bukan alpha |
| BRK_L168/L336 | semua | — | nan | nan | — | — | **n = 1–3 → INVALID** |

**Hasil Binance full (24 276 bar, 54 simbol, 5,5 tahun):**

| Mekanisme | H | mean (bps) | t | S | Bench mean | Verdict |
|---|---|---|---|---|---|---|
| TSMOM_L336 | 30 | +12,85 | 1,26 | 0,70 | +14,57 | kalah dari beli-tahan |
| TSMOM_L336 | 48 | +18,25 | 1,21 | 0,64 | +23,89 | kalah |
| TSMOM_L336 | 72 | +28,45 | 1,92 | 0,68 | +34,82 | kalah |

**Kesimpulan Uji #2 (dua venue, 30 trial, 0 pass):**
1. Time-series momentum di 2024–2026 **tidak mengalahkan beli-tahan** — persis peringatan
   literatur bahwa trend crypto pasca-2021 adalah **beta**, bukan alpha.
2. Di SoDEX real era, momentum 7 hari justru **terbalik** di 48–72 jam (t −2,90 / −5,50,
   n 42–63) — tanda bahwa token ekuitas + kripto di venue ini mean-reverting di horizon itu.
   Namun n kecil & lag NW besar → status: **petunjuk, bukan bukti**.
3. Breakout **tidak teruji**, bukan terbukti gagal: desain ternary (±1/0) dengan syarat ≥20
   nama aktif serentak membuatnya jarang menyala (n=1–25). Perlu versi rank
   (jarak ke high 168j sebagai skor kontinu) sebelum boleh disebut gugur.

---

## 7. Uji #3 — Verifikasi n kecil

**Masalah:** `xsec_mech_study.nw_t` meng-clamp lag ke `min(lag, n−1)`. Untuk H72 dengan
n=44, lag efektif = 43 — bandwidth ≈ n. Estimator Newey-West dengan bandwidth sebesar sampel
**bias turun** → t inflasi. Semua "signifikan" di H48/H72 dengan n ≤ hold wajib dicurigai.

**Alat:** `scripts/research/verify_small_n_h30h72.py` — t_plain, t_nw(lag=1), t_nw(lag=hold),
t_nw(lag=n/4), bootstrap blok stasioner 5 000×, permutasi 200×.

**Hasil (8 kandidat, 8 GAGAL):**

| Key | n | mean bps | t_plain | t_lag1 | t_lag_hold | CI95 bootstrap | p_perm | Verdict |
|---|---|---|---|---|---|---|---|---|
| RANGEPOS_H24 | 134 | +5,30 | 0,81 | 0,78 | 0,86 | [−8,0; +19,0] | 0,005 | GAGAL |
| RANGEPOS_H30 | 107 | +6,62 | 0,84 | 0,81 | 1,15 | [−9,7; +22,8] | 0,035 | GAGAL |
| RANGEPOS_H48 | 66 | −3,76 | −0,30 | −0,31 | −1,19 | [−20,9; +13,6] | 0,460 | GAGAL |
| **RANGEPOS_H72** | **44** | **+20,68** | **1,39** | **1,61** | **5,42** | **[−2,0; +42,9]** | 0,045 | **GAGAL** |
| LTREV_L180_H72 | 42 | +21,88 | 0,84 | 0,95 | 2,07 | [−22,4; +69,7] | 0,135 | GAGAL |
| REV_IDIO_H30 | 106 | +7,50 | 0,80 | 0,84 | 0,90 | [−9,8; +26,4] | 0,035 | GAGAL |
| MOM_L63_H72 | 44 | +2,82 | 0,09 | 0,11 | 0,38 | [−37,2; +44,6] | 0,265 | GAGAL |
| MOM_L21_H24 | 134 | −24,26 | −2,66 | −2,43 | −2,94 | [−43,4; −3,3] | 0,875 | GAGAL |

**Studi kasus RANGEPOS_H72:** panel melaporkan t = 4,20; dengan lag=hold menjadi 5,42;
dengan lag=1 **turun ke 1,61**; bootstrap CI95 [−2,0; +42,9] **memuat nol**. Setelah patch
harness v2 (lag sah = 11, lihat §8b) angka finalnya **t = 2,00** — tetap tidak lolos. Ini contoh
sempurna bahwa satu angka t bisa dibuat terlihat "signifikan" hanya dari pilihan bandwidth.
Angka itu **bukan edge** — dan jika dipakai untuk mengalokasikan modal di n=44, itu
pertaruhan, bukan strategi.

---

## 8. Tiga cacat metodologi yang ditemukan

| # | Cacat | Dampak | Perbaikan | Status |
|---|---|---|---|---|
| 1 | `nw_t(lag=hold)` saat n ≤ 2×hold | t H48/H72 inflasi (4,20 → 2,00 dengan lag sah; ekstrem 5,42 pada lag=n−1) | `safe_lag = min(hold, max(1, n//4))`, laporkan `t_lag`, tolak t bila n<8 | **DIPATCH 2026-10-25** — lihat §8b |
| 2 | ~~Kontrol shuffle tidak sah untuk sinyal ternary~~ **DIKOREKSI**: shuffle **per bar lintas nama** (`xsec_mech_study` baris 212–224) = permutasi peringkat yang **SAH** untuk sinyal kontinu maupun ternary | Bukan cacat validitas; yang nyata adalah **daya rendah**: sinyal ternary penuh nol (mis. 2 dari 25 nama non-nol) → permutasi nyaris tidak mengubah bobot → t_kontrol ≈ t_sinyal secara mekanis, sehingga kontrol tidak informatif | Laporkan fraksi ties/kerapatan sinyal bersama t_kontrol; bila ingin daya lebih tinggi, bandingkan dengan sinyal biner acak berkerapatan sama (bukan mengganti jenis kontrol) | **DIKOREKSI 2026-10-25** (audit ulang kode) |
| 3 | Segmen butuh n ≥ 90 (3×30) → H72 (n 42–45) tak punya segmen | Kandidat H72 tak bisa diuji stabilitas | Segmen tetap disyaratkan n≥90 (**gate tidak dilonggarkan**); tambah penanda eksplisit `segments_untested: true` agar "tak teruji" tidak muncul sebagai `None` mengambang | **DIPATCH 2026-10-25** |

Ketiganya **tidak** membatalkan verdict (semua jalan menuju arah yang sama: gagal), tetapi
wajib diperbaiki sebelum trial berikutnya — kalau tidak, kita akan terus "menemukan"
signifikansi palsu di horizon panjang.

---

## 8b. Verifikasi patch (harness v2 — 2026-10-25)

Patch diterapkan ke `xsec_mech_study.py` (`HARNESS_VERSION = "v2-2026-10-25-nwlag"`,
`safe_lag`, `t_lag`, `segments_untested`), lalu **seluruh panel dijalankan ulang** dari sumber
data yang sama. Panel beku 7-Okt (`PRAREG_PANEL_PANJANG_*`) **tidak disentuh** — mtime tetap
2026-10-07/08, md5 tetap; hanya panel turunan yang dihitung ulang.

**Uji unit (kunci perilaku):** `tests/test_xsec_harness_nwfix.py` — 6/6 lulus
(`lag ≤ n//4`, `n<8 → t=nan`, `segments_untested` benar, `nw_t` NaN untuk n kecil).

**Dampak pada hasil (404 baris trial dibandingkan, seluruh berkas):**

| Panel | Trial | t terbaik **sebelum** | t terbaik **sesudah** | lag | n | Sharpe | Lulus? |
|---|---:|---:|---:|---:|---:|---:|---|
| SoDEX real (H30–72) | 72 | 4,20 | **2,00** | 11 | 44 | 2,30 | 0 |
| SoDEX full | 72 | 1,95 | 1,94 | 38 | 155 | 1,43 | 0 |
| Binance full | 96 | 1,92 | 1,92 | 30 | 806 | 1,49 | 0 |
| Lit-gel.2 SoDEX real | 32 | 0,73 | 0,73 | 25 | 102 | 0,99 | 0 |
| Lit-gel.2 SoDEX full | 32 | 2,19 | **1,75** | 38 | 152 | 1,19 | 0 |
| Lit-gel.2 Binance | 40 | 3,10 | 3,10 | 72 | 334 | 1,39 | 0 |
| TS SoDEX real | 28 | 2,62 | **1,81** | 10 | 40 | 1,94 | 0 |
| TS Binance | 32 | 1,92 | 1,92 | 72 | 332 | 0,68 | 0 |

**SoDEX real — 5 teratas setelah koreksi (venue yang diminta):**

| Mekanisme | t baru | t lama | lag | n | Sharpe | Verdict |
|---|---:|---:|---:|---:|---:|---|
| RANGEPOS_H72 (fee 1×) | 2,00 | 4,20 | 11 | 44 | 2,30 | tidak lolos (ambang 3,48–3,61) |
| RANGEPOS_H72 (fee+slip) | 1,88 | 3,91 | 11 | 44 | 2,16 | tidak lolos |
| LTREV_L180_H72 | 1,17 | 2,27 | 10 | 42 | 1,46 | tidak lolos |
| RANGEPOS_H30 | 1,16 | 1,14 | 26 | 107 | 1,40 | tidak lolos |
| LTREV_L180_H72 (fee+slip) | 1,13 | 2,20 | 10 | 42 | 1,41 | tidak lolos |

**Bacaan:**

1. Patch bersifat **bedah**: Binance (n besar, `lag=hold` sudah sah) **tidak berubah sama sekali**
   (Δt = 0,00); yang berubah hanya trial dengan n ≤ 4×hold — tepat seperti desain.
2. Inflasi terbesar ada di H72 SoDEX real: **4,20 → 2,00** (−52%). Ini membalik status
   RANGEPOS_H72 dari "kandidat kuat" menjadi "tidak signifikan setelah koreksi bandwidth".
3. **Tidak ada satu pun** dari 404 baris yang lulus gate, sebelum maupun sesudah patch
   (0 → 0). Verdict tidak berubah; yang berubah adalah **kekuatan klaim** — sekarang
   angka yang tersisa sudah tidak bisa dituduh sebagai artefak lag.
4. Sharpe annual hampir tidak bergeser (perbedaan kecil berasal dari data yang ter-refresh,
   bukan dari patch): Sharpe tidak memakai lag NW, jadi ini uji konsistensi tambahan.

---

## 9. Yang mati, yang belum teruji, yang masih mungkin

**Mati (dengan bukti, jangan diulang tanpa alasan baru):**

| Keluarga | Bukti kematian |
|---|---|
| Momentum cross-sectional L21/L63 | PRAREG-28/29 + panel hari ini; kontrol negatif lebih kuat dari sinyal |
| Reversal 21 jam | PRAREG-3 OOS t=0,38; artefak harga basi (14–31% bar equity return nol) |
| Reversal harian RANGEPOS | PRAREG-1/2 + verifikasi hari ini (8/8 gagal) |
| Carry/funding satelit | PRAREG-23-H2: plafon 3,6× di bawah lantai; data 22 hari |
| Maker / market-making | Spread 0,08–1,03 bps < fee 2,28 bps → mustahil secara aritmetika |
| Short-only | Semua buku negatif (memory: 7 mesin −$522 vs 3 mesin +$363) |
| Time-series momentum 30–72j | Uji hari ini: kalah dari beli-tahan di 2 venue |
| Grid single-name 1.080 uji | 0 lolos BH (docs/HASIL_72J_DAN_GRID_1080) |

**Belum teruji (layak, dengan syarat data):**

| # | Jalur | Syarat | Cara uji falsifiable |
|---|---|---|---|
| A | **Seleksi mesin / meta-labeling** | riwayat ≥ 300 trade/mesin | pilih 3 mesin teratas rolling 30 hari; bandingkan WR/expectancy vs semua-mesin; kontrol = pilih acak |
| B | Breakout versi **rank kontinu** | OHLCV | jarak-ke-high 168j sebagai skor; uji H30/48/72 dengan harness yang diperbaiki |
| C | Gate rezim (HMM/vol bucket) | OHLCV + vol | matikan mesin saat rezim X; uji ΔPnL vs tanpa gate |
| D | Event/kalender 24–72j (listing, unlock, makro) | kalender event | event study: abnormal return window ±72j, bootstrap |
| E | Lead-lag BTC → alt | OHLCV 1m/1h | regresi lag; uji OOS; kontrol = acak pasangan |
| F | OI/forced-flow forward | collector 15s ≥ 60 hari | pra-registrasi sekarang, verdict 25-Nov |

**Kesimpulan §9:** dari 7 keluarga, 1 sudah mati total (5, 6), 1 belum diuji dan paling
menjanjikan (7 = meta/seleksi mesin), 4 mati untuk horizon ini. Tidak ada jalur sinyal baru
yang punya bukti kuat dan belum dicoba **kecuali** B dan F — keduanya butuh data/perbaikan
alat dulu, bukan opini.

---

## 10. Rekomendasi falsifiable + cara verifikasi

**R1 — Jangan tambah mesin sinyal H30/48/72. (Keputusan: sekarang)**
Dasar: 120 trial CS + 30 TS + 8 verifikasi = 0 lolos. Menambah mesin = multiple testing
tanpa kekuatan.

**R2 — Perbaiki harness sebelum trial berikutnya. (SELESAI 2026-10-25)**
`lag = min(hold, max(1, n//4))` + `t_lag` transparan + `segments_untested` eksplisit; gate tidak
dilonggarkan. **Verifikasi terpenuhi:** panel dijalankan ulang (harness v2), H48/H72 berubah
(4,20 → 2,00; 2,62 → 1,81; 2,19 → 1,75), Binance n besar tidak berubah (Δt = 0,00), 0 dari 404
baris lulus sebelum maupun sesudah. Uji unit: `tests/test_xsec_harness_nwfix.py` 6/6 lulus.

**R3 — Uji jalur A (seleksi mesin), pra-registrasi terpisah. (1 hari desain)**
Hipotesis: memilih 3 mesin teratas rolling 30 hari menghasilkan expectancy bersih > semua-
mesin, dengan WR lebih tinggi.
**Lulus jika:** Δnet > 0, t ≥ 2,0, kontrol pemilihan acak gagal, dan hasil bertahan di
2 segmen. **Gagal jika:** delta ≤ 0 atau kontrol ikut menang.
Bukti pendukung internal: 3 mesin +$363,57 vs 7 mesin −$522,11 (buku 2 051 trade).

**R4 — Pra-registrasi F (OI/forced-flow forward) sekarang, verdict 25-Nov.**
Collector `anantara-forced-flow` sudah jalan (OI 15s). Syarat n ≥ 60. Tanpa pra-registrasi
sekarang, data 60 hari akan habis untuk post-hoc.

**R5 — Uji ulang RANGEPOS_H72 hanya jika n ≥ 100 forward.**
Bukan sekarang. Angka sekarang = pertaruhan, bukan edge.

---

## 11. Keterbatasan, keyakinan, dan lampiran

**Keterbatasan yang harus dibaca sebelum memakai dokumen ini:**
1. Era real SoDEX hanya 4,4 bulan (3 244 bar). Semua verdict venue ber-n kecil.
2. Volume era mirror fabrikasi → semua analisis volume/likuiditas **hanya sah** di era real.
3. Breakout belum teruji (n terlalu kecil) — jangan dikutip sebagai "gagal".
4. Panel Binance memakai 54 simbol top; hasil tidak otomatis berlaku untuk 95 simbol SoDEX.
5. Semua hasil = **deskriptif historis**, bukan OOS forward. Yang menentukan adalah forward.
6. Hasil net = net-of-fee saja; funding-drag H30–72j (3,75–27 bps) belum termasuk → angka
   H48/H72 = batas atas kondisi riil.
7. Konteks multiple-testing (peta gel.-1): best-of-200 strategi nol-skill bisa mencetak
   Sharpe 2,12 (PSR 0,9999, DSR 0,81); N=250 trial → E[max Sharpe] ≈ 1,34. Dengan 210 trial
   hari ini, ambang S 2,3 + BH-FDR adalah minimum, bukan kemewahan.

**Tingkat keyakinan:**

| Klaim | Keyakinan |
|---|---|
| Tidak ada metode CS H30/72 yang lolos gate | **Tinggi** (120 trial, kontrol jalan, konsisten) |
| TS momentum ≤ beli-tahan di 2 venue | **Tinggi** (5,5 th Binance + 4,4 bln SoDEX) |
| RANGEPOS_H72 bukan edge | **Tinggi** (bootstrap + permutasi + lag sah) |
| Era mirror = data sintetis | **Tinggi** (n=0 + corr 1,0000 + volume tetap) |
| Breakout gagal | **Rendah** — belum teruji, jangan dikutip |

**Lampiran — artefak & reproduksi:**

```
reports/sodex/PANEL_EXTEND_H30H72_sodex_full.json     36 trial
reports/sodex/PANEL_EXTEND_H30H72_sodex_real.json     36 trial
reports/sodex/PANEL_EXTEND_H30H72_binance_full.json   48 trial
reports/sodex/TS_MECH_H30H72_sodex_real.json          14 trial
reports/sodex/TS_MECH_H30H72_binance_full.json        16 trial
reports/sodex/LIT_NEW_MECHS_H30H72_sodex_full.json    16 trial (gelombang 2)
reports/sodex/LIT_NEW_MECHS_H30H72_sodex_real.json    16 trial (gelombang 2)
reports/sodex/LIT_NEW_MECHS_H30H72_binance_full.json  20 trial (gelombang 2)
reports/sodex/VERIFIKASI_N_KECIL_H30H72_sodex_real.json  8 kandidat, 200 permutasi
reports/sodex/LEDGER_TRIAL_H30H72_2026-10-25.json     ledger ringkas semua gelombang
reports/sodex/AUDIT_NWFIX_DIFF.json                    404 baris: t lama vs t baru (harness v2)
reports/sodex/AUDIT_PRAREG26_INDEPENDEN.json           replikasi independen PRAREG-26
reports/sodex/*_pre_nwfix.json                         artefak pra-patch (pembanding, jangan dihapus)
scripts/research/panel_extend_h30h72_descriptive.py
scripts/research/ts_mech_h30h72.py
scripts/research/lit_new_mechs_h30h72.py
scripts/research/verify_small_n_h30h72.py
scripts/research/audit_prereg26_independen.py          audit ganda PRAREG-26 (ditulis dari nol)
tests/test_xsec_harness_nwfix.py                       6 test: safe_lag, nan n<8, segmen
tests/test_sodex_wallet_failclosed.py                  3 test: denominator fail-closed
docs/sodex/AUDIT_PRAREG26_DENOMINATOR_2026-10-25.md    memo audit denominator + replikasi
docs/sodex/PETA_LITERATUR_METODE_BARU_2026-10-25.md   12 metode, sitasi + link
```

Reproduksi:

```bash
/usr/bin/python3 scripts/research/panel_extend_h30h72_descriptive.py sodex_full sodex_real binance_full
/usr/bin/python3 scripts/research/ts_mech_h30h72.py sodex_real binance_full
/usr/bin/python3 scripts/research/lit_new_mechs_h30h72.py sodex_real sodex_full binance_full
/usr/bin/python3 scripts/research/verify_small_n_h30h72.py
```

**Sumber literatur utama (26 total di peta):** Dobrynskaya (SSRN 3913263); Han/Kang/Ryu
(SSRN 4675565); Zarattini et al., *Catching Crypto Trends* (SFI RP 25-80); López de Prado,
*Advances in Financial Machine Learning* ch. 3; Robot Wealth (meta-labelling, index-of-
strategies); Quantpedia; Applied Economics Letters (crypto reversals 2020); VSE WP 2023/01/03.

---

*Dokumen ini deskriptif. Tidak ada parameter produksi, target, atau gerbang yang diubah.
Semua angka dapat direproduksi dari artefak di atas.*
