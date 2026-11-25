# ANALISA ULANG VIABILITAS SoDEX — 2026-10-25

**Pertanyaan Mas Anas (verbatim):** *"jadi intinya project sodex ini telah gagal karena tidak mungkin bisa dilanjutkan di real trading nyata dengan dana nyata pada 01 Desember 2026 ataupun pada 01 Januari 2027, dikarenakan tidak mungkin ada edge yang bisa mencapai targetnya? benar begitu ya? atau bagaimana? apakah tidak ada solusi lain atau jalan keluar lainnya?"*

**Metode analisa ulang:** kontrol acak vs mesin per era, CUSUM flip-date, dekomposisi gate pra/pasca-flip, korelasi per-era (uji Simpson), bootstrap blok mingguan honest, matematika target, kaidah PRAREG-26. Semua angka di bawah dihitung dari state paper aktual hari ini (`data/paper_test_*_state.json`, 2.619 trade dedup; RANDOM dikecualikan dari buku mesin).

---

## 1. JAWABAN LANGSUNG

**Tidak, pernyataan itu tidak persis benar — tapi kesimpulan operasionalnya mendekati benar untuk tanggal yang disebut.**

Pisahkan tiga klaim yang tercampur:

| Klaim | Verdict bukti |
|---|---|
| (a) Buku mesin sekarang rugi dan tidak mencapai target | **BENAR, terbukti angka** |
| (b) Real trading dana nyata pada 01-Des-2026 buku ini = melanggar disiplin riset sendiri | **BENAR** |
| (c) TIDAK MUNGKIN ada edge yang bisa mencapai target (gagal total, tidak ada jalan keluar) | **TIDAK TERBUKTI — ini melewati bukti** |

Yang terbukti: **satu keluarga edge (momentum/reaksi pada 10 mesin sinyal) mati sejak ~25-Sep-2026 pada venue SoDEX dengan biaya taker ~11,4 bps**. Yang belum terbukti: bahwa *tidak ada edge lain* yang bisa mencapai target. Itu klaim universal yang tidak bisa dibuktikan dari data 10 mesin momentum.

---

## 2. BUKTI LENGKAP (semua dihitung hari ini)

### 2.1 Buku penuh: rugi struktural
- 2.232 trade mesin (RANDOM dikecualikan): gross **+2,09 bps**, net **−8,03 bps**, total **−$507,20**, hit 38,1%.
- Biaya riil **11,39 bps/trade** (gross − net per trade). Gross buku hanya 3,4 bps → rugi *sebelum* memilih sinyal.

### 2.2 Kontrol acak: mesin TIDAK sedang anti-prediktif… kecuali pasca-flip
| Era | Mesin gross | RANDOM gross | Delta | t |
|---|---:|---:|---:|---:|
| Semua era | +2,09 (n=2.232) | −17,93 (n=387) | +20,0 bps | — |
| Pra-flip (<25-Sep) | **+28,06** (n=1.400) | tidak ada data RANDOM | — | — |
| Pasca-flip | **−41,60** (n=832) | −17,93 (n=387) | **−23,68 bps** | **t = −2,40** |

**Bacaan:** pasca-flip, mesin "terbaik" bukan hanya rugi — ia **lebih buruk dari lempar koin** secara signifikan (t=−2,40). Ini menunjukkan sinyal momentum pasca-flip bersifat *counter-productive* (terbalik), bukan sekadar noise.

### 2.3 Flip edge: CUSUM menempatkan pergantian di akhir September
CUSUM gross mingguan 3 mesin: puncak **2026-W39** (±24–30 Sep), lembah W33. Konsisten dengan flip ~25-Sep yang terdeteksi sebelumnya.

### 2.4 Kinerja pasca-flip buku 3 mesin = resep likuidasi
30 hari terakhir: **20 window, mean −8,19%/window, total −$398,06** (≈ −164% wallet dalam ~25 hari). Di real dengan dana nyata, buku ini akan **ter-likuidasi** jauh sebelum sebulan — bukan sekadar tidak mencapai target.

### 2.5 Gate volatilitas: memisahkan ARAH, belum menghasilkan LABA
Dekomposisi window ON gate (`vol7 ≥ median 12 window`) sesuai aturan beku + Amandemen-1 (kosong dilewati):

| Kelompok | n | mean | median | hit | worst |
|---|---:|---:|---:|---:|---:|
| ON pra-flip | 13 | **+12,71%** | +14,16% | 69,2% | −25,55% |
| ON pasca-flip (dengan kosong) | 11 | −1,51% | 0,00% | 36,4% | −34,54% |
| ON pasca-flip (tanpa kosong) | 8 | **−2,07%** | +1,86% | 50,0% | −34,54% |
| OFF pasca-flip | 13 | **−11,44%** | −5,72% | 23,1% | −35,81% |

