# AMANDEMEN PRAREG-31 #1 — KONVENSI WINDOW KOSONG

**Tanggal:** 2026-10-25 ±15:45 WIB — **SEBELUM window forward pertama** (2026-10-26T00:00Z)
**Mengubah:** §3 dokumen beku `PRAREG31_GATE_VOLATILITAS.md` (sha256 `525227e7…`, tetap disimpan apa adanya)
**Sifat:** koreksi konvensi perhitungan. Tidak menyentuh ambang, kriteria A–E, buku, periode, atau stop rule.

---

## 1. Yang dikoreksi

Teks beku §3 menulis:

> Window tanpa trade = 0,0% (tidak dilewati) — konsisten dengan `AMANDEMEN_TARGET_AB_2026-10-10.md`

Itu **salah kutip**. `AMANDEMEN_TARGET_AB_2026-10-10.md` §"Window kosong" menetapkan:

> **Window kosong: dilewati** (tidak dihitung 0,0%); jumlahnya dilaporkan sebagai `n_empty`.

## 2. Aturan yang berlaku (mulai sekarang)

| Jenis window forward | Perlakuan |
|---|---|
| Ada trade, gate ON | dihitung (masuk M1–M7) |
| Ada trade, gate OFF | dihitung untuk pembanding & permutasi |
| **Tanpa trade, data tidak stale** | **DILEWATI**, dicatat `n_empty` |
| Data stale > 6 jam (berapa pun trade-nya) | FLAT **0,0% dan DIHITUNG** (proteksi fail-closed data mati — tidak berubah) |

`n_empty` dilaporkan setiap evaluasi. Kriteria A–E, ambang median-12, buku 3 mesin, periode forward, minimum 12 window, stop rule: **tidak berubah**.

## 3. Mengapa amandemen ini sah (tiga syarat)

1. **Belum ada satu pun window forward** — forward baru mulai 2026-10-26T00:00Z. Tidak ada data yang bisa "dipilih".
2. **Tidak ada hasil yang berubah**: seluruh angka in-sample di dokumen beku (tabel §1) sudah dihitung dengan konvensi skip-empty (bucket window hanya dibuat bila ada trade) — teks §3 yang salah itu tidak pernah dipakai dalam perhitungan.
3. **Bukan snooping untuk memperbaiki hasil**: efek koreksi ini justru **memperburuk** gambaran gate. Window ON pasca-flip: mean berubah dari −1,51% (n=11, dengan 3 window kosong dihitung 0,0%) menjadi **−2,07% (n=8)**. Saya mengamandemen melawan kepentingan hipotesis sendiri. Kontrol permutasi M5 memakai himpunan window yang sama, sehingga perbandingan gate vs acak tetap adil.

## 4. Implementasi

- Evaluator: `scripts/research/prereg31_gate_eval.py` — field `empty` per window, `n_empty` di status, window kosong dikeluarkan dari `usable`.
- Test baru: `tests/test_prereg31_gate.py::test_window_kosong_dilewati_amanemen`.
- Registri: baris amandemen di-append ke `reports/sodex/PRAREG31_REGISTRY.jsonl` (hash asli + hash amandemen).

## 5. Hash amandemen

Dihitung pada saat penyimpanan file ini: lihat `AMANDEMEN_PRAREG31_KONVENSI_WINDOW.md.sha256`.

## 6. Catatan implementasi (bagian dari amandemen ini)

- M4 (uji-t berpasangan) diimplementasikan sebagai: portofolio-gate vs portofolio-tanpa-gate
  per window — window ON selisih 0 (posisi sama), window OFF selisih `−pct` (gate tidak
  berposisi). Implementasi awal memakai selisih dua nilai identik per window (selalu 0,
  vacuous) — dikoreksi sebelum window forward pertama.
- Diagnostik prapendafuan yang dicatat demi transparansi (bukan bagian kriteria):
  korelasi vol7–gross mingguan **per era** ternyata lemah/negatif (pra-flip r = −0,41,
  pasca-flip r = −0,15; n 8/5) meski pooled +0,59 — pola Simpson. Motivasi mekanistik gate
  karenanya lebih lemah dari tertulis di dokumen beku; uji tetap berjalan karena sudah
  dibekukan dan hasil forward, bukan korelasi, yang memutuskan.

---
*AMANDEMEN PRAREG-31 #1 — 2026-10-25. Setelah 2026-10-26T00:00Z amandemen lain pada aturan buku/kriteria DILARANG.*
