# D15 — Sensus Edge Seluruh Mesin (D14/D14b) + Konsolidasi:mv_funding

**Tanggal**: 05 Oktober 2026
**Keluarga**: 21 mesin (dibekukan di Lampiran A D14, pra-registrasi commit `dc4633f`)
**Pertanyaan**: Dari **seluruh** mesin di ekosistem, berapa yang edge-nya **tervalidasi** dan cukup untuk jalur target 0,8%/48 jam?

---

## 1. Ringkasan Putusan

**VERDICT: TIDAK-ADA-MESIN-LULUS (P9).** Portofolio 6–8 mesin **belum punya jalur** hari ini.

- Keluarga 21 → sanggup diuji (n≥20 trade) **6**.
- **LULUS P9 semuanya = 0** (lima syarat: n_win≥20 ∧ SR_thn≥2,3 ∧ 3/3 segmen positif ∧ p_terburuk<0,05 ∧ BH-FDR q=0,10).
- Satu-satunya lolos statistik penuh = `hl_replay` — **dikeluarkan dari P9 sebelum unblind** karena flag REPLAY (simulasi historis, in-sample by construction). Ini tetap BH-lulus=1 tapi TIDAK dihitung kandidat.
- Kandidat nyata yang tersisa: **`mv_funding`** (CARRY, delta-neutral) — **satu-satunya** — gagal satu syarat: n_windows=**15<20**.
- Instrumen SAH: FPR pada H0 sintetis p=0,0575 (≈α), gabungan (p∧SR) = 0,010.

---

## 2. Tabel Sensus (dari `data/sodex_edge_census.json`, di-commit)

| Mesin | Flag | n | n_win | mean48 | sd48 | SR_thn | p_day | p_worst | seg | BH | P9 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hl_replay | REPLAY | 2185 | 45 | +17,312% | 27,849% | 8,40 | 0,0003 | 0,0003 | 3/3 | 1 | (excl) |
| **mv_funding** | CARRY | 96 | **15** | +0,397% | 0,666% | **8,06** | **0,0359** | 0,0359 | **3/3** | 0 | ❌ n<20 |
| spot_swing_cex | — | 189 | 15 | +2,110% | 8,136% | 3,50 | 0,4018 | 0,4018 | 2/3 | 0 | ❌ |
| twoway | — | 371 | 31 | +3,408% | 15,487% | 2,97 | 0,2355 | 0,2429 | 2/3 | 0 | ❌ |
| realwide | — | 238 | 31 | +1,595% | 9,737% | 2,21 | 0,4081 | 0,4081 | 1/3 | 0 | ❌ |
| donchian | — | 187 | 22 | +1,552% | 12,446% | 1,68 | 0,5222 | 0,5769 | 2/3 | 0 | ❌ |
| …15 mesin negatif/s Schwäche | | | | | | | | | | | ❌ |
| micro_live | **UANG-NYATA** | **7** | 3 | −0,803% | 0,788% | −13,77 | 0,4859 | n/a | 0/0 | 0 | ❌ |

---

## 3. Temuan keamanan: LANE LIVE `micro_live`

**Insiden tak terdeteksi sebelumnya**:
- 171/178 baris ledger `realwide_micro_live.jsonl` = artefak audit-log PALGU (dry-run/flatten berulang pra-guard insiden 25-Sep, `close_rc=None`); 95 baris berlabel KILL_FLATTEN semua dgn `exit_price=2486,22` IDENTIK di 9 hari berbeda → **faktual bukan trade**.
- PnL uang-nyata TERVERIFIKASI sejak live: `$‑22,69` dari **8 trade** (7 baris ledger valid + 1 VENUE_RECONCILE), WR 3/8. **TIDAK signifikan** (n terlalu kecil) — klaim "rugi $‑403" DITOLAK.
- Remediasi protokol: **P12 ditambahkan ke pra-registrasi** (data-hygiene untuk mesin uang-nyata: buang `close_rc` kosong atau duplikat butir-identik) SEBELUM evaluasi ulang, di-commit.
- Live service `anantara-realwide-livetest` = **inactive (dead)** — tidak ada posisi terbuka, tidak ada risiko baru.

## 4. mv_funding — kandidat tunggal; apa yang sudah lolos & apa yang belum

Lolos:
- **Statistik**: p_day(hari) = 0,0359; p cluster-8h = **0,0307** (unit sampling BENAR untuk carry, sign-flip per slot settlement); p_terburuk 0,0359 < 0,05.
- **3/3 segmen** kronologis positif (census resmi, grid 48j GLOBAL per P3/P4).
- **B0 net-of-cost**: fee 7 bps RT all-maker sudah net di `pnl_usd` (understate 17% — konservatif); margin keamanan biaya = **2× RT penuh tambahan** (POSITIF sampai +35 bps/jendela; NEGATIF baru di +50 bps).
- **SR thn** 8,06 ≫ 2,3.

