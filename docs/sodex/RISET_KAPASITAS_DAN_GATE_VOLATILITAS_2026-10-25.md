# RISET KAPASITAS GROSS & GATE VOLATILITAS — JALAN MENUJU 0,8%/WINDOW SoDEX

**Tanggal:** 2026-10-25 · **Venue:** SoDEX perps · **Mode:** penelitian, READ-ONLY (tanpa order)
**Target yang diuji:** ≥ **0,8% dari TOTAL modal wallet per window 30 jam**, akumulasi, harga mati
**Wallet acuan:** $243,02 → target = **$1,94/window**
**Sifat dokumen:** DESKRIPTIF + desain uji forward. **Tidak ada klaim bahwa target sudah tercapai.**

---

## 0. Ringkasan eksekutif (angka dulu)

1. **Biaya riil rata-rata buku = 11,39 bps/trade**, bukan 6,5 bps. Gross buku penuh hanya **+3,43 bps** → net **−7,96 bps/trade**. Secara struktural buku ini rugi sebelum memilih sinyal.
2. **Hanya 3 dari 10 mesin** yang gross-nya pernah konsisten di atas biaya: **twoway (+20,18), realwide (+15,59), donchian (+14,98)** bps.
3. **Edge ketiganya berbalik tanda sekitar 2026-09-25.** 30 hari terakhir: twoway −$181,83 (gross −33,5 bps), realwide −$127,60 (−41,1), donchian −$88,63 (−39,6). Kombinasi ketiganya: **−8,19%/window**, hit 35%.
4. **Padahal pada rezim sebelumnya ketiganya melewati target:** kombinasi 3 mesin, 59 window, **mean +1,404%/window** (median −0,30%, hit 49,2%) — artinya target 0,8% *pernah* terlampaui rata-rata, tetapi tidak stabil (median negatif).
5. **Kandidat penjelas yang bisa diukur ex-ante:** gross mingguan naik seiring **volatilitas BTC 7 hari sebelumnya** (r = 0,55–0,59; median gross per kuartil vol: **−50,5 → +6,0 → +16,4 → +30,1 bps**).
6. **Gate parameter-free** (`vol7 ≥ median 12 window terakhir`) in-sample: **mean 3,563%/window, median +1,851%, hit 54,8%** (31 window ON dari 59) vs tanpa gate 1,404% / −0,296% / 49,2%. **CI95 blok mingguan [−6,94; +11,70] memuat nol** → belum bukti.
7. **Karena itu seluruh klaim di atas ditutup dengan uji forward beku: PRAREG-31**, hash `525227e7…`, forward 26-Okt→25-Nov, 12 window minimum, kriteria A–E, kontrol gate acak ber-duty sama.
8. **PRAREG-26 (14d net>0) diukur ulang:** aturan itu menghasilkan **hit 32,2%** dan buku praktis kosong — ia memilih mesin *setelah* edge berbalik. Ini alasan mekanis kenapa verdict 25-Nov kemungkinan besar **TIDAK LOLOS**, bukan karena aturannya "salah tulis".

**Kesimpulan satu baris:** target 0,8%/window tidak dicapai oleh pemilihan sinyal; yang tersisa dan bisa diuji adalah **kapan mesin di-deploy** — dan itu sekarang diuji forward, bukan diklaim.

---

## 1. Pertanyaan penelitian

Target 0,8% per window 30 jam pada wallet $243,02 berarti **$1,94 net per 30 jam**, akumulasi, tanpa kompromi harga. Pertanyaannya bukan "sinyal apa yang bagus" tetapi tiga pertanyaan yang lebih tajam:

- **Q1 (kapasitas):** berapa bps gross yang benar-benar ditangkap mesin, dan berapa yang dimakan biaya?
- **Q2 (struktur):** apakah buku rugi karena **alpha-nya hilang** atau karena **biayanya terlalu besar**? Dua dunia ini punya obat yang berbeda.
- **Q3 (waktu):** kalau alpha ada tapi tidak stabil, apakah ada variabel **ex-ante** yang memisahkan periode hidup dan mati?

---

## 2. Metode