- Gate **masih memisahkan arah** pasca-flip: ON −2,07% vs OFF −11,44% (selisih ~9 poin) — ia menghindari window terburuk.
- Tapi **keduanya negatif**: gate yang benar pun belum menghasilkan laba di rezim sekarang.
- Mean in-sample penuh (+6,19%) adalah **artefak era pra-flip**: 3 window terbaik menyumbang 104,6% dari seluruh profit gate. Kutip angka itu sebagai bukti = kesalahan seleksi.

### 2.6 Korelasi vol→gross pooled adalah Simpson's paradox
Pooled r = +0,59 → **per era**: pra-flip r = −0,41 (n=8 minggu), pasca-flip r = −0,15 (n=5). Motivasi mekanistik gate lebih lemah dari tertulis; sudah dicatat di Amandemen-1 §6 demi transparansi. Uji tetap jalan karena dibekukan sebelum forward.

### 2.7 Probabilitas lolos target — UPPER BOUND (asumsi rezim tidak berubah)
Bootstrap blok dari 11 window ON pasca-flip aktual (distribusi: −34,5; −27,3; −21,3; −0,8; 0; 0; 0; +1,1; +20,5; +21,4; +24,3):

| Horizon | P(A: mean ≥ 0,8%) | P(B: median>0 & hit ≥ 50%) | **P(A dan B)** |
|---|---:|---:|---:|
| 12 window | 33,8% | 24,4% | **19,0%** |
| 24 window | 27,6% | 12,4% | **10,1%** |

Ini **plafon optimistis** (asumsi masa depan identik pasca-flip in-sample). Realita bisa lebih rendah (rezim berubah lagi) — atau lebih tinggi kalau rezim momentum kembali hidup. **Menunggu lebih lama tidak menaikkan peluang** (24w < 12w): buku ini tidak menyembuhkan dirinya sendiri dengan waktu.

### 2.8 Matematika target vs kenyataan
Butuh **8,9–16 bps net/trade** (9–15 trade/window, ukuran 50–100% wallet). Pasca-flip net mesin terbaik: **−59 bps**. Selisih yang harus ditutup: **±70 bps/trade** — itu bukan penalaan parameter; itu perubahan rezim/pasar atau keluarga strategi berbeda.

### 2.9 PRAREG-26 (seleksi 14d net>0): filter anti-momentum, terukur hit 32,2%
Aturan memilih mesin *setelah* edge mati dan butuh 14 hari lagi saat edge hidup → subset kosong 14/14 titik → M3/M4 gagal. Verdict 25-Nov kemungkinan besar **TIDAK LOLOS** — bukan karena salah tulis, tapi karena desainnya tertinggal dari flip.

### 2.10 Batas data yang jujur
- RANDOM hanya ada pasca-flip → kontrol acak pra-flip tidak bisa diuji.
- n pasca-flip: 832 trade, 11 window ON, 5 minggu — kecil; semua probabilitas di §2.7 punya lebar besar.
- `spot_swing_v2` tidak terukur di audit gross (state tanpa `pnl_pct`).
- Semua angka = paper fill model `poll`; real bisa lebih buruk (slippage/spread).

---

## 3. KENAPA TANGGAL 01-DES / 01-JAN MENENTUKAN

- **01-Des-2026** = ±30 window 30 jam dari sekarang. PRAREG-31 selesai **25-Nov** (24 window) → verdict ada **6 hari sebelum** 01-Des. Jadi keputusan real 01-Des **bisa** berbasis data forward, bukan opini — syaratnya disiplin menunggu verdict.
- **01-Jan-2027** = ±54 window. Melimpah untuk verdict, tapi per §2.7, waktu tambahan **tanpa perubahan buku** malah menurunkan peluang (10,1% pada 24 window). Waktu bukan obatnya; bukti buku baru-lah obatnya.

**Kaidah keputusan (disiplin, bukan opini):**
```
IF PRAREG-31 verdict 25-Nov = LOLOS (A-E semua)
   → layak masuk tahap berikutnya: pilot real ukuran mikro (≤ 10% wallet),
     kill-switch harian, BUKAN full deployment.
ELSE
   → TIDAK layak real pada 01-Des. Titik. Lanjut paper / ganti jalur edge.
```
Melanggar ini dengan dana nyata = melanggar standar riset yang menjadi fondasi semua project Anantara (n≥30/OOS/kontrol negatif).

---

## 4. JALAN KELUAR — 5 NYATA, DENGAN SYARAT DAN PELUANG JUJUR

### Jalur A — Selesaikan PRAREG-31 (sudah berjalan, biaya 0)
Forward 26-Okt→25-Nov, pengawal harian cron 07:00. **Peluang prior ≤19%** (upper bound §2.7). Kalau LOLOS → satu-satunya jalan sah menuju real pilot 01-Des. Kalau gagal C/D (gate tidak mengalahkan acak) → jalur gate ditutup, TANPA menambah ambang baru (anti-snooping).

