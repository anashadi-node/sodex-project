# R4 — PROTOKOL BEKU: GATE REGIME (hapus trade yang melawan arah pasar)

**Dibekukan:** 10-Okt-2026, SEBELUM evaluasi forward dihitung
**Sifat:** read-only. TANPA order, TANPA perubahan track/threshold/live-flag.
**Dasar:** R3C — WR holdout 27,8% (train 41,2%) pada buku **93% LONG**; LONG 25,4% vs SHORT 44,1%; TP 28%→9%. Kontrol RANDOM 19,0% → ΔWR sinyal +8,8 pp. Diagnosis: efek regime, bukan sinyal mati.

## Klasifikasi regime (ex-ante, tanpa look-ahead)

Sumber: `data/sodex_klines/1h/BTC-USD.json` (bar `bars`, venue SoDEX); fallback feather Binance `BTC_USDT_USDT-1h-futures`.
Ambil bar **tertutup terakhir yang t-nya < waktu entry** (tidak boleh bar yang memuat entry).

```
ret24 = c[t]/c[t-24] - 1        sma72 = mean(c[t-71..t])
BULL  (LONG_OK)  : ret24 > 0  DAN c[t] > sma72
BEAR  (SHORT_OK) : ret24 < 0  DAN c[t] < sma72
MIXED            : sisanya (konflik / datar)
```

## Aturan gate yang diuji (beku)

- **G1**: buang entry **LONG** bila regime bukan BULL.
- **G2**: buang entry **SHORT** bila regime bukan BEAR.
- **G12**: G1 + G2 (buku hanya trade searah regime).

**Ruang lingkup**: hanya PENGHAPUSAN. Tidak ada trade baru yang dikarang; memperbanyak SHORT adalah mesin baru, bukan gate, dan **tidak diuji di R4**.

## Kriteria keputusan (beku)

Jendela verdict = **forward murni**: semua entry dengan `entry ≥ 2026-10-11T00:00Z`.
- **LOLOS**: WR subset dipertahankan ≥ 45,0% **dan** ΔWR(kept − dropped) ≥ +5,0 pp **dan** n_kept ≥ 40 **dan** binomial satu-sisi p<0,05 terhadap baseline train 40,9%.
- **KUAT**: tambahan WR_kept ≥ 50% dan ΔWR ≥ +10 pp.
- **GAGAL**: salah satu tidak terpenuhi.
- Sekunder (bukan syarat): metrik window resmi 30 jam (median & hit ≥0,8%, wallet 242,79) pada subset kept vs baseline; dinyatakan *underpowered* bila <8 window.
- Pembanding wajib: WR arm **RANDOM** pada jendela yang sama (gate harus mengalahkan kontrol, ΔWR>0).

## Disiplin evaluasi (anti optional-stopping)

- Verdict diambil **SEKALI**, ketika **kedua** syarat terpenuhi: kalender ≥ **17-Okt-2026** DAN n_kept ≥ 40. Tidak ada penghentian dini, tidak ada perubahan ambang setelah melihat data.
- Monitor harian bersifat **operasional, bukan inferensial**: hasilnya dilaporkan apa adanya tetapi tidak dipakai untuk mengubah aturan atau mengambil keputusan lebih awal.
- Jendela retrospektif 1–10 Okt sudah terlihat di R3C → dilaporkan sebagai **label deskriptif, BUKAN verdict**.
- Efek regime tidak menambah look count pada data train (klasifikasi memakai harga BTC, bukan outcome trade).

## Batas yang diakui

1. Gate hanya bisa membuang; ia tidak bisa menciptakan trade yang tidak ada. Keuntungan maksimum = menghindari kerugian, bukan menambah profit baru.
2. Klasifikasi 3-state dari 2 kondisi sederhana → rentan salah label saat pasar choppy; itu sebabnya MIXED diperlakukan sebagai "blokir kedua arah" pada G12.
3. Bila forward tidak menghasilkan ≥40 trade kept, uji dinyatakan TIDAK KONKLUSIF (bukan lolos).
4. Tidak mengubah target 0,8%, tidak mengubah SL/TP/leverage, tidak menyalakan order.

*Protokol beku · Hermes Anantara v3 · 10-Okt-2026*
