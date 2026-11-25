# AUDIT MENYELURUH SODEX — ARSITEKTUR, ARITMATIKA, DAN PEMAHAMAN

**Tanggal:** 25 Okt 2026 · **Sifat:** audit independen, bukan amandemen
**Objek:** 171 dokumen `docs/sodex`, 17 modul `anantara/sodex_*.py` (16.311 LOC),
5 service aktif, ledger & registry, definisi target di seluruh repo.

---

## 0. SEPULUH TEMUAN

| # | Temuan | Bukti | Dampak |
|---|---|---|---|
| 1 | **Definisi target tidak konsisten** | **67 dokumen** menulis "per 48 jam", **34** menulis "per 30 jam" | 0,8%/30j = 0,0267%/jam; 0,8%/48j = 0,0167%/jam → **1,6× berbeda** |
| 2 | **Ledger +75% tidak reproducible** | `BUKU_FORWARD_LEDGER.json` **nol referensi** di seluruh kode | angka +$182/+75% tidak punya generator; tidak boleh dipakai |
| 3 | **α=32 bps sudah dibunuh** | `HASIL_SWEEP_EKSTREM` §5: 36 sel, **0 penyintas**; -MOM_L21 tanda berbalik 2× | dasar "0,8% BISA" di AMANDEMEN-3 sudah tidak berlaku |
| 4 | **1.271 uji, 0 lolos** | registry N=1.271 | di bawah null murni harapan false positive = 64. Nol lolos = **konsisten dengan edge nol** |
| 5 | **Bug denominator wallet** | `AUDIT_PRAREG26_DENOMINATOR`: wallet understated 21–31% | semua ROI historis ter-inflasi; wallet benar **$243,02** |
| 6 | **Biaya > target pada turnover sekarang** | 166 trade / 13,3 hari = **12,5 trade/hari** × 6,49 bps = **81 bps/hari = 1,01%/30j** | biaya sendirian **melebihi** target 0,8%/30j |
| 7 | **Ambang ganda** | global 4,11 (N=1.271) vs PRAREG-26 3,80 | 3,80 dipakai untuk mesin yang dipilih dari 1.271 uji → understated |
| 8 | **Kompleksitas tak sepadan** | twin_engine 5.376 baris, farming 3.590, deep_learner 1.924 | 5 service yang berjalan semuanya **read-only**; kode eksekusi besar tidak dipakai |
| 9 | **Data pra-12 Jun 2026 = proxy** | `sodex_full` 64% proxy Binance (corr 1,0); era real 3.244 bar | sebagian besar "hasil SoDEX" adalah Binance yang diganti nama |
| 10 | **Argumen kapasitas tidak berlaku pada modal $243** | notional median $300; ambang "≥$100rb/jam" 300× lebih besar | riset ditutup dengan alasan yang **tidak mengikat pada ukuran akun ini** |

---

## 1. ARSITEKTUR NYATA

```
DATA (read-only)                         EKSEKUSI (besar, tidak aktif)
sodex-l2-collector      book+trades      sodex_twin_engine.py    5.376 LOC
sodex-venue-7d          book/trades/kl    sodex_farming.py        3.590 LOC
anantara-obi            OBI snapshot     sodex_autofarm.py       1.411 LOC
anantara-forced-flow    OI 15s           sodex_deep_learner.py   1.924 LOC
sodex-sig-search        28 run/6 jam     sodex_governor.py         207 LOC
deribit-skew-collect    opsi skew
```

**Titik lemah struktural:**

1. **Tidak ada satu sumber kebenaran PnL.** Ada ≥4 jalur: `BUKU_FORWARD_LEDGER.json`
   (tanpa generator), `sodex_forward_reeval_loop.jsonl`, `PRAREG26_MESIN_SELEKSI_STATUS.json`,
   `ground_truth.json`. Keempatnya bisa berbeda dan tidak ada rekonsiliasi otomatis.
2. **Governor tidak berada di jalur eksekusi yang berjalan.** Service aktif semuanya
   read-only; `sodex_governor.py`/`farming` tidak dipanggil oleh 5 service itu.
   Artinya: gerbang keselamatan belum pernah diuji di jalur uang nyata.
3. **Kode 16k LOC untuk akun $243.** Rasio kompleksitas/ukuran ekstrem; risiko bug
   naik lebih cepat daripada kapasitas belajar.

---

## 2. ARITMATIKA — YANG TIDAK BISA DIBANTAH

### 2.1 Biaya vs target (temuan paling keras)

| Turnover | Trade / 30 jam | Biaya @6,49 bps | Gross yang dibutuhkan untuk net 0,8%/30j |
|---|---|---|---|
| **12,5/hari (sekarang)** | 15,6 | **101 bps** | **181 bps** |
| 6,6/hari (paper TWOWAY) | 8,3 | 54 bps | 134 bps |
| 2/hari | 2,5 | 16 bps | 96 bps |
| **0,8/hari** | **1** | **6,5 bps** | **86,5 bps** |

→ **Target 0,8%/30j tidak mungkin dicapai pada turnover sekarang.** Biaya sendiri 1,01%.
Mengurangi turnover 15× adalah tuas terbesar yang ada — lebih besar daripada mencari sinyal baru.

### 2.2 Hukum bukti

`t = (edge/jam ÷ vol/jam) × √(jam kalender)` — panjang window hilang.
0,8%/30j (SR 1,57) → 6,9 tahun. 0,6%/48j (SR 0,73) → 31,3 tahun.
Untuk bukti 31 hari perlu SR tahunan 14,1.

