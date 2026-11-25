# REKONSILIASI TUJUAN · TARGET · TIMELINE — SoDEX vs Master Spec V2

**Tanggal:** 22-Okt-2026 · **Metode:** baca 11 bagian V2 + 12 dokumen keputusan internal (file:line/tanggal), bandingkan baris-per-baris, tandai KONSISTEN/KONTRADIKSI/BELUM DIPUTUSKAN. Tidak ada angka yang diasumsikan.
**Status dokumen V2:** rekomendasi eksternal, *"belum backtest, LiveTradePermission = NO"* — bukan keputusan proyek, harus diuji seperti dokumen lain.

---

## 0. Temuan paling penting (baca ini dulu)

**Proyek SoDEX kita sendiri — bukan V2 — punya DUA target dan DUA timeline yang berjalan paralel sejak 9–10 Okt, dan belum pernah direkonsiliasi satu sama lain.** V2 hanya mempertegas bahwa sejak awal sudah ada ketidaksinkronan internal:

| Track | Lahir | Target | Horizon | Leverage | Deadline | Status implementasi (22-Okt) |
|---|---|---|---|---|---|---|
| **Track-55** (α/Kelly) | 9-Okt, `AMANDEMEN_ATURAN_2026-10-09` | 0,8%/48 jam | ≤55 jam diizinkan | **DIIZINKAN** (half-Kelly) | **Sertifikasi 20-Nov**, S≥5,76 | **0 baris kode leverage** di mesin aktif; horizon tetap 30 jam di semua engine |
| **Track-30** (A&B grid) | 10-Okt, `AMANDEMEN_TARGET_AB` | 0,8%/window | **30 jam** | tidak disebut (de facto 1×) | **Verdict 25-Nov**, give-up 30-Nov | **Aktif berjalan** — ini yang dipakai tracker resmi, PRAREG-26, PRAREG-27 |

Track-55 disetujui user 9-Okt, tidak pernah dicabut secara tertulis, masih disebut di `PROGRES_2026-10-19.md` baris P3 ("Sertifikasi 20-Nov, S≥5,76"). Tapi **sejak 10-Okt, seluruh implementasi nyata diam-diam pindah ke Track-30** tanpa amandemen yang menyatakan "Track-55 dibatalkan". Ini sendiri adalah pelanggaran terhadap prinsip yang nanti ditulis V2 ("jangan mengubah denominator/aturan tanpa amandemen tertulis") — **kita melanggar prinsip V2 sebelum V2 ada**.

**Pertanyaan yang harus dijawab user sebelum 20-Nov:** apakah Track-55 (sertifikasi S≥5,76, 20-Nov) masih berlaku, atau sudah digantikan Track-30 (verdict 25-Nov)? Tidak ada dokumen yang mencabutnya. **Saya akan menyarankan jawaban di §5**, tapi ini bukan keputusan saya.

---

## 1. TUJUAN — bandingkan filosofi dasar

| Dimensi | V2 (§01, §02) | Proyek SoDEX kita | Verdict |
|---|---|---|---|
| Sifat target | *"aspirasi, bukan jaminan, bukan alasan memaksakan transaksi"* | "**harga mati**" (user, berulang) — eksplisit bukan aspirasi | **KONTRADIKSI FILOSOFIS.** Bukan salah/benar, tapi dua cara pandang berbeda. V2 mengizinkan NO TRADE 48 jam; proyek kita menjalankan 18 mesin terus-menerus. |
| Prioritas | *"risk-first profitability, bukan memaksimalkan frekuensi/leverage/WR"* | R2 (9-Okt) "**leverage diizinkan**"; 18 arm paralel = tinggi frekuensi eksperimen | **SEBAGIAN KONTRADIKSI** — R2 belum pernah dieksekusi (0 leverage di kode), jadi tidak ada kontradiksi *praktik*, tapi kontradiksi *tertulis* |
| Definisi siklus | 1 keputusan portofolio, confirm dulu apakah 1-posisi atau multi-posisi; laporkan **dua metrik terpisah** | Tidak pernah diputuskan secara eksplisit; tracker resmi menghitung agregat semua posisi dalam window 30 jam (= multi-posisi), tanpa laporan per-posisi terpisah | **BELUM DIPUTUSKAN** — gap nyata, V2 benar menyoroti ini |
| Primary objective | ekspektasi bersih positif, bukan ROI absolut | sama — tapi diukur dengan leverage 7,4× (temuan F1 audit 21-Okt) | V2 **benar**; temuan F1 kita sudah menunjukkan masalah ini sebelum membaca V2 |

