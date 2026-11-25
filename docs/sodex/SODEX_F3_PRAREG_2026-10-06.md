# SODEX F3 — Pra-Registrasi Funding-Squeeze + OBI Nyata (Evaluasi #44)

**Tanggal beku:** 06-Okt-2026 · **Status:** BEKU setelah commit — kriteria tidak boleh diubah setelah hasil keluar.
**Evaluator:** `scripts/sodex_prereg_f3.py` (READ-ONLY, tanpa jalur order/sign).

## 0. Kenapa ini, bukan dibangun dari nol

`anantara/sodex_twin_engine.py::generate_directional_signal` (baris 3355-3435) sudah mengimplementasikan sinyal funding+OBI (disebut **E2Dir**). Riset asli (`docs/SODEX_E2_RESEARCH_2026-06-20.md`, 20-21 Jun 2026) menguji **5 hipotesis sekaligus** (momentum kontinuasi, momentum reversi, OFI kontinuasi, OFI reversi, funding E2Dir) dan memilih funding sebagai "menang" karena WR tertinggi (63,3%, n=30, p=0,072 **binomial satu-sisi, TANPA koreksi BH-FDR untuk 5 uji sekaligus**). Dengan koreksi Holm/BH untuk m=5 pada α=0,05, p=0,072 **tidak lolos** ambang mana pun. Ini klasik "pilih yang terbaik dari banyak uji" — bukan edge terbukti, kandidat yang pantas diuji ulang dengan protokol ketat. F3 = uji ulang SATU hipotesis itu saja, pra-registrasi penuh, data forward segar, n lebih besar.

## 1. Hipotesis H3 (satu-satunya, dibekukan)

> Funding rate |fr| ≥ ambang produksi, dikonfirmasi arah oleh **OBI20 nyata** (dari depth order book asli, bukan proksi spread kasar di kode E2Dir lama) pada ambang produksi, memprediksi pergerakan harga 30 menit (hold E2Dir) yang profitable net setelah biaya taker 2×4bp.

## 2. Parameter — SEMUA konstanta produksi, VERBATIM, tidak direkalibrasi

| Param | Nilai | Sumber |
|---|---|---|
| `FUNDING_THR` | 0,00003 (0,003%) | `TE_E2_DIR_FUNDING_THR` default kode L417 |
| `OBI_THR` | 0,15 | `TE_E2_DIR_OBI_THR` default kode L418 |
| `HOLD_S` | 1800 (30 menit) | `TE_E2_DIR_HOLD_S` default kode L411 |
| `TAKER_FEE` | 0,04% × 2 leg | whitepaper SoDEX (dikonfirmasi 2 sumber, 06-Okt) |
| `FUNDING_SOURCE` | `data/sodex_funding/funding_rates_history.jsonl` (mark/predicted, per simbol, dikumpul `sodex_funding_rate_collector.py`, mulai 2026-10-02) | collector aktif |
| `OBI_SOURCE` | `freqtrade_user_data/data/sodex/obi/obi_*.jsonl`, field `obi20` (depth 20 level nyata) | collector aktif, BUKAN proksi spread-kasar di kode lama |

**Deviasi dicatat (bukan silent):** `generate_directional_signal` versi produksi menghitung OBI dari jarak spread ke mid (proksi kasar, L3392-3404: *"book() hanya ada bid/ask price, bukan depth"*), karena API live tidak expose depth. F3 memakai **OBI20 nyata** dari collector (data riset, bukan dari API live) — ini perbaikan metodologis, bukan kecurangan, tapi berarti F3 mengukur batas ATAS kemungkinan (upper bound) dibanding apa yang benar-benar dilihat engine live saat ini.

## 3. Mekanika operasional (beku)

