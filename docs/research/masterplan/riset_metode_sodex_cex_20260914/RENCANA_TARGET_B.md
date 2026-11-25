# RENCANA KERJA — MENUJU TARGET B (0,8% PNL BERSIH RATA-RATA / 48 JAM)
**Mandat Mas Anas, 1 Okt 2026 — HARGA MATI. Divisi RISET Anantara Sakti.**
**Status: DITERIMA sebagai target resmi. Dokumen ini = spesifikasi teknis + tangga bukti.**

---

## 0. PERNYATAAN JUJUR (satu kali, lalu kita kerja)

Ini **masalah Sharpe, bukan masalah return**. Return bisa dinaikkan dengan leverage;
Sharpe tidak. Target B = **0,4%/hari = 146%/tahun (simple)**.
Pada vol portofolio 25%/tahun, ini menuntut **Sharpe ≈ 5,8**.
Benchmark terukur kita sekarang: **B0 = Sharpe 1,05**.

**Konsekuensi yang harus diterima sejak awal:**
```text
Bukan "trading lebih banyak" atau "leverage lebih besar" yang menutup jarak ini.
Hanya dua jalur matematis: (1) lebih banyak bet independen, (2) kualitas per-bet lebih tinggi.
Jika kita menempuh jalur leverage, Sharpe TIDAK naik — risiko naik, target tetap jauh.
```

---

## 1. DEKOMPOSISI TARGET → SPESIFIKASI

```text
Sharpe_tahunan  = sqrt(N_bet) x (edge_net / vol_per_bet)
Return_tahunan  = N_bet x f x edge_net           (f = rata-rata deployment wallet)
```

Dengan vol per-bet 1,5%, untuk mencapai 146%/tahun:

| Kualitas per-bet | Bet/tahun | **Bet/hari** | Edge NET/bet | Deployment f |
|---:|---:|---:|---:|---:|
| Sharpe 0,05 | 13.642 | 37,4 | 7,5 bps | 14% |
| **Sharpe 0,10** | 3.411 | **9,3** | **15,0 bps** | 29% |
| **Sharpe 0,15** | 1.516 | **4,2** | **22,5 bps** | 43% |
| **Sharpe 0,20** | 853 | **2,3** | **30,0 bps** | 57% |
| Sharpe 0,30 | 379 | 1,0 | 45,0 bps | 86% |

**Cek terhadap biaya (fee 8 bps RT):**
```text
edge net 15,0 bps -> gross 23,0 bps = 2,9x fee
edge net 22,5 bps -> gross 30,5 bps = 3,8x fee
edge net 30,0 bps -> gross 38,0 bps = 4,8x fee
```
→ Target B menuntut **edge gross 2,9–4,8× biaya round-trip, secara konsisten**. Ini spec yang jelas.

---

## 2. LEVER DIVERSIFIKASI (inilah kunci menuju Sharpe 5,8)

Sharpe gabungan K mesin dengan korelasi rata-rata ρ:

| K mesin (Sharpe 1,05 masing-masing) | ρ=1,0 | ρ=0,3 | ρ=0,1 | **ρ=0,0** |
|---:|---:|---:|---:|---:|
| 3 | 1,05 | 1,44 | 1,66 | 1,82 |
| 6 | 1,05 | 1,63 | 2,10 | 2,57 |
| 10 | 1,05 | 1,73 | 2,41 | **3,32** |

**Temuan penting:** diversifikasi mesin Sharpe-1,05 saja **TIDAK CUKUP** (maksimal 3,32 pada ρ=0).
Kita butuh **KEDUANYA**: mesin lebih baik **dAN** tidak berkorelasi.

| Kombinasi | Sharpe gabungan |
|---|---:|
| 6 mesin × Sharpe 2,0, ρ=0,1 | 4,00 |
| 10 mesin × Sharpe 2,0, ρ=0,1 | 4,59 |
| 6 mesin × Sharpe 2,5, ρ=0,0 | **6,12** ✅ |
| 8 mesin × Sharpe 2,3, ρ=0,05 | ~6,0 ✅ |

