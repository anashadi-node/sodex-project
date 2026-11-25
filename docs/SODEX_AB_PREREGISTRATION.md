# PRE-REGISTRASI EKSPERIMEN SoDEX — exit & gate

Dibuat: 2026-11-06 (UTC+7). Wajib dibaca sebelum menjalankan/menafsirkan A/B.
Tujuan berkas: **mencegah post-hoc reasoning** — kriteria keputusan ditetapkan
SEBELUM data terkumpul, sehingga hasil tidak bisa "dipilih yang menang".

## 1. Aturan readout A/B exit REGIME_FLIP (aktif)

Sumber: `scripts/sodex_ab_flip_readout.py`, dijalankan `sodex-ab-flip-readout.timer`
tiap 6 jam, keluaran di-append ke `reports/sodex/AB_REGIMEFLIP_READOUT.md`.

| Aturan | Nilai |
|---|---|
| Arm TREATMENT | `anantara-paper-swing` (flip=0), `anantara-paper-swing-partial` (flip=0 + BTC gate) |
| Arm KONTROL | `anantara-paper-swing-strict` (flip=1) |
| Awal jendela | `ActiveEnterTimestamp` unit (trade pra-restart TIDAK dihitung) |
| Ambang n | **n ≥ 20 per arm**; di bawah itu status MONITOR (bukan bukti apa pun) |
| Uji | bootstrap CI95 (10k) atas mean `pnl_pct` + t-test satu sisi + BH-FDR antar arm |
| Terima treatment | CI95 > 0 **dan** q < 0,05 |
| Tolak treatment (revert) | CI95 seluruhnya < 0 **atau** DiD vs kontrol ≤ −0,10pp dengan q < 0,05 |
| Selain itu | MONITOR, tidak ada perubahan parameter |

## 2. Syarat roster uang nyata 1 Des 2026 (harga mati, sudah ada sebelumnya)

- Net **≥ +0,205pp/trade** (gross yang dibutuhkan setelah biaya 0,098pp round-trip).
- Batas bawah CI95 **> 0** pada window ≥ 7 hari dan n ≥ 100.
- Satu lane masuk roster hanya bila memenuhi keduanya; tidak ada pengecualian "hampir".

## 3. Bukti replay exit-geometry (independen, 2026-11-06)

`scripts/research/replay_exit_geometry_20261107.py` — entry/SL asli lane, exit
dievaluasi ulang pada 1h candle Binance, SL didahulukan bila TP & SL tersentuh di
bar yang sama, biaya 0,10pp per round-trip, horizon 168 jam.

| lane | varian | n | mean | p |
|---|---|---|---|---|
| swing | cur (aturan sekarang) | 899 | −0,102pp | 0,023 |
| swing | no_ts72 (time-stop dibuang) | 899 | **+0,014pp** | 0,80 |
| swing | trail1r (trailing setelah +1R) | 899 | **+0,055pp** | 0,22 |
| partial | cur | 970 | −0,099pp | 0,003 |
| partial | no_ts72 | 970 | **+0,007pp** | 0,89 |
| partial | trail1r | 970 | **+0,064pp** | 0,14 |
| twoway | cur | 578 | +0,002pp | 0,98 |
| twoway | trail1r | 578 | **+0,074pp** | 0,43 |

KOREKSI PENTING: baris `cur` sebelumnya mengurangi biaya 0,10pp padahal `pnl_pct`
ledger sudah net → `cur` tampak 0,10pp lebih buruk dari kenyataan dan keunggulan
semua varian jadi palsu 0,10pp. Sudah diperbaiki di skrip; tabel di atas versi benar.

## 3b. Bukti sisi ENTRY (7 hari, n=599, swing+twoway, UJI SATU SISI + BH-FDR)

| split | n | mean | q(BH) | tafsir |
|---|---|---|---|---|
| pair=LIT | 27 | −0,711pp | 0,0005 | negatif nyata |
| pair=HYPE | 31 | −0,666pp | 0,0027 | negatif nyata |
| conviction=random(0) | 444 | −0,163pp | 0,0027 | negatif nyata |
| atr≤1,2% | 371 | −0,202pp | 0,0154 | negatif nyata |
| pair=DOGE | 34 | −0,527pp | 0,0180 | negatif nyata |
| atr>3% | 30 | −0,562pp | 0,0180 | negatif nyata |
| atr 1,2–2% | 168 | −0,277pp | 0,0395 | negatif nyata |
| conviction≥0,5 (SIGNAL) | 155 | −0,405pp | 0,0395 | negatif nyata |
| btc_regime=BULL | 146 | −0,435pp | 0,0403 | negatif nyata |
| atr 2–3% | 30 | +0,107pp | 0,70 | belum signifikan |
| pair=TRX | 23 | +0,199pp | 0,87 | belum signifikan |

