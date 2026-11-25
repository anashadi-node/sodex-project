# SODEX Twin Engine — Audit Read-Only 3-Subagen (Sintesis) — 06-Okt-2026

**Scope:** `anantara/sodex_twin_engine.py` (5262 baris), READ-ONLY, tidak ada file diubah.
**Status mesin saat audit:** `anantara-sodex-twin-watchdog.service` **INACTIVE**, tidak ada proses jalan (dikonfirmasi langsung). **Tidak ada jalur uang nyata aktif saat ini.** Semua flag live default aman: `TE_E2_ENABLED=0, TE_E2_DIR_ENABLED=0, TE_E2_MOM_ENABLED=0, TE_E2_DIR_LIVE=0, TE_E2_MOM_LIVE=0`.

## KRITIS — TERBUKTI (perbaikan wajib sebelum live mana pun, butuh approval sebelum edit)

| # | Lokasi | Temuan | Mitigasi saat ini |
|---|---|---|---|
| **K1** | `_maker_leg` L3226/3245 | **Stop-loss arah TERTUKAR**: `buy` memicu SL saat harga NAIK, `sell` memicu SL saat harga TURUN — kebalikan total dari fungsi SL | Tidak ada mitigasi runtime; hanya aman karena E2 churn disabled |
| **K2** | `churn_cycle` L3298-3319 | Partial-fill leg2 diperlakukan sebagai close sukses → `e2_clear_open()` hapus record, posisi residual di exchange hilang dari crash-recovery | Tidak ada mitigasi runtime |
| **K3** | `edge_ok()` L3829-3836, dipanggil L3872 | Fail-open eksplisit: n<30 sampel → `return True` ("boleh trading") — DB kosong/baru dianggap edge terbukti | `TE_E2_DIR_ENABLED=0` saat ini |
| **K4** | `_manage_position` L4031-4053, entry L3944-3945 | Exit E2Dir LIVE **tidak kirim order close** ke exchange — SL/TP/timeout dihitung dari mid lokal, hanya `ledger.e2_dir_close()`; posisi exchange tetap terbuka, budget gate baca ledger yang under-report rugi | `TE_E2_DIR_LIVE=0` saat ini (FORCE PAPER) |

## SEDANG — perlu rencana perbaikan, tidak darurat

- **S1** `poll_fill` cache reset (L2002-2007, 2862/2898, 4412-4420): oid asing di cache → `order.filled` di-reset paksa; exception mid-step tertangkap tanpa `try/finally` → cache stale; bisa memicu cancel atas posisi yang sebenarnya terisi (DUGAAN dampak, mutasi TERBUKTI).
- **S2** `check_equity` fail-skip (L2076-2078, 4460-4461): `account_equity()` gagal → `return` tanpa evaluasi drawdown/daily-loss, tanpa alert. Diakui desain di komentar kode (B13) — tapi secara disiplin fail-closed, ini fail-open.
- **S3** Konfirmasi live dekoratif (L5237-5243 + `watchdog_twin.sh:208,338` + `start_twin_live.sh:22`): docstring janji 3-kunci (`--live`+`CONFIRM_LIVE`+frasa ketik manual), tapi non-tty skip frasa DAN watchdog export `CONFIRM_LIVE=YES` permanen → di deployment nyata cuma 1 kunci efektif, tak pernah interaktif.
- **S4** `flush-pair --yes` CLI (L4964-5018, dispatch L5227-5228 vs flock L5249): lewati CONFIRM_LIVE, lewati frasa, **di luar lock singleton** — bisa jalan bersamaan dengan daemon quoting pair sama (risiko self-trading).
- **S5** Shutdown cancel-all (L4534-4549): `except Exception: pass` per-order, lalu Telegram klaim "semua order dibatalkan" tanpa syarat — order GTC bisa tetap hidup tanpa daemon menjaga.
- **S6** `RedactFilter` (L476-489): hanya censor `SODEX_API_KEY/API_SECRET/TELEGRAM_BOT_TOKEN` — **`SODEX_PRIVATE_KEY` tidak tercakup**, risiko bocor ke log via exception (belum ada bukti kejadian nyata).
- **S7** `watchdog_twin.sh:338` `set -a; source .env`: ekspor SEMUA var .env (termasuk secret) ke setiap child/restart — memperluas permukaan bocor.
- **S8** Fitur Pre-Gain mati separuh (L3641-3683, 4447-4451): sinyal di-queue dan Telegram lapor "N SHORT signals queued" tapi konsumen **tidak pernah dipanggil** — sinyal kedaluwarsa diam-diam, menyesatkan evaluasi strategi BEAR.
- **S9** `generate_directional_signal`/`generate_momentum_signal` (L3392-3419, 3509-3519) — proxy OBI `(a_dist-b_dist)/(a_dist+b_dist)` **secara aljabar selalu ≈0** jika `mid=(bid+ask)/2` (DUGAAN, perlu cek `Book.mid`) → jika benar, konfirmasi OBI E2Dir **tidak pernah aktif**, sinyal live cuma digerakkan funding saja. *(Konsisten dengan keputusan F3 pra-registrasi memakai OBI20 nyata, bukan proxy ini.)*
- **S10** Jalur hedge/churn live (`Engine1._rebalance_hedge`, `Engine2Perps.churn_cycle/_maker_leg`) tidak panggil `Guards.check_equity()`, hanya `Treasury.authorize()` (budget, bukan drawdown).
- **S11** Divergensi default modal: `TE_CAPITAL_USD` default kode 60 vs `start_twin_live.sh` fallback 94 — cap risiko beda 1,5× tergantung jalur start.
- **S12** `name=place_post_only` tapi order dikirim `--tif gtc` ("GTX tidak didukung") — bisa cross-spread jadi taker, bukan maker, meski sudah terdokumentasi sendiri.
- Cancel-path spot rapuh (cl_ord_id sintetis tak match; substring-match symbol tanpa verifikasi); leverage gagal-set tapi order tetap jalan; potensi `ZeroDivisionError` di `_maker_leg` aggressive mode tanpa guard `entry_px<=0`.