**Spec final: ~6–8 mesin, masing-masing Sharpe ≥2,3, korelasi antar-mesin ≤0,1.**

---

## 3. KANDIDAT MESIN, DIURUT POTENSI SHARPE

```text
Peringkat  Mesin                                  Potensi Sharpe  Alasan
1          Market-neutral funding/basis          2,0-3,0         varians rendah alami
2          Market making (maker, rebate)         3,0-10          eksekusi-kritis, kapasitas terbatas
           (butuh infra: fill model, queue, latency)
3          Cross-sectional momentum (mingguan)   1,2-1,5         butuh short + biaya
4          Breakout / trend regime (S2)          0,8-1,2         = B0 kita
5          Order flow / microstructure (S1)      belum diketahui  wajib lulus C1/C2 dulu
6          Basis + price-volume (fitur S6)       sebagai fitur   bukan mesin mandiri
X          Mean reversion 1h-1d                  FALSIFIED       (H6a kita + C3)
X          Low-vol gating                        FALSIFIED       (H3 kita)
X          Bracket/target-profit exit            FALSIFIED       (H1b v4 kita)
```

**Mesin #1 dan #2 adalah satu-satunya kandidat dengan potensi Sharpe ≥2.** Ini fokus kita.

---

## 4. TANGGA BUKTI (jangan lompat — setiap tahap punya gate)

```text
T0  INFRASTRUKTUR (wajib sebelum strategi apa pun)
    recorder data mentah per venue, cost model versioned, fill model,
    registry trial (semua percobaan termasuk gagal), harness fail-closed.
    GATE: cost model & fill model punya uji sintetik yang lulus.

T1  ALPHA POSITIF DI PAPER (beta-netral, universe likuid)      ← KITA DI SINI, BELUM LULUS
    Gate: net PnL > 0 setelah fee+funding+spread, 30 hari paper,
          beta dinetralkan (regresi ke BTC/market), 4 subperiode >= 3 positif.
    Status sekarang: alpha terukur −0,133R (NEGATIF). BELUM LULUS.

T2  SHARPE ROLLING 90 HARI >= 1,5 (setara B0+)
    Gate: 90 hari rolling Sharpe >= 1,5, MaxDD <= 25%, DSR > 0 dengan trial count jujur.

T3  MESIN KEDUA + KORELASI TERUKUR
    Gate: 2 mesin, masing-masing Sharpe >= 1,5, korelasi Pearson <= 0,3
          pada PnL harian. Sharpe gabungan >= 2,1.

T4  IMPLEMENTATION SHORTFALL < 25%
    Gate: slippage/fill nyata (micro-live) vs model <= 25% selisih, 60 hari.

T5  SKALA + MESIN KE-3..6 → Sharpe gabungan menuju 2,5-3
T6  BARU bicara 0,8%/48 jam (Sharpe ~5,8)
```

| Tahap | Sharpe | Setara PnL/48 jam | Perkiraan waktu |
|---|---:|---:|---|
| Sekarang | ~0 (alpha negatif) | rugi | — |
| T1 lulus | — | ~0,02% (positif) | 1–2 bulan |
| T2 | 1,5 | ~0,08% | 3–4 bulan |
| T3 | 2,1 | ~0,12% | 5–7 bulan |
| T5 | 3,0 | ~0,17% | 9–14 bulan |
| T6 | 5,8 | 0,80% | belum dapat dijadwalkan jujur |

**Penting:** angka "Setara PnL/48 jam" di atas dihitung pada **modal divisi saat ini**.
B0 kita (modal kecil) terbukti mampu Sharpe 1,05 — jadi tahap T2–T3 realistis.
Tahap T5–T6 memerlukan mesin market-making dengan infra, yang belum ada.

