# Eksekusi Rekomendasi — SoDEX + CEX-Binance

**Waktu eksekusi:** 2026-11-12 21:40 → 22:25 UTC (2026-11-13 04:40 → 05:25 WIB)
**Otorisasi:** Owner — "Approve semua rekomendasi super terbaik… untuk sodex semua paper test dan experimental super wajib harus tetap berjalan sempurna luar biasa"
**Prinsip yang dipakai:** tidak ada unit paper test yang dihentikan; semua perubahan bersifat opt-in (default = perilaku lama).

---

## 1. Status akhir (terverifikasi, bukan klaim)

| Pemeriksaan | Hasil |
|---|---|
| Health-check 22 lane paper (SoDEX + CEX) | **FAIL=0 WARN=0 PASS=22** |
| Unit paper test aktif | 22/22 `active` |
| State korup / 0-byte / basi | 0 |
| `SAFETY_HALT` | tidak aktif |
| Gate produksi CEX | tetap `kill TRIGGERED` (tidak disentuh) |
| `dry_run` CEX | tetap `true` |
| Test suite terdampak | 481 passed (twoway/cex/lane) + 26 (spot) + 20 (gate) + 6 (kuota) |

---

## 2. Yang diperbaiki (dengan bukti)

### 2.1 Lane CEX spot mati senyap 6 hari — SELESAI
- **Gejala:** `data/paper_test_spot_swing_cex_spot.json` = 105.559 byte NUL sejak 2026-11-07T16:24Z; 1.401 baris `spot paper state unreadable`; 0 entry 6 hari.
- **Akar masalah:** `_save_state` memakai `tmp.write_text(...)` tanpa `flush`/`fsync` sebelum `replace` → file bisa ter-rename dalam keadaan kosong/NUL.
- **Perbaikan:** `flush` + `fchmod 0600` + `fsync(file)` + `replace` + `fsync(direktori)` (`scripts/paper_test_spot_swing_cex_spot.py`).
- **Pemulihan data:** `scripts/repair_spot_paper_state.py` merekonstruksi state dari ledger append-only (183 trade); file korup di-rename `*.corrupt-<utc>`, **tidak dihapus**.
- **Verifikasi:** lane aktif, state valid, health-check PASS, 26 test lulus (termasuk 2 test baru: tidak ada byte NUL, `fsync` dipanggil sebelum rename).

### 2.2 Tidak ada lagi kegagalan senyap — SELESAI
- **Baru:** `scripts/paper_lane_health.py` (stdlib, 22 lane terdaftar) → verdict PASS/WARN/FAIL dengan alasan eksplisit: unit mati, state hilang, JSON rusak, byte NUL, state basi > 3× interval, ERROR setelah siklus sukses terakhir.
- **Terpasang di cron:** job health 5-menit dan pulse 30-menit sekarang mencetak `PAPER LANES: FAIL=n WARN=n` dan `❌ PAPER LANE FAIL: <unit> — <alasan>`.
- **Catatan bug alat sendiri:** versi pertama memilih `*_error.log` basi (Agustus) dan melaporkan 75 ERROR palsu → diganti peta log eksplisit + hanya menghitung ERROR setelah siklus sukses terakhir. False positive dihapus.

### 2.3 Arm riset AB9a/9b/9c: 6 hari 0 entry — SELESAI (dugaan awal saya SALAH)
- **Dugaan awal:** gate BTC momentum memblokir semua entry. **Salah.**
- **Bukti funnel:** `reason_no_signal` 20–22 dari 23 pair, `skip_signal_inactive` sama besar.
- **Akar masalah sebenarnya:** (1) kaki LONG menuntut `close > SMA50` → nyaris tak pernah benar di BEAR; (2) kaki SHORT `short_ok = False` hardcoded sejak 2026-09-02. Tidak ada jalur entry tersisa.
- **Perbaikan opt-in:** `TW_SHORT_LEG=1` (default 0) dan `PAPER_BTC_GATE_QUOTA=N` (default 0, kuota per label agar RANDOM tidak menghabiskan jatah SIGNAL).
- **Bukti sesudah (22:26 UTC):**

| Arm | entry_signal | quota_pass_signal | open | SIGNAL open |
|---|---:|---:|---:|---:|
| ab9a | 2 | 2 | 4 | 2 (BTC, ETH) |
| ab9b | 2 | 2 | 4 | 2 (BTC, ETH) |
| ab9c | 0 | 2 | 2 | 0 (`skip_pre24` = filter arm sendiri) |
| ab9d | 0 | — | 3 | 1 (tidak berubah) |