**Kesimpulan Tujuan:** Secara substansi tujuan kita (profit bersih wallet, swing 1-48 jam, SoDEX) **sejalan** dengan V2. Yang tidak sejalan adalah **sikap terhadap kewajiban bertransaksi** — proyek kita punya tekanan psikologis "harga mati" yang V2 secara eksplisit memperingatkan sebagai jebakan (memaksakan transaksi demi target).

---

## 2. TARGET — bandingkan angka dan definisi matematis

| Parameter | V2 | Track-55 (9-Okt) | Track-30 (10-Okt, aktif) | Verdict |
|---|---|---|---|---|
| Angka target | **0,4% DAN 0,8%**, dua ambang terpisah | 0,8% saja (0,4% hanya "kondisi pembatalan" bila α≤20bps) | 0,8% saja (0,4% ditolak eksplisit, `AMANDEMEN_3` opsi B) | **Kita lebih sempit dari V2** — sengaja, dan beralasan (dihitung, bukan selera) |
| Horizon | 1–48 jam (rentang) | ≤55 jam | **30 jam tetap** | **KONTRADIKSI ANTAR TRACK KITA SENDIRI** — V2 tidak bisa jadi wasit karena V2 sendiri pakai rentang, bukan angka tetap |
| Denominator E₀ | **Dibekukan di awal siklus**; dilarang diubah setelah hasil diketahui | tidak dibahas detail | `sodex_maturation_tracker.py` pakai **wallet hari ini** untuk 57 window historis | **KITA MELANGGAR V2 — dan ini G2, temuan sudah ada di `GAP_ANALYSIS_V2.md`** |
| Leverage | boleh, dengan HUMAN_APPROVAL_REQUIRED + risk cap | **diizinkan** half-Kelly per instrumen | **tidak ada** (semua arm 1×) | V2 netral; kita sendiri tidak konsisten (disetujui tapi tidak dipakai) |
| Cap eksposur/risk budget | wajib, HUMAN_APPROVAL_REQUIRED | diusulkan (tangga leverage, lantai likuidasi 30%) tapi **belum disetujui formal** | **tidak ada sama sekali** | **GAP G1 — kritis, confirmed V2 benar** |
| Pelaporan realized vs unrealized | wajib dua laporan terpisah | tidak dipisahkan | tidak dipisahkan (tracker campur closed+snapshot wallet) | **V2 benar, belum kita penuhi** |
| Breakeven & EV | formula wallet-level EV, bukan sekadar hit rate | dipakai (α, Kelly) | **tidak dihitung** di tracker 30h (hanya mean/median/hit) | **V2 benar — tracker 30h tidak menghitung EV_wallet formal** |

**Angka target numerik yang benar-benar diuji hari ini (Track-30, data 21-Okt):**

| Denominator | Mean/window | Hit ≥0,8% | Status |
|---|---|---|---|
| Wallet $243 (resmi, tapi melanggar V2 G2) | +1,146% | 47,4% | A lolos titik, CI memuat 0 |
| Buku $1.800 = 1× wallet (V2-compliant untuk leverage, tidak utk E0 freeze) | +0,155% | 28,1% | jauh di bawah |

**Kesimpulan Target:** Target kita **lebih disiplin dari V2 pada satu ambang (menolak floor 0,4%)**, tapi **lebih longgar dari V2 pada dua hal krusial**: denominator tidak dibekukan (G2), dan tidak ada cap risiko (G1). V2 benar pada kedua hal ini.

---

## 3. TIMELINE — semua tanggal yang pernah ditetapkan (urut, dengan sumber)

| Tanggal | Peristiwa | Dokumen sumber | Masih berlaku? |
|---|---|---|---|
| 30-Sep-2026 | **Freeze uang SoDEX** — `LIQ_DRY=1`, unit livetest nonaktif | `MONITOR_HANDOFF_2026-09-30.md` §67–71 | ✅ berlaku, dikonfirmasi ulang 9-Okt §5 |
| 9-Okt-2026 | Target 0,8%/48j dipertahankan + leverage diizinkan + horizon ≤55j | `AMANDEMEN_ATURAN_2026-10-09...` | ⚠️ **tidak pernah dicabut tertulis**, tapi tidak diimplementasikan sejak 10-Okt |
| 9-Okt-2026 | α minimum ditetapkan: 43,4 bps (target 0,8%), 29,1 bps (target 0,4%) | `AMANDEMEN_3_ANALISA_TARGET_040_VS_080.md` §7 | ⚠️ α **belum pernah diukur** forward sejak itu (0 mesin tersertifikasi, per memo 9-Okt sendiri) |
| 10-Okt-2026 | Redefinisi ukur: grid **30 jam** tetap, jangkar 03-AguZ, A&B | `AMANDEMEN_TARGET_AB_2026-10-10.md` | ✅ **aktif, ini yang jalan sekarang** |
| 10-Okt-2026 | PRAREG-26 dibekukan: seleksi mesin, verdict rencana **2-Nov** | `PRAREG_26_MESIN_SELEKSI.md` | ⚠️ dicabut oleh amandemen 19-Okt |
| 19-Okt-2026 | PRAREG-26 Amandemen-1: verdict **25-Nov**, t≥3,80; give-up **30-Nov tetap** | `AMANDEMEN_PRAREG26_JADWAL_2026-10-19.md` | ✅ **aktif** |
| 19-Okt-2026 | Catatan P3 (`PROGRES_2026-10-19.md`): **"Sertifikasi 20-Nov (S≥5,76) + proses unfreeze"** | `PROGRES_2026-10-19.md` baris 126 | ⚠️ **masih tercatat sebagai item terbuka, tapi tidak match dengan Track-30 yang berjalan** |
| 21-Okt-2026 | Amandemen-1 PRAREG-27 (paritas eksposur $1.800=$1.800); audit F1–F8 | `AMANDEMEN_PRAREG27_1_EKSPOSUR.md`, `AUDIT_2026-10-21.md` | ✅ aktif |
| 22-Okt-2026 (hari ini) | — | — | 29 hari ke 20-Nov · **34 hari ke 25-Nov** · 39 hari ke 30-Nov |

