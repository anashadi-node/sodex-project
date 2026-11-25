---
name: prereg-25-breadth-universe
description: PRAREG-25 — pra-registrasi dibekukan: breadth (top-20 likuid) untuk membeli daya statistik. Sinyal identik PRAREG-23.
metadata:
  type: project
---

# PRAREG-25 — BREADTH: UNIVERSE 6 → TOP-20 LIKUID

**Status: DIBEKUKAN SEBELUM DATA DIEVALUASI.** Di-hash sebelum satu baris hasil PRAREG-25 dilihat.

- Tanggal beku: 09-Okt-2026 · Disetujui Anas: opsi "PRAREG-25".
- **Hipotesis:** PRAREG-24 gagal pada (d) dan (e) karena **daya statistik**, bukan karena sinyal
  atau eksposur. Menambah **jumlah taruhan independen** menaikkan daya statistik **tanpa** menaikkan
  risiko per taruhan.
- **Perubahan tunggal dari PRAREG-24:** universe 6 → **top-20 likuid** dari pool tetap.
  **Sinyal tetap identik** (kode `series_for` yang sama; implementasi cepat wajib lulus uji ekuivalensi).
- Ambang: **t ≥ 3,6** · **Bonferroni 2 lengan → p < 0,025** · **DSR** dihitung dengan n_trials jujur.

## 1. Pool kandidat (tetap, ditulis sebelum hasil)
66 simbol Binance spot USDT dari `scripts/research/prereg25_fetch_universe.py`, **termasuk yang sudah
delisting** (FTT, LUNA, SRM, TOMO, AGLD, NKN) untuk **menekan — bukan menghapus — bias survivorship**.
Simbol tanpa data (<500 bar) dibuang **mekanis** dan dicatat di `data/prereg25/MANIFEST.json`.

## 2. Seleksi universe (mekanis, tanpa look-ahead)
- Pada **akhir setiap bulan**, hitung **median quote-volume 30 hari** (USDT) tiap kandidat.
- Ambil **20 teratas** → itu universe bulan berikutnya.
- Koin eligible untuk **sinyal** bila punya **≥360 hari** riwayat.
- Tidak ada intervensi manusia per koin. Koin mati akan keluar sendiri saat likuiditasnya hilang.

## 3. Sinyal & sizing
- **Sinyal: IDENTIK PRAREG-23/24** — ensemble Donchian 9 window + stop ratchet, diimpor dari
  `prereg23_trend_daily`. Implementasi cepat (rolling max/min) wajib **lulus uji ekuivalensi**
  baris-per-baris terhadap `series_for` pada 3 koin; bila tidak identik → hasil batal.
- **Dua lengan pra-registrasi (keduanya dilaporkan):**
  | Lengan | Rumus | Catatan |
  |---|---|---|
  | **S-A** (kontrol) | `(longs/9) × min(1, 0,25/vol) ÷ N` | seperti V0; diperkirakan gagal **(f)** by construction |
  | **S-B** (primer) | `(longs/9) × min(1, 0,25/vol)`, **cap Σw ≤ 1,00** | seperti V1 tanpa pembagi N |
- **Tanpa leverage.** Sisanya USDC. Eksekusi harian, pita rebalance 20% (kontrol biaya rotasi).

## 4. Biaya
- **Utama 25 bps/sisi**, sekunder 10 bps/sisi. Rotasi bulanan menaikkan turnover — **wajib dilaporkan**
  sebagai bagian hasil (bukan disembunyikan).

## 5. Gerbang — semua wajib (25 bps, jendela terverifikasi)
| # | Kriteria |
|---|---|
| a | Sharpe ≥ Sharpe BTC buy-and-hold |
| b | maxDD ≤ 50% × drawdown BTC |
| c | Positif di ≥2 dari 3 sub-periode |
| d | ≥60% blok 20-hari positif **dan** median blok 20-hari > 0 |
| e | **p < 0,025** (Bonferroni 2 lengan), bootstrap blok 20 hari vs BTC |
| **h** | **DSR > 0** dengan **n_trials = 80** (jumlah trial jujur; 76 tercatat + 2 lengan + margin) |
| f | **≥ 0,10%/48 jam** (lantai tangga disetujui) |
| g | Eksposur rata-rata ≥ 0,30 (lengan S-B) |

## 6. Sensitivitas WAJIB dilaporkan (bias yang tidak dapat dihapus)
1. Hasil **tanpa 3 koin berkinerja terbaik** (uji ketergantungan pada pemenang).
2. Hasil **tanpa koin yang delisting** (uji ketahanan bila pool lebih bersih).
3. Hasil pada **ekstensi 2025-10-10 → 2026-10-07** (tidak terverifikasi) — dilaporkan terpisah.
4. **Turnover & biaya** per tahun.

## 7. Pengungkapan & disiplin
- **Pool kandidat tetap mengandung bias survivorship** (koin harus masih ada di daftar Binance hari ini
  untuk bisa saya unduh; koin yang mati di luar daftar itu tidak terwakili). Ini **dinyatakan terbuka**.
- Tidak ada ambang yang diubah setelah melihat hasil. Tidak ada pemilihan koin manual.
- Bila lengan lolos: promosi tetap butuh **paper-forward ≥ 30 hari** + keputusan Anas.
- Trial **wajib** dicatat di `reports/sodex/sodex_trial_registry.json` lewat `TrialRegistry` (termasuk gagal).
