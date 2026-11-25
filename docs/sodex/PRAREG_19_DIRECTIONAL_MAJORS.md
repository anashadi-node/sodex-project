# PRAREG-19 — DIRECTIONAL MAJORS (BTC/ETH/SOL), α ≥ 32 bps/48 jam

**Status: DIBEKUKAN di muka (keluarga sinyal, gerbang, dan jumlah sel dipatok SEBELUM data disentuh).**
Dasar mandat: butir 3 dari 3 yang disetujui Mas Anas 2026-10-09 (alihkan riset ke directional majors).
Tanggal beku: 2026-10-09 · Sifat hasil historis: **DESKRIPTIF** (verdict hanya dari forward).

---

## 1. Mengapa jalur ini berbeda dari yang ditutup

| Uji | Cross-sectional (DITUTUP) | Directional majors (PRAREG-19) |
|-----|---------------------------|-------------------------------|
| Kapasitas | 95% nama tanpa likuiditas | BTC+ETH = $2,03 jt/jam (85% venue) |
| Kelas aset | tokenized equity (harga basi) | kripto murni, 24/7 |
| Bukti | 350 window SoDEX | **2,8 tahun Binance (24.276 bar)** — korelasi 0,999 vs SoDEX (terverifikasi) |
| Leverage aman | L≈7× → jarak 12,7% < ekor p5 → **mati** | L 1,5× → jarak 65% → **hidup** |
| Bar | S_ann≥5,78 (butuh 42 hari mustahil) | **α ≥ 32 bps/48j** |

## 2. Bar sukses (dibekukan)

| Metrik | Ambang |
|--------|--------|
| **α** (return ekses vs drift pasar, 48 jam) | **≥ 32 bps** |
| t-statistik α | **≥ 1,96**, BH-FDR q=0,10 atas seluruh sel |
| **t_ctrl** (regresi return terhadap return pasar) | **\|t\| < 2** — WAJIB, karena tahun sampel turun (−15…−28 bps) membuat short-bias terlihat bagus tanpa alpha |
| Biaya | net > 0 setelah **taker 2,80 bps/leg** (konservatif; maker 1,14) |
| Turnover | to ≤ 1,5 |
| Baterai stabilitas | 4 saringan lulus (potongan sampel; 5 window terbaik <35%; likuiditas; \|t\|≥2) |
| OOS | holdout **1-Agu-2026 → 9-Okt-2026** (tidak disentuh sampai gerbang lulus) |
| Setelah half-Kelly | ≥ **48 bps/48 jam** per instrumen (target 0,8% dicapai oleh ≥3 majors, §5 Amandemen-3) |

## 3. Keluarga sinyal (DIBEKUKAN — 4 mekanisme × 2 arah × 3 aset = 24 sel)

| # | Mekanisme | Definisi tepat | Data |
|---|-----------|----------------|------|
| M1 | `BRK_DONCHIAN` | long bila close > max(high, 24 bar) sebelumnya; short bila close < min(low, 24 bar); hold 48 jam | klines 1h |
| M2 | `MA_SLOPE` | tanda slope EMA21 dan EMA63 searah → posisi searah; hold 48 jam | klines 1h |
| M3 | `FADE_Z48` | z = (close − MA48)/σ48; fade bila \|z\| ≥ 1,5; hold 48 jam | klines 1h |
| M4 | `VOL_GATE_BRK` | M1 hanya bila ATR% 24 jam berada di **kuartil bawah** distribusi 90 hari | klines 1h |

Setiap mekanisme diuji **long dan short** (2 arah) pada BTC, ETH, SOL → 24 sel. **Tidak ada sel tambahan** yang boleh ditambahkan setelah melihat hasil (kalau perlu, buka PRAREG baru).

**Bukan sinyal mandiri** (dan karena itu TIDAK dihitung sebagai sel, hanya sebagai kondisi): jam UTC, hari, funding prediktif (data funding 5 jam ke depan belum tersedia andal di SoDEX → **dikeluarkan dari keluarga ini**, jangan dipaksakan).

## 4. Metode

1. **Data:** `data/binance_klines/1h/{BTC,ETH,SOL}USDT.json` (24.276 bar, 2024-01-01 →), dibekukan dengan sidik-jari (`klines_snapshot.py --freeze`).
2. **Return ekses:** return strategi − (β × return pasar aset itu), β dari regresi OLS sepanjang periode. **Kontrol drift wajib** — tanpa ini, short di tahun turun akan lolos gerbang sebagai artefak.
3. **Sertifikasi:** t pada α; n=1.020 window → t = √1020 × (α/σ). Pada α=32 bps & σ=3,26%, t = **3,15** → **bukti cukup pada 2,8 tahun** (bandingkan: hanya 350 window di SoDEX → t=1,96, di batas).
4. **Baterai stabilitas 4 saringan** dijalankan pada setiap sel yang lolos gerbang (post-hoc hanya untuk MEMBUNUH).
5. **Biaya 2,80 bps/leg** (taker), turnover dihitung dari pembalikan posisi.
6. Forward: setelah lolos, masuk harness forward 42 hari (mode D) — **tanpa order nyata**.

## 5. Yang TIDAK dilakukan pada tahap ini

- Tidak ada leverage dalam pengukuran (leverage hanya di lapisan alokasi, diatur `lev_discipline.py`).
- Tidak ada order/posisi nyata. Semua read-only.
- Tidak ada penyetelan ambang setelah melihat hasil (goalpost-moving = pembatalan otomatis).

## 6. Aturan interpretasi

- Hasil historis = **DESKRIPTIF**. Verdict = **forward**.
- Sel yang lulus gerbang tetapi gagal baterai → **MATI** (pelajaran dari `-MOM_L21`).
- Jika **0 sel** yang lolos: itu hasil yang sah dan berharga — dicatat, lanjut ke keluarga berikutnya dengan PRAREG baru.
- Jika α terukur **≤20 bps**: itu memicu §5 Amandemen-3 (target turun otomatis ke ~0,4%), **bukan** penambahan leverage untuk mengejar 0,8%.