| Aspek | Keputusan | Alasan |
|---|---|---|
| Sumber trade | `data/paper_test_*_state.json`, 10 mesin universe beku | Data uang-paper, bukan uang nyata; tidak ada look-ahead |
| Gross | `sign(direction) × (exit/entry − 1) × 1e4`; pakai `gross_pct` bila tersedia | Memisahkan pergerakan harga dari biaya |
| Net | `net_pct`/`pnl_pct` dari state (model biaya paper masing-masing mesin) | Net adalah yang dibayar wallet |
| Biaya | `gross − net` per trade | Mengukur biaya *riil* per mesin, bukan asumsi 6,5 bps |
| Kontrol | trade berlabel `RANDOM` (track/arm/regime) dikecualikan | Kontrol negatif tidak boleh masuk buku |
| Dedupe | `(engine, pair, entry_ts, exit_ts)` unik | Rule 12: dedup sebelum menghitung |
| Window | grid 30 jam, jangkar 2026-08-03Z, bucket `exit_ts`, window kosong = 0,0% | Definisi resmi `AMANDEMEN_TARGET_AB` |
| CI | **block bootstrap per minggu** (bukan per trade) | Trade dalam seminggu tidak independen |
| Harness | v2 (`safe_lag`, `t_lag`, `segments_untested`) | Patch 25-Okt: NW lag=hold menginflasi t |

**Periode:** seluruh histori paper (Agu–Okt 2026). Forward PRAREG-31 mulai 2026-10-26.

---

## 3. Temuan 1 — Biaya riil 11,39 bps/trade; hanya 3 mesin yang gross > biaya

`scripts/research/gross_capacity_audit.py` → 1.959 trade bersih (RANDOM dikecualikan):

| Mesin | n | gross bps | net bps | biaya bps | hold (jam) | Diagnosis |
|---|---:|---:|---:|---:|---:|---|
| twoway | 436 | **+20,18** | +12,59 | 7,59 | 13 | alpha > biaya |
| realwide | 268 | **+15,59** | +8,78 | 6,80 | 7 | alpha > biaya |
| donchian | 206 | **+14,98** | +7,82 | 7,16 | 5 | alpha > biaya |
| shortbear | 41 | +39,98 | −48,41 | **88,40** | 5 | biaya model ekstrem (funding?) — tidak tradeable |
| swing | 419 | +6,48 | +1,24 | 5,24 | 3 | tipis, di bawah ambang |
| aster | 243 | −8,26 | −27,03 | 18,77 | 10 | alpha negatif |
| hyperliquid | 214 | −17,54 | −37,76 | 20,22 | 10 | alpha negatif |
| portfolio | 86 | −40,51 | −49,28 | 8,77 | 7 | alpha negatif |
| pasar_anantara_trade | 46 | −96,98 | −102,06 | 5,08 | 9 | alpha sangat negatif |
| spot_swing_v2 | — | *tidak terukur* | — | — | — | state tidak menyimpan pnl_pct (celah data) |
| **Buku penuh** | **1.959** | **+3,43** | **−7,96** | **11,39** | 7 | **rugi struktural** |

**Bacaan:** biaya bukan angka kecil yang bisa diabaikan — ia **3,3× gross buku penuh**. Setiap diskusi "sinyal" yang tidak menyebut 11,4 bps ini adalah diskusi yang belum lengkap.

---

## 4. Temuan 2 — Edge 3 mesin berbalik tanda ~25-Sep-2026

`scripts/research/engine_trend_window.py`, gross bps per minggu:

| Minggu | twoway | realwide | donchian | swing |
|---|---:|---:|---:|---:|
| 08-29→09-05 | +21,6 | −22,8 | +20,3 | −52,2 |
| 09-05→09-12 | +17,0 | +9,7 | +2,3 | −3,5 |
| 09-12→09-19 | **+119,5** | +44,9 | +28,4 | +12,5 |
| 09-19→09-26 | **+24,9** | **+40,3** | **+88,1** | **+35,3** |
| 09-26→10-03 | −39,1 | −50,7 | −42,3 | −40,4 |
| 10-03→10-10 | −73,1 | −77,3 | −37,1 | −50,4 |
| 10-17→10-24 | −70,9 | −42,9 | −110,7 | −15,3 |

**30 hari terakhir (net):** twoway −45,57 bps (n=133), realwide −50,64 (n=84), donchian −48,96 (n=60).

**Agregasi window 30 jam (seluruh histori):**

| Buku | window | mean % | median % | hit % | total $ |
|---|---:|---:|---:|---:|---:|
| twoway | 58 | +1,168 | −1,34 | 48,3 | +164,66 |
| realwide | 48 | +0,586 | −0,41 | 47,9 | +68,36 |
| swing | 52 | +0,206 | −5,66 | 38,5 | +25,97 |
| **KOMBINASI 3** | **59** | **+1,404** | **−0,72** | **49,2** | **+201,29** |
| Kombinasi 3, **30 hari terakhir** | 20 | **−8,19** | −3,46 | 35,0 | −398,06 |

**Poin penting:** target 0,8% **pernah** terlampaui rata-rata (+1,404%), tetapi **median negatif** → buku ini adalah "beberapa minggu besar + banyak minggu kecil rugi". Itu profil yang tidak boleh di-sizing besar dan tidak boleh diklaim stabil.

---

## 5. Temuan 3 — Matematika target: 8,9–16 bps net per trade

`scripts/research/vol_gate_simulation.py`:

| Trade/window | Ukuran posisi | Net bps/trade yang dibutuhkan |
|---:|---:|---:|
| 5 | 25% wallet | 64,0 |
| 5 | 50% wallet | 32,0 |
| 5 | 100% wallet | 16,0 |
| 9 | 50% wallet | 17,8 |
| 9 | 100% wallet | 8,9 |
| 15 | 50% wallet | 10,7 |
| 25 | 50% wallet | 6,4 |

**Implikasi:** pada 9 trade/window dengan ukuran penuh, dibutuhkan **8,9 bps net/trade**. twoway pada minggu baik memberi ~15 bps net — cukup. Pada minggu buruk memberi −45 bps — tidak cukup, dan itulah yang terjadi sekarang. **Target bukan mustahil secara matematis; yang tidak ada adalah stabilitas.**

---

## 6. Temuan 4 — Volatilitas 7 hari sebelumnya adalah kandidat pemisah (n minggu kecil!)

`scripts/research/regime_conditioning.py` — fitur dihitung dari 7 hari **sebelum** minggu berjalan (tanpa look-ahead), 30 titik (4 mesin × ~8 minggu):

| Uji | Nilai |
|---|---|
| korelasi gross vs vol7 SoDEX | **r = 0,553** |
| korelasi gross vs vol7 Binance | **r = 0,593** |
| korelasi gross vs ret7 BTC | r = 0,512 |
| median gross, kuartil vol 26–30% | **−50,5 bps** |
| kuartil 30–32% | +6,0 bps |
| kuartil 32–35% | +16,4 bps |
| kuartil 35–42% | **+30,1 bps** |

**Simulasi gate (59 window 30 jam, in-sample):**

| Varian | window ON | mean % | median % | hit % | CI95 blok mingguan |
|---|---:|---:|---:|---:|---|
| tanpa gate | 59 | 1,404 | −0,296 | 49,2 | [−5,75; +8,99] |
| vol ≥ 30% | 44 | 2,468 | +0,057 | 50,0 | [−6,03; +10,62] |
| vol ≥ 33% | 29 | 2,526 | +1,124 | 51,7 | [−7,43; +11,92] |
| vol ≥ 35% | 18 | 8,796 | +4,061 | 66,7 | [−0,64; +19,74] |
| **vol ≥ median 90d (parameter-free)** | **31** | **3,563** | **+1,851** | **54,8** | **[−6,94; +11,70]** |
| PRAREG-26 (14d net>0) | 59 | 1,411 | 0,000 | **32,2** | — |

**Yang boleh dan tidak boleh disimpulkan:**

