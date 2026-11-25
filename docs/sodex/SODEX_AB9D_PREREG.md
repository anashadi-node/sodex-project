# PRA-REGISTRASI A/B 9 — Gate Makro BTC (ON vs OFF)

**Tanggal beku:** 2026-11-12 (sebelum ada satu pun trade tertutup di arm mana pun)
**Status:** mengikat. Angka/aturan di dokumen ini tidak boleh diubah setelah data masuk.
**Alat baca:** `scripts/research/ab9_readout.py` (dedup + bootstrap CI95, seed 20261112)

## 1. Pertanyaan yang diuji

Apakah **gate makro BTC** (`TW_REGIME_GATE=1`: hanya entry bila rezim BTC mengizinkan)
menaikkan atau menurunkan **expected return per trade** di lane paper TWO-WAY?

Konteks masalah: 122 jam tanpa satu trade. Funnel membuktikan gate BTC memblokir 100%
sinyal (bukan karena tidak ada sinyal sama sekali). Tanpa uji A/B, keputusan
"gate itu bagus" hanya kepercayaan, bukan bukti.

## 2. Arm (definisi beku)

| Arm | Gate BTC | Sinyal | Geometri | Peran |
|---|---|---|---|---|
| 9a | ON | dibalik (`TW_INVERT_SIGNAL=1`) | TP 1,5% / SL 6% / time-stop 24 j | pembanding utama (gate ON) |
| 9b | ON | dibalik | TP 1,5% / SL 6% / 24 j | replikasi gate ON |
| 9c | ON | dibalik | TP 1,5% / SL 6% / 24 j | replikasi gate ON |
| 9d | **OFF** | dibalik | TP 1,5% / SL 6% / 24 j | perlakuan (gate OFF), `PAPER_RELAXED=1` |

Satu-satunya variabel yang sengaja berbeda antara 9a dan 9d: **gate BTC**.
9d memakai state/log/funnel terpisah total (`paper_test_twoway_ab9d_*`).

## 3. Metrik (satu metrik utama, sisanya pendukung)

- **Utama:** mean `pnl_pct` per trade tertutup (net, sudah dipotong biaya) =
  expected return per trade. Satuan persen.
- Pendukung: median, winrate, jumlah USD, rata-rata jam tahan, sebaran per pair.
- Dipisah per **track**: `RANDOM` (kontrol acak, tidak dipengaruhi gate sinyal) dan
  `SIGNAL` (dipengaruhi gate). Perbandingan utama memakai `ALL`; `RANDOM` dipakai
  sebagai kontrol falsifikasi: kalau gate tidak menyentuh track RANDOM (memang
  tidak menyentuh entry acak selain lewat `skip_random_btc_gate`), selisih di
  track RANDOM harus ≈ 0. Selisih besar di RANDOM = ada variabel pengganggu.

## 4. Aturan keputusan (beku)

1. **n minimal 20 trade tertutup per arm per bandingan.** Di bawah itu →
   `INSUFFICIENT`, dan **tidak ada klaim apa pun** yang boleh ditulis, termasuk
   "trennya terlihat bagus".
2. Uji: bootstrap persentil 10.000 resample dari selisih mean (9d − 9a).
3. **CI95 tidak memuat 0 → EFEK NYATA.** Tanda menentukan arah:
   - CI95 seluruhnya > 0 → gate OFF (9d) lebih baik → usul ke Owner: buka gate.
   - CI95 seluruhnya < 0 → gate ON (9a) lebih baik → gate dipertahankan; 9d dimatikan.
4. **CI95 memuat 0 → TIDAK TERBUKTI.** Tulis apa adanya; jangan mengubah gate,
   jangan menambah arm baru untuk "mengejar" hasil.
5. Dedup wajib berdasarkan `id` trade sebelum menghitung (jejak duplikat pernah
   membuat false positive 58% vs 5%).
6. Ukuran efek harus juga dibandingkan dengan **biaya** (fee+slip) dan dengan
   target 0,7% per window. Signifikan secara statistik ≠ cukup untuk target.

## 5. Kapan berhenti

- Baca antara: 2026-11-19 (n belum cukup → lanjut).
- Baca final: **2026-11-29** (H-2 sebelum target live 2026-12-01), atau lebih awal
  bila tiap arm sudah ≥ 20 trade tertutup.
- Bila sampai 2026-11-29 salah satu arm tetap < 20 trade, kesimpulan yang
  dilaporkan adalah **"belum cukup data"** — bukan kesimpulan arah.

## 6. Yang TIDAK boleh dilakukan selama eksperimen

- Mengubah TP/SL/time-stop/leverage/ukuran posisi arm mana pun.
- Menambah atau menghapus pair universe.
- Restart arm hanya untuk "menyegarkan" hasil (restart tidak mereset statistik,
  tetapi memutus trade yang sedang terbuka bila state hilang — dilarang).
- Mencampur data arm dengan lane lain (ab9 lama, 4 lane shadow, dst).
