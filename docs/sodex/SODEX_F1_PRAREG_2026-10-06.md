# SODEX F1 — PRA-REGISTRASI Uji Forward Momentum 20 Simbol

**Status: DIBEKUKAN sebelum ada PnL forward yang dihitung.** Setelah hasil keluar, isi dokumen ini dan `scripts/sodex_prereg_f1.py` **tidak boleh diubah**.
**Tanggal beku:** 06-Okt-2026 · **Persetujuan pemilik:** 06-Okt-2026 ("Approve" untuk kriteria penerimaan dan pra-registrasi) · **Registry:** evaluasi **#42**.
**Mode:** READ-ONLY. Tidak ada order, sign, atau perubahan gate/leverage/sizing/target. LOCKBOX lama (2026-09-01..10-05) **tidak dibaca**.

---

## 1. Hipotesis (satu, tidak ada penyetelan)

> **H1:** Pada 20 pasar SoDEX, masuk **searah** setelah gerakan ≥2,0% dalam 15 menit, tahan 24 jam, menghasilkan PnL bersih **rata-rata ≥0,40% per episode** dan, dalam portofolio tanpa leverage, **rata-rata ≥0,8% per jendela 48 jam**.
> **H0:** rata-rata ≤ 0.

Satu hipotesis → tidak perlu koreksi multi-uji. Pemilihan θ=2,0% berasal dari DEV 3 simbol (θ∈{1,0; 1,5; 2,0}%), sehingga ada bias seleksi; itu sebabnya ambang C1 dipasang di 0,40% dan bukan di >0.

## 2. Data uji (lockbox baru = seluruh data forward ini)

| Item | Nilai beku |
|---|---|
| Simbol | 20 simbol collector (`BTC ETH SOL ZEC DOGE SUI XAUT QNT BNB PONS LIT HYPE AAVE XRP US500 UNI ARB SNDK AVAX SPCX`) |
| Mulai | **2026-10-07 00:00 UTC** (setelah commit ini; semua sebelum tanggal itu **tidak** dipakai) |
| Data yang tidak boleh dibaca | semua data ≤2026-10-06; LOCKBOX lama |
| Harga per menit | harga trade dengan **timestamp terbesar** di menit itu (duplikat dan disorder tape tidak berpengaruh) |

## 3. Definisi (beku)

- **Event:** pada menit *t* (ada trade), `|P(t)/P(t−15m) − 1| ≥ 2,0%`; `P(t−15m)` = harga trade terakhir ≤5 menit sebelumnya (ffill). Klaster: ambil event **pertama**, abaikan event berikutnya <60 menit pada simbol yang sama.
- **Masuk:** taker di harga menit event, **searah** gerakan. **Keluar:** taker 24 jam kemudian (harga trade terakhir ≤10 menit sebelum waktu keluar).
- **Episode lengkap:** keluar sudah teramati. Yang belum lengkap tidak dihitung.
- **Biaya bersih:** `2 × (setengah-spread median OBI simbol + 2 bp) + 10 bp slippage tambahan di entry` (stres; spread median tidak mencerminkan kondisi saat gerakan cepat). Simbol tanpa data OBI: persentil-95 antar simbol.
- **Kontrol:** arah dibalik (fade), biaya sama.
- **Portofolio jendela:** jendela 48 jam non-overlap dari 2026-10-07 00:00 UTC; tiap posisi **15% dompet**; eksposur bruto terbuka ≤ **100%** (tanpa leverage; posisi yang melewati batas ditolak); PnL diakui saat keluar; hanya jendela penuh.

## 4. Gerbang pemicu (anti-intip)

Evaluasi **sekali**, ketika **semua**: ≥**150** episode lengkap, ≥**14** hari berepisode, ≥**10** simbol berepisode. Atau pada **HARD_STOP 2026-11-07** apa pun hasilnya.
Sebelum itu hanya `--count-only` yang boleh dijalankan (hanya menghitung; tidak membaca harga keluar). `--final` **menolak** berjalan sebelum gerbang terbuka.

## 5. Kriteria lulus — SEMUA harus terpenuhi

| # | Kriteria |
|---|---|
| C0 | n ≥150; hari ≥14; simbol ≥10; episode tak-terselesaikan ≤5% (kalau tidak → **INCONCLUSIVE**, bukan lulus) |
| C1 | rata-rata bersih/episode ≥ **0,40%** |
| C2 | p **sign-flip level hari** (satu sisi) < **0,05** — kluster = hari UTC, karena gerakan pasar menyerempakkan banyak simbol |
| C3 | rata-rata momentum > rata-rata kontrol fade |
| C4 | buang 3 episode terbaik → rata-rata masih > 0 |
| C5 | masuk terlambat 2 menit → rata-rata masih > 0 |
| C6 | tiga segmen waktu berurutan: ≥2 positif |
| C7 | tidak ada satu hari yang menyumbang >35% total PnL |
| C8 | **rata-rata PnL jendela 48 jam ≥ 0,8% DAN batas bawah CI95 bootstrap (antar jendela) > 0** — kriteria penerimaan resmi, disetujui pemilik 06-Okt |

**Putusan:** semua terpenuhi → `PASS`. C0 gagal → `INCONCLUSIVE`. Lainnya → `FAIL`. Hasil dicatat sebagai evaluasi #42 dan **tidak diuji ulang atau disetel**.

## 6. Yang terjadi setelah putusan