- **Boleh:** ada gradien yang konsisten antara vol pra-minggu dan gross mesin; gradien itu **cukup besar untuk layak diuji forward**.
- **Tidak boleh:** "gate ini menghasilkan 3,56%/window". CI95 memuat nol; ambang 30/33/35 dipilih setelah melihat data; n efektif hanya ~9 minggu (4 mesin dalam minggu yang sama tidak independen).

---

## 7. Temuan 5 — Kenapa PRAREG-26 hampir pasti gagal (mekanisme, bukan nasib)

Aturan PRAREG-26: mesin lolos bila **14 hari terakhir net > 0**. Diukur pada grid 30 jam: **hit 32,2%**, mean 1,411%, median 0,000 (buku flat di mayoritas window karena tidak ada mesin lolos).

Mekanismenya:

1. Edge berbalik ~25-Sep. Aturan 14-hari butuh ~14 hari untuk "melihat" pembalikan; selama itu ia masih memilih mesin yang baru saja mati.
2. Setelah 9-Okt, semua mesin negatif → subset kosong → buku FLAT → 0% (bukan rugi, tapi juga tidak bisa mencapai 0,8%).
3. Saat edge kembali hidup, aturan yang sama butuh 14 hari lagi untuk mengizinkan mesin masuk — terlambat.

**Jadi PRAREG-26 bukan "salah tulis"; ia adalah filter anti-momentum pada kualitas edge.** Hasilnya: buku kosong 14/14 titik keputusan dan M3/M4 tidak akan terpenuhi. Ini konsisten dengan audit denominator 25-Okt (9/9 mesin 14d negatif, −$345,10 pada snapshot 00:00Z; −$548,29 pada snapshot 08:00Z).

---

## 8. Keputusan: PRAREG-31 (beku, forward)

Karena gate adalah **satu-satunya kandidat yang melewati matematika target tanpa mengubah sinyal**, ia didaftarkan sebagai uji forward, bukan di-deploy:

| Item | Nilai |
|---|---|
| Dokumen beku | `docs/sodex/PRAREG31_GATE_VOLATILITAS.md` |
| SHA-256 | `525227e733d63b9faeefb85f96c0d46c312b092dd59f94379c1459f74c20eb86` |
| Aturan gate | `vol7(t) ≥ median(vol7 12 window sebelumnya)`, vol7 = pstdev(log ret 1h BTC SoDEX, 168 jam) × √8760 × 100, bar close ≤ t |
| Buku | twoway + realwide + donchian (universe beku) |
| Forward | window start ≥ 2026-10-26T00:00Z, end ≤ 2026-11-25T00:00Z |
| Minimum data | 12 window usable; < 12 → **DATA KURANG** |
| Kriteria lolos | A: M1 ≥ 0,8% · B: median > 0 & hit ≥ 50% · C: t paired ≥ 2,0 · D: p permutasi < 0,05 (kontrol gate acak duty sama) · E: tidak ada pelanggaran aturan |
| Evaluator | `scripts/research/prereg31_gate_eval.py` → `reports/sodex/PRAREG31_STATUS.json` |
| Status hari ini | **DATA KURANG** (23 window forward terdaftar, 0 usable — forward belum mulai) |
| Registri | `reports/sodex/PRAREG31_REGISTRY.jsonl` |
| Pengawal harian | cron 07:00 WIB: snapshot mesin + audit PRAREG-26 + evaluator PRAREG-31 |

**Kontrol negatif wajib:** gate acak dengan jumlah window ON sama (10.000 permutasi). Kalau gate acak sama baiknya, yang bekerja bukan volatilitas — hanya "tidak selalu di pasar".

---

## 9. Limitasi (jujur, ini yang bisa membatalkan kesimpulan)

