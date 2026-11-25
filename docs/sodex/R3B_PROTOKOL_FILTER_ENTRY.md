# R3B — PROTOKOL BEKU: UJI FILTER ENTRY (tanpa mengubah target 0,8%)

**Dibekukan:** 10-Okt-2026, SEBELUM holdout dihitung
**Sifat:** read-only. TANPA order, TANPA perubahan parameter track/live.
**Dasar:** R3A anatomi rugi pada **TRAIN saja** (`entry < 2026-10-01T00:00Z`, n=1659, WR dasar 40,9%). 43 hipotesis diuji, BH-FDR q<0,10 → 8 lolos. Holdout (n=436) BELUM dihitung (buta).

## Aturan yang dibekukan (ex-ante, mekanis)

**R-A — Jam UTC 12 dilarang.** Train: WR 18,5% (n=54) vs sisa 41,6%, ΔWR −23,1%, z=−3,40, q=0,0147, mean −$2,51/trade.
Mekanisme yang diklaim: sesi likuiditas tipis/transisi (US pre-open) → whipsaw.

**R-B — Tolak entry bila ATR% ≥ 1,0 (hanya track yang mencatat `atr_pct`, yaitu realwide).** Train: WR 36,3% (n=267) vs ATR<1% 44,8% (n=402), ΔWR −6,8%, q=0,233 (borderline — TIDAK signifikan setelah BH).
Mekanisme yang diklaim: volatilitas ekstrem → SL lebih cepat tersentuh oleh noise, bukan oleh arah.

**R-AB (gabungan)** = tolak jika (jam UTC = 12) ATAU (atr_pct ≥ 1,0).

## Kriteria keputusan (beku, SEBELUM holdout dilihat)

Holdout = semua entry dengan `entry ≥ 2026-10-01T00:00Z` dari 7 track (mekanisme & berkas sama dengan R3A). Untuk tiap aturan:

- **LOLOS:** subset yang DIPERTAHANKAN punya WR ≥ 45,0% **dan** ΔWR(dipertahankan − dibuang) ≥ +5,0 pp **dan** n_dipertahankan ≥ 40 **dan** uji binomial satu-sisi p<0,05 terhadap baseline train 40,9%.
- **KUAT:** tambahan syarat: WR_dipertahankan ≥ 50% dan ΔWR ≥ +10 pp.
- **GAGAL:** salah satu syarat tidak terpenuhi.
- Kontrol: WR arm **RANDOM** di holdout dilaporkan; subset yang dipertahankan harus **mengalahkan kontrol** (ΔWR > 0). Jika kontrol tidak ada/terlalu tipis, dilaporkan apa adanya.
- Sekunder (bukan syarat): metrik window resmi 30 jam pada subset terfilter, median & hit. Dinyatakan **underpowered** bila <8 window — tidak boleh dipakai untuk mengklaim lolos.
- R-B hanya berlaku pada track yang punya `atr_pct`; bila n_holdout-nya <40, dinyatakan **tidak dapat diuji** (bukan lolos, bukan gagal).

## Batasan yang diakui (beku)

1. Aturan dipilih SETELAH melihat train → ada risiko seleksi; holdout adalah satu-satunya arbiter, dan hanya **satu** uji per aturan (tidak ada p-hunting lanjutan).
2. Efek jam rawan overfit (24 jam diuji); R-A adalah yang terkuat secara statistik tapi tetap harus lolos holdout.
3. Uji ini menguji **arah** (WR), bukan langsung PnL window. Gate window tetap dilaporkan sebagai sekunder.
4. Tidak ada perubahan pada track live, threshold, atau file state. Filter hanya dihitung di runner analisis.

## Yang TIDAK dilakukan

Tidak mengubah target 0,8%, tidak mengubah SL/TP/leverage, tidak menyalakan order, tidak menambah koin demi p-value. Setiap look tambahan dicatat sebagai trial di registry kanonik (ambang t naik).

*Protokol beku · Hermes Anantara v3 · 10-Okt-2026*
