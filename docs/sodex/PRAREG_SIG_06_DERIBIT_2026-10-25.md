# PRAREG-SIG-06 — OPTIONS-IMPLIED SKEW (DERIBIT)

**Tanggal:** 25 Okt 2026 · **Status:** dibekukan SEBELUM data dikumpulkan
**Sumber:** Deribit publik (`get_book_summary_by_currency`), read-only, tanpa kredensial
**Alasan:** satu-satunya kelas data yang belum pernah disentuh — mengukur **posisi dan
harga asuransi**, bukan turunan harga spot. 1.080 uji pada data harga sudah gagal; menambah
uji di data yang sama = p-hacking.

---

## Data yang dikumpulkan (mulai 25 Okt 2026, 5 menit/siklus, **180 hari**)

**Koreksi jujur (25 Okt):** 40 observasi non-overlap 72 jam = **120 hari** data,
ditambah 60 hari pemanasan z-score → minimum **180 hari**. Kolektor 30 hari
sebelumnya TIDAK akan pernah cukup; sudah dinaikkan ke 180 hari.

| Field | Definisi |
|---|---|
| `S` | underlying_price Deribit |
| `atm_iv[exp]` | mark_iv strike terdekat ke S, per expiry |
| `skew25[exp]` | IV(put K≈0,95S) − IV(call K≈1,05S) |
| `rr25[exp]` | risk reversal 25-delta proxy (sama, tanda terbalik) |
| `pc_oi` | total OI put / total OI call |
| `T_d[exp]` | hari ke expiry |

Minimal 4 expiry dengan T ≥ 0,5 hari; jika kurang → siklus ditandai `partial`.

## Hipotesis (dibekukan — tidak boleh diubah setelah melihat data)

| # | Hipotesis | Arah yang diharapkan | Uji |
|---|---|---|---|
| **H1** | Skew ekstrem (persentil ≥90 dalam 30 hari) memprediksi **reversal** 72 jam | return berlawanan arah skew | regresi return 72j pada skew_z, sampel non-overlap |
| **H2** | Inversi term structure (ATM IV front > back) memprediksi **ekspansi volatilitas** 24–72 jam | realisasi > implied | uji selisih RV−IV, Wilcoxon |
| **H3** | Perubahan skew 24 jam memprediksi **drift arah** 72 jam | tanda skew_change = tanda drift | regresi, kontrol beta BTC |

**Kontrol negatif wajib:** acak-tanda skew (permutasi 1.000×). Jika hasil nyata tidak
lebih baik dari permutasi, hipotesis ditolak.

## Gerbang statistik (WAJIB — diperbarui 25 Okt)

- **n_trials kumulatif = 1.261** (`reports/sodex/TRIAL_BUDGET.json`)
- **Ambang: |t| ≥ 4,11** (Bonferroni dua sisi α=0,05). Bukan 2,0. Bukan 3,6.
- Biaya: **10 bps per round-trip** (konservatif, termasuk slippage).
- Sampel: non-overlap (satu observasi per 72 jam), split waktu 70/30.
- **Lulus** hanya jika: |t| ≥ 4,11 **dan** tanda latih = tanda uji **dan** kontrol
  permutasi kalah **dan** efek > biaya.

## Yang TIDAK boleh dilakukan

1. Mengubah ambang setelah melihat hasil.
2. Menambah horizon/lookback baru setelah data terlihat (itu uji baru → hitung N).
3. Mengklaim edge dari korelasi in-sample.
4. Menggunakan data < 120 observasi non-overlap untuk klaim apa pun.

## Keputusan yang mungkin

(a) satu hipotesis lulus → uji forward paper 30 hari; (b) semua gagal → jalur opsi
ditutup dan dicatat di registry; (c) data tidak memadai → lanjutkan koleksi.

**Tidak ada order otomatis. Tidak ada modal berisiko.**
