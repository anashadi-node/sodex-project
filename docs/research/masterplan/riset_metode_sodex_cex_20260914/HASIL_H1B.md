# HASIL H1b — SIMULASI KEBIJAKAN EXIT (protokol diperketat) + KOREKSI H1

**Dijalankan 1 Okt 2026 · 812 trade dianalisis (149 dibuang fail-closed) · horizon tetap 24 jam**
**Protokol: G2 cost stress 1×/1,5×/2× · G3 universe · G4 split · G5 subperiode · G6 beta-neutral · G7 PnL bersih**
**Kontrol negatif aktif · bootstrap CI95 · 4 iterasi metodologi (v1→v4)**

---

## RINGKASAN EKSEKUTIF — 3 pembalikan besar

```text
1) H1 versi pertama OVERSTATED. MFE besar (median +1,087R) sebagian besar = BETA.
   Periode sampel 6 Agu–1 Okt 2026: BTC +31,95% · ETH +42,98% · SOL +64,62%
   Sampel 95% LONG (775 L vs 37 S) di pasar yang naik kuat.

2) SETELAH BETA DINETRALKAN: alpha sistem = NEGATIF.
   actual excess R: mean −0,133 · median −0,191   ← RUGI setelah beta dibuang

3) TIDAK ADA kebijakan exit berbasis aturan yang menyelamatkan.
   Semua target-profit membuatnya LEBIH BURUK. Hanya "tahan tanpa stop" positif —
   dan itu rapuh secara statistik (CI [0,014; 0,529], median tetap negatif).
```

**Kesimpulan keras: bottleneck utama BUKAN capture-exit. Bottleneck utama adalah TIDAK ADANYA ALPHA.**
Memperbaiki exit pada sistem tanpa alpha tidak menciptakan profit.

---

## 1. Empat iterasi metodologi (jejak audit)

| Versi | Masalah ditemukan | Perbaikan |
|---|---|---|
| v1 | — | Jendela = [entry, exit aktual] |
| v2 | **Kontrol negatif LOLOS**: random ≈ kebijakan terbaik | Deteksi via skill riset #9 |
| v3 | Kolom `baseline` gagal (harness fail-closed bekerja benar); jendela aktual membuat random exit = keluar di tengah hold | **Horizon TETAP 24/48 jam** untuk semua kebijakan |
| v3→ | E[R] sangat besar & mencurigakan → **BETA terdeteksi** (BTC +32% di sampel) | — |
| v4 | — | **Neutralisasi beta (G6)**: excess = sign×r_trade − sign×r_market_24h |

Jejak ini menunjukkan nilai gate: tanpa G6, saya akan melaporkan "temuan" yang salah arah.

---

## 2. Hasil v4 — EXCESS R (beta dinetralkan), horizon 24 jam, n=812

```text
Rata-rata pergerakan pasar searah posisi pada horizon 24j : +0,408% (median −0,134%)
actual excess R sistem                                    : mean −0,133 · median −0,191
```

| Kebijakan | E[R] excess | median R | WR% | CI95 E[R] | net 1× | net 2× |
|---|---:|---:|---:|---|---:|---:|
| tp_0.5R | −0,368 | −0,025 | 49,3 | [−0,497; −0,243] | **−0,427** | −0,486 |
| tp_1R | −0,276 | −0,064 | 47,3 | [−0,407; −0,155] | −0,335 | −0,394 |
| tp_1.5R | −0,208 | −0,118 | 44,7 | [−0,337; −0,087] | −0,267 | −0,326 |
| tp_2R | −0,142 | −0,119 | 43,7 | [−0,268; −0,021] | −0,201 | −0,260 |
| ladder_1R | −0,177 | −0,036 | 48,9 | [−0,304; −0,056] | −0,236 | −0,295 |
| **trail_0.5R** | **−0,001** | **+0,122** | **54,4** | **[−0,143; +0,141]** | **−0,060** | −0,119 |
| trail_0.75R | −0,102 | +0,040 | 51,7 | [−0,241; +0,037] | −0,161 | −0,220 |
| trail_1R | −0,188 | −0,046 | 47,8 | [−0,330; −0,053] | −0,247 | −0,306 |
| time_half | −0,045 | −0,053 | 47,9 | [−0,235; +0,146] | −0,104 | −0,163 |
| hold_to_end | **+0,269** | −0,111 | 44,6 | **[+0,014; +0,529]** | **+0,210** | +0,151 |
| RANDOM_control | +0,066 | −0,016 | 49,4 | [−0,137; +0,268] | +0,007 | −0,052 |

### Bacaan
```text
• SEMUA kebijakan target-profit (tp_*, ladder) → excess R NEGATIF, makin ketat makin buruk.
  Mengunci profit lebih awal memotong drift yang justru satu-satunya sumber return.
• trail_0.5R = kebijakan aturan TERBAIK (net −0,060R, WR 54,4%) tapi MASIH negatif.
• hold_to_end satu-satunya positif (net +0,210R) tapi:
    - CI95 [0,014; 0,529] — batas bawah nyaris menyentuh nol
    - median −0,111R (distribusi digerakkan sedikit outlier besar)
    - tanpa stop = risiko tak terbatas → TIDAK bisa diterapkan
• Kontrol negatif (v4): random +0,007 · terbaik +0,210 → "LULUS" secara aturan,
  TAPI margin rapuh dan median semua kebijakan negatif.
```

---

## 3. KOREKSI TERHADAP H1 (versi pertama)

