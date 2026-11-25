# PRAREG-SIG-08 — FUNDING CARRY DELTA-NEUTRAL (OOS 2025–2026)

**Tanggal:** 25 Okt 2026 · **Status:** dibekukan sebelum uji konfirmatori dijalankan

## Hipotesis

**H1-CARRY:** Portofolio *short perp + long spot* pada simbol dengan funding
7-hari positif menghasilkan carry bersih positif setelah biaya, dengan Sharpe
tahunan yang cukup tinggi untuk dibuktikan cepat.

## Mengapa ini berbeda

1.080 uji sebelumnya menebak **arah harga**. Carry tidak menebak arah: ia memanen
**pembayaran funding** dan lindung nilai delta. Risiko utamanya bukan harga,
melainkan **konvergensi basis** — dan itu WAJIB dimasukkan sebagai biaya.

## Desain (satu konfigurasi, tidak boleh diubah setelah hasil)

| Komponen | Aturan |
|---|---|
| Universe | Binance, funding ≥ 500 event sejak 2024 |
| Seleksi | **Top 10** menurut mean funding harian tahun **2024** (latih) |
| Uji | **2025-01-01 s/d 2026-10-24** (out-of-sample, tidak dipakai memilih) |
| Filter aktif | trailing 21 event (7 hari) mean funding > 0 |
| PnL per event | `funding_bps + (basis_sebelum − basis_sesudah)` bps |
| Basis | `markPrice / spot_close − 1`, markPrice dari record funding, spot dari klines 1h |
| Biaya | 6,49 bps setiap transisi aktif↔datar (satu round-trip) |
| Portofolio | equal weight antar simbol aktif |
| Window | harian (3 event) |

## Gerbang

| Gerbang | Aturan |
|---|---|
| Signifikansi | \|t\| ≥ 4,11 (N=1.272) |
| Arah | mean net > 0 |
| Bukti minimum | ≥ 180 hari uji dan ≥ 5 simbol aktif |
| Kontrol | tanpa biaya basis (versi "naif") harus lebih tinggi — jika tidak, model salah |

## Metrik yang wajib dilaporkan

mean bps/hari, sd, SR tahunan, t, **leverage yang dibutuhkan untuk 0,8%/30 jam**,
dan **waktu sampai t=4,11**.

## Prediksi falsifiable

Jika mean net ≤ 0 setelah basis → carry mati sebagai jalur target.
Jika mean net > 0 tetapi SR < 1,5 → tidak lebih cepat dibuktikan daripada directional.
