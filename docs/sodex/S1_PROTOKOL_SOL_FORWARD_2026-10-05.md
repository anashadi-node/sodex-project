# S1 — PRA-REGISTRASI UJI FORWARD SOL (dibekukan sebelum evaluasi)

**Tanggal beku**: 05 Oktober 2026
**Status**: DIBEKUKAN — ambang di bawah TIDAK BOLEH diubah setelah hasil keluar.
**Sumber ambang**: D13 baris S1 (`reports/sodex/D13_KOREKSI_D12_DAN_R1_R3_2026-10-05.md` L359).
**Mode**: READ-ONLY, paper lane. Tidak ada uang nyata, tidak ada perubahan gate/leverage/sizing.

---

## 1. Hipotesis

**H1**: Sinyal entry SOL pada lane-lane yang tercatat di bawah memiliki ekspektasi
positif yang **bertahan lintas-waktu** (bukan artefak satu jendela historis).
Dasar: D13 §R1–R3 menemukan SOL sebagai satu-satunya sub-populasi yang tetap
PROMISING setelah koreksi korelasi (`p_cluster` 0,5041 pada data historis —
TIDAK lolos), sehingga satu-satunya jalan sah adalah **uji forward**.

H0 (yang harus difalsifikasi): ekspektasi SOL forward = 0.

## 2. Sumber data — DIBEKUKAN (tidak boleh tambah/kurangi setelah 05-Okt-2026)

| # | Berkas | Alasan masuk |
|---|--------|--------------|
| 1 | `data/paper_test_realwide.jsonl` | lane forward utama (REAL-wide) |
| 2 | `data/paper_test_realwide_atrvol.jsonl` | varian ATR/vol dari lane yang sama |
| 3 | `data/paper_test_realwide_atrvolopen.jsonl` | varian ATR/vol + open |
| 4 | `data/paper_test_donchian.jsonl` | lane breakout independen |
| 5 | `data/paper_test_pasar_anantara_trade.jsonl` | lane orkestrator |

Filter: `sym`/`pair` dimulai dengan `SOL` (SOL, SOLUSDT, SOL-USD).
Rekam jejak forward dimulai **exit_ts ≥ 2026-10-02T00:00:00Z** (= anchor T1).

## 3. Unit analisis & uji — DIBEKUKAN

- **Grid jendela**: 48 jam, non-overlap, **anchor global tetap** `2026-10-02T00:00:00Z`.
  (Sama seperti P3/P4 D14. Anchor TIDAK boleh digeser — menggeser anchor = p-hacking.)
- **Isi jendela**: rata-rata `pnl_pct` trade SOL yang exit di dalam jendela.
  Jendela tanpa trade: **DIBUANG** dari n, dan rasio jendela kosong DILAPORKAN wajib.
- **Uji utama (p_worst = maksimum dari tiga p, semua harus < 0,05)**:
  1. `p_day_cluster` — sign-flip bootstrap pada blok **hari** (menghormati korelasi harian; pelajaran R3/SOL: p trade-level i.i.d. terlalu lembek).
  2. `p_window` — sign-flip bootstrap pada deret jendela.
  3. `p_sign` — uji tanda binomial satu sisi pada deret jendela.
- **Segmen**: 3 segmen kronologis, **3/3 harus positif** (mean jendela > 0).
- **Sensitivitas biaya**: mean jendela harus tetap > 0 pada **2× biaya** yang dimodelkan lane (P8).
- Bootstrap: 5.000 simulasi, seed tetap 20261005.

## 4. Ambang putusan — DIBEKUKAN

| Putusan | Syarat |
|---------|--------|
| **PASS** | n_jendela ≥ 30 **∧** p_worst < 0,05 **∧** 3/3 segmen positif **∧** 2× biaya masih positif |
| **FAIL** | n_jendela ≥ 30 **∧** (p_worst ≥ 0,05 **∨** segmen < 3/3 **∨** 2× biaya ≤ 0) |
| **INCONCLUSIVE** | n_jendela < 30 |
| **INCONCLUSIVE-STALLED** | tidak ada trade SOL baru selama 14 hari berturut-turut (bukan PASS — tidak boleh ditutup dengan statistik lama) |

Estimasi jujur: dengan laju historis (2 trade forward dalam 3 hari), n≥30 jendela
berisi trade ≈ **60+ hari kalender** → putusan paling cepat **awal Desember 2026**.
Laju yang lebih lambat TIDAK mempercepat putusan dan TIDAK boleh mengubah ambang.

## 5. Kontrol anti-overfit (mengikat)

1. Ambang TIDAK diubah setelah hasil keluar — apa pun hasilnya.
2. Daftar lane sumber TIDAK diubah setelah 05-Okt.
3. Anchor TIDAK digeser; tidak boleh ada pengecualian "outlier".
4. Kalau hasil PASS, promosi tetap butuh T2/T3/T4 + approval user (tidak ada gerbang belakang).
5. Kontrol negatif: deret acak dengan mean & sd sama dijalankan sebagai pembanding
   dan dilaporkan berdampingan (bukan untuk menaikkan p).

## 6. Produk

- `reports/sodex/S1_sol_forward_latest.json` — hasil numerik + putusan.
- `reports/sodex/S1_sol_forward_latest.md` — laporan singkat.
- `reports/sodex/S1_sol_forward_registry.jsonl` — append tiap run (jejak audit).

---

*Dibekukan: 05-Okt-2026. Penulis: Hermes Anantara v3. Protokol ini konsisten dengan
batas keamanan: gate T1 utuh, tanpa leverage, target 0,8%/48 j Tidak diubah,
SODEX_TOTAL_WALLET tidak diubah, E1 beku, arm A1 mati, RW_MARGIN_UTIL_CAP OFF.*
