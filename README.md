# SoDEX — swing-trading perps (venue: sodex.com)

Ekstraksi **hanya-SoDEX** dari monorepo Anantara Sakti: kode eksekusi/guard, paper arena, riset, dokumen, unit systemd, dan test.
Bukan produk jadi. Status jujur ada di bagian "Status" — **NO-GO untuk live** sampai gerbang bukti terpenuhi.

## North Star (harga mati)
Profit **≥ 0,8 % dari TOTAL modal wallet (spot + perps)** per window 1–30 jam, **kumulatif** (bukan per-trade). Definisi dikunci di
`docs/sodex/` (KANON, AMANDEMEN_3, KEPUTUSAN_TARGET). Dokumen lama yang masih menulis 0,7 % / 0,40 % = riwayat, bukan target aktif.

## Status (per 2026-11-25, dari output tool yang dijalankan hari itu)
| Item | Hasil terukur |
|---|---|
| Preflight live | **9/12 — BELUM_SIAP**; blocker: `secret_env` (kredensial venue tidak ada), `reconcile` (watchdog CRITICAL, 2 posisi tak terekonsiliasi), `promo_gate` (`DATA_KURANG`, n_hari=20 < 30) |
| Edge lintas lane paper (audit ulang 2026-11-25 05:33 UTC) | **0 kandidat edge**. 13 lane memiliki n ≥ 20; 5 lane `DATA_KURANG` (n<20). Mean tertinggi +0,223 %/posisi, CI95 [−0,37 ; +0,77], q(BH)=1,000. Return per posisi, bukan total-wallet/window. |
| Alpha vs kontrol RANDOM (2026-11-25 16:30 UTC) | **0 lane dengan alpha terbukti.** Delta SIGNAL−RANDOM per lane: −0,55 … +0,31 pp; semua CI95 delta memuat nol; p ≥ 0,05. Artinya mean positif pada lane mana pun (bila ada) dijelaskan oleh arah/rezim, bukan oleh sinyal. |
| Sumber rugi terukur | RR lane A/B 9a–9e = **0,25** (TP 1,5 % / SL 6,0 %) → WR impas **80,0 %** vs WR nyata **68,9 %**. Biaya round-trip terkalibrasi **≈15,7 bps** = 10 % dari jarak TP. Lihat `reports/sodex/RESEARCH_GEOMETRI_EXIT_BETA_2026-11-25.md`. |
| Kontrol A/B | semua negatif / belum signifikan (n kecil) |
| Test | pohon publik (setelah sanitasi): **1.359 passed / 45 skipped** (4 skip butuh `data/binance_klines`, tidak dibundel); monorepo: 1.552 passed / 36 skipped |
| Scan secret | gitleaks 8.28.0 pada pohon publik **dan riwayat commit**: `no leaks found`; 81 false-positive awal di-ignore per-baris (`.gitleaksignore`); kontrol positif mendeteksi 5/5 token uji, termasuk di path yang sama → tidak buta |
| Lisensi | **tanpa LICENSE** = hak cipta penuh. Publik boleh melihat/mengunduh; tidak ada izin memodifikasi atau mendistribusikan ulang. |
| Order live / `LIVE_ARMED` / `dry_run` | tidak pernah disentuh oleh pekerjaan ini |

Artinya: infrastruktur makin aman (monitor fail-closed, gate tak bisa hijau palsu), tetapi **tidak ada bukti edge** yang mendekati 0,8 %. Menaikkan sizing/leverage
pada lane bermean ≤ 0 hanya memperbesar rugi. Jangan arm live tanpa bukti + keputusan eksplisit Owner.

## Tata letak
| Path | Isi |
|---|---|
| `anantara/sodex_*.py`, `perps_volume_engine.py` | governor (safety-critical), signal, twin engine, farming, intel, autofarm |
| `scripts/sodex_*.py` | preflight, watchdog, promotion gate, reconcile, collector, analisis |
| `scripts/sodex_fleet_edge_audit.py` | audit edge lintas lane (bootstrap CI95, BH, dedup, epoch) — read-only |
| `scripts/research/mode_a_20261026/` | riset Mode A (spot-leverage), shadow37, forward36 |
| `systemd/` | unit service/timer lane paper + monitor |
| `tests/` | regresi + kontrol negatif |
| `docs/sodex/`, `docs/SODEX_*.md` | KANON, runbook go-live, pra-registrasi, audit, kompendium A–Z (HTML) |
| `reports/sodex/` | ledger/riset terbit (bukan state runtime) |
| `data/` | runtime (diabaikan git) — lihat `data/sodex_data_README.md` |

## Menjalankan test
```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
make test            # pytest tests/
make selfcheck       # governor --selfcheck
make edge-audit      # audit edge lintas lane (butuh data/paper_test*_state.json)
```
Catatan: unset `PYTHONPATH` bila shell host mengisinya. Beberapa test membaca `anantara/anantara_daemon.py` **secara tekstual**; file itu dibawa apa adanya dan
**tidak dapat dijalankan mandiri** (mengimpor modul divisi lain di monorepo). Jalur tanda-tangan live (`eth_account`, `msgpack`) tidak diuji di sini (skip).

## Aturan keselamatan (tidak bisa di-override)
1. Tidak ada kredensial di repo. `secrets/`, `.env*`, kunci → `.gitignore`; hanya `*.template` yang boleh.
2. Governor expectancy = safety-critical; ubah hanya dengan data (n ≥ 20, p < 0,05, BH-corrected).
3. `dry_run`, `LIVE_ARMED`, target, SL/TP/leverage/sizing hanya berubah dengan approval eksplisit Owner + backtest.
4. `shuffle: false` pada time-series. Dilarang menghapus posisi/state saat ada posisi terbuka.
5. `DATA_KURANG`, status hilang/stale, akun tidak cocok, endpoint rekonsiliasi tidak lengkap → **fail-closed**.

## Publikasi & placeholder (repo ini versi publik)
Repo ini dipublikasikan **hanya-baca untuk publik** (tanpa kolaborator; branch `main` diproteksi). Sebelum publikasi, pohon disanitasi:

| Perlakuan | Keterangan |
|---|---|
| Alamat wallet | Diganti pseudonim `0x` + HMAC-SHA256 satu arah dengan kunci acak sekali-pakai (tidak disimpan) → tidak bisa dibalik. Alamat nol (`0x000…000`) dipertahankan. |
| Path rumah | `/home/<user>` → `/home/USER`. **Ganti dulu** sebelum menjalankan `systemd/*.service` atau skrip yang memakai path absolut. |
| ID chat/telegram | `<REDACTED>`. |
| Dikeluarkan dari repo publik | `reports/sodex/sodex_wallet_forensic_7d_*` (json+md), `docs/SODEX_17W_TRADING_AUDIT.html`, `scripts/gen_sodex_audit_html.py`, `reports/sodex/sodex_forward_reeval_loop.jsonl` — memuat alamat wallet pihak lain, ukuran akun, dan/atau path lokal. |

Kode yang dipertahankan tetap utuh secara fungsional: test suite dijalankan ulang **setelah** sanitasi.

## Asal repo
Dibangun dari working tree monorepo (commit induk `eed95d8` + perubahan lokal belum-commit) dengan allowlist + closure import; **riwayat git induk tidak dibawa**
(riwayat monorepo pernah memuat kredensial; repo ini mulai dari satu commit bersih yang telah di-scan).
