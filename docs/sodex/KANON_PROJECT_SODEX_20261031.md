# SoDEX — Kanon Tujuan, Target, Algoritma, Prinsip, Workflow

**Tanggal kanon:** 31-Okt-2026 · **Status:** referensi operasional utama.
Dokumen ini merangkum keputusan yang sudah disetujui; tidak mengganti amandemen
sumber. Jika konflik, dokumen sumber ber-hash dan pra-registrasi yang lebih spesifik menang.

## 1. Tujuan
Membangun sistem SoDEX spot + perps yang menghasilkan **alpha bersih** setelah fee,
spread, slippage, funding, dan beta pasar; return dihitung terhadap **total wallet
spot + perps**. Real live trading modal kecil dimulai 01-Des-2026 sebagai uji eksekusi,
bukan klaim edge telah terbukti.

## 2. Target — dua lapisan yang tidak boleh dicampur
### Target utama proyek
Tangga resmi per window: lantai 0,10%; sasaran 0,25%; stretch 0,40%; **penuh 0,80%**.
Level penuh tetap tujuan akhir. Kelulusan memakai **A DAN B** pada grid tetap 30 jam,
anchor 2026-08-03T00:00:00Z: A mean ≥ ambang; B median > 0 dan hit ≥50%; window
kosong dilewati dan dilaporkan; minimum 10 window berisi. Denominator total wallet.

### Target operasional arm awal
**0,01% per 5 jam net** untuk PRAREG-23b/perps. Ini tidak menggantikan 0,8%/30 jam.
Mode A spot historis sekitar 0,006%/5 jam. PRAREG-38 P1 point estimate 0,01285%/5 jam,
tetapi target belum terbukti statistik (`p(M≤0,010)=0,3215`).

## 3. Algoritma
1. Signal engines spot/perps menghasilkan kandidat entry.
2. Paper execution mencatat trade dan state JSON.
3. Settlement hanya untuk trade selesai dan bar tertutup:
   `alpha_net = r_trade − beta_side × r_BTC − biaya`, beta +1 long/−1 short.
   Data kurang → UNSETTLED; tidak dikarang.
4. Seleksi statistik: rolling/forward, OOS, t/WR/E/MDD, BH-FDR, kontrol negatif.
5. PRAREG-40: reflection deterministik, maksimal 3 aturan dari episode dengan
   `exit_ts < entry_ts`; tidak ada LLM di jalur keputusan.
6. PRAREG-41: forward blocklist ETH/ASTER/SUI.
7. PRAREG-42: forward SHORT 00–05 UTC; rezim BTC-vs-MA50h hanya diagnostik.

## 4. Prinsip kerja
- Falsification-first: hipotesis, window, biaya, dan gate dibekukan sebelum hasil.
- Net profit, bukan gross PnL; alpha harus dipisahkan dari beta pasar.
- Backtest menghasilkan kandidat; forward/OOS menentukan kelayakan.
- Tidak ada lookahead, shuffle time-series, atau penyelamatan post-hoc.
- Multiple testing wajib dikoreksi; n kecil = monitor/data invalid, bukan verdict.
- Pasar jelek tidak menjadi alasan mengubah gate; rezim dianalisis pra-hasil.
- Safety/privacy pertama: dry-run default, fail-closed, kill switch, cap modal/order,
  IOC limit, tidak retry order berstatus ambigu, kredensial tidak pernah masuk git/log.
- Perubahan target fundamental hanya melalui persetujuan user + amandemen tertulis.

## 5. Workflow
`market/orderbook/funding → signal spot+perps → paper execution → settlement 06:40 →
PRAREG40_SETTLED.jsonl → overlay 40/41/42 pukul 06:45/06:50/06:55 → checkpoint
07-Nov → verdict PRAREG-26 25-Nov + arm lain 26-Nov–01-Des → preflight 27–29 Nov →
user signs LIVE_ARMED + CONFIRM_LIVE → live modal kecil 01-Des → rekonsiliasi order,
fill, dan PnL nyata → scale hanya setelah edge dan execution terbukti`.

PRAREG-40 berjalan sampai 30-Des dan dievaluasi 31-Des; tidak boleh menjadi alasan
GO live 01-Des.

## 6. Fakta terakhir yang wajib diingat
- Baseline settled 1.690 trade/15 track: tidak ada track lolos BH q=0,05.
- PnL paper banyak dijelaskan beta pasar; buku 87% long.
- ETH/ASTER/SUI negatif bukan sekadar fee; kandidat terbaik adalah short 00–05 UTC,
  tetapi masih in-sample dan wajib forward.
- Pilot reflection membaik +8,3 bps tetapi ΔWR +1,8 pp <3 pp → G3 gagal.
- Klaim sah sekarang: pipeline berjalan, kandidat hidup, **edge forward belum terbukti**.

## 7. Dokumen sumber otoritatif
- `AMANDEMEN_TARGET_AB_2026-10-10.md`
- `AMANDEMEN_TANGGA_TARGET_RESMI_2026-10-22.md`
- `PRAREG_23b_MODE_A_5JAM.md`, `PRAREG_26_MESIN_SELEKSI.md`
- `PRAREG_38_PERPS.md`, `PRAREG40_DESIGN.md`
- `PRAREG41_DESIGN.md`, `PRAREG42_DESIGN.md`
- `GO_LIVE_01DES_RUNBOOK.md`