Yang boleh disimpulkan: **tidak ada** subset entry yang terbukti positif; sebaliknya
banyak subset terbukti negatif. Sinyal (conviction≥0,5) lebih buruk dari kontrol acak
(−0,405pp vs −0,163pp) — konsisten dengan temuan lama "T+4h/T+12h anti-predictive".
Semua bucket ATR negatif kecuali 2–3% → indikasi geometri SL/TP tetap tidak cocok
dengan volatilitas pair, dan itulah yang ditargetkan fitur `PAPER_ATR_SL`.

**Kesimpulan yang boleh diklaim (dan tidak lebih):**
1. Familia exit time-stop/REGIME_FLIP menjelaskan hampir seluruh kerugian lane swing:
   membuangnya mengangkat swing dari −0,102pp → +0,014pp dan partial −0,099pp → +0,007pp.
2. Perbaikan itu **belum cukup**: varian terbaik (trail1r) hanya +0,055..+0,074pp,
   **p = 0,14–0,43 (tidak signifikan)** dan masih jauh di bawah syarat +0,205pp.
3. Karena entry TIDAK diubah di replay ini, sisa gap = **kualitas entry**, bukan geometri exit.
   Mengklaim exit-geometry adalah "penyembuh" akan melanggar poin ini.

## 4. Kandidat A/B 7 — trailing exit setelah +1R (STATUS: MENUNGGU APPROVAL OWNER)

- Perlakuan: ganti exit lane menjadi trailing setelah +1R (varian `trail1r`), **satu lane saja**.
- Kontrol: lane yang sama dengan aturan sekarang (atau lane kembar yang identik).
- Durasi minimum: sampai n ≥ 20 per arm; keputusan hanya via aturan bagian 1.
- Kriteria LOLOS (pra-dideklarasi): CI95 > 0 **dan** mean ≥ +0,205pp → layak roster.
- Kriteria GAGAL → revert: CI95 < 0, atau mean < 0,10pp setelah n ≥ 60 per arm.
- Dilarang: mengubah entry, SL, leverage, atau ukuran posisi dalam eksperimen yang sama
  (satu variabel per eksperimen, kalau tidak hasilnya tidak bisa diatribusikan).

## 6. A/B 8 (STATUS: **JALAN PARALEL sejak 2026-11-06 15:30:14 UTC**, disetujui Owner)

Laporan bukti: `reports/sodex/AB8_LANES_20261106.md`. Kedua arm berjalan di lane riset
terisolasi (`PAPER_STATE_SUFFIX` berbeda) sehingga tidak mengganggu lane produksi.

| arm | unit | variabel tunggal |
|---|---|---|
| 8a | `anantara-paper-ab8atr.service` | `PAPER_ATR_SL=1` (SL=1×ATR, floor 1%, cap 4%, TP=2,5×SL) |
| 8b | `anantara-paper-ab8trail.service` | `SW_TRAIL_TRIGGER_R=1.0 SW_TRAIL_R=1.0` (trailing setelah +1R) |

Keduanya memakai `SW_REGIME_FLIP=0` yang sama dengan lane `swing` (kontrol/referensi)
supaya perbedaannya hanya satu variabel. Revert: `systemctl --user disable --now <unit>`
(fitur default OFF di kode, lane produksi tidak berubah).


Dua kandidat, **satu variabel masing-masing**, evaluasi dengan aturan bagian 1
(keduanya boleh jalan paralel karena lane-nya terpisah).

### 8a. Geometri ATR — SEDANG BERJALAN
Dasar bukti: semua bucket ATR negatif kecuali 2–3% (q<0,05) → SL 1% tetap tidak cocok
dengan volatilitas pair. Fitur default OFF di kode; dinyalakan lewat `/usr/bin/env` di
unit (bukan lewat `Environment=`, karena `EnvironmentFile=` menimpanya).
Cara pasang (lane riset terisolasi, bukan lane produksi):

```
mkdir -p ~/.config/systemd/user/<unit-riset>.service.d
cat > ~/.config/systemd/user/<unit-riset>.service.d/ab8-atr.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/env PAPER_ATR_SL=1 PAPER_ATR_SL_MULT=1.0 PAPER_ATR_SL_FLOOR=0.010 \
  PAPER_ATR_SL_CAP=0.040 PAPER_ATR_RR=2.5 PAPER_STATE_SUFFIX=_ab8atr \
  /home/USER/anantara-sakti/.venv-research/bin/python3 -u \
  scripts/paper_test_swing.py --loop --interval 300
EOF
systemctl --user daemon-reload && systemctl --user restart <unit-riset>
```
Verifikasi wajib setelah restart: `tr '\0' '\n' < /proc/$(systemctl --user show -p MainPID --value <unit-riset>)/environ | grep PAPER_ATR`.

