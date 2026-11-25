# SODEX — HASIL PARALEL: F3 Rate-Check Interim + Bedah C3/E2Dir

**Tanggal:** 2026-10-09 · **Status:** READ-ONLY (tidak ada perubahan ambang/gate/live-flag).
**Pemicu:** approval Mas Anas 08-Okt — kerjakan paralel Prioritas 1 (F3 re-check) & 2 (bedah C3/E2Dir).
**Scope berlaku:** wallet SoDEX SAJA (keputusan 08-Okt).

---

## PRIORITAS 1 — F3 interim rate-check (jendela 92-simbol, 2,11 hari)

Dijalankan `scripts/sodex_rate_check.py` (`.venv-research/bin/python3`), deteksi cakupan-penuh otomatis.

```
jendela = 2026-10-06 22:00 .. 2026-10-09 00:36 UTC (2,11 hari) | simbol dinilai = 92
[1] funding lolos        =  238  (112,88/hari)
[2] + OBI tersedia       =  236  (111,93/hari)   <- cakupan OBI BERHASIL (99%)
[3] + OBI selaras (onset)=    1  (  0,47/hari)   <- penyumbat SEJATI
proyeksi 44 hari ke HARD_STOP 2026-11-20 = ~21 episode (butuh 100)
==> VERDICT LAJU: GAGAL (falsifier terpenuhi: 0,47 < 1,0/hari)
kontributor onset: CXMT-USD=1
```

### Baca hasil

1. **Tuas perluasan OBI 20→92 BEKERJA** — [2] naik ke 111,93/hari (99% dari funding lolos).
   Ini menutup hipotesis "penyumbat = cakupan" secara tuntas.
2. **Penyumbat sejati = konjungsi `|funding|≥0,003%` ∧ `|obi20|≥0,15`** — hanya **0,47 onset/hari**
   (1 onset dalam 2,11 hari). Konsisten dengan LAJU §7: P(|obi20|≥0,15 | event funding) ≈ 3,45%.
3. **Statistik:** peluang mengamati ≤1 onset dalam 2,11 hari bila laju sejati ≥2,3/hari =
   **≈4,6%** (Poisson, λt=4,85). Bukti awal sudah **menolak** target laju.
4. **Satu-satunya onset = CXMT-USD** — token sangat tipis (bukan penyumbang likuiditas utama),
   kemungkinan besar **non-tradeable**. Bahkan onset tunggal ini diragukan sah.

### Disiplin pra-registrasi

Falsifier resmi = "setelah 7 hari (≈14-Okt), bila [3] < 1,0/hari → GAGAL". Ini **baru 2,11 hari**,
jadi secara formal 14-Okt tetap jadi titik putus. **Tapi bukti awal sudah GAGAL** (0,47/hari jauh
di bawah 1,0), dan probabilitas pemulihan ke ≥2,3/hari ≈ 4,6%. Rekomendasi: **terima GAGAL sekarang,
biarkan 14-Okt sebagai konfirmasi formal — jangan tunggu dengan harapan palsu.**

---

## PRIORITAS 2 — Bedah C3 (E2Dir amplifier)

Baca `scripts/sodex_e2dir_amplifier.py` (270 baris, READ-ONLY scanner) + rujukan `sodex_twin_engine.py::generate_directional_signal`.

### Temuan: C3 BUKAN keluarga baru — ini rehash dua keluarga yang sudah ada

| Komponen C3 | Sumber | Status keluarga |
|---|---|---|
| **E2Dir** (funding + OBI arah) | `generate_directional_signal` L3355-3435 | = **F3** (sedang forward-test, kini GAGAL) |
| **Pre-Loser** (short 24h-change ≤ −1%) | `change_pct` overlay | = **momentum/loser** (difalsifikasi studi 3-segmen) |

`expected_edge_bps` pada scanner adalah **formula tangan** (`loser_bps + funding_bps×2 − spread −
cost`), bukan edge terukur. Ini **heuristik peringkat**, bukan sinyal teruji.

### Kesimpulan

- **E2Dir = funding + OBI = hipotesis F3**, sudah diuji ulang oleh F3 (protokol ketat) dan **F3
  kini GAGAL pada laju**. Tidak ada yang "belum diuji" pada inti E2Dir.
- **Overlay "loser"** = momentum 24-jam, keluarga yang **sudah difalsifikasi** (0 mesin valid,
  studi 3-segmen; audit §6: edge terbaik 0,02% vs target 0,4–0,8%).
- **C3 = kombinasi keluarga-gagal + keluarga-falsified.** Tidak ada kandidat pra-registrasi baru
  di sini.

---

## KESIMPULAN GABUNGAN (scope SoDEX SAJA)

Setelah P1 + P2:

| Thread SoDEX | Status final |
|---|---|
| F3 (funding-squeeze + OBI) | **GAGAL** — laju 0,47/hari, proyeksi ~21/100 episode |
| C3 (E2Dir amplifier) | **BUKAN keluarga baru** — rehash F3 + momentum-falsified |
| F1 (momentum forward) | TIDAK CUKUP (1,07/hari → ~47/150) |
| PRAREG-16 (MACD fade BULL) | n≈5–8 vs ambang 40 |
| S1 (SOL) | INCONCLUSIVE |

**Tidak ada lagi jalur sinyal SoDEX yang belum difalsifikasi atau belum diuji.** Kesimpulan jujur
yang tersisa, konsisten dengan audit proyek (AUDIT_BIAYA_AKUN §6): **belum ada edge yang terbukti
di SoDEX; target 0,8%/48 jam tidak terjangkau pada scope SoDEX-saja; penurunan target tidak
mengubah ini (gap 25–40×).**

Rekomendasi akhir: **hormati HARD_STOP 20-Nov-2026** sebagai gerbang final. Biarkan F1/F3/PRAREG-16/S1
berjalan ke titik putusnya (verdict formal), tetapi **jangan menurunkan target dan jangan
membangun mesin baru dari keluarga yang sudah difalsifikasi**.

— Hermes Anantara v3 — 2026-10-09
