# PRAREG-SIG-07 — MOMENTUM CROSS-SECTIONAL MARKET-NEUTRAL (48 JAM)

**Tanggal:** 25 Okt 2026 · **Status:** dibekukan SEBELUM dijalankan
**Alasan:** seluruh 1.080 uji sebelumnya bersifat **directional** (tebak arah).
Hipotesis ini berbeda secara ekonomi: tidak menebak arah pasar, melainkan
**selisih** antara pemenang dan pecundang relatif — sehingga eksposur pasar
hilang dan sd per window seharusnya jauh lebih kecil.

---

## Hipotesis (satu, bukan grid)

**H1-XS:** Pada universe likuid SoDEX era-real, simbol dengan return 24 jam
teratas mengungguli simbol dengan return 24 jam terbawah selama 48 jam
berikutnya, setelah biaya.

- Sinyal: `r24 = close(t0)/close(t0-24j) - 1`
- Portofolio: long 3 teratas, short 3 terbawah, **dollar-neutral**, equal weight
- Horizon: 48 jam, **non-overlap** (satu observasi per 48 jam)
- Biaya: 6,49 bps per leg round-trip × 2 leg = **12,98 bps per rebalance**
- Universe: simbol dengan ≥ 2.000 bar era-real dan median quote volume ≥ **$5k/jam**
  *(amandemen pra-jalan 25 Okt: ambang $100k hanya menyisakan 3 simbol → 0 window;
  diturunkan sebelum uji dijalankan, tanpa melihat hasil. Sensitivitas biaya dilaporkan.)*
- Data: hanya `t ≥ 2026-06-12` (sebelum itu mirror Binance sintetis)

## Gerbang (tidak bisa dinegosiasikan setelah dijalankan)

| Gerbang | Aturan |
|---|---|
| Signifikansi | \|t\| ≥ 4,11 (N=1.081, Bonferroni) |
| Arah | mean net > 0 |
| Split waktu | tanda & signifikansi di 70% awal harus berulang di 30% akhir |
| Kontrol | permutasi 1.000× (long/short acak) harus kalah p < 0,05 |
| Bukti minimum | n ≥ 40 window non-overlap |

## Yang TIDAK boleh dilakukan setelah melihat hasil

- Mengubah jumlah long/short (3 → 5) untuk mengejar hasil.
- Mengubah horizon sinyal (24j → 72j) atau holding (48j → 72j).
- Membuang simbol yang merugikan.
- Menambah filter regime.

Varian lain hanya boleh dilaporkan sebagai **eksploratif** dan masuk registry
sebagai uji tambahan (BH correction diperbarui).

## Prediksi falsifiable

Jika H1-XS benar dengan Sharpe per window ≥ 0,3, maka bukti bisa dicapai dalam
± (4,11/0,3)² ≈ 188 window ≈ 1 tahun. Jika Sharpe ≤ 0,1, jalur ini mati dan
tidak boleh diulang dengan variasi parameter.
