# SODEX — Scan Audit & Peta Jalan 40 Hari (06-Okt-2026)

**Status:** audit read-only, tidak ada perubahan gate/leverage/sizing/target. LOCKBOX (2026-09-01..10-05) **tidak dibaca**.
**Skrip yang dibuat (dapat diulang):** `scripts/sodex_scan_audit.py` (keamanan/jalur-uang/data/track), `scripts/sodex_window_sim.py` (simulasi dompet per jendela 48 jam, DEV saja).

---

## 0. Jawaban jujur atas permintaan "keyakinan 100%"

Tidak ada metode ilmiah yang memberi 100%. Yang bisa diberikan: **kriteria lulus/gagal yang ditulis sebelum menguji**, dan bukti terukur. Angka-angka di bawah menunjukkan bahwa **belum ada satu pun mesin yang terbukti** mencapai target; peta jalan di §5 adalah jalur tercepat yang sah untuk *membuktikan atau menggugurkan* satu kandidat dalam 40 hari.

## 1. Definisi target — satu masalah yang harus diputuskan

| Sumber | Bunyi |
|---|---|
| `CLAUDE.md` | ≥0,8% TOTAL wallet di **SETIAP** rentang **30 jam**, kumulatif |
| Memori resmi / D14 / R4 | ≥0,8% PnL bersih per **48 jam** (rata-rata, jalur Sharpe≥2,3 × 6–8 mesin) |

Dua masalah, bukan satu: (a) 30 jam vs 48 jam; (b) kata **"SETIAP"** = syarat per-jendela, berbeda jauh dari **rata-rata**. Bagian 3 menunjukkan bahwa syarat "setiap jendela" tidak dapat dijamin oleh strategi apa pun yang berbasis kejadian.
Uji ini memakai **48 jam** (utama) dan melaporkan *hit-rate per jendela* sebagai metrik tambahan.

## 2. Temuan audit

| # | Tingkat | Temuan | Bukti | Status |
|---|---|---|---|---|
| S1 | **KRITIS** | `origin/main` (push terakhir 15-Jun) memuat key Binance, key OpenRouter, JWT, dan token Telegram di `docs/SECURITY_AUDIT_20260607.md` dan `freqtrade_user_data/config.json`. Versi lokal sudah disunting (0 hit) tetapi **riwayat dan remote belum** | `git grep` (nilai tidak dicetak). Perbandingan hash: **key Binance di remote = key AKTIF di `.env`**; token Telegram di remote ≠ token aktif (sudah dirotasi). Repo: HTTP 404 tanpa auth (privat) | **Butuh tindakan Anda**: rotasi key Binance + OpenRouter + JWT. Saya tidak boleh `push --force`/menulis ulang riwayat (Red Line) |
| S2 | RENDAH | ClamAV bersih (scripts, anantara, systemd, unit user, rc shell) | exit 0 | **Database virus 15 hari** (28130, 21-Sep): jalankan `freshclam` |
| S3 | — | Tidak ada proses dari `/tmp`, `/dev/shm`; tidak ada crontab; egress hanya VPN NordLynx; tidak ada `ld.so.preload` | `sodex_scan_audit.py security` | Bersih |
| S4 | — | **Tidak ada service yang sedang berjalan memuat skrip berkemampuan order/sign** | `sodex_scan_audit.py live` | Bersih. Lane uang nyata beku sesuai keputusan 30-Sep |
| S5 | RENDAH | 1 karakter soft-hyphen (U+00AD) di **komentar** `sodex_twin_engine.py:525` | bukan kode | Tidak diubah (file kritis, risiko>manfaat) |
| S6 | RENDAH | 9 unit sodex di systemd tidak punya salinan di `git/systemd/` | audit | Cadangkan salinan |
| S7 | RENDAH | `except … return kosong` di 10 modul (kandidat fail-open) | pola | Perlu ditinjau per pemakai, bukan temuan terbukti |
| D1 | RENDAH | Tape forward: **±2% baris duplikat per hari** (id sama, isi identik) dan **±50% baris tidak urut waktu** | 40 hari diperiksa | Dampak ke harga per-menit: median 0 bp, p95 ≈2 bp, p99 ≈5 bp, maks 91 bp vs ambang uji 200 bp → **hasil θ=2% tidak tercemar**. Perbaikan di *loader*, bukan collector/evaluator beku |
| D5 | **SEDANG** | `sodex_forward_momentum.py::day_cluster_p` memberi p≈0,5 untuk data apa pun (uji sintetis +5% → 0,4999; 0% penolakan pada data nol) → kriteria `p_day<0,05` uji 5-Okt **mustahil lulus**. `r4_dev_harness` dan `s1_sol_forward` benar | Dengan metode benar `p_hari` θ=2%=0,153 → **GAGAL tetap**. Skrip beku tidak diedit; F1 memakai `day_signflip_p` (terkalibrasi). Lihat `SODEX_F1_PRAREG_2026-10-06.md` §8 |
| D2 | — | 6 hari hilang (03–08 Agu); selain itu data 131 hari utuh, collector segar (<1 menit) | audit | Diketahui |
| D3 | RENDAH | `paper_test_pasar_anantara_trade_state.json` basi 534 jam | digantikan track `pasar_anantara_cex` (segar) | Warisan, bukan bug |
| D4 | INFO | 581 commit lokal belum di-push; `HEAD` ≠ `origin/main` | git | Lihat S1 sebelum push |