Belum:
- **n_windows = 15 < 20** (span data 14,02 hari). Butuh **+5 jendela 48j** ≈ **10 hari data tambahan**.
- BH-FDR atas keluarga: gagal (0/6) sebelum n cukup — jalur = lengkapi data, bukan ubah ambang.
- Korelasi portofolio ρ≤0,10: belum dapat dihitung (butuh ≥2 mesin lulus P9).

Diar小小的经历 di **`funding_carry_test`** (engine pendahulu, 39 CLOSED 9/13–9/19, 12/39 WR, mean −2,142%/trade): fase eksperimentasi lama dgn notional/fee berbeda; **TIDAK dipakai** sebagai basis kandidat mv_funding (regime beda).

---

## 5. Kesinambungan dgn riwayat D13

| Tema | D13 (R1–R3) | D15/D14b |
|---|---|---|
| REAL-wide level | PROMISING-NOT-ESTABLISHED (BH 0/22) | census: SR_thn 2,21, p_day 0,4081 — **TIDAK lulus**, konsisten |
| SOL | difalsifikasi via cluster hari | konsisten (census tak meragukan) |
| micro_live | belum di-sensus — | kini: **$‑22,69 n=8 nyata**; n=171 palsu dibuang P12 |
| target 0,8%/48j | sharpe 4-6 real vs 8,6× paper sizing | **jln terdekat = lengkapi mv_funding data 10 hari** |

---

## 6. Batas & apa yang TIDAK mengubah

- **Target 0,8%/48j = harga mati.** TIDAK di-turunkan.
- **Ambang P9 TIDAK diubah** setelah hasil (integritas pra-registrasi).
- **Gate T1 utuh, tanpa leverage, SODEX_TOTAL_WALLET tidak diubah, E1 beku, arm A1 mati, RW_MARGIN_UTIL_CAP OFF.**
- `hl_replay` tetap ditandai REPLAY (TIDAK dipromosikan via pintu belakang statistik).

## 7. Langkah Berikutnya (usulan, butuh approval user)

1. **Percepat mv_funding ke n=20** (≈10 hari, data meluncur sendiri saat window berjalan → bisa diuji ~15-Okt) — putusan tanggal itu: P9 ulang.
2. **S1 forward test** (jalur kedua): n≥30 jendela, p terburuk <0,05, 3/3 segmen — pra-registrasi sudah ada.
3. **Test T3/T4 mesin kedua + korelasi** setelah ≥2 mesin lulus P9.

---

## Lampiran

- **C** — mv_funding dihitung ulang dari sumber (mean/sd/segmen).
- **C-2** — penjelasan seg1 negatif (ramp-up).
- **D** — sensitivitas biaya (G2).
- **E** — p cluster-8h (unit benar carry).

**Lampiran C** — mv_funding dihitung ulang dari sumber (`data/mv_funding_paper.json`, 96 trade, ret = pnl_usd/notional, FEE understate 17%):
- Jendela 48j non-overlap = **15** (butuh 20, kurang 5).
- Mean +0,3975% | sd 0,6353% | SR tahunan (deret jendela) = **8,06** (census resmi P3/P4; hitung per-trade = 8,45 — unit beda, dilaporkan dua-duanya).
- Sekuen: `+-+--+++++++-++`
- Segmen (census, grid GLOBAL): **3/3 positif** → P7 LULUS.
  (Perhitungan-ulang manual danwith anchor lokal = exit pertama memberi seg1 −0,034% —
  PERBEDAAN ANCHOR, bukan data beda. Pangkal kebenaran = census resmi 3/3.)
  Bottleneck P9 satu-satunya yang tersisa = n_windows 15<20.

**Lampiran C-2**: catatan ramp-up seg1 (hitung manual, anchor lokal) = −0,034% kecil dan tidak
mengubah verdict; census resmi dgn grid global memberi 3/3 positif — DIPAKAI yang census

**Lampiran D — G2 biaya**:

| Biaya | mean net | SR tahunan | Putusan |
|---|---|---|---|
| 0 (baseline) | +0,3975% | 8,06 | POSITIF |
| +9 bps (1 leg taker) | +0,3075% | 6,23 | POSITIF |
| +18 bps (RT full) | +0,2175% | 4,40 | POSITIF |
| +35 bps (2× RT penuh) | +0,0475% | 0,96 | POSITIF (tipis) |
| +50 bps | −0,1025% | −2,07 | NEGATIF |
| +72 bps (4× RT) | −0,3225% | −6,50 | NEGATIF |

**Lampiran E — p cluster-8h** = **0,0307** (sign-flip per slot settlement 8 jam, unit benar utk carry); p harian 0,0359; p trade-level i.i.d. 0,0091 (terlalu lembek — pelajaran R3/SOL). p_worst = 0,0359 < 0,05.

---

*Sensus data: `data/sodex_edge_census.json` (di-commit). Pra-registrasi: `docs/sodex/D14_PROTOKOL_SENSUS_EDGE_2026-10-05.md` (commit dc4633f + amend P12 LAMPIRAN A/D14b).*