### Konflik timeline yang nyata

1. **20-Nov vs 25-Nov — mana yang mengikat?** Tenggat 20-Nov (sertifikasi S≥5,76, Track-55) datang **5 hari sebelum** verdict 25-Nov (Track-30). Jika 20-Nov tiba dan tidak ada sertifikasi S≥5,76 (hampir pasti — S baseline 2,30, "perlu 266 hari" per catatan memori), **apa konsekuensinya**? Tidak ada dokumen yang menjawab. Apakah proyek "gagal" di 20-Nov sebelum verdict Track-30 sempat keluar di 25-Nov?
2. **V2 tidak punya tanggal** — jadi V2 tidak bisa menyelesaikan konflik #1. V2 hanya berguna untuk menata **urutan fase** (Discovery→Data→Engine→Hypotheses→FiveKills→Shadow→Live), bukan kalender.
3. **"42 hari = HARD_STOP 20-Nov"** (dihitung dari 9-Okt) sudah **kedaluwarsa secara matematis**: memo 9-Okt sendiri menyatakan sertifikasi horizon 48 jam butuh **406 hari**, dan pada 19-Okt progres menyebut "S 2,30 perlu 266 hari" (dari memori) — **keduanya jauh di atas sisa 29 hari**. Tenggat 20-Nov **sudah diketahui tidak bisa dipenuhi sejak ditetapkan** — ini bukan risiko baru, ini fakta yang sudah ada di dokumen aslinya (`MEMO_KEPUTUSAN_TARGET_UTAMA_2026-10-09.md` §1: *"target kelas 48 jam tidak dapat disertifikasi sebelum 20-Nov"*).
4. **Implikasi jujur:** Track-55/20-Nov sudah **dinyatakan mustahil oleh dokumennya sendiri** sejak hari dibuat. Mempertahankannya di `PROGRES_2026-10-19.md` sebagai item terbuka P3 tanpa catatan ini **berisiko menyesatkan** — pembaca bisa mengira 20-Nov adalah tenggat yang realistis untuk dikejar.

**Kesimpulan Timeline:** V2 tidak memberi tenggat apa pun — ini murni milik kita. Tapi audit jujur menunjukkan: **kita punya satu tenggat (20-Nov) yang sejak lahir sudah terbukti mustahil secara matematis oleh dokumen kita sendiri, dan masih tercantum sebagai item aktif.** Ini harus diluruskan sebelum 20-Nov tiba supaya tidak dibaca sebagai "proyek gagal" ketika sebenarnya tenggat itu sudah salah sejak awal.

---

## 4. Yang V2 benar dan sudah ditemukan sendiri lewat audit 21-Okt (tidak diulang detail — lihat `GAP_ANALYSIS_V2.md`)

| # | Isu | V2 | Kita |
|---|---|---|---|
| G1 | Cap eksposur/leverage | wajib HUMAN_APPROVAL | tidak ada; buku 7,4× wallet |
| G2 | E₀ dibekukan per siklus | wajib | tracker pakai wallet hari ini |
| G3 | Trial registry | wajib (Kill 5) | baru dibuat 21-Okt, 18 arm |
| G4 | Sealed holdout | wajib | tidak ada |
| G6 | P(hit sebelum stop) | wajib (§4.4) | belum dihitung (MFE/MAE ada di data, belum dipakai) |
| G7 | Isolasi kredensial agen riset | wajib | hanya prosedural |

## 5. Yang kita SUDAH lebih maju dari V2 (jujur, bukan hanya kritik ke dalam)