- **PASS bukan GO-LIVE.** Live butuh keputusan GO-LIVE eksplisit pemilik; micro-live maksimum 15% dompet per posisi, gate T1 utuh, tanpa leverage.
- **FAIL / INCONCLUSIVE:** tidak ada pelonggaran ambang. Bottleneck dianalisis ulang dari rincian kegagalan.

## 7. Ekspektasi jujur (ditulis sebelum hasil)

- SE rata-rata per episode ≈ 4,6%/√150 ≈ **0,37%**. Bila rata-rata sebenarnya 0,8% → peluang lulus C1 ≈ 86%; bila 0,40% → ≈50%; bila 0 → ≈14%.
- C8 jauh lebih ketat daripada C1. Dengan diversifikasi 20 simbol dan 15% per posisi, peluang lulus C8 **rendah kecuali** edge simbol alt benar-benar ada **dan** sebaran PnL jendela turun dari ±2,6% (3 simbol) ke ≈1,3%. Itu asumsi, bukan temuan.
- Peluang kumulatif lulus seluruh C0–C8 saya taksir **≤25%**. Hasil FAIL adalah hasil yang sah dan berguna.

## 8. Pengungkapan cacat protokol sebelumnya

`scripts/sodex_forward_momentum.py::day_cluster_p` (uji 5-Okt) menghitung `P(rata-rata resampel ≥ rata-rata teramati)` — bootstrap terpusat pada nilai teramati sehingga selalu ≈0,5. Diuji: data sintetis +5% (sd 0,5%) → p=0,4999; kalibrasi 100 dataset nol → 0% penolakan (daya nol). Kriteria `p_day<0,05` di uji 5-Okt **tidak mungkin lulus**. Implementasi `r4_dev_harness` dan `sodex_s1_sol_forward` memakai sign-flip benar dan **tidak terpengaruh**.
Dampak: dengan metode benar `p_hari` θ=2,0% = **0,153** (bukan 0,495) → **tetap tidak signifikan**, putusan GAGAL tidak berubah. Skrip lama tidak diedit (protokol beku); F1 memakai `day_signflip_p` (kalibrasi: 3,7% penolakan palsu pada 300 dataset nol; daya 72% untuk +1%/sd 5% n=120).

## 9. Perintah

```
.venv-research/bin/python3 scripts/sodex_prereg_f1.py --count-only   # kapan saja
.venv-research/bin/python3 scripts/sodex_prereg_f1.py --final        # hanya saat gerbang terbuka
.venv-research/bin/python3 -m pytest tests/test_sodex_prereg_f1.py -q
```

## 10. AMENDEMEN 07-Okt-2026 (sebelum PnL apa pun dihitung)

Dasar: audit read-only evaluator (2 subagen, `deleg_9a86e82e`) menemukan cacat biaya
deterministik. Amendemen dilakukan saat tape forward F1 **belum menghasilkan episode**
(0/150 episode, 0/14 hari, 0/10 simbol pada 07-Okt) — jadi **bukan p-hacking**: tidak ada
hasil yang bisa "dilihat" sebelum ambang dibetulkan.

1. **`FEE_TAKER` 0,0002 → 0,0004 (2 bp → 4 bp/leg).** Taker resmi SoDEX 0,040%/leg
   (`docs/FACT_SHEET_EKONOMI_VENUE_2026-10-01.md`, `SODEX_F2_CLOSED_2026-10-06.md`, whitepaper).
   Nilai lama = setengah biaya nyata → bias optimistis deterministik ~0,04 pp/episode (~10%
   ambang C1); terbukti **membalik C1** pada edge bruto 0,50%/episode. (F3 sudah 4 bp; F1 salah tulis.)
2. **Biaya funding 24 jam ditambahkan: `FUNDING_BP_24H = 2,4 bp`** (simetris, konservatif).
   Sebelumnya NOL. Rujukan: funding nyata ~0,024%/24 jam (`docs/sodex/AUDIT_BIAYA_AKUN_2026-10-05.md`).
3. **Anti-optional-stopping:** hasil `--final` ditulis ke nama ber-timestamp (tak menimpa) +
   log append-only `SODEX_F1_LOOKS.jsonl` + kunci `SODEX_F1_FIRSTLOOK.json`. Keputusan
   pra-registrasi = **look PERTAMA**; look ulang hanya dicatat, tidak mengubah ambang.

Ambang/verdict lain (C0–C8, θ, HOLD, F_START, HARD_STOP) **TIDAK diubah**.
Tes regresi: `tests/test_sodex_prereg_f1.py::test_amendment_fee_is_official_4bp_and_funding_charged`.

## 11. PERPANJANGAN HARD_STOP 07-Okt-2026 (approval user, opsi A)

- `HARD_STOP`: **2026-11-07 → 2026-11-20 (+13 hari, MAKSIMAL)**.
- Alasan: laju episode nyata lebih lambat dari asumsi awal; tanpa perpanjangan gerbang tidak
  akan terbuka. Perpanjangan ini **tidak mengubah ambang apa pun** (N_MIN=150, DAYS_MIN=14,
  SYMS_MIN=10, θ=0,02, C0–C8 tetap).
- **Sekali saja.** Tidak ada perpanjangan lagi setelah 20-Nov-2026; sesudahnya wajib full
  live real trading.
- Riset laju & proyeksi: `docs/sodex/SODEX_LAJU_EPISODE_RISET_2026-10-07.md`.