### 8b. Trailing exit setelah +1R
Dasar bukti: varian terbaik replay (+0,055..+0,074pp) tetapi p=0,14–0,43 → belum
signifikan. Kalau dipilih, **wajib** dicatat sebagai uji konfirmasi (bukan klaim
perbaikan) dan dievaluasi dengan aturan bagian 1.

### Larangan berlaku untuk keduanya
Tidak boleh mengubah entry/SL/leverage/sizing lain di eksperimen yang sama; tidak
boleh menyentuh lane produksi (`swing`, `swing-strict`, `swing-partial`) yang sedang
dipakai A/B 1/4/5; revert = hapus drop-in + `daemon-reload` + restart.

## 5. Kalau tidak ada lane yang lolos sebelum 1 Des

Roster live tetap **kosong/kecil apa adanya** dan keputusan ditulis apa adanya ke Owner.
Memaksa lane masuk roster karena tanggal adalah pelanggaran kode etika, bukan optimisme.

## 6b. A/B 9 — balik arah sinyal (STATUS: JALAN, lane riset terisolasi, PAPER ONLY)

Ditemukan 2026-11-07 dari audit entry-side dan di-hardening sebelum ada lane apa pun.

Rantai bukti (semua di repo, bisa diperiksa ulang):
1. `reports/sodex/EDGE_GRID_WALKFORWARD.md` — 240 konfigurasi exit (TP×SL×horizon),
   split waktu 70/30: **tidak ada** konfigurasi yang lolos (terbaik OOS +0,165pp,
   q-BH 0,16–0,28). Geometri exit bukan obat → masalah ada di sisi ENTRY.
2. `reports/sodex/ENTRY_EDGE_HORIZON_20261107.md` — track SIGNAL vs RANDOM pada
   horizon tetap: SIGNAL **lebih buruk di semua horizon**, Δ −0,64pp (4j) sampai
   −3,25pp (72j), q-BH ≈ 0.
3. `reports/sodex/SIGNAL_FLIP_TEST_20261107.md` — matched pair×minggu (confound
   komposisi pair/waktu dihapus): Δ −1,50pp @24j, CI95 [−1,96,−1,05], q≈0.
   Flip walk-forward: OOS +1,124pp (CI95 [+0,40,+1,86]) @24j.
4. `reports/sodex/SIGNAL_FLIP_HARDENING_20261107.md` — cluster-robust (bootstrap
   blok per pair+hari), dedupe keras, dua paruh OOS, jackknife drop-1-pair
   (terburuk tetap +1,23pp), 20/21 pair positif, dan tetap positif saat kontrol
   RANDOM pair-minggu ≥0 (pasar tidak jatuh) → bukan sekadar "short saat pasar turun".
5. Geometri flipped yang dipilih **hanya dari IS** (≤ 2026-10-30 22:12Z), lalu
   diukur di OOS yang tidak tersentuh: TP1,5%/SL6%/24j → IS +0,884pp, **OOS
   +0,823pp** (CI95 bawah +0,306pp). Geometri lama (TP2,5–4%/SL1–2%) pada arah
   flipped: IS −0,53pp / OOS −0,25pp → geometri lama memang membunuh edge.

| arm | unit | perlakuan |
|---|---|---|
| 9a | `anantara-paper-ab9a.service` | `TW_INVERT_SIGNAL=1` saja (geometri & gate IDENTIK lane `twoway` produksi) |
| 9b | `anantara-paper-ab9b.service` | `TW_INVERT_SIGNAL=1 TW_TP_PCT=0.015 TW_SL_PCT=0.06 TW_TIME_STOP_H=24` |

Desain: 9a menguji **satu variabel** (arah), 9b menguji kandidat lengkap. Di dalam
setiap lane, track **RANDOM memakai geometri & gate yang sama** → kontrol matched
alami. Flag `TW_INVERT_SIGNAL` default **OFF** di kode; lane produksi tidak berubah.

Kriteria keputusan (bagian 1 + tambahan khusus A/B 9):
- Terima kandidat hanya bila track SIGNAL lane 9b: n≥20, net ≥ +0,205pp, CI95 bawah > 0,
  **dan** net SIGNAL > net RANDOM di lane yang sama (kalau kalah dari acak dengan
  geometri sama, edge-nya ilusi).