1. **n efektif ~9 minggu**, bukan 59 window: window dalam minggu yang sama berkorelasi. Block bootstrap dipakai justru karena itu, dan hasilnya CI lebar.
2. **Ambang absolut (30/33/35) dipilih setelah melihat data** — hanya deskriptif; yang diuji forward adalah aturan median (parameter-free).
3. **Zona abu-abu 27–33%:** gate ON di 22-Okt (vol 33,3 > median 32,3) padahal mesin sedang rugi. Gate tidak sempurna; forward test akan mengukur seberapa tidak sempurna.
4. **Biaya model berbeda antar mesin** (aster 18,8 bps; shortbear 88,4 bps) — angka biaya bukan satu angka universal; angka 11,39 adalah rata-rata tertimbang n.
5. **spot_swing_v2 tidak terukur** (state tidak menyimpan pnl_pct) — satu mesin hilang dari audit; tidak mengubah kesimpulan karena gross-nya historis tipis.
6. **Klines BTC SoDEX stale ~5 jam** saat analisis (bar terakhir 03:00Z). Untuk forward, evaluator menandai window FLAT bila stale > 6 jam — dan itu berarti **kolektor klines harus hidup**, kalau tidak PRAREG-31 akan berakhir DATA KURANG.
7. **Semua ini paper trading** dengan model fill `poll`; biaya nyata bisa lebih tinggi (slippage, spread SoDEX tipis).

---

## 10. Rekomendasi (falsifiable)

| # | Aksi | Kriteria berhasil | Biaya |
|---|---|---|---|
| R1 | Jalankan PRAREG-31 sampai 25-Nov (pengawal harian sudah aktif) | 12 window usable; verdict A–E dihitung otomatis | 0 (read-only) |
| R2 | Perbaiki celah data `spot_swing_v2` (simpan `pnl_pct`) agar audit berikutnya 10/10 mesin | audit gross 10/10 lengkap | ~1 jam |
| R3 | Kalau PRAREG-31 gagal pada C/D (gate tidak mengalahkan acak): hentikan jalur gate, jangan tambah ambang baru | keputusan berhenti tercatat | 0 |
| R4 | Kalau PRAREG-31 lolos A–D: baru boleh dibahas deployment (flag on/off mesin), dengan sizing ≤ 50% wallet dan kill-switch | pembahasan deployment, bukan eksekusi otomatis | 1 hari |
| R5 | Jangan mengubah PRAREG-26 (tetap verdict 25-Nov) — mengubahnya sekarang = data snooping | hash tetap `OK` | 0 |

---

## 11. Berkas & reproduksibilitas

```
scripts/research/gross_capacity_audit.py        audit kapasitas gross (1.959 trade)
scripts/research/engine_trend_window.py         tren mingguan + agregasi window 30 jam
scripts/research/regime_conditioning.py         fitur vol/ret ex-ante vs gross
scripts/research/vol_gate_simulation.py         simulasi gate + matematika target
scripts/research/prereg31_gate_eval.py          evaluator aturan beku PRAREG-31
scripts/research/prereg26_engine_snapshot.py    snapshot 14-hari per mesin (pengawal harian)
tests/test_prereg31_gate.py                     6 test: no-look-ahead, fail-closed, stale→FLAT
reports/sodex/GROSS_CAPACITY_AUDIT.json
reports/sodex/ENGINE_TREND_WINDOW.json
reports/sodex/REGIME_CONDITIONING.json
reports/sodex/VOL_GATE_SIMULATION.json
reports/sodex/PRAREG31_STATUS.json
reports/sodex/PRAREG31_REGISTRY.jsonl
reports/sodex/PRAREG26_ENGINE_SNAPSHOT.json
docs/sodex/PRAREG31_GATE_VOLATILITAS.md (+ .sha256)
```

**Reproduksi:**
```bash
cd ~/anantara-sakti
/usr/bin/python3 scripts/research/gross_capacity_audit.py
/usr/bin/python3 scripts/research/engine_trend_window.py
/usr/bin/python3 scripts/research/regime_conditioning.py
/usr/bin/python3 scripts/research/vol_gate_simulation.py
/usr/bin/python3 scripts/research/prereg31_gate_eval.py
/usr/bin/python3 -m pytest tests/test_prereg31_gate.py -q
sha256sum -c docs/sodex/PRAREG31_GATE_VOLATILITAS.md.sha256
```

---
*Laporan riset 2026-10-25 — angka dapat berubah setiap hari; verdict hanya boleh diambil dari window forward PRAREG-31, bukan dari dokumen ini.*
