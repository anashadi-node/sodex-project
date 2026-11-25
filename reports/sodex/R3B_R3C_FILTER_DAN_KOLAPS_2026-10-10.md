# R3B/R3C — FILTER ENTRY GAGAL DI HOLDOUT & DIAGNOSIS KOLAPS OKTOBER

**Tanggal:** 10-Okt-2026 · **Sifat:** read-only, tanpa order
**Protokol beku:** `docs/sodex/R3B_PROTOKOL_FILTER_ENTRY.md` sha256 `2f2ce12dbb4e93c4…` (dibekukan & commit `f8f5d4e` SEBELUM holdout dihitung)
**Runner:** `scripts/research/r3a_anatomi_rugi.py` (train) · `r3b_filter_holdout.py` sha256 `18af9bf9cb526302…` (holdout, satu kali) · `r3c_diagnosis_holdout.py`
**Data:** `reports/sodex/R3A_ANATOMI_RUGI_TRAIN.json`, `R3B_FILTER_HOLDOUT_2026-10-10.json`

## R3A — anatomi train (n=1659, WR dasar 40,9%, 43 hipotesis, 8 lolos BH-FDR q<0,10)

| Kandidat ex-ante | n | WR | ΔWR | q |
|---|---|---|---|---|
| jam UTC 12 | 54 | **18,5%** | −23,1 pp | 0,0147 |
| hold 6–18 jam | 228 | 50,0% | +11,9 pp | 0,0214 |
| track realwide | 228 | 49,6% | +10,1 pp | 0,0426 |
| jam UTC 15 | 91 | 54,9% | +14,9 pp | 0,0426 |
| jam UTC 3 / 10 | 70 / 60 | 55,7% / 56,7% | +15,5 / +16,4 pp | 0,0689 |
| ATR ≥1% (buruk) | 267 | 36,3% | −6,8 pp | 0,233 |

**Temuan negatif penting**: skor `conviction` **tidak diskriminatif** (0,6–0,79 → WR 43,3%; 0,8–0,99 → 42,1%). Jadi tidak ada "skor keyakinan" yang bisa dipakai sebagai filter. Side S terlalu tipis di train (n=42).

## R3B — uji holdout (frozen, satu kali): KEDUA ATURAN **GAGAL**

| Aturan | kept n | WR kept | ΔWR | binom p | Verdict |
|---|---|---|---|---|---|
| R-A tolak jam 12 UTC | 233 | 25,75% | +25,75 pp (dari 3 trade!) | 1,000 | **GAGAL** |
| R-B tolak ATR ≥1% | 69 | 18,84% | **−6,16 pp (terbalik)** | 0,99997 | **GAGAL** |
| R-AB gabungan | 209 | 25,84% | +3,62 pp | 1,000 | **GAGAL** |

Kriteria beku menuntut WR_kept ≥ 45% + ΔWR ≥ +5 pp + n ≥ 40 + binomial p<0,05 + kalahkan kontrol. Tidak ada yang terpenuhi. **R-B bukan hanya gagal — ia berbalik arah**: di holdout, trade ber-ATR tinggi justru lebih sering menang (25,0% vs 18,8%). Sinyal ATR di train = artefak sampel.

## R3C — mengapa holdout jeblok: **regime, bukan bug**

| | TRAIN | HOLDOUT (≥1-Okt) |
|---|---|---|
| WR sinyal | 41,2% (n=1692) | **27,8%** (n=270) |
| WR **LONG** | 41,4% (1570 trade, 93% porsi) | **25,4%** (236) |
| WR **SHORT** | 38,5% (122) | **44,1%** (34) |
| TP tercapai | 482 dari 1692 (28%) | **25 dari 270 (9%)** |
| SL | 749 | 153 dari 270 (**57%**) |
| WR kontrol RANDOM | n/a (n<20) | **19,0%** (n=200) |