- **Onset:** menit mana pun funding snapshot terbaru |fr| ≥ FUNDING_THR untuk simbol S, DAN OBI20 pada menit yang sama konfirmasi arah (sell butuh obi20 < −OBI_THR; buy butuh obi20 > +OBI_THR).
- **Arah:** fr>0 (long membayar) → SHORT; fr<0 → LONG. (Sama persis kode E2Dir.)
- **Independensi:** gap ≥1 jam antar-onset per simbol (funding settle per jam di SoDEX — lihat `sodex_funding_rate_collector.py` komentar).
- **Entry/Exit:** TAKER kedua sisi (sama seperti produksi — E2Dir memang taker, bukan maker: riset Juni membuktikan maker gagal total di SoDEX). Entry mid saat onset; exit mid 30 menit kemudian.
- **Net:** (mid_exit/mid_entry − 1) × arah − 2×0,04% − funding yang dibayar/diterima selama hold (dari rate aktual, bukan diabaikan).

## 4. Gerbang & kriteria (beku)

- **Gerbang:** ≥**100** episode (lebih besar dari n=30 asli — tujuan eksplisit memperbaiki kelemahan sampel kecil), ≥10 hari, ≥5 simbol; atau **HARD_STOP 2026-11-07** (sejajar F1/F2).
- **C1** WR > 50% (one-sided binomial p<0,05 TANPA koreksi, prasyarat minimum) · **C2** p **setelah koreksi Bonferroni m=1** (ini satu-satunya hipotesis dalam F3, jadi m=1 — BEDA dari kesalahan riset Juni yang menguji 5 tanpa koreksi) <0,05 · **C3** mean net >0 setelah fee+funding · **C4** buang 3 episode terbaik masih WR>50% · **C5** segmen waktu (2 pertiga) konsisten arah · **C8** jendela 48 jam: mean ≥0,8% dan CI95 bawah >0 (kriteria resmi, sama F1/F2).

## 5. Batas kejujuran

- Threshold funding produksi (0,003%) mungkin **terlalu tinggi** vs magnitudo nyata SoDEX (komentar kode: "max funding ~0,008%/8h, 10× lebih kecil dari Binance") → count-only awal akan mengonfirmasi/membantah ini secara empiris SEBELUM menuduh threshold salah.
- OBI20 nyata ≠ OBI proksi yang dipakai engine live → PASS F3 TIDAK otomatis berarti E2Dir live akan profit; butuh langkah lanjutan (beri engine akses depth nyata) sebelum promosi.
- n=100 masih kecil untuk klaim definitif; ini perbaikan dari n=30, bukan solusi penuh.

## 6. Perintah

```
.venv-research/bin/python3 scripts/sodex_prereg_f3.py --count-only   # kapan saja
.venv-research/bin/python3 scripts/sodex_prereg_f3.py --final        # setelah gerbang terbuka
```

## 7. AMENDEMEN 07-Okt-2026 (sebelum PnL apa pun dihitung)

Dasar: audit read-only evaluator (2 subagen, `deleg_9a86e82e`). Amendemen saat F3 baru punya
1/100 episode siap — **bukan p-hacking**.

1. **C2 diganti: "Bonferroni m=1" → uji sign-flip level HARI (`day_signflip_p`).**
   `Bonferroni m=1` = identitas (p×1) → **nol perlindungan** terhadap klasterisasi harian;
   laju false-pass terukur **20–38%** pada data nol terklaster (nominal 5%). Fungsi
   `day_signflip_p` sudah ada di skrip tetapi **tak pernah dipanggil** (kode mati) — kini
   dipakai; ini mengembalikan F3 ke standar F1. C1 tetap binomial episode (prasyarat minimum).
   Ambang tetap **p < 0,05**.
2. **Biaya funding diperbaiki (kode vs spec):** spec C3 minta "funding dari rate aktual selama
   hold", tetapi kode lama memakai **baris berikutnya × 0,5** → **KREDIT tak layak pada ~94%
   onset**. Kini hanya settlement yang **benar-benar terlewati** dalam (t0, t0+HOLD_S], pakai
   rate settlement itu, dedup per `funding_time`.
3. **C5 diperbaiki (kode vs spec):** spec minta "segmen **waktu**", kode lama urutan
   symbol-major. Kini episode diurutkan `t_in` sebelum dibagi tiga.
4. **Gerbang diperbaiki:** dulu `n_onsets`; kini `n_ready` (episode yang keluar-nya sudah
   teramati, tanpa membaca harga) → gerbang tidak terbuka lebih awal dari yang bisa disimulasikan.
5. **Anti-optional-stopping:** hasil `--final` → nama ber-timestamp + `SODEX_F3_LOOKS.jsonl` +
   kunci `SODEX_F3_FIRSTLOOK.json`. Keputusan pra-reg = look PERTAMA.

Ambang (C0–C8, θ funding, HOLD_S, N_EP_MIN, HARD_STOP) **TIDAK diubah**.
Tes regresi: `tests/test_sodex_prereg_f3.py`.

## 8. PERPANJANGAN HARD_STOP 07-Okt-2026 (approval user, opsi A)

- `HARD_STOP`: **2026-11-07 → 2026-11-20 (+13 hari, MAKSIMAL)**.
- Alasan: laju episode nyata lebih lambat dari asumsi awal. Perpanjangan ini **tidak
  mengubah ambang apa pun** (N_EP_MIN=100, DAYS_MIN=10, SYMS_MIN=5, θ funding/OBI, C0–C8 tetap).
- **Sekali saja.** Tidak ada perpanjangan lagi setelah 20-Nov-2026; sesudahnya wajib full
  live real trading.
- Riset laju & proyeksi: `docs/sodex/SODEX_LAJU_EPISODE_RISET_2026-10-07.md`.

## 9. PERLUASAN SEMESTA OBI 07-Okt-2026 (approval user: "GO 20 → 92")

- Semesta OBI: **20 → 92 simbol** (= semua pasar SoDEX ber-funding).
- Alasan: penyumbat F3 terukur = **CAKUPAN, bukan ambang**. Laju onset nyata dgn 20 simbol
  penuh hanya 0,69/hari → proyeksi 44 hari ≈ 30 episode (butuh 100).
- **Ambang TIDAK diubah** (θ funding/OBI, C0–C8, N_EP_MIN=100, DAYS_MIN=10, SYMS_MIN=5).
- **Catatan likuiditas (jujur):** ~34–45 dari 92 pasar punya volume 24 jam < 10.000 USD
  (snapshot 07-Okt: 34; angka bergerak mengikuti volume bergulir). Episode dari pasar tipis
  **tidak boleh** dianggap tradeable; bila PASS bergantung pada pasar tipis, verdict harus
  ditolak. Verdict wajib dibaca dgn konteks likuiditas.
- **Implementasi konteks likuiditas (NON-GATING):**
  - `scripts/sodex_tickers_snapshot.py` → snapshot `data/sodex_market_tickers.json`
    (GET publik `markets/tickers`; fail-closed: gagal → snapshot TIDAK ditulis).
  - `scripts/sodex_prereg_f3.py`: `liquidity_view()` menambahkan kunci `liquidity` pada hasil
    (`by_bucket`, `thin_share`, `tradable_only_secondary`). **Sengaja TIDAK menyentuh
    `criteria`** → verdict C0–C8 tetap dapat direproduksi tanpa data likuiditas
    (dijaga tes `tests/test_sodex_f3_liquidity.py`).
  - Snapshot diambil pada **waktu evaluasi** → proksi likuiditas kontemporer, bukan saat onset.
    Memadai untuk menggugurkan PASS yang bergantung pasar tipis (pasar tipis cenderung tetap
    tipis), tetapi **bukan** pengukuran likuiditas per-episode.
- Konfigurasi: `~/.config/systemd/user/anantara-obi.service.d/10-symbols.conf`
  (backup `10-symbols.conf.bak-20261007`). Terverifikasi 92 simbol aktif.
- Riset: `docs/sodex/SODEX_LAJU_EPISODE_RISET_2026-10-07.md` §6.
