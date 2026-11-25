> **DIGANTIKAN oleh `AUDIT_FORENSIK_V2_2026-10-25.md`.** Dokumen ini hanya membaca track paper
> dan tidak memuat ledger uang nyata (15.647 RT, net −$592,04). Pertahankan sebagai jejak,
> jangan dipakai untuk keputusan.

# AUDIT FORENSIK 7 BULAN — Mengapa SoDEX Tidak Kunjung Lolos

**Tanggal:** 25 Okt 2026 · **Basis:** 1.155 commit, 23 track paper, 1.638 trade, 1.277 uji terdaftar
**Sifat:** diagnosis, bukan pembelaan. Semua angka bisa direproduksi dari repo.

---

## 0. Jawaban singkat

Bukan AI-nya yang gagal. Bukan eksekusinya. Bukan datanya.

**Yang gagal: sinyal entry tidak punya edge kotor sama sekali.**
Dari **905 trade** yang punya harga entry/exit, rata-rata return **kotor** (sebelum biaya)
adalah **−0,025%** dengan t = **−0,32**. Artinya: sistem memprediksi arah sebaik lempar koin,
lalu membayar biaya **0,20% per trade**. Hasilnya rugi pasti, bukan rugi karena sial.

Kontrol acak membuktikan hal yang sama: pada track yang sama, entri **RANDOM** menghasilkan
−0,243% sedangkan entri **SIGNAL** −0,801%. Di track lain, sinyal lebih baik 0,76 pp.
**Tidak ada alpha yang konsisten — hanya noise yang berganti tanda.**

---

## 1. Bukti empiris (bukan opini)

### 1.1 Agregat seluruh track paper

| Metrik | Nilai |
|---|---|
| Track dibuat | 23 |
| Track yang **tidak pernah** trading | **13** (57%) |
| Total trade | 1.638 |
| Total PnL paper | **−$1.094,61** |
| Trade dengan data harga lengkap | 905 |
| **Gross mean per trade** | **−0,025%** (t = −0,32; CI95 ±0,153%) |
| Biaya mean per trade | **0,199%** (median 0,064%, p90 0,200%) |
| Net mean per trade | −0,224% |
| WR gross / net | 42,4% / 39,9% |

**Baca angka ini:** gross mean −0,025% dengan CI95 [−0,18%; +0,13%] **mengecualikan**
kebutuhan +0,86% per trade untuk mencapai target. Ini bukan "belum terbukti" —
ini **terbukti tidak cukup** untuk kelas strategi yang diuji.

### 1.2 Track unggulan (yang paling banyak data)

| Track | Trade | Hari | Window 30j | Mean/window | Median | sd | Hit |
|---|---|---|---|---|---|---|---|
| realwide | 310 | 79,3 | 51 | **+0,03%** | −0,54% | 9,69% | 43,1% |
| realwide_atrvolopen | 146 | 28,8 | 19 | **−3,03%** | −2,62% | 6,33% | 15,8% |

Target: **+0,8% per window**. Track terbaik menghasilkan **+0,03%** — **3,8% dari target**.
Dengan sd 9,69%, untuk membuktikan mean +0,8% pada t=4,11 dibutuhkan **2.478 window = 8,5 tahun**.
Bahkan pada ambang layar t=2,5: **3,1 tahun**.

### 1.3 Grid 1.080 kombinasi (PRAREG-SIG-05)

| Metrik | Nilai |
|---|---|
| Kombinasi diuji | 1.080 |
| Lolos BH-FDR | **0** |
| p_min | 0,0115 (ambang BH 9,26×10⁻⁵) |
| t terbaik | **+2,38** |
| Kontrol acak | −10,5 bps |

Dalam 1.080 undian, t maksimum yang diharapkan **di bawah hipotesis nol** sekitar 3,2–3,5.
t terbaik 2,38 **lebih buruk dari kebetulan**. Grid itu tidak menemukan apa pun.

---

## 2. Root cause — analisis IS / IS NOT

**Deviasi:** sistem tidak mencapai target 0,8%/window; bahkan tidak mencapai nol.