### Jalur B — Ganti KELUARGA edge, bukan parameter (riset baru, 4–8 minggu)
Keluarga momentum harian terbukti mati. Keluarga yang strukturnya berbeda dan belum diuji di buku ini:
1. **Mean-reversion likuiditas intra-window** (hold < 8 jam, fokus disannonisasi spread) — biaya taker 11,4 bps menyulitkan; perlu protokol entry pasif.
2. **Event/schedule-driven** (listing, funding settlement 8h, pembakaran/unlock) — rezim-dependen lebih rendah.
3. **Cross-venue basis/funding** (HL-Harvest infrastruktur sudah ada) — delta-neutral; jujur: yield normalnya ~0,1–0,3%/30 jam, **tidak mencapai 0,8% sendirian**, tapi menjadi penyumbang stabil.
Standar masuk yang sama: pra-registrasi beku + forward + kontrol acak. BUKAN tuning mesin lama.

### Jalur C — Venue shift untuk edge yang sama (evaluasi murah, 1–2 minggu)
Alpha pra-flip (+28 bps gross) di Binance maker (RT ~4–5 bps) atau Hyperliquid (~3–4 bps) menyisakan net positif jauh lebih tebal; di SoDEX taker-only biaya 11,4 bps memakan separuh gross. **Batas jujur:** ini memperbaiki biaya, BUKAN menghidupkan alpha yang sudah mati pasca-flip — pasca-flip gross mesin −41 bps di venue manapun tetap rugi. Berguna hanya jika edge hidup kembali ATAU diuji di venue dengan data yang lebih panjang (Binance 24.276 bar vs SoDEX 3.244 bar real → kekuatan statistik 7× lebih baik).

### Jalur D — Rekalibrasi target/window (WENENANG USER, bukan keputusan saya)
Target 0,8% per window 30 jam = ~19%/bulan compound (~230%/tahun) — kelas risiko hedge-fund-teragresif. User-lah pemegang otoritas harga mati ini. Pilihan yang bisa didiskusikan: 0,8%/minggu, atau 0,8%/bulan, atau definisi window berbeda. **Catatan jujur:** bahkan 0,8%/bulan (mean 0,027%/window) TIDAK dicapai buku pasca-flip sekarang (−2,07%/window ON) — jadi rekalibrasi target TANPA ganti buku tetap berakhir gagal. Rekalibrasi hanya bermakna setelah ada buku yang tak-rugi.

### Jalur E — Stop terukur (bukan menyerah, tapi memotong kerugian riset)
Kalau pada 25-Nov: PRAREG-31 gagal DAN PRAREG-26 gagal (diperkirakan) → keputusan disiplin: **tutup jalur SoDEX momentum, realokasi waktu riset ke Binance/HL** (venue dengan data panjang dan biaya rendah), dokumentasikan verdict. Ini bukan kegagalan project — ini ilmiah: hipotesis difalsifikasi, modal dan waktu diselamatkan.

---

## 5. APA YANG SAYA REKOMENDASIKAN (urutan, dengan tanggal)

| Tanggal | Aksi |
|---|---|
| 26-Okt s.d. 25-Nov | Jalur A berjalan otomatis (cron 07:00). Sambil menunggu: Jalur C evaluasi (murah, data panjang Binance), dan mulai pra-registrasi keluarga edge baru (Jalur B#2 event-driven) untuk di-forward Desember. |
| 25-Nov | Verdict ganda: PRAREG-26 + PRAREG-31. |
| 26–30-Nov | Kalau ada yang LOLOS → pilot real mikro (≤10% wallet, kill-switch). Kalau semua gagal → Jalur E: stop SoDEX momentum, realokasi. |
| 01-Des-2026 | Real penuh **hanya** jika pilot mikro positif + verdict lolos. Skenario ini probabilitasnya rendah (≤19%) — jujur dari sekarang. |
| 01-Jan-2027 | Titik evaluasi buku baru (Jalur B/C) dengan data forward Desember penuh. |

---

## 6. SATU KALIMAT PENUTUP

Buku momentum SoDEX **pada rezim saat ini** terbukti rugi struktural dan bahkan lebih buruk dari acak (t=−2,40) — real pada 01-Des dengan buku ini melanggar disiplin sendiri; TAPI "tidak mungkin ada edge yang mencapai target" **belum terbukti** — yang benar: edge keluarga ini mati, gate volatilitas masih menyisakan pemisahan arah yang layak diuji (peluang ≤19%), dan ada 4 jalur keluar lain yang belum difalsifikasi — semuanya butuh bukti forward, bukan opini, dan jadwal 01-Des hampir pasti terlalu cepat untuk semuanya kecuali verdict PRAREG-31.

---
*Dokumen analisa ulang 2026-10-25 · READ-ONLY terhadap semua mesin/protokol berjalan · angka reproduksi: lihat §7 dokumen RISET_KAPASITAS_DAN_GATE_VOLATILITAS_2026-10-25.md dan evaluator PRAREG-31.*
