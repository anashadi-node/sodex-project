# AMANDEMEN DEFINISI TARGET 0,8% — A DAN B (GRID TETAP 30 JAM)

**Tanggal keputusan:** 10-Okt-2026 · **Pengambil keputusan:** Mas Anas (user) · **Pelaksana:** Hermes Anantara v3
**Status:** BERLAKU sejak 10-Okt-2026 · **Sifat:** definisi pengukuran target (bukan perubahan target)

---

## 1. Keputusan

Target **0,8% dari TOTAL modal wallet per window** sekarang lolos **hanya jika DUA syarat lolos sekaligus**:

| Kode | Syarat | Rumus |
|---|---|---|
| **A** | Akumulasi (mean) | `mean window 30 jam ≥ 0,8%` |
| **B** | Konsistensi | `median window > 0` **DAN** `hit(window ≥ 0,8%) ≥ 50%` |

**Grid:** window **30 jam** pada **grid TETAP** dengan jangkar absolut **2026-08-03 00:00:00Z**.
**Window kosong:** **dilewati** (tidak dihitung 0,0%); jumlahnya dilaporkan sebagai `n_empty`.
**Syarat minimum:** `≥10` window berisi sebelum verdict boleh dihitung.

## 2. Alasan (berbasis pengukuran, bukan selera)

1. Pengukuran 10-Okt (`reports/sodex/AB_TARGET_2026-10-10.md`) menunjukkan **mean bisa lolos bersamaan dengan median gagal** — mean ditarik ekor kanan. Contoh TWOWAY train: mean **+3,398%**, median **+0,167%**, hit **44,4%**.
2. **Syarat B sangat sensitif pada grid**: pada data yang sama, B gagal di grid tetap 30 jam (median +0,167%) tetapi lolos di grid span (median +1,881%). Karena itu grid **wajib dipatok** agar verdict tidak bisa bergeser tanpa jejak.
3. Terdahulu (30-Sep-2026) median & hit sudah dijadikan gerbang; amandemen ini **memindahkan dasarnya ke grid tetap** dan menegaskan sifatnya **A DAN B**.

## 3. Yang TIDAK berubah

- Angka target tetap **0,8% per window** (harga mati) — bukan target baru.
- Wallet denominator tetap **TOTAL wallet divisi** (spot+perps) dari snapshot on-chain.
- Dua gate (**REAL-WIDE**, **TWO-WAY**) tetap **terpisah**; sampel tidak boleh digabung.

## 4. Perubahan implementasi

| Berkas | Perubahan |
|---|---|
| `scripts/sodex_maturation_tracker.py` | `window_metrics()` → grid TETAP (jangkar 2026-08-03Z), window kosong dilewati + `n_empty`; tambah `window_metrics_span()` sebagai pembanding (bukan verdict); gate jadi `window_mean>=0.8% (grid tetap)`, `window_median>0 (grid tetap)`, `window_hit>=50% (grid tetap)`, `window_A&B (grid tetap)` |
| `tests/test_sodex_maturation_window.py` | +6 tes: grid tetap (bukan span), window kosong dilewati & dihitung, trade sebelum jangkar diabaikan, jejak definisi lama, A&B wajib dua-duanya (mean lolos + median gagal → tidak lolos) |

## 5. Verifikasi

- `pytest tests/test_sodex_maturation_window.py` → **19 passed**.
- Tracker dijalankan 10-Okt (04:15Z): REAL-WIDE `mean +1,157% · median −0,296% · hit 11/27` → **A lolos, B gagal → NO-GO**; TWO-WAY `mean +1,411% · median −0,321% · hit 25/52` → **A lolos, B gagal → NO-GO**.

## 6. Catatan jujur (batas definisi ini)

1. Window pertama/terakhir bisa **parsial** (terpotong tepi data) dan dihitung apa adanya.
2. Trade dengan exit **sebelum jangkar** (2026-08-03Z) tidak masuk grid — untuk data sekarang tidak ada (semua track mulai setelah 31-Jul).
3. Metrik window mengasumsikan window saling bebas; autokorelasi membuat rentang keyakinan agak optimistis.
4. Definisi ini **mempersulit** lolos (A DAN B), dan itu disengaja: mencegah verdict GO karena mean yang ditopang outlier.

*Amandemen · Hermes Anantara v3 · 10-Okt-2026 · hash tercatat di `docs/sodex/AMANDEMEN_TARGET_AB_2026-10-10.md.sha256`*