**Klaim lama saya:**
> "median MFE +1,087R vs median realized −0,125R → bottleneck = CAPTURE exit;
> bracket mekanis akan memulihkan; 52,2% posisi menyentuh +1R"

**Yang harus dikoreksi:**
```text
❌ MFE tinggi itu SEBAGIAN BESAR BETA. Di pasar +32% dengan 95% posisi long,
   mencapai excursion favorable besar adalah HAL YANG DIHARAPKAN, bukan bukti
   bahwa sinyal kita bagus atau bahwa exit kita merusaknya.

✅ Yang TETAP berdiri dan justru LEBIH KUAT:
   Sistem menghasilkan median realized NEGATIF meskipun pasar naik +32% dan
   95% posisinya long. Itu bukti masalah NYATA (bukan sekadar pasar tidak mendukung).
   Setelah beta dinetralkan: mean excess R = −0,133, median −0,191.

✅ Yang BERUBAH:
   "Bracket exit akan memulihkan" → DITOLAK. Semua varian bracket menghasilkan
   excess R lebih negatif daripada sistem aktual.
```

---

## 4. Benchmark B0 (wajib menurut dokumen)

```text
B0 Donchian-ensemble long/flat 1x, 30 simbol, 563 hari (17 Mar 2025 – 30 Sep 2026), fee 8 bps:
  Total +25,83% | CAGR +16,06% | Sharpe 1,05 | MaxDD −14,7%
  BTC buy & hold periode sama: +1,54%
```
**B0 = Sharpe 1,05, CAGR 16,06% — benchmark yang serius.** Setiap strategi (termasuk sistem kita sekarang) harus mengalahkannya net-of-cost, atau tidak dipromosikan. Tidak ada komponen sistem kita saat ini yang terbukti melakukannya.

Implikasi matematis target: B0 ≈ **0,041%/hari**. Target 0,8% per 30 jam = 1,6%/hari ≈ **39× B0**.
Perlu klarifikasi tafsir target dengan Mas Anas (lihat bagian 5).

---

## 5. Pertanyaan yang HARUS diklarifikasi (bukan asumsi saya)

```text
Target: "PNL kumulatif ≥0,8% TOTAL wallet per 30 jam".
Jika diartikan SETIAP window 30 jam → 1,6%/hari → ~5.800%/tahun. Tidak ada bukti
   di seluruh korpus (dan tidak ada di dokumen V1/V2) bahwa ini dapat dicapai
   secara berkelanjutan oleh siapa pun pada venue ini.
Jika diartikan AKUMULASI sepanjang bulan (window yang ditrade saja) → setara
   beberapa % per bulan, masih sangat tinggi tapi tidak mustahil untuk edge kelas atas.
→ Perlu keputusan Mas Anas: mana tafsirnya? Ini mengubah seluruh desain riset.
```

---

## 6. Yang BERDIRI setelah H1b (untuk dipakai ke depan)

```text
CONFIRMED  : biaya fee 8–9 bps RT dominan; funding kecil (0,53 bps/hari)
CONFIRMED  : B0 (Donchian ensemble) = Sharpe 1,05 / CAGR 16,06% → bar wajib
CONFIRMED  : sistem saat ini punya excess alpha NEGATIF (−0,133R rata-rata, 24j)
CONFIRMED  : pasar naik +32% selama sampel → setiap klaim PnL historis kita
             WAJIB dinetralkan beta sebelum diinterpretasi
REJECTED   : "bottleneck = capture exit; bracket akan memulihkan" (hipotesis H1 lama)
REJECTED   : semua kebijakan target-profit tetap (tp_0.5R…tp_2R, ladder_1R)
PROMISING  : trail_0.5R = paling mendekati netral (WB 54,4%, net −0,060R) — kandidat
             untuk diuji ULANG pada sampel beta-netral & universe likuid
UNCERTAIN  : hold_to_end — positif tapi CI lebar + median negatif + tanpa stop
```

---

## 7. Pelajaran metodologis (paling berharga dari sesi ini)

```text
1. KONTROL NEGATIF menyelamatkan saya 2×: pertama mendeteksi jendela uji terlalu mudah,
   kedua memaksa saya melihat bahwa "kemenangan kebijakan" hanyalah drift pasar.
2. FAIL-CLOSED bekerja: kolom baseline yang hilang => GAGAL, bukan angka palsu.
   (kelas bug yang sama dengan fill-phantom rc=0/orderID=0 yang sudah dikenal)
3. BETA-NEUTRALISASI mengubah kesimpulan secara total. Tanpa G6, saya akan melaporkan
   "temuan" bahwa bracket exit memulihkan kinerja — kesimpulan yang SALAH dan berbahaya
   kalau dipakai untuk keputusan modal.
4. Dokumen V1/V2 sudah memperingatkan ini (G6 wajib regresi ke CMKT/CSMB/CMOM).
   Peringatan itu TERBUKTI benar pada data kita sendiri dalam < 1 jam pengujian.
```

## 8. Berikutnya
```text
[ ] Klarifikasi tafsir target 0,8%/30j (perlu keputusan Mas Anas)
[ ] H6b-rev: ulangi momentum dengan beta-netral + G3/G4/G5
[ ] Uji trail_0.5R pada sampel beta-netral universe likuid (menggantikan bracket lama)
[ ] Bandingkan sistem aktual vs B0 pada periode & universe sama, beta-netral
[ ] Laporan Fase 4 (MD+HTML+PDF) dengan label V/H/P/X
```