| Dimensi | IS (ada masalah) | IS NOT (tidak ada masalah) | Distinction |
|---|---|---|---|
| **WHAT** | Semua keluarga TA: donchian, trend, reversal, XS momentum, TA-16, range-pos | Eksekusi order, sizing, SL/TP, circuit breaker | Masalah ada di **prediksi arah**, bukan di eksekusi |
| **WHERE** | Semua venue (SoDEX, Binance, HL, Aster) | Bukan spesifik satu bursa | Bukan masalah venue — polanya lintas venue |
| **WHEN** | Sepanjang 79 hari, semua rezim (BULL/BEAR/CHOP) | Bukan hanya saat volatil | Bukan masalah rezim — konstan |
| **EXTENT** | 905 trade, 23 track, 1.277 uji | Tidak ada satu keluarga pun yang positif konsisten | Bukan kebetulan statistik — sistematis |

**CHANGE yang bertanggung jawab:** tidak ada perubahan pasar. Ini **latent condition**:
edge TA retail pada kripto likuid 1h–30h **memang nol**. Selama ini tertutupi oleh
(a) sampel kecil per track, (b) asumsi biaya 6,49 bps padahal realisasi 19,9 bps,
(c) harapan bahwa parameter yang lebih baik akan menemukannya.

**5 Whys:**
1. Kenapa rugi? → Net mean −0,22%/trade.
2. Kenapa net negatif? → Gross ≈ 0 dan biaya 0,20%.
3. Kenapa gross ≈ 0? → Indikator tidak memprediksi arah (WR 42% = dasar acak).
4. Kenapa tetap dipakai? → Setiap track dihentikan sebelum n cukup; 13/23 track nol trade.
5. Kenapa berhenti sebelum n cukup? → Setiap kandidat dievaluasi dengan ambang t≥4,11
   yang **mustahil dicapai** dalam hitungan minggu (butuh 8,5 tahun), sehingga selalu
   "gagal" lalu diganti kandidat baru → **siklus churn tanpa akumulasi bukti**.

---

## 3. Cacat proses yang memperparah (dan ini bisa diperbaiki)

### 3.1 Inflasi anggaran uji
**1.080 dari 1.277 uji (85%) berasal dari SATU grid parameter.** Grid bukan hipotesis
independen — titik-titiknya berkorelasi. Menghitungnya sebagai 1.080 uji menaikkan ambang
Bonferroni ke **4,11**, sehingga tes yang sah pun ikut mati. Ambang efektif seharusnya
dihitung dari **jumlah keluarga independen** (~10–20), bukan jumlah kombinasi.

### 3.2 Horizon bukti tidak cocok dengan horizon target
Target diukur per 30 jam, tetapi bukti diukur pada level trade dengan sd 2,34%.
Membuktikan target di level window butuh **tahun**; di level trade butuh ~145 trade.
Selama definisi bukti tidak diselaraskan, sistem akan selalu "belum terbukti".

### 3.3 Churn
13 dari 23 track tidak pernah trading. Tidak ada satu strategi yang dibiarkan
mengumpulkan 300+ trade dalam satu rezim. Tanpa itu, tidak ada yang bisa dipelajari.

### 3.4 Biaya riil 3× asumsi
Asumsi 6,49 bps; realisasi **19,9 bps** (median 6,4; p90 20,0). Selisih ini
memakan seluruh margin tipis yang mungkin ada.

---

## 4. Bottleneck (TOC) — satu constraint, bukan sepuluh

| Kandidat constraint | Bukti | Status |
|---|---|---|
| **Edge informasi (prediksi arah)** | gross t = −0,32, WR 42% | **CONSTRAINT** |
| Biaya | 0,20%/trade | Subordinat — bahkan gratis biaya, gross ≈ 0 |
| Modal $243 | profit absolut kecil, tapi target dalam % | Bukan penyebab gagal |
| Eksekusi/AI/infra | 1.638 trade, 0 pelanggaran, service sehat | Bukan penyebab |
| Ambang t=4,11 | mustahil dalam 51 hari | **Constraint sekunder** (proses) |

**Kesimpulan TOC:** menambah fitur, mengganti AI, atau menambah modal **tidak akan**
menaikkan throughput, karena constraint-nya adalah **informasi**, bukan kapasitas.

**Bukti struktural tambahan:** spread SoDEX median **0,31 bps**, sedangkan biaya
taker round-trip 5,6 bps. Spread > 2× biaya taker terjadi pada **0,0%** snapshot.
Artinya **market making / scalping spread mustahil secara aritmetika** di venue ini.
Satu-satunya jalan adalah edge arah (>20 bps per trade) atau arbitrase lintas venue.

---

## 5. Apa yang berbeda dari orang lain yang "berhasil"