---

## 5. APA YANG SAYA KERJAKAN (pekerjaan nyata, berurutan)

```text
LANGKAH 1  Beta-netral + G3/G4/G5 pada SEMUA mesin yang ada
           → ubah semua laporan agar tidak lagi memakai return terkontaminasi beta
           → tetapkan angka "jarak ke target" yang jujur per divisi

LANGKAH 2  Bangun HARNESS EVALUASI tunggal (spec dokumen V1 §13)
           walk-forward bersarang + purge/embargo + cost stress 1x/1,5x/2x +
           DSR atas jumlah trial + PBO + registry trial
           → tanpa ini, setiap "temuan" berikutnya tidak bisa dipercaya

LANGKAH 3  Replikasi B0 secara benar sebagai lantai (baseline wajib)
           B0 = Sharpe 1,05 terukur. Semua mesin harus mengalahkannya.

LANGKAH 4  Bangun MESIN #1 dengan potensi Sharpe tertinggi = MARKET-NEUTRAL FUNDING
           Target: Sharpe 2,0+ pada paper-beta-netral.
           Bukti yang sudah ada: persisten hanya INJ (30,6% window); median funding
           per episode 3,3 bps < fee 8 bps → HARUS seleksi persistensi, bukan level spread.

LANGKAH 5  Uji MESIN #2 = CROSS-SECTIONAL MOMENTUM (Yang 2025, mingguan)
           wajib long-only dulu (E2: alpha momentum banyak dari short) + biaya nyata.

LANGKAH 6  Ukur korelasi PnL antar mesin; buang yang > 0,3.

LANGKAH 7  Laporkan "jarak ke target" mingguan dengan angka, bukan opini.
```

---

## 6. RISIKO YANG HARUS DIKELOLA (bukan untuk menakuti, tapi untuk dijaga)

```text
R1  Sharpe 5,8 tidak punya preseden publik. Probabilitas mencapai ini dalam
    12 bulan: RENDAH. Karena itu target antara (T1-T3) wajib dihormati —
    kalau T1 tidak lulus dalam 2 bulan, itu sinyal berhenti dan menilai ulang.
R2  Semakin tinggi target, semakin besar tekanan menaikkan risiko.
    ATURAN KERAS: leverage TIDAK boleh dinaikkan untuk mengejar target.
    (Preseden nyata: rugi UNI −$19,06 dengan order 3,39x ukuran normal.)
R3  Jendela < 6 bulan tidak boleh dipakai menilai alpha (SE Sharpe ±2,3 pada 72 hari).
R4  Setiap mesin wajib punya kill-switch dan batas kerugian harian/mingguan.
R5  Modal nyata tetap FROZEN sampai T2 lulus + approval Mas Anas.
```

---

## 7. KONTRAK KERJA SAYA

```text
Saya bekerja dengan asumsi:
  - Target resmi = 0,8% net rata-rata per 48 jam (Target B, HARGA MATI)
  - Target antara T1-T5 dihormati sebagai gate, bukan sebagai "target lunak"
  - Ukuran keberhasilan jangka pendek = NAIKNYA SHARPE, bukan naiknya return
  - Setiap klaim wajib: n, CI, beta-netral, biaya, kontrol negatif, label bukti
  - Laporan "jarak ke target" dengan angka
  - Saya akan menyanggah dengan data kalau ada langkah yang justru merusak Sharpe
```

**Kalimat kunci:**
> Target B diterima. Jalan menujunya bukan dengan mengambil lebih banyak risiko,
> tetapi dengan membangun **lebih banyak mesin yang tidak saling berkorelasi, masing-masing
> dengan Sharpe tinggi**. Pekerjaan pertama saya: pastikan angka kita jujur dulu
> (beta-netral, biaya nyata, harness fail-closed) — karena target seberat ini
> tidak boleh dikejar dengan pengukuran yang salah.
