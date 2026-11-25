# R2D — BATAS ATAS TUAS BIAYA: ditutup secara aritmetika

**Tanggal:** 10-Okt-2026 · **Sifat:** read-only, tanpa order
**Runner:** `scripts/research/r2d_batas_biaya.py` · Data: `reports/sodex/R2D_BATAS_BIAYA_2026-10-10.json`

## Pertanyaan

Arah "serang biaya" (`ARAH_BARU_BIAYA_DAN_CAPTURE_2026-10-09.md` §4.1, §5 langkah 2): kalau biaya turun ke maker/queued-fill, apakah track bisa lolos gate? Sebelum mengukur fill-rate (yang butuh recorder L2 — dan recorder kita berhenti 2-Agu), ukur dulu **ukuran hadiahnya**: berapa gain maksimum yang mungkin dari SEMUA biaya? Jika biaya dihapus 100% pun median tidak > 0, tidak ada konfigurasi fill yang bisa menyelamatkannya.

## Metode

Metrik gate resmi direplikasi persis (`scripts/sodex_maturation_tracker.py`): window 30 jam, akumulasi `pnl_usd` / wallet $242,79, median & hit (≥0,8%). Seleksi gate persis: REAL-WIDE cutover 2026-09-05 02:20Z + exclude {SUI,ADA,HYPE,ONDO}; TWO-WAY seluruh riwayat.
Skenario: **A** as-recorded (net) · **B** SEMUA biaya dihapus (fee 2,4 bps RT + slip SL 5 bps) = batas maksimum matematis · **D** biaya 2× (stress).

## Hasil

| Track | n | Window | A: as-recorded | **B: biaya DIHAPUS** | D: biaya 2× |
|---|---|---|---|---|---|
| **TWO-WAY** | 422 | 50 | median **−1,771%** · hit 40,0% | median **−1,576%** · hit 42,0% | median −1,966% · hit 40,0% |
| **REAL-WIDE** | 187 | 27 | median **−0,418%** · hit 33,3% | median **−0,279%** · hit 33,3% | median −0,539% · hit 33,3% |

Biaya terukur: TWO-WAY median **5,9 bps/trade** (mean 7,4), total $30,38 fee + $27,15 slip = **$57,53 = 23,7% wallet** over 63 hari. REAL-WIDE median 4,4 bps/trade, $13,46 + $18,45.

**Prize maksimum dari seluruh lever biaya:** TWO-WAY **+0,195 pp** per window (dari −1,771% ke −1,576%). REAL-WIDE **+0,139 pp** (dari −0,418% ke −0,279%). Memori: sinyal-only REAL-WIDE bahkan tepat 0,000% di skenario B, hit tetap 32%.

## Verdict: TUAS BIAYA TERTUTUP

Aritmetika sederhana memutuskan: **menghapus 100% biaya (mustahil) hanya menutup 12% dari jarak ke median 0** (0,195 dari ~1,58 pp untuk TWO-WAY; 0,139 dari ~0,42 pp REAL-WIDE). Tidak ada konfigurasi fee, maker-fill, atau queue yang bisa menutup 88% sisanya — karena hadiahnya dibatasi keras oleh 100% biaya itu sendiri. Hit-rate juga tidak bergerak signifikan (40% → 42%).

**Konsekuensi: pengukuran fill-rate maker TIDAK PERLU dilakukan.** Recorder L2 berhenti 2-Agu 23:08Z (`sodex_book_recorder.db`, 83 simbol, 24 jam saja) dan tanpa itu fill-rate tak bisa diukur forward — tapi kini terbukti tidak relevan: bahkan dunia hipotetis tanpa biaya sama sekali tidak meloloskan gate.

## Yang sebenarnya menjadi constraint

- Median window negatif sementara mean positif besar (TWO-WAY mean **+1,467%**, median **−1,771%**; total +73,4%) → **distribusi lotere**: sebagian kecil window membawa seluruh profit; mayoritas window rugi. Biaya uniform $0,474/window tidak akan pernah mengubah bentuk itu.
- Ini konsisten dengan temuan sebelumnya: D11 (33 trade = 336% profit — membuang ekor → −117%), R2C (mean capture +1R negatif di semua dataset), dan dokumen arah §3.4 ("2 mesin lolos MEAN tapi median ≤ 0 = lotere").
- Jadi urutan lever yang tersisa: ~~capture exit~~ (R2B/R2C: mati) → ~~biaya/venue~~ (R2D: mati, hadiah 12% dari kebutuhan) → **bentuk/varians distribusi** (satu-satunya keluarga lever yang belum diuji dan secara aritmetika masih mungkin mengubah median).

## Lampiran

- Angka A TWO-WAY (median −1,771%, hit 40,0%) **cocok persis** dengan `data/sodex_maturation_status.json` (median −1,77%, hit 40,0%) → replikasi metrik resmi terverifikasi.
- Komposisi arm dilaporkan apa adanya: TWO-WAY {NONE 353, SIGNAL 37, RANDOM 32}, REAL-WIDE {NONE 144, SIGNAL 25, RANDOM 18}. Skenario B pada subset signal-only tidak mengubah kesimpulan (REAL-WIDE 0,000%, hit 32%).
- Batas: slip SL 5 bps & fee 2,4 bps diambil dari model sim (nilai pasti per-leg tidak konsisten antar sumber — dicatat di dokumen arah §koreksi 2); walau angka biaya berbeda 2×, arah kesimpulan tidak berubah (skenario D tetap negatif lebih dalam).

*Laporan · Hermes Anantara v3 · 10-Okt-2026*