## RENDAH

Dead code `_get_trend()`; duplikasi logic reversion/continuation; `subprocess shell=True grep .env` berisiko salah-parse (bukan kebocoran nilai — TERBUKTI nilai tak pernah ter-log); komentar `_poll_all_orders()` merujuk fungsi yang tak ada; cadence komentar "~15 menit" vs hitungan aktual ~2,8 menit; state momentum paper in-memory (hilang saat restart, bukan risiko uang); `ps aux | grep` deteksi proses rapuh terhadap kebetulan string.

## Falsifikasi positif (hipotesis AWAL yang GUGUR — dicatat demi kejujuran)

- "SAFETY_HALT marker write-only / fail-open" **GUGUR**: marker DIBACA oleh `watchdog_twin.sh`, `sodex_safety_guardian.py`, `sodex_deadman_switch.py` — gating lintas-proses, bukan dalam file ini saja. Desain cross-process, bukan bug.
- Tidak ditemukan: salah satuan fee/bp dalam rentang 3600-akhir; look-ahead bias dalam rentang tersebut; file I/O non-atomik langsung dalam rentang 1800-3600; kredensial literal ter-log; flag "LIVE=True by default" eksplisit di mana pun.
- Rate-limit restart (5/jam + cooldown 300s), cek HALT file sebelum restart, dan cleanup orphan order saat startup — semua TERBUKTI berfungsi sesuai desain.

## Rekomendasi prioritas (menunggu approval — ini file jalur eksekusi, Pre-Deploy Review wajib)

1. **K1 (SL tertukar)** dan **K2 (partial-fill leg2)** — perbaiki duluan, keduanya hanya 1-5 baris per fix, risiko regresi kecil, dampak besar jika E2 churn pernah di-live-kan lagi.
2. **K3/K4** — sudah termitigasi oleh flag, tapi harus diperbaiki SEBELUM `TE_E2_DIR_ENABLED`/`TE_E2_DIR_LIVE` pernah diset 1 (gate wajib, bukan opsional).
3. **S9** verifikasi `Book.mid` — jika terkonfirmasi OBI selalu ≈0, ini menjelaskan sebagian kelemahan riset Juni (E2Dir 63,3% WR itu funding-only, bukan funding+OBI seperti diklaim desain) → relevan langsung untuk F3.
4. S2, S6, S7, S3, S4 — perbaikan keamanan proses, tidak urgent (engine tidak jalan), tapi wajib sebelum restart produksi berikutnya.

**Tidak ada file produksi diubah dalam audit ini.** Semua temuan di atas = status quo terdokumentasi, menunggu keputusan Anda.