- **Semua track jeblok**, kecuali yang berorientasi SHORT: realwide 49,6%→28,0%, twoway 45,3%→**16,2%**, swing 36,6%→19,4%, hyperliquid 35,1%→20,9%; `shortbear` justru naik 47,6%→**53,3%**.
- Artinya: buku kita **93% LONG**. Oktober = pasar yang tidak memberi TP (TP turun dari 28% ke 9% trade) → longs kena SL. Ini **efek regime**, bukan kerusakan data: sanity check 10 loss terbesar menunjukkan harga & gerak konsisten (−2% s/d −5%, SL wajar), tanpa anomali harga.
- **Sinergi penting**: sinyal (27,8%) vs kontrol RANDOM (19,0%) = **ΔWR +8,8 pp**. Jadi sinyal **masih punya informasi** — tapi tidak cukup untuk melawan regime yang memusuhi longs.
- Catatan keterbatasan: angka R3B (n=236 sinyal) dan R3C (n=270) berbeda karena R3C memuat 2 track tambahan (portfolio, shortbear). `pnl_pct` tidak ada di sebagian track (aster/hyperliquid) → kolom median% di runner = 0, artefak; WR & usd tidak terpengaruh. Klines 1d SoDEX belum punya bar Oktober (lag refresh) — arah pasar disimpulkan dari perilaku long/short, bukan dari klines.

## Kesimpulan

1. Filter entry pilihan train **GAGAL** di holdout — jangan dipakai. Bukti keras bahwa pencarian filter dari data yang ada = overfit.
2. **Diagnosis sebenarnya**: keunggulan sistem bersifat **regime-dependent** (long WR 41% saat ramah, 25% saat tidak), bukan timing per-trade. SHORT bekerja justru ketika LONG gagal (44,1% WR di Okt).
3. Ini mengarah ke satu-satunya tuas yang belum diuji dan **masih punya mekanisme jelas**: **gate regime / utilisasi sisi SHORT** — bukan menambah filter mikro, tapi tidak melawan arus.

## Batas

- Holdout 10 hari, 6 window — underpowered untuk klaim kuat; verdict "GAGAL" tetap sah karena kriteria beku tidak terpenuhi.
- Efek jam secara inheren rawan overfit (24 jam diuji) — itulah mengapa holdout dipakai, dan hasilnya menolak.
- 3 look tambahan dicatat sebagai trial di registry (R3A train, R3B holdout, R3C diagnosis).

*Laporan · Hermes Anantara v3 · 10-Okt-2026*

---

## KOREKSI PASCA-AUDIT (10-Okt, `reports/sodex/AUDIT_R3_R5_2026-10-10.md`)

1. **R3A**: n_train 1659 → **1658** (1 baris duplikat dibuang); baseline WR 40,9% → **40,8%**; hipotesis lolos q<0,10: 8 → **9**.
2. **Temuan jam-12 BERTAHAN** setelah 40 baris tanpa entry-time dikeluarkan dari dimensi waktu: n=54/WR 18,5% → **n=49/WR 18,4%** (ΔWR −23,5%). Jadi R-A **bukan** artefak timestamp.
3. **R3B holdout**: n=436 → **437** (1 trade kontrol baru; track masih hidup). Verdict R-A/R-B/R-AB tetap **GAGAL**; R-B tetap **terbalik** (ΔWR −6,16 pp).
4. `median_pct` kini `None` bila `pnl_pct` memang tidak ada di track (aster/hyperliquid/spot_swing_v2) — tidak lagi dilaporkan sebagai 0,000.
5. **Kerangka target dikoreksi** (lihat audit §5): kebutuhan Sharpe tahunan untuk 0,8%/48j adalah **~0,57** (σ terukur 255,7%/tahun), bukan ~4,6; constraint sebenarnya = **konsistensi (median window −1,18% sementara mean +1,40%)**. Definisi metrik & target = wewenang user.