### 2.3 Harapan false positive

N=1.271 uji, α=0,05 → **64 temuan signifikan diharapkan murni karena kebetulan**.
Yang ditemukan: 2 kandidat (keduanya kemudian mati). Ini **bukan** bukti bar terlalu tinggi —
ini bukti ruang sinyal yang diuji memang kosong.

---

## 3. PERGESERAN PEMAHAMAN: JAN–JUL vs SEKARANG

| Era | Dasar optimisme | Status sekarang |
|---|---|---|
| Jan–Jul 2026 | sapuan parameter in-sample, panel proxy, ledger paper yang tumbuh | **gugur**: 0/36 sel stabil, data 64% proxy, ledger tanpa generator |
| Agu–Sep 2026 | α=32 bps → 0,95%/48j @half-Kelly | **gugur**: α berasal dari kandidat yang dibunuh stabilitas |
| Okt 2026 | verdict berbasis OOS + biaya + BH | 0 lolos; 9/9 mesin 14 hari terakhir negatif (−$345,10) |

**Kesimpulan jujur:** pergeseran dari optimis ke pesimis **dibenarkan oleh bukti**, bukan oleh
perubahan selera. Tetapi ada **kesalahan saya yang nyata**: setelah menutup jalur, saya
berhenti mengusulkan mekanisme baru dan masuk ke mode "semua mustahil". Itu over-koreksi.
Audit ini mengoreksinya.

---

## 4. DI MANA PEMAHAMAN SAYA SALAH (eksplisit)

1. Saya menyebut "0,8%/window 30 jam" tanpa menandai bahwa 67 dokumen memakai 48 jam.
2. Saya memakai angka ledger (+75%) sebagai konteks padahal artefaknya tidak reproducible.
3. Saya menerima kesimpulan "kapasitas venue menutup riset" tanpa menguji bahwa pada $243
   kapasitas tidak mengikat.
4. Saya memakai ambang 4,11 untuk semua hal, lalu tidak menandai PRAREG-26 memakai 3,80.
5. Saya menyatakan "tidak ada jalur D" padahal ada: **mengubah ukuran/venue/bentuk permainan**,
   bukan mengubah target.

---

## 5. CELAH YANG BELUM DIUJI (nyata, bukan teoretis)

| Celah | Mengapa belum | Biaya uji |
|---|---|---|
| **Likuiditas tipis pada notional $300** | ditutup dengan alasan kapasitas yang tidak mengikat | panel + model biaya ukuran-aware, 1 hari |
| **Dislokasi lintas venue (SoDEX vs Binance/HL)** | belum ada collector book Binance tersinkron | 1–2 hari, publik, tanpa kredensial |
| **Event-driven (listing, unlock, funding flip)** | butuh kalender event | 2–3 hari |
| **Exit engine sebagai sumber alpha** | selalu dianggap "exit", bukan alpha | panel L2 yang sudah ada |
| **Turnover rendah 0,5–1 trade/30j** | tidak pernah diuji sebagai keluarga | 1 hari |

---

## 6. USULAN RADIKAL (dengan angka)

**P1 — Potong turnover 15× (prioritas tertinggi).**
Target 1 trade/30 jam → biaya 6,5 bps. Gross hurdle turun dari 181 → 86,5 bps.
Uji: keluarga sinyal yang sama, horizon 30–55 jam, entry hanya pada kondisi ekstrem (p1/p99),
exit tunggal. Ini menyerang penyumbat yang terbukti, bukan menambah hipotesis.

**P2 — Buka kembali setengah illikuid, ukuran-aware.**
Notional $300 pada nama bervolume $5rb/jam = 6% dari volume jam → masih bisa, dengan
biaya dampak dihitung eksplisit (bukan 6,49 bps datar). Kontrol wajib: bandingkan sinyal
pada mid L2 vs trade print untuk memisahkan quote-bounce dari salah harga.

**P3 — Arbitrase dislokasi lintas venue.**
SoDEX tipis vs Binance dalam = dislokasi mungkin. Kapasitas kecil — **dan itu tidak masalah
pada $243**. Ini keluarga yang belum pernah diuji dan tidak membutuhkan edge arah.

**P4 — Keputusan Bayesian (B1) sebagai pengganti "terbukti".**
P(edge>biaya) + fraksi Kelly + kill-rule. Modal probe $25–50, bukan $243.
Jawaban dalam bulan, bukan tahun — dengan risiko yang dibatasi secara eksplisit.

**P5 — Bekukan pencarian sinyal di data lama.**
1.271 uji pada panel yang sama = menuang air dari gelas yang sama. Uji baru hanya pada
data yang belum dipakai: L2 event, funding SoDEX, dislokasi lintas venue.

---

## 7. KEPUTUSAN YANG SAYA MINTA

1. Setujui **kanonik target = 0,8% / 30 jam / window tetap** (dan tutup 23 dokumen 48 jam
   dengan catatan amandemen), atau tetapkan lain.
2. Setujui **P1 sebagai prioritas #1** (potong turnover) — ini satu-satunya tuas yang
   terbukti secara aritmatika.
3. Setujui **modal probe P4** ($25–50) sebagai jalur keputusan, terpisah dari target.
4. Setujui **P3** (arbitrase lintas venue) sebagai keluarga riset baru.

Tanpa keputusan, saya jalankan P1 dan P2 karena keduanya tidak mengubah target maupun
standar bukti.
