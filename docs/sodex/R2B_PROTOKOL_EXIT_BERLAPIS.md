# R2 CABANG B — PROTOKOL BEKU: apakah aturan exit berlapis menaikkan MEDIAN, tanpa membunuh ekor?

**Tanggal:** 10-Okt-2026 · **Izin:** Mas Anas (`lanjut B`) · **Sifat:** read-only, TANPA order/posisi/flag live.
**Runner:** `scripts/research/r2b_partial_exit.py` · di-hash bersama berkas ini **sebelum** dijalankan.
**Prasyarat:** `docs/sodex/R2B_KELAYAKAN_DATA_2026-10-10.md` (data LAYAK; ambiguitas intrabar 0,02%).

## Pertanyaan (falsifiable)
H0: tidak ada aturan exit berlapis yang menaikkan median hasil per-trade di ATAS kebetulan.
H1: ada ≥1 aturan berlapis dengan median delta > 0 yang bertahan di data yang tidak dipakai memilihnya, di kedua koreksi bias.

Ini menguji **BENTUK payoff**, bukan pemilihan sinyal. Hanya jalur harga dari trade yang **sudah** diambil engine —
tanpa look-ahead pada entry, tanpa sinyal baru. Menjawab langsung temuan D11/H1 (median MFE +1,087R vs realized −0,125R).

## Data & satuan
- Sumber: 589 trade TWOWAY+REALWIDE yang punya jalur 1h (dari 691); jalur = `data/sodex_klines/1h/<SYM>-USD.json`.
- R per trade = |entry_price − sl_price| (TWOWAY) / entry_p × sl (REALWIDE). Level: +0,5R / +1,0R / +1,5R.
- Hasil diukur sebagai **delta** vs baseline (exit aktual yang tercatat = R0), dalam **% wallet** memakai $242,71.
- **Baseline R0 = hasil aktual tercatat.** Semua aturan dibandingkan berpasangan pada trade yang sama.

## Keluarga aturan (tetap: 4 varian, TIDAK boleh ditambah setelah hasil dilihat)
| Kode | Aturan |
|---|---|
| **R1** | 50% keluar di +1,0R, sisa berjalan sampai TP/SL aktual |
| **R2** | 50% keluar di +1,0R, sisa trailing stop di breakeven setelah +1R tersentuh |
| **R3** | 33% di +0,5R, 33% di +1,0R, sisa berjalan sampai TP/SL aktual |
| **R4** | 100% keluar di +1,0R (kontrol pembanding: "panen penuh", dibandingkan D11) |

## Aturan teknis (dibekukan sebelum run)
1. **Trigger** = harga menyentuh level dalam bar 1h yang bersinggungan hold. Bar ambigu (memuat level DAN SL) → **SL dianggap lebih dulu** (pesimistis). Terukur 2/9.584 bar.
2. **Bar kosong** (trade <2 bar intra-hold) → trade di-DROP; jumlahnya dilaporkan.
3. **Biaya:** fee proporsional notional → memecah exit menjadi 2 tidak mengubah total fee pada tarif sama. Karena itu **tidak diklaim hemat biaya**; yang diuji murni efek bentuk payoff. Sensitivitas biaya tambahan per leg ekstra: **0 / 1 / 2 bps**.
4. **Koreksi bias cakupan (WAJIB):** bobot ulang 589 trade agar komposisi exit_reason = komposisi 691 trade. Ini menutup bias optimistis (TIME 100% terpakai vs SL_BEAR 55%). Hasil dilaporkan **mentah dan berbobot**.

## Desain & kriteria
- **Split:** 60% trade pertama (menurut waktu entry) = DISCOVERY; 40% terakhir = HOLD-OUT. Hold-out tidak dipakai memilih varian.
- **Statistik uji:** median delta discovery per varian; p via permutasi tanda (5.000, seed 20261010); Bonferroni 4 varian → **α = 0,0125**.
- **LOLOS** hanya bila SEMUA benar:
  1. median delta discovery > 0 dan p < 0,0125 · **dan**
  2. median delta hold-out > 0 · **dan**
  3. median **window 30j** (definisi gate resmi) pada hold-out > 0 · **dan**
  4. lolos **berbobot** (median delta berbobot > 0) dan lolos sensitivitas fee +2 bps
- Selain itu → **R2B_NEGATIF**. Hasil positif tidak mengizinkan deploy: hanya maju ke forward paper (n≥100, kill-rule).
- Dilarang setelah melihat hasil: menambah level/varian, mengubah α, memindah titik split, mengganti window, mengecualikan trade selain aturan-2.

## Dinyatakan SEBELUM hasil
- Uji ini bisa **gagal dua arah**, dan keduanya bermakna: (a) positif → jalur menuju versi payoff baru untuk diuji forward;
  (b) negatif → **cabang exit tertutup**; sisa satu-satunya arah adalah biaya/venue, bukan exit.
- Daya rendah: hold-out ≈ 236 trade; deteksi median +0,10% wallet/trade berdaya terbatas.
- Simulator jalur = klines 1h SoDEX (bukan tick). Fill nyata tetap belum terbukti.
- Setiap varian dicatat sebagai trial di `sodex_trial_registry.json` (ambang t program naik sesuai).

**Hash beku (sha256 protokol+runner, 16 hex):** `c724887ac5a1ef4d` — dicatat di commit SEBELUM run.
**Pasca-refresh klines:** 23/23 simbol ter-update ke bar 2026-10-09 22:00Z (exit 0); ekor 3,5 jam tertutup.
**Fingerprint pasca-refresh:** `reports/sodex/R2B_FINGERPRINT.json`.