- Tolak/revert bila n≥20 dan SIGNAL ≤ RANDOM atau CI95 seluruhnya < 0.
- **PERINGATAN RISIKO yang wajib dibaca:** profil ini menang kecil sering, kalah besar
  jarang (SL 6%). Ekor buruk = beberapa posisi short terkena squeeze bersamaan.
  Karena itu: paper only, tanpa uang nyata, sampai kriteria di atas terpenuhi **dan**
  Owner memberi GO-LIVE eksplisit. Sizing live, bila nanti disetujui, wajib dibatasi
  (usulan: ≤ 1/3 Kelly dan stop harian tetap 8%).

### A/B 9c — filter akar masalah "chase" (jalur RISET, PAPER ONLY)

Ditambahkan 2026-11-07 setelah root cause H5 teridentifikasi (bukan ditebak):

- Return PRA-entry 24 jam: **SIGNAL +2,677% vs RANDOM −1,085%** (Mann-Whitney
  p=3,15e-121). Sinyal lane ini secara harfiah adalah detektor "pair yang baru naik".
- Kenaikan itu memprediksi hasil **negatif** di dalam pair yang sama (Spearman
  demeaned: −0,046 @24j p=0,014; −0,119 @72j p=1,5e-10).
- Filter sederhana diuji walk-forward: `short hanya pre24>3%` / hold 24j → OOS
  **+1,797pp** (CI95 [+0,34,+3,29], n=37); tiap-tiap hungga 48j juga lolos.
- Yang **gagal** dan wajib dicatat: entry pasif (limit diskon 0,25–1,0%) tidak
  menyelamatkan apa pun (SIGNAL tetap −0,81pp dan tetap kalah dari RANDOM dengan
  mekanik entry sama), tidak ada horizon positif (1 jam pun −0,274pp), conviction
  tidak menambah informasi (rho −0,014, p=0,76).

Konfigurasi lane: `TW_INVERT_SIGNAL=1 TW_PRE24_MIN=3.0 TW_TP_PCT=0.015 TW_SL_PCT=0.06
TW_TIME_STOP_H=24` (unit `anantara-paper-ab9c.service`). Fitur `TW_PRE24_MIN` default
**OFF** (None) → lane produksi tidak berubah; nilai `pre24_pct` disimpan di setiap
posisi sebagai jejak audit.

Kriteria: sama seperti A/B 9 (bagian 1 + 6b). Catatan kejujuran: n OOS hanya 37 →
lane hidup ini yang menentukan, bukan replay.

## 7. Keputusan Owner 2026-11-07 — LONG-sinyal dihentikan di 5 lane paper

Bukan A/B baru, melainkan **tindakan atas temuan yang sudah konklusif** (verdict
pre-registrasi: tolak/revert bila n≥20 dan CI95 seluruhnya < 0 → terpenuhi).

Bukti per lane (hold 24 jam, biaya 0,10pp, entry berbasis kline 1 jam):

| lane | n SIGNAL | net 24j | CI95 bawah | pra-entry 24j | n RANDOM | net RANDOM |
|---|---|---|---|---|---|---|
| swing | 65 | −1,910pp | −2,790 | +3,30% | 428 | +0,179pp |
| swing_partial | 57 | −2,025pp | −2,975 | +2,51% | 447 | −0,076pp |
| swing_strict | 38 | −0,557pp | −1,661 | +3,69% | 408 | +0,039pp |
| twoway | 137 | −0,553pp | −1,123 | +2,52% | 75 | −0,350pp |
| twoway_p27 | 114 | −1,744pp | −2,462 | +2,26% | 43 | −0,271pp |
| **semua** | **411** | **−1,303pp** | — | **+2,68%** | **1404** | **+0,018pp** |

Ciri pembeda: pra-entry SIGNAL positif besar vs RANDOM negatif (Mann-Whitney
p=3,15e-121) dan run-up itu memprediksi hasil negatif di dalam pair yang sama →
lane ini memburu kenaikan, kenaikan itu mean-revert.

Tindakan: drop-in `zz-block-long-signal.conf` di `anantara-paper-swing`,
`-swing-strict`, `-swing-partial`, `-twoway`, `-twoway-p27` → env
`SW_BLOCK_LONG_SIGNAL=1` / `TW_BLOCK_LONG_SIGNAL=1` (**default OFF di kode**).
Blokir hanya menyentuh arah yang DIPERDAGANGKAN (dievaluasi SESUDAH inversi) dan
tidak menyentuh track RANDOM, jadi kontrol matched tetap hidup di lane yang sama.
Setiap penolakan dicatat di log: `SKIP <pair>: LONG-sinyal dihentikan`.

Revert: hapus drop-in tersebut → `systemctl --user daemon-reload` → restart unit.
Lane riset 9a/9b/9c tidak memakai env ini (arah akhir SHORT) → eksperimen tetap jalan.