| # | Area | V2 minta | Kita sudah punya |
|---|---|---|---|
| 1 | Model biaya | "gunakan effective fee dari API" | sudah terukur (6,68 bp RT, 05-Okt), lebih presisi dari tabel default V2 (yang 43% lebih mahal) |
| 2 | Anti look-ahead | wajib test | sudah diverifikasi (bar tertutup, lag 65 menit) |
| 3 | Deteksi data buta | tidak disebut eksplisit | sudah ada (autoheal, EMPTY_STREAK_LIMIT), ditemukan & diperbaiki 2 insiden nyata (realwide, twoway buta 8 hari) |
| 4 | Disiplin pra-registrasi + hash | wajib | sudah berjalan 27+ dokumen ber-hash, lebih banyak dari yang V2 contohkan |
| 5 | Kontrol drift data venue | tidak disebut | sudah diuji (`AMANDEMEN_3` §1 — korelasi SoDEX vs Binance 0,999, bukan bias data) |
| 6 | Analisis Kelly/leverage per instrumen | disebut umum | kita sudah punya rumus terverifikasi + testnya (`lev_discipline.py`, 28 tes) — **meski belum dipakai di track yang aktif** |

**Kesimpulan jujur:** secara *kedalaman kuantitatif* kita sudah melampaui V2 di banyak tempat. Kelemahan kita bukan kekurangan analisis — **kelemahan kita adalah tata kelola dokumen**: terlalu banyak track paralel (Track-55 vs Track-30) yang tidak saling mencabut secara eksplisit, sehingga orang luar (atau V2 sebagai "orang luar" simulatif) membaca ketidaksinkronan yang sebenarnya murni administratif, bukan karena risetnya lemah.

---

## 6. Rekomendasi (default yang saya sarankan, bukan keputusan final)

| # | Rekomendasi | Alasan |
|---|---|---|
| R1 | **Cabut Track-55 secara tertulis.** Nyatakan: horizon resmi = 30 jam (Track-30); leverage R2 tidak dipakai; tenggat 20-Nov **dicabut** karena sudah dinyatakan mustahil oleh dokumennya sendiri sejak 9-Okt | Menghapus konflik timeline #1 dan #3; tidak mengubah angka target (0,8% tetap) |
| R2 | **Satu-satunya tenggat resmi = PRAREG-26: verdict 25-Nov, give-up 30-Nov.** Semua laporan progres merujuk ke sini saja | Konsisten dengan apa yang benar-benar berjalan (Track-30) |
| R3 | **Terapkan G1/G2 sebelum 25-Nov** (cap eksposur 1× E₀ untuk pelaporan diagnostik; bekukan E₀ per window) — sudah diajukan di `DECISIONS_REQUIRED.md` D1 | Supaya verdict 25-Nov tidak diulang audit F1 setelah fakta |
| R4 | **Definisikan siklus (1 posisi vs portofolio) secara eksplisit** dan laporkan dua metrik terpisah seperti V2 minta | Gap nyata, belum ada biaya untuk menutupnya |
| R5 | Floor 0,4% V2 **tetap ditolak** — sudah dihitung tuntas di `AMANDEMEN_3`, bukan soal selera | Konsisten dengan keputusan user 9-Okt yang sudah berbasis angka |

---

## 7. Jawaban langsung ke pertanyaan user

**"Sesuaikan semua dengan Tujuan, Target, Timeline SoDEX."**

- **Tujuan**: sejalan dengan V2 pada substansi (profit bersih, swing, SoDEX, risk-aware); berbeda filosofi pada "harga mati" vs "aspirasi" — ini pilihan user, bukan error, tapi perlu disadari konsekuensinya (tekanan memaksakan transaksi yang justru V2 peringatkan).
- **Target**: 0,8%/window tetap valid sebagai angka; **tapi definisi pengukurannya (denominator, cap risiko) belum sesuai standar V2 maupun standar ilmiah dasar** — ini G1/G2, sudah diaudit 21-Okt, menunggu keputusan D1.
- **Timeline**: **ini yang paling butuh tindakan sekarang** — ada dua tenggat paralel (20-Nov dan 25-Nov) yang belum pernah direkonsiliasi, dan salah satunya (20-Nov) sudah terbukti mustahil sejak hari ditetapkan. Ini bukan temuan dari V2 — ini murni temuan dari membandingkan dokumen kita sendiri satu sama lain, yang baru terlihat ketika saya diminta "menyesuaikan semuanya" dan terpaksa membaca ulang seluruh rantai keputusan 9–21 Okt secara berurutan.

*Disusun 22-Okt-2026 · bukti file:line & tanggal dokumen · tidak mengubah kode/target/parameter apa pun.*