- **Efek samping dicek:** lane produksi `anantara-paper-twoway` tidak punya env riset → perilaku identik.

### 2.4 Deadlock gate CEX — SELESAI tanpa membuka gate produksi
- **Akar masalah:** gate kill TRIGGERED sejak 2026-09-14 memblokir semua entry SIGNAL → sampel tidak bertambah → gate tidak pernah bisa dievaluasi ulang (deadlock).
- **Perbaikan:** instance riset terisolasi (`anantara-paper-cex-signal-research.service` + timer gate 5 menit) dengan state/ledger/gate sendiri.
- **Verifikasi:** gate instance riset `kill=OK`, dan **7 entry baru tercatat** (4 SIGNAL + 3 RANDOM) — entry SIGNAL pertama sejak 60 hari. Gate produksi tetap `TRIGGERED`.

### 2.5 Denominator modal basi — SELESAI
- `.env.swing` `SODEX_TOTAL_WALLET` = **$243,39**, sedangkan venue terverifikasi = **$234,17** (perps $205,77 + spot $28,39). Selisih 3,8% di bawah ambang update 5% → tidak pernah tersinkron.
- Perbaikan: `--min-delta` pada `scripts/sodex_wallet_denominator.py`, lalu `--min-delta 0.001 --apply` (backup `.env.swing.bak-<utc>`).
- Dampak: target 0,8%/window **$1,947 → $1,873**. Target tidak berubah; denominator yang tadinya menggelembungkan target sudah benar.

### 2.6 Dokumen rencana 1 Des: 0,7% → 0,8% — SELESAI
`docs/sodex/SODEX_MENUJU_1DES_2026.md` diselaraskan ke North Star (0,8%), tabel aritmetika dihitung ulang dari denominator $234,17, dan ditambah §7 berisi koreksi akar masalah AB9.

---

## 3. Analisis bukti: `early_loss_cutoff` (TIDAK diubah)

Sumber: Postgres `anantara.trades`, `exit_reason='early_loss_cutoff'`, 60 hari → **n=13**, WR 0%, mean −1,630%, total −4,38 USD.

Analisis path-ordered (klines 1h, SL −4%, ROI bertingkat 12%→1,5%, cap 24 jam):

| Hasil bila cutoff dimatikan | n |
|---|---:|
| ROI tercapai lebih dulu | 4 (mean +2,25%) |
| SL −4% kena lebih dulu | 4 |
| Belum keluar pada 24 jam | 5 |

| Skenario | Total PnL (13 trade) | Per trade |
|---|---|---|
| Aktual (cutoff ON) | −21,19% | −1,630% |
| Counterfactual (cutoff OFF) | −14,73% | −1,133% |
| Selisih | **+6,46 pp** | **+0,50 pp** |

**Uji signifikansi:** 4 vs 4 pada trade decisive → binomial dua sisi **p = 1,000**. Tidak signifikan.
**Keputusan:** cutoff **tidak diubah**. Desain A/B dipra-registrasi di `docs/cex/PRAREG_ELC_AB_2026.md` (target n≥60 readout, n=196 final, power 80%, guard drawdown, kriteria berhenti).
**Alat baru:** `scripts/elc_ab_readout.py` (Welch t, Mann-Whitney, bootstrap CI95) — sudah dieksekusi dengan data sintetis untuk membuktikan alat berjalan; **bukan** hasil nyata.

---

## 4. Blackout feed klines — TERUKUR, TIDAK BERMASALAH SEKARANG

| Log | `feed blackout` WARN | `gagal fetch` |
|---|---:|---:|
| paper_test_twoway.log | 0 | 0 |
| paper_test_realwide.log | 0 | 0 |
| paper_test_swing.log | 0 | 0 |
| paper_test_spot_swing_cex.log | 0 | 0 |

Crash-loop AB9a/b/c (`[FATAL] feed buta 3 siklus entry berturut`) terakhir tercatat 2026-11-12 08:52 lokal; sejak restart 09:27 `NRestarts=0` dan tidak ada FATAL baru → perbaikan anggaran retry (commit `3b9f11b`) efektif.

---

## 5. Masih terbuka (butuh keputusan Owner)

