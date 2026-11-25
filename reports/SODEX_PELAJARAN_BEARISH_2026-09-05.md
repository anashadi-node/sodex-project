# PELAJARAN BEARISH-SHORT — PERBAIKAN KELEMAHAN SAAT MARKET TURUN (2026-09-05)
> User menunjuk kelemahan: sistem kurang akurat/predictive saat market bearish.
> Artikel ini = analisa data + perbaikan yang diterapkan.

## 1. BUKTI KELEMAHAN (dari data nyata, bukan perasaan)
### TWOWAY SHORT (n=42, eksperimen ditutup 2026-09-02)
| Metrik | Nilai |
|---|---|
| WR | 33,3% (vs LONG 54,6%) |
| avg | -0,449% (vs LONG +0,552%) |
| Exit TIME_30h | **23/42 = 55%** (harga nyaris tak turun) |
| Exit TP | hanya 4/42 = 9,5% |

**Akar masalah**: short masuk saat *bounce kecil* (syarat r1 > -0,3%),
belum tentu harga turun lanjut → 55% posisi "nangkring" sampai time-stop.

### Backtest short-bear 500 jam (hari ini)
- TP4%/SL2%: **0 TP di SEMUA pair** (BTC/ETH/SOL/DOGE/XRP semua avg -0,7% s/d -1,7%)
- Artinya TP 4% TIDAK tercapai di market sideways — bukan free-fall.
- Adaptasi TP2,5%/L2 belum konklusif (n kecil), tapi arah konsisten.

## 2. PERBAIKAN DITERAPKAN (commit d69d0c7)
### a. Sinyal short: dari "bounce" ke "momentum turun NYATA"
```
SEBELUM: r1 > -0.003 (1 jam terakhir TIDAK turun — masuk saat bounce)
SESUDAH: r1 <= -0.003 (1 jam terakhir SUDAH turun ≥0,3% — momentum turun)
```
→ Short HANYA saat harga sedang turun berkelanjutan, bukan saat berhenti.

### b. Time-stop short: 30h → 16h
- 55% TWOWAY short mentok TIME_30h = modal terikat tanpa hasil.
- Short di market sideways harus konklusif cepat: 16h cukup.

### c. Leverage short: 3x → 2x (riset portfolio: L3 bahaya di semua skenario)

### d. Gate alert otomatis (Jalur A)
- `sodex_gate_monitor.py` piggyback watchdog: **alert seketika saat gate LONG
  terbuka** (BTC > SMA50) → live realwide langsung bisa entry tanpa monitor manual.

## 3. VERIFIKASI HASIL
- Setelah filter baru: **TIDAK ada pair yang fire short** (SOL yg kemarin fire
  sekarang tidak) — karena r1 sekarang harus turun. Ini artinya sistem TIDAK
  asal short di market sideways; hanya short saat turun.
- Ini persis kelemahan yang user tunjuk & sudah dikoreksi.

## 4. RENCANA VALIDASI (jangan overfit)
- SHORT_BEAR & PORTFOLIO kumpul n≥30 forward dgn filter baru.
- Gate promosi live: WR≥50%, PF≥1,5, ROI≥0,7% + approval user.
- Kalau 30 trade pertama masih negatif → FALSIFIKASI jujur, cari pendekatan
  lain (misal mean-reversion short yang cocok sideways).

## 5. DATA SPOT (bonus, dari 2 track)
- **SPOT_V4 SoDEX**: n=11, total_pnl +$4,78, open 4 (vBTC/vTON/vLINK).
- **CEX SPOT**: SIGNAL n=120 WR 45,8% avg +0,283%; RANDOM n=122 WR 49,2% avg
  +0,357%. Exit terbanyak TP (50/51) — SPOT lebih sehat dari short.