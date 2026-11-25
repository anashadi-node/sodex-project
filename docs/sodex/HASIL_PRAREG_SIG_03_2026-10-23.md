# HASIL PRAREG-SIG-03 — Cross-Sectional Momentum 1–7 Hari

**Tanggal eksekusi:** 2026-10-23
**Pra-registrasi:** `docs/sodex/PRAREG_SIG_03_2026-10-23.md` (sha256 `6139fee7…1ac9a`, dibekukan sebelum run)
**Skrip:** `scripts/sodex_sig03_xsec_momentum.py`
**Data:** `data/binance_klines/1d`, cutoff 2026-10-07, 245 simbol, 2.587 hari
**Segmen dinilai:** OOS 2024-01-01 → 2026-10-07, **n = 1.011 hari**

---

## VERDICT: **DITOLAK**

Satu kriteria gagal (K2). Sesuai pra-registrasi: **gagal satu kriteria = keluarga momentum cross-sectional ditutup**, tidak ada uji ulang dengan L/H lain.

| # | Kriteria | Ambang | Hasil | Status |
|---|---|---|---|---|
| K1 | Mean net OOS | > 0 dan ≥ 9,57 bps/hari | **12,18 bps/hari** (gross 14,37 − biaya 2,19) | PASS |
| K2 | t HAC (NW lag 7) | ≥ 2,5 | **2,416** | **FAIL** |
| K3 | CI95 bootstrap blok | lower > 0 | **[+1,08, +23,98]** bps/hari | PASS |
| K4 | Kontrol acak p95 | strategi > p95 | 12,18 vs **2,95** (mean acak −0,06) | PASS |
| K5 | Alpha vs long-only universe | > 0 | **+12,19 bps/hari**, beta −0,001 | PASS |
| K6 | Kontrol delay +1 hari | ≈ 0 | 12,01 bps (t 2,33) | CATATAN |
| K7 | Konsistensi tahunan | ≥ 2 dari 3 positif | 2024 +0,36 / 2025 +3,94 / 2026 +38,38 | PASS |

**Enam dari tujuh lolos. Yang gagal adalah kriteria inferensi — dan itu yang menentukan.**

---

## Mengapa t = 2,416 tidak boleh dibulatkan jadi "lulus"

1. **Ambang 2,5 sudah ditetapkan sebelum run.** Menurunkannya setelah melihat hasil = p-hacking.
2. **Uji non-overlapping (n=145 minggu) memberi t = 2,005** — lebih lemah, bukan lebih kuat.
3. **34 bulan OOS, 14 bulan negatif.** Mean positif ditopang segelintir bulan: Agu 2026 +118,7; Sep 2025 +70,6; Jul 2026 +56,1 bps/hari.
4. **Tidak stasioner:** 2024 hanya +0,36 bps/hari, 2026 +38,38 bps/hari. Performa 2026 = 100× 2024. Edge model seperti ini tidak bisa diandalkan untuk alokasi modal.
5. **Survivorship bias:** dataset berisi **0 dari 245 simbol yang delisted** — hanya simbol yang masih hidup hari ini. Artinya hasil di atas sudah **optimistis secara struktural**; edge yang sudah gagal di data yang bias naik tidak layak dicari pembelaan.
6. **Kontrol delay nyaris identik** (12,01 vs 12,18 bps) → bukan timing presisi, melainkan drift lambat yang kebetulan menguntungkan periode 2025–2026.

---

## Sensitivitas biaya (bukan bagian kriteria, untuk gambaran)

| Biaya taker RT/leg | Mean net |
|---|---|
| 10 bps (asumsi pra-reg) | 12,18 bps/hari |
| 15 bps | 11,09 bps/hari |
| 20 bps | 9,99 bps/hari |
| 30 bps | 7,80 bps/hari |

Bahkan pada biaya 3× asumsi, gross tetap positif — masalahnya bukan biaya, tapi **keyakinan statistik dan stabilitas antar-periode**.

---

## Konsekuensi (sesuai §9 pra-registrasi)

- Keluarga **momentum cross-sectional 1–7 hari DITUTUP**.
- Tidak ada uji ulang dengan L/H berbeda, tidak ada sub-sampel baru, tidak ada "coba 14 hari".
- Tidak ada alokasi modal. Tidak ada perubahan kode produksi/daemon — nol order, nol modal.
- Verdict SoDEX **25 November 2026** berjalan **tanpa arah riset terbuka**. Give-up 30 November 2026.
- Satu-satunya pekerjaan SoDEX yang tersisa sampai verdict: kolektor L2 (biaya nol, bukti passivity) dan pemantauan buku.

## Catatan metodologis untuk uji berikutnya

Jika suatu saat ada PRAREG baru di keluarga mana pun, dua hal ini wajib masuk desain:
1. **Universe point-in-time** termasuk simbol yang delisted (dataset sekarang tidak memuatnya) — tanpa ini, setiap hasil long/short otomatis bias naik.
2. **Ambang t ditetapkan per horizon**, bukan diwarisi; n efektif setelah autokorelasi harus dihitung sebelum run, bukan sesudah.

---

**Kesimpulan satu baris:** cross-sectional momentum mingguan adalah kandidat terbaik yang tersisa, dan ia gagal pada kriteria keyakinan yang sudah ditetapkan sebelum data disentuh — karena itu keputusannya berhenti, bukan diperpanjang.
