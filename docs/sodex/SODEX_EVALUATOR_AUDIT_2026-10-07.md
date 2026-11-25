# Audit Read-Only Evaluator Pra-Registrasi F1 (#42) & F3 (#44)

Tanggal: 2026-10-07 WIB · Metode: 2 subagen read-only (`deleg_9a86e82e`) + verifikasi mandiri langsung.
Lingkup: `scripts/sodex_prereg_f1.py` (beku `6f718bc`), `scripts/sodex_prereg_f3.py` (beku `25360b4`).
Pertanyaan: risiko **false-pass** (lolos saat edge nol) dan cacat metodologis.

## 1. Ringkasan

| # | Temuan | Severitas | Bukti | Dampak | Tindakan |
|---|--------|-----------|-------|--------|----------|
| 1 | F1 `FEE_TAKER = 0,0002` (2 bp/leg) — resmi **4 bp/leg** | **KRITIS** | `f1.py:27`; venue 0,040%/leg; F3 sudah 4 bp | Bias optimistis ~0,04 pp/ep; **membalik C1** pada edge bruto 0,50%/ep | **DIPERBAIKI** → 0,0004 |
| 2 | F1 funding 24 jam **tak dibebankan** | SEDANG | `f1.py` §3 spec diam; funding nyata 0,024%/24j | Bias optimistis ~2,4 bp/ep | **DIPERBAIKI** → `FUNDING_BP_24H=2,4` |
| 3 | F3 `day_signflip_p` **kode mati** — C1/C2 pakai binomial episode | **KRITIS** | `f3.py:131` def, **0 pemanggilan**; C2 = `p_raw*1` (identitas) | False-pass **20–38%** pada data nol terklaster (nominal 5%) | **DIPERBAIKI** → C2 = sign-flip hari |
| 4 | F3 biaya funding: pakai **baris berikutnya ×0,5** | SEDANG | `f3.py:simulate` lama | Kredit tak layak pada ~94% onset | **DIPERBAIKI** → settlement terlewati saja |
| 5 | F3 C5 "segmen waktu" tapi kode **symbol-major** | SEDANG | `f3.py:judge` lama | C5 tak mengukur stabilitas temporal | **DIPERBAIKI** → urut `t_in` |
| 6 | `--final` bisa dijalankan ulang (menimpa hasil) | SEDANG | `main()` menulis file per-tanggal | Celah **optional-stopping** | **DIPERBAIKI** → timestamp + log append-only + FIRST-LOOK |
| 7 | F3 gerbang `n_onsets` > episode bisa disimulasikan | RENDAH | `f3.py:state` lama | Gerbang bisa terbuka sedikit lebih awal | **DIPERBAIKI** → `n_ready` (tanpa baca harga) |
| 8 | F1 CI bootstrap anti-konservatif; C3 redundan dgn C1 | RENDAH | `f1.py` | Efek marginal pada putusan marginal | **TIDAK diubah** (di luar lingkup approval) |

## 2. Falsifikasi jujur — yang TERBUKTI BUKAN masalah

- **F1 `day_signflip_p` BERDAYA & terkalibrasi** (3,7% false-reject pada 300 dataset nol; daya 72% untuk +1%/sd 5%, n=120). Dugaan awal "kelas bug daya-nol seperti `day_cluster_p`" **GUGUR**.
- **Tak ada look-ahead** di F1 maupun F3 (`mid_at`/`find_onsets`/`simulate` semua `bisect_right-1`; tak ada harga masa depan).
- **Ambang verbatim** — semua θ/ambang di kode = dokumen pra-reg.
- **Unit spread/slippage benar**; `binom_p`, `boot_ci_low`, `window_pnls` benar.
- **Tak ada drift skrip** — sha256 = commit beku (`25360b4`); `git diff` kosong sebelum amendemen.
- **`judge()` 0/200 PASS** pada data tanpa edge (uji null F1).

## 3. Bukti RED (kode lama vs baru)

Data uji: 10 hari × 10 episode; 7 hari semua-positif, 3 hari semua-negatif (day-shock, edge nol).

```
n=100 positif=70 WR=70,00%  p_raw(binomial episode)=3,93e-05
C1 (WR>50% & p_raw<0,05)          = True
C2 LAMA (p_bonferroni_m1 = p_raw) = True    <-- LULUS PALSU
C2 BARU (p_hari klaster = 0,1717) = False   <-- benar (hanya 7/10 hari positif)
```

## 4. Prinsip: mengapa amendemen ini sah

- Amendemen dilakukan saat **F1 = 0/150 episode** dan **F3 = 1/100 episode** — belum ada PnL dihitung → **bukan p-hacking**; tidak ada hasil yang bisa "dilihat".
- Ambang/θ/HARD_STOP **tidak diubah**; yang diperbaiki = model biaya + uji statistik yang dimaksud spec.
- Transparan: catat di dokumen pra-reg (§AMENDEMEN) + commit terpisah + tes regresi.

## 5. Tes regresi

- `tests/test_sodex_prereg_f1.py::test_amendment_fee_is_official_4bp_and_funding_charged`
- `tests/test_sodex_prereg_f3.py::test_c2_uses_day_clustered_signflip_not_raw_binomial` (bukti RED)
- `tests/test_sodex_prereg_f3.py::test_funding_charged_only_for_crossed_settlements`
- `tests/test_sodex_prereg_f3.py::test_simulate_funding_sign_and_no_settlement`
- `tests/test_sodex_prereg_f3.py::test_c5_segments_use_time_order_not_symbol_major`

## 6. Risiko sisa

- Item RENDAH (#8) belum disentuh: CI bootstrap F1 anti-konservatif; C3 redundan dgn C1. Tidak mengubah arah putusan, tetapi layak ditinjau bila putusan **marginal**.
- `docs/sodex/SODEX_F1_PRAREG` §3 asli masih menulis "2 bp" — **dibiarkan** sebagai catatan historis; koreksi ada di §10 AMENDEMEN (jangan edit diam-diam).
