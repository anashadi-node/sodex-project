# Eksekusi 2026-11-07 — temuan entry anti-predictive + A/B 9 (lane riset)

Ringkas untuk Owner. Semua angka berasal dari script di repo, bisa dijalankan ulang.

## 1. Geometri exit: jalan buntu (terukur, bukan opini)

`reports/sodex/EDGE_GRID_WALKFORWARD.md` — 240 konfigurasi (TP 0,5–4% × SL 0,5–3% ×
horizon 12–168 jam) diuji dengan split waktu 70/30 memakai **entry asli lane**:

- Yang lolos IS>0 DAN OOS>0: **50/240**, tetapi yang **terbaik** hanya **OOS +0,165pp**,
  dengan **q(BH) 0,16–0,28** → tidak signifikan setelah koreksi 240 uji.
- Ambang roster uang nyata +0,205pp **tidak tersentuh**. Konsisten dengan plafon replay
  sebelumnya (≈ +0,16pp).
- Kesimpulan: memperbaiki exit tidak cukup. Masalahnya di ENTRY.

## 2. Entry SIGNAL: anti-predictive (temuan utama)

`reports/sodex/ENTRY_EDGE_HORIZON_20261107.md`, 3.076 entry unik (463 SIGNAL / 2.613 RANDOM):

| horizon | SIGNAL | RANDOM | Δ | p |
|---|---|---|---|---|
| 4 jam | −0,595pp | +0,045pp | −0,640pp | <0,0001 |
| 12 jam | −0,652pp | +0,094pp | −0,746pp | <0,0001 |
| 24 jam | −1,546pp | +0,152pp | −1,698pp | <0,0001 |
| 48 jam | −2,463pp | −0,018pp | −2,446pp | <0,0001 |
| 72 jam | −3,369pp | −0,122pp | −3,246pp | <0,0001 |

Makin lama dipegang, makin buruk → bukan soal timing keluar; arah sinyal yang salah.
Track RANDOM (kontrol yang lane jalankan sendiri) rata-rata datar → bukan pasar yang
jatuh, tapi **pemilihan sinyalnya**.

## 3. Uji bantai sebelum menyimpulkan (hardening)

`reports/sodex/SIGNAL_FLIP_TEST_20261107.md` + `SIGNAL_FLIP_HARDENING_20261107.md`:

| uji | hasil |
|---|---|
| matched pair × minggu (confound komposisi dihapus) | Δ −1,50pp @24j, CI95 [−1,96,−1,05], q≈0 ✅ |
| cluster-robust (bootstrap blok pair+hari) | flipped +1,430pp @24j, CI95 [+0,957,+1,896], p<0,0001 ✅ |
| dedupe keras (1 entry per pair+hari+arah) | 255 entry, hasil sama ✅ |
| dua paruh OOS | +1,71pp / +1,15pp (keduanya positif) ✅ |
| jackknife drop-1-pair terburuk | masih +1,23pp (6× ambang) ✅ |
| 20/21 pair | flipped positif ✅ |
| saat kontrol RANDOM pair-minggu ≥0 (pasar tidak jatuh) | +1,22pp (tetap positif) ✅ |

Catatan penting: **semua entry SIGNAL di lane adalah LONG** (473/473), sehingga "flip"
praktis = SHORT. Itu sebabnya uji "pasar jatuh atau tidak" di atas wajib, dan lolos.

## 4. Kandidat lane: hanya geometri yang dipilih di IS

Geometri dites pada arah flipped, dipilih **hanya dari IS** (≤ 2026-10-30 22:12Z), lalu
diukur pada OOS yang tidak tersentuh:

| konfigurasi | IS | OOS | CI95 bawah OOS |
|---|---|---|---|
| TP1,5% / SL6% / 24 jam | +0,884pp | **+0,823pp** | **+0,306pp** |
| TP2,0% / SL6% / 24 jam | +0,818pp | +0,902pp | +0,381pp |
| TP1,0% / SL6% / 6 jam | +0,547pp | +0,654pp | +0,451pp |
| geometri lama TP2,5/4% + SL1–2% | −0,53pp | −0,25pp | — (gagal) |

Ambang roster +0,205pp terlampaui 4×, dengan batas bawah CI95 jauh di atas 0.

## 5. Yang sudah dijalankan (paper, lane riset terisolasi)

| unit | perlakuan | verifikasi |
|---|---|---|
| `anantara-paper-ab9a` | `TW_INVERT_SIGNAL=1` saja (geometri & gate identik `twoway` produksi) | `active`, env terbaca dari `/proc/<pid>/environ` ✅ |
| `anantara-paper-ab9b` | `TW_INVERT_SIGNAL=1 TW_TP_PCT=0.015 TW_SL_PCT=0.06 TW_TIME_STOP_H=24` | `active`, env terbaca ✅ |

- Fitur default **OFF** (`TW_INVERT_SIGNAL=0`, `TP_PCT`/`SL_PCT` default lama 4%/2%) →
  lane produksi tidak berubah; 6 unit test baru mengunci itu.
- Kontrol matched: track RANDOM di lane yang sama memakai geometri & gate yang sama.
- Aturan verdict + peringatan risiko (SL 6% = ekor tebal) tertulis di
  `docs/SODEX_AB_PREREGISTRATION.md` §6b. **Paper only — tanpa uang nyata tanpa GO-LIVE Owner.**

## 6. Perbaikan insiden (ditemukan saat kerja, bukan dicari-cari)

- `sodex-window-planner.service` **mati exit 1** karena satu HTTP 429 dari venue tanpa
  retry (03:46 WIB). Sudah diperbaiki: backoff eksponensial + jitter untuk 429/5xx,
  fail-closed untuk error non-retryable. Unit dijalankan ulang → **exit 0**.
  Dikunci oleh `tests/test_sodex_window_planner_retry.py` (3 test).

## 7. Batas klaim (jangan dilebihkan)

- Angka flip adalah **replay** pada kline 1h, bukan eksekusi nyata; slippage/impact dan
  antrian order belum masuk model.
- Profil flipped = menang sering kecil, kalah jarang besar (SL 6%) → ekor buruk bisa
  menghapus banyak kemenangan; wajib dibatasi sizing bila nanti live.
- 463 entry SIGNAL berasal dari Oktober–November; stabilitas jangka lebih panjang belum
  teruji. Justru itu alasan lane 9a/9b dijalankan hidup (paper), bukan langsung uang nyata.

## 8. ROOT CAUSE (bukan lagi gejala) — H5: sinyal itu detektor "pair yang baru naik"

Diuji 4 hipotesis penyebab, lalu sidik jari chase (`reports/sodex/SIGNAL_ROOTCAUSE_20261107.md`
+ `SIGNAL_MOMENTUM_RC_20261107.md`):

| uji | hasil | tafsir |
|---|---|---|
| H1 entry pasif (limit diskon 0,25–1,0%, jendela 2–12 jam) | EV naik maks +0,36pp, SIGNAL **tetap −0,81pp** dan tetap kalah dari RANDOM (Δ −0,24…−0,47pp) | bukan harga masuk |
| H2 horizon 1–72 jam | 1 jam pun **−0,274pp** | bukan timing keluar |
| H3 kalibrasi conviction | rho **−0,014** (p=0,76); 0,60 → −1,63pp, 0,80 → −1,51pp | conviction tanpa informasi |
| H4 rezim & jam UTC | 100% entry di rezim MOMENTUM; semua jam q=1,00 | tidak ada gate waktu |
| **H5 pra-entry 24 jam** | **SIGNAL +2,677% vs RANDOM −1,085%** (Mann-Whitney p=3,15e-121) | sinyal membeli setelah pump |
| H5 prediktif (dalam pair, demean) | pre24 → hasil24: rho **−0,046** (p=0,014); pre72: **−0,119** (p=1,5e-10) | run-up → harga balik turun |

**Kesimpulan kausal:** lane ini secara harfiah memburu kenaikan (chase momentum), dan
kenaikan itu mean-revert. Itu menjelaskan sekaligus: conviction tidak berguna,
entry pasif tidak menolong, tidak ada horizon positif, dan pembalikan arah justru
positif besar.

## 9. Kandidat yang lolos walk-forward (SIGNAL saja, biaya 0,10pp, split IS/OOS)

| aturan | hold | OOS net | CI95 | n |
|---|---|---|---|---|
| short apa adanya | 24j | **+1,670pp** | [+0,88,+2,47] | 124 |
| short apa adanya | 48j | **+3,115pp** | [+2,43,+3,78] | 124 |
| short hanya pre24>3% | 24j | **+1,797pp** | [+0,34,+3,29] | 37 |
| short hanya pre24>6% | 24j | +2,943pp | [+0,88,+4,90] | 17 |
| long apa adanya (kontrol) | 24j | −1,870pp | [−2,67,−1,08] | 124 |
| long hanya pre24<3% | 24j | −1,816pp | [−2,76,−0,92] | 87 |

10 dari 21 kandidat lolos (net OOS ≥ +0,205pp dan CI95 bawah > 0) — **semuanya di sisi
short**; semua varian long gagal, termasuk "long tapi hanya setelah harga turun".

## 10. Yang dijalankan sekarang (paper, lane riset)

| unit | perlakuan | alasan |
|---|---|---|
| `anantara-paper-ab9a` | short sinyal, geometri produksi | uji satu variabel (arah) |
| `anantara-paper-ab9b` | short sinyal + TP1,5%/SL6%/24j | kandidat utama (OOS +0,823pp) |
| `anantara-paper-ab9c` | short sinyal **hanya bila pre24 ≥ 3%** + geometri 9b | kandidat kualitas (OOS +1,797pp, n kecil) |

Semua fitur **default OFF** di kode (`TW_INVERT_SIGNAL`, `TW_PRE24_MIN`); nilai
`pre24_pct` direkam di tiap posisi sebagai jejak audit. Test suite **1357 passed**.