| Yang mereka lakukan | Kenapa kita tidak bisa tiru begitu saja |
|---|---|
| **Market making dengan rebate** | SoDEX tidak memberi rebate; maker fee 1,14 bps, spread 0,31 bps → rugi tiap fill |
| **Arbitrase lintas venue** | Butuh modal terparkir di 2 venue + eksekusi simultan; hurdle 17,6 bps |
| **Funding/basis carry** | 0,7 bps/hari × $243 = $0,017/hari — tidak material |
| **Trend daily/weekly** | Biaya 0,2% vs pergerakan 4–5%/hari — masuk akal, **belum diuji** |
| **High-variance small-cap momentum** | Menang besar karena survivorship; yang gagal tidak membuat thread |
| **Jual bot/sinyal** | Model bisnis ≠ profit trading; metriknya subscription, bukan PnL |

**Poin penting:** klaim "AI agent otonom profit" di publik hampir selalu salah satu dari:
backtest tanpa biaya, ukuran akun kecil dengan keberuntungan, atau pendapatan dari menjual
sistem. Tidak ada bukti bahwa **prediksi arah retail** punya edge di pasar ini.

**Yang membedakan mereka bukan AI-nya — melainkan sumber edge-nya.**
Kita punya automation yang bekerja; kita tidak punya sumber edge.

---

## 6. Jalan keluar — diurutkan berdasarkan bukti, bukan harapan

### Jalur A — Arbitrase lintas venue (P3) · **sedang berjalan**
Tidak butuh prediksi. Hurdle 17,6 bps; p99 dislokasi 18,7 bps → **tipis tapi nyata**.
Kapasitas kecil justru cocok untuk $243. Verdict menunggu 50 event.
**Risiko:** leg risk, modal terbelah dua, frekuensi <50 event.

### Jalur B — Event-driven / listing baru SoDEX · **belum diuji**
Listing perp baru biasanya dislokasi besar pada jam pertama. Modal kecil cukup.
Bisa diuji dalam 2 minggu dengan data listing + harga 1 jam pertama.
**Ini satu-satunya keluarga yang pergerakannya (5–30%) jauh di atas biaya (0,2%).**

### Jalur C — Trend pada timeframe harian · **belum diuji**
Biaya 0,2% vs sd harian 4–5% → rasio biaya/edge jauh lebih baik daripada 1h.
Hold 3–10 hari; target per 30 jam dihitung akumulatif.
**Belum ada bukti**, tapi belum pernah diuji dengan benar (bukan grid 1 jam).

### Jalur D — Turunkan target ke tangga realistis
0,8%/30j = **234%/tahun** majemuk. Itu kelas top-decile global, bukan target retail
di venue tipis. Tangga 0,1% / 0,25% / 0,4% sudah ada dan lebih bisa dibuktikan.
**Butuh persetujuan Anda** — target tidak boleh saya ubah sendiri.

### Jalur E — Berhenti menambah keluarga TA
Bukan menyerah: **905 trade sudah menutup pintu itu** dengan CI yang mengecualikan target.
Melanjutkan grid TA = membakar waktu dengan hasil yang sudah diketahui.

---

## 7. Rekomendasi operasional (30 hari)

1. **Hentikan** semua track TA baru. Bekukan sebagai bukti, bukan hapus.
2. **Fokuskan** compute ke P3 (jalan) + Jalur B (listing event).
3. **Perbaiki protokol bukti:** hitung uji efektif per keluarga (bukan per kombinasi);
   selaraskan unit bukti (trade-level) dengan unit target (window-level).
4. **Satu strategi, satu rezim, 300 trade** sebelum boleh diganti.
5. **Verdict 15 Des:** P3 dan B masing-masing PASS/FAIL dengan CI95, bukan opini.

---

## 8. Yang tidak saya klaim

- Saya tidak bisa menjamin Jalur B atau C berhasil. Keduanya **belum diuji**.
- Saya tidak bisa membuktikan 0,8%/30j mustahil secara matematis — hanya bahwa
  **kelas strategi yang diuji** tidak bisa mencapainya (CI mengecualikan).
- Probabilitas yang saya sebut adalah penilaian, bukan hasil hitungan.

**Satu kalimat:** kegagalan ini bukan karena kurang AI, kurang data, atau kurang usaha —
melainkan karena kita mencari **prediksi** di tempat yang tidak menyimpannya,
dengan biaya yang lebih besar daripada sinyalnya.