1. **Target 0,8% belum tercapai di lane mana pun.** 22 lane sehat, tetapi tidak ada lane dengan expectancy positif jangka panjang. Kesehatan infrastruktur ≠ edge.
2. **Go-live 1 Des tidak on-track** (0/7 lane memenuhi target; readout flip baru 0/20 per arm saat mulai).
3. **Arm B `early_loss_cutoff` belum diimplementasikan** — menunggu approval karena menyentuh logika exit (parameter fundamental).
4. **Lane CEX produksi masih beku** (kill TRIGGERED). Instance riset mengumpulkan bukti; keputusan membuka gate tetap milik Owner.
5. ~~ab9c masih 0 entry karena `skip_pre24`~~ → **DIPUTUSKAN OWNER 2026-11-13: dipertahankan sebagai pembeda hipotesis.** ab9c = arm "entry hanya saat range 24 jam ≥ 3%". Verifikasi: `skip_pre24=2` per siklus, `quota_pass_signal=2` (lolos gate BTC, diblok filternya sendiri) — bekerja sesuai desain. Dicatat di `docs/sodex/SODEX_MENUJU_1DES_2026.md` §7.1 agar tidak "diperbaiki" di sesi berikutnya.
6. ~~ab9a dan ab9b identik secara fungsional~~ → **DIPUTUSKAN OWNER: opsi 2 — ab9b diberi variabel bebas tunggal.** `TW_TP_PCT` 1,5% → **3,0%** (SL −6%, time-stop 24 jam tetap). R:R 1:4 → 1:2, break-even WR 80,0% → 66,7% (WR terukur 39,2%, n=602 → geometri adalah constraint). Verifikasi dari `/proc/<pid>/environ`: `TW_TP_PCT=0.030`; banner log `TP+3%/SL-6% @3x`. Rincian + kriteria readout: `docs/sodex/SODEX_MENUJU_1DES_2026.md` §7.2.
7. **Celah telemetri ditemukan & diperbaiki:** `funnel_flush` hanya dipanggil di dalam blok entry, jadi saat cap penuh (6 SIGNAL + 2 RANDOM) file funnel berhenti diperbarui — bukti hilang tepat saat arm saturasi. Kini ada cabang `else` → `cycle_caps_full`. Terbukti: ab9a/ab9b menulis `{"cycle_caps_full": 1}` dengan `tp_pct` 0.015 vs 0.030.
8. **ab9a/ab9b sedang SATURASI** (6 SIGNAL + 2 RANDOM = 8 posisi). 0 entry baru sampai posisi tertutup (TP/SL/time-stop 24 jam) — ini wajar, bukan kerusakan.
9. **Lane produksi twoway masih memuat label lama "0.7%"** di proses yang berjalan (kosmetik, hilang saat restart berikutnya; tidak di-restart paksa agar tidak mengganggu).

---

## 6. Perubahan berkas

| Berkas | Jenis |
|---|---|
| `scripts/paper_lane_health.py` | baru — health 22 lane |
| `scripts/repair_spot_paper_state.py` | baru — rebuild state spot dari ledger |
| `scripts/elc_ab_readout.py` | baru — readout A/B cutoff |
| `tests/test_twoway_btc_gate_quota.py` | baru — 6 test kuota + short leg |
| `tests/test_paper_test_spot_swing_cex_spot.py` | + `TestDurableStateWrite` (2 test) |
| `scripts/paper_test_spot_swing_cex_spot.py` | `_save_state` durable |
| `scripts/paper_test_spot_swing_cex.py` | `_r6_paper_path`, `RESEARCH_UNQUARANTINE`, `[IDLE-CAUSE]` |
| `scripts/paper_test_twoway.py` | `TW_SHORT_LEG`, `PAPER_BTC_GATE_QUOTA`, label 0,8% dinamis |
| `scripts/sodex_wallet_denominator.py` | `--min-delta` |
| `docs/sodex/SODEX_MENUJU_1DES_2026.md` | 0,8% + denominator + §7 koreksi |
| `docs/cex/PRAREG_ELC_AB_2026.md` | baru — pra-registrasi A/B |
| `systemd/anantara-paper-cex-signal-research.service` + gate service/timer | baru — instance riset CEX |
| `~/.config/systemd/user/anantara-paper-ab9{a,b,c}.service.d/*.conf` | drop-in kuota + short leg |
| `~/.hermes/profiles/sodex-cex-monitor/scripts/sodex_cex_health_5min.py`, `..._pulse_30min.py` | health lane terpasang |
| `.env.swing` | `SODEX_TOTAL_WALLET` 243.39 → 234.17 (backup tersimpan) |

**Tidak ada commit/push** — repo dibiarkan pada keadaan kerja (sesuai instruksi tidak commit tanpa permintaan).