Tidak ditemukan: malware, unit mencurigakan, jalur order aktif, kebocoran baru di `HEAD`.
**Cakupan yang TIDAK dicakup:** audit kode baris-demi-baris `sodex_twin_engine.py` (5.262 baris), uji penetrasi, pemindaian data 8 GB oleh ClamAV.

## 3. Diagnosis strategi — apa yang diukur simulasi tingkat dompet

Kandidat terbaik (momentum, event ≥2% dalam 15 menit, tahan 24 jam, 3 simbol, DEV 94 hari), **tanpa leverage (gross ≤1×)**:

| Metrik | Nilai |
|---|---|
| Episode | 53 (0,53/hari) |
| Rata-rata bersih / episode | **+0,823%** |
| **Median** / episode | **−0,640%** |
| Win-rate | 49,1% |
| Simpangan baku / episode | **4,58%** |
| Jendela 48 jam yang punya trade | **34,7%** |
| Rata-rata PnL per jendela 48 jam (f=1,0) | **+0,647%**, CI95 **[−0,056; +1,428]** |
| Jendela yang mencapai ≥0,8% | **18,4%** |
| Jendela terburuk | −4,60% |

**Kerapuhan:**

| Uji | Hasil | Arti |
|---|---|---|
| Delay masuk 1/2/5 menit, slippage +5/10/20 bp | rata-rata/episode tetap +0,62…+0,94% | **Edge tidak bergantung pada eksekusi sempurna** (kabar baik) |
| Buang 1 / 3 / 5 episode terbaik | +0,54% / +0,21% / **−0,11%** | **Seluruh edge = beberapa kejadian** (ETH 19-Agu +15,7%, SOL 26-Agu +9,3%, …) |
| Per bulan | Jun n=37 +0,64%; **Jul n=1 −3,04%**; Agu n=15 +1,53% | Terkonsentrasi pada satu pekan ekstrem; satu bulan hampir tanpa sampel |
| θ=1,5% (n=165) | rata-rata +0,10%, hit-rate 26,5% | Edge hilang bila ambang diturunkan |

**Kesimpulan:** profil ini adalah **"tiket lotre"** — median negatif, mean positif karena ekor kanan. Ini tidak dapat memenuhi syarat "≥0,8% di setiap jendela"; bahkan sebagai rata-rata, batas bawah CI-nya negatif. Tetapi ia **bukan edge palsu yang sudah gugur**: tidak runtuh oleh slippage/delay, positif di Jun dan Agu. Keputusan yang benar: **perlu lebih banyak episode independen**, bukan lebih banyak leverage (konsisten dengan bottleneck yang sudah dikunci).

