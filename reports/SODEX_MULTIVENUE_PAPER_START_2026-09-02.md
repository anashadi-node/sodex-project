# SODEX — PAPER TEST MULTI-VENUE PARALEL (2026-09-02)
# Hyperliquid & Aster — paralel terisolasi, tanpa mengganggu SoDEX
# Hermes Anantara v2 | scientific: sinyal identik, venue berbeda

---

## KEPUTUSAN VENUE YANG DIUJI

| Venue | Status API | Fee | Alasan diuji |
|-------|-----------|-----|-------------|
| **Hyperliquid** | ✅ Terverifikasi (l2Book, allMids) | taker 0.045% | KPI 88, likuiditas #1 |
| **Aster** | ✅ Terverifikasi (Binance-compatible) | taker 0.04% / maker 0% | API termudah, TVL $1.46B |
| Vertex | ⏸️ Pending | — | Endpoint belum bisa diakses (404) — catat |
| Lighter | ⏸️ Pending | — | Domain tidak resolve — catat |

> **Ilmiah:** bukan opini — 2 venue yang API-nya benar-benar terhubung diuji;
> 2 lainnya ditunda sampai koneksi terverifikasi (tidak menebak/memalsukan data).

---

## ARSITEKTUR (apples-to-apples)

```
Sinyal IDENTIK (Binance 1h: close>SMA50>SMA200, mom24>0)
        │
        ├──► eksekusi simulasi di HYPERLIQUID (mark price + l2Book spread)
        │        fee taker 0.045%
        │
        └──► eksekusi simulasi di ASTER (bookTicker + bid/ask)
                 fee taker 0.04%
        
Exit: TP 4% / SL 2% (t=0) / time-stop 30h / lev 3x — IDENTIK realwide
State: data/paper_test_{venue}_state.json (terpisah)
Service: anantara-paper-hyperliquid · anantara-paper-aster (baru)
```

**Penting:** strategi SAMA persis di kedua venue → perbedaan hasil = murni
efek venue (spread, slippage, harga, fee). Ini isolasi variabel yang benar.

---

## STATUS AWAL (05:17 WIB)

| Venue | Service | Open | Closed | Catatan |
|-------|:-------:|:----:|:------:|---------|
| Hyperliquid | ✅ active | 0 | 0 | menunggu sinyal |
| Aster | ✅ active | **1** (UNI @ 6.36) | 0 | sudah buka posisi |

**Contoh kerja nyata:** posisi UNI @ 6.36 di Aster memakai mark price venue
live (bukan asumsi) — spread model half_spread=0.0015 (0.15%) tercatat.

---

## GARANSI KEAMANAN (tidak mengganggu SoDEX)

| Check | Status |
|-------|:------:|
| 6 service SoDEX (swing/partial/twoway/realwide/spot/donchian) | ✅ semua active |
| State SoDEX intact (124/44/35 closed) | ✅ tidak tersentuh |
| Service baru = nama terpisah (anantara-paper-hyperliquid/aster) | ✅ terisolasi |
| Env file = .env.swing (non-secret) | ✅ tidak pegang key |
| State file = paper_test_{venue}_state.json (baru) | ✅ tidak bentrok |
| Read-only API (tanpa order) | ✅ PAPER ONLY |

---

## MONITORING & KEPUTUSAN

- Report otomatis: kedua venue masuk `sodex_progress_report.py` (berikutnya)
- Target evaluasi: **n≥50 trade per venue** (~30 hari)
- Metrik banding: EV/trade, ROI wallet, hit-rate 0.7%, spread efektif
- **Keputusan akhir:** venue dengan CI95 EV > 0 & spread terbaik → kandidat
  adopsi (paper dulu, lalu konfirmasi user sebelum real-money)
- SoDEX TETAP berjalan sebagai baseline — tidak dimatikan

---

## YANG BELUM (jujur)

- **Vertex & Lighter:** endpoint tidak bisa diakses dari server (404 / DNS).
  Perlu verifikasi domain resmi via docs lebih dalam sebelum adapter.
- Kedua venue baru: belum ada closed trade → n kecil, hanya uji koneksi & sinyal.
- Progress reporter utama belum meng-include multi-venue (tambahan berikutnya).

---

*Laporan 2026-09-02 05:20 WIB | Hermes Anantara v2*
*Paper test multi-venue paralel — aman, terisolasi, scientific.*