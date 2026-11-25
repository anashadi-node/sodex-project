---
name: prereg-24-varian-eksposur
description: PRAREG-24 — pra-registrasi dibekukan: varian sizing (eksposur) dengan sinyal IDENTIK PRAREG-23 H1. Menyasar lantai tangga 0,10%/48 jam.
metadata:
  type: project
---

# PRAREG-24 — VARIAN EKSPOSUR (SIZING SAJA; SINYAL IDENTIK PRAREG-23)

**Status: DIBEKUKAN SEBELUM DATA DIEVALUASI.** Di-hash sebelum satu baris hasil dilihat.

- Tanggal beku: 09-Okt-2026 · Disetujui Anas: opsi "Varian eksposur".
- Dasar diagnosis: PRAREG-23 H1 punya Sharpe **+1,47** tetapi hanya **0,0738%/48 jam** karena
  **eksposur rata-rata 0,11** (89% USDC). Sinyalnya bukan penyumbat — **sizing** penyumbat.
- Ambang keputusan: **t ≥ 3,6**; multiple-testing 3 varian → **Bonferroni p < 0,05/3 = 0,0167**.

---

## YANG TIDAK BERUBAH (dikunci)
- **Sinyal IDENTIK** — kode diimpor dari `scripts/research/prereg23_trend_daily.py`
  (`series_for`). Bukan salinan: itu modul yang sama, sehingga tidak mungkin menyimpang.
- Universe, data, fingerprint, biaya, pemanasan 360 hari, 9 window Donchian, pita rebalance 20%,
  eksekusi harian — **semuanya sama** dengan PRAREG-23.
- **Tanpa leverage**: total bobot ≤ 1,00 (sisanya USDC).

## YANG BERUBAH (hanya fungsi sizing)
| Varian | Tanpa pembagi N | Vol-target |
|---|---|---|
| **V0** (baseline = H1) | tidak (÷N) | 25% |
| **V1** | **ya** | 25% |
| **V2** | tidak (÷N) | **50%** |
| **V3** | **ya** | **50%** |

`bobot_koin = (jendela long / 9) × min(1, vol_target / vol_tahunan_90h)` — lalu ÷N bila varian
memakai pembagi, lalu **di-cap**: bila Σbobot > 1,00 → diskalakan ke 1,00 (tanpa leverage).

V0 wajib mereproduksi PRAREG-23 H1 (Sharpe ≈ +1,47) sebagai **uji konsistensi internal**;
bila tidak cocok, seluruh hasil PRAREG-24 batal.

## GERBANG — semua wajib (biaya 25 bps/sisi)
| # | Kriteria | Kenapa |
|---|---|---|
| a | Sharpe ≥ Sharpe BTC | mutu sinyal |
| b | maxDD ≤ 50% × Drawdown BTC | risiko |
| c | Positif di ≥ 2 dari 3 sub-periode | ketahanan rezim |
| d′ | **≥60% blok 20-hari positif DAN median blok 20-hari > 0** | pengganti (d) |
| e | **p < 0,0167** (Bonferroni 3 varian), bootstrap blok 20 hari vs BTC | signifikansi |
| f | **Return ≥ 0,10%/48 jam** (lantai tangga disetujui) | kriteria ekonomi |
| g | Eksposur rata-rata ≥ 0,30 | bukti varian benar-benar mengubah sizing |

## PENGUNGKAPAN WAJIB (risiko goalpost-moving)
Kriteria **(d) PRAREG-23** ("Sharpe tanpa 5% hari terbaik > 0,5") **gagal**, dan **(d′) dirumuskan
setelah fakta itu diketahui**. Ini mengandung risiko *goalpost-moving* dan harus dinyatakan terbuka.
Mitigasi yang dipakai:
1. **(d′) bukan pelonggaran**: 60% blok positif + median blok positif adalah syarat keras yang
   H1 sendiri belum tentu lolos.
2. **(e) DIPERKETAT** dari p<0,05 → **p<0,0167** (Bonferroni untuk 3 varian).
3. Ditambah kriteria baru yang **tidak ada** di PRAREG-23: **(f) ekonomi** dan **(g) eksposur**.
4. **PRAREG-23 tetap GAGAL** dan tidak diubah. PRAREG-24 adalah protokol **baru**, bukan
   amandemen retroaktif. H1 tidak dipromosikan oleh hasil PRAREG-24.
5. Bila varian lolos, promosi tetap butuh: **paper-forward** ≥ 30 hari + keputusan Anas.

## Pelaporan
- Jendela **terverifikasi (≤ 2025-10-09)** dan **ekstensi** dilaporkan terpisah.
- Biaya 25 bps (keputusan) dan 10 bps (informasi).
- Format tunggal: **% per 48 jam** dari total wallet.
- Varian yang gagal **dibuang**, tidak "diperbaiki" sampai lolos.