**Aritmetika kebutuhan sampel (jendela 48 jam):** simpangan baku jendela ≈2,6%. Untuk menolak H0 "rata-rata ≤0" pada rata-rata sebenarnya 0,8% (satu sisi, 95%): n ≈ (1,645×2,6/0,8)² ≈ **29 jendela ≈ 57 hari** forward. Bila ketersebaran turun (diversifikasi 17 simbol → σ≈1,3%) → ≈7 jendela ≈ 14 hari. **Pelebaran simbol yang sudah berjalan adalah satu-satunya tuas yang memperpendek waktu pembuktian.**

## 4. Mengapa target "SETIAP jendela" tidak dapat dijamin

Strategi berbasis kejadian: 65% jendela tidak memiliki trade → PnL jendela 0 < 0,8%. Dengan diversifikasi 17 simbol dan f≈0,15/posisi, perhitungan kasar: rata-rata ≈0,9–1,0% per jendela, σ≈1,9% → hit-rate ≈50% (**asumsi**, belum diuji — edge simbol alt belum terbukti). Jadi kriteria penerimaan yang dapat diuji adalah **rata-rata jendela dengan batas bawah CI**, bukan "setiap". Perlu keputusan Anda (§6).

## 5. Peta jalan 40 hari (sampai 15-Nov-2026)

| Tanggal | Langkah | Kriteria lulus (ditulis SEBELUM menguji) | Jika gagal |
|---|---|---|---|
| 06–08 Okt | Rotasi key Binance/OpenRouter/JWT oleh Anda; `freshclam`; salin unit ke git | key lama dicabut | — |
| s/d 28 Okt | Biarkan collector 20 simbol mengumpulkan; counter memantau (68/150 sekarang, ETD 28 Okt) | ≥150 episode **independen** (maks 1 per simbol-60 menit) | Perpanjang; tidak ada pintasan |
| 28–30 Okt | **Pra-registrasi** (commit lebih dulu): uji DEV simbol-baru saja, θ=2%: rata-rata bersih ≥0,40%, BH-FDR q=0,10, p_day<0,05, segmen ≥2/3, **buang-3-terbaik masih >0**, delay-2m masih >0, `lockbox` baru terpisah | semua terpenuhi | Mesin gugur → evaluasi #42 dicatat, bottleneck dianalisis ulang |
| 30 Okt–3 Nov | Uji lockbox baru satu kali | sama, tanpa penyetelan | Gugur |
| 3–15 Nov | Jika lulus: **micro-live** (modal kecil, T1 gate utuh, tanpa leverage) — tujuannya mengumpulkan jendela forward nyata | ≥7–14 jendela 48 jam, rata-rata ≥0,8% dengan CI | Kembali ke paper |

**Realitas 15 November:** jika semua lulus tepat waktu, yang tercapai adalah **micro-live dengan bukti awal**, bukan bukti 100%. Bukti penuh (≥29 jendela) baru ada ±pertengahan Des bila sigma tetap 2,6%.

## 6. Keputusan yang saya butuhkan dari Anda (aturan: tidak ubah target/parameter fundamental tanpa persetujuan)

1. **Kriteria penerimaan resmi**: "rata-rata PnL bersih per jendela 48 jam ≥0,8% dengan batas bawah CI95 >0" (usulan) — atau tetap "setiap jendela" (tidak dapat dijamin)?
2. **Rotasi key** (S1): konfirmasi sudah/akan dilakukan.
3. Izin menyiapkan pra-registrasi 28 Okt (belum ditulis).

## 7. Perintah untuk mengulang

```
.venv-research/bin/python3 scripts/sodex_scan_audit.py all
.venv-research/bin/python3 scripts/sodex_window_sim.py
```
