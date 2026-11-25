# PRAREG-3 — REVERSAL 21 JAM dengan PEMISAHAN WAKTU IS 60% / OOS 40%

**Status: DIBEKUKAN SEBELUM DIJALANKAN.**
Ditulis 2026-10-07T14:10:05Z (21:10 WIB), **sebelum satu pun angka IS/OOS dihitung**
untuk hipotesis ini. Setelah hasil keluar, berkas ini **tidak diubah** (amendemen hanya
boleh MEMPERKETAT).
Registry trial ekosistem: **41** (PRAREG-1 = 39, PRAREG-2 = 40, ini = 41).
Kartu: `t_8e776d73` · Divisi project SoDEX.

---

## 0. Deklarasi jujur tentang apa yang SUDAH terlihat (wajib dibaca lebih dulu)

Kartu ini meminta PRAREG-3 untuk "reversal 21 jam". Angka-angka berikut **sudah saya lihat
sebelum dokumen ini ditulis** — jadi wajib dideklarasikan, bukan disembunyikan:

1. `MOM_L21` pada panel SoDEX 1h (95 simbol × 8.533 bar) memberi **S_ann = −2,70, t_NW = −4,71**
   (hold 48) dan **S_ann = −3,38, t_NW = −4,59** (hold 24) — sudah lolos BH-FDR, arah negatif.
   Ini bukti kuat bahwa **MOMENTUM 21 jam di SoDEX 1h adalah ANTI-PREDIKTIF**.
2. Kebalikannya (`−MOM_L21`, yang disebut "reversal 21 jam") pada baseline yang sama:
   **net = −25,94 bps, turnover = 1,295, t_NW = −4,71 → mirror-nya +15,58 bps dengan t_NW = +2,82**.
3. Asimetri ini punya sebab mekanis: selisih t antara `−MOM` (+4,71) dan mirror `+MOM`
   (−2,82) adalah tepat **2 × biaya = 10,36 bps**, karena turnover kedua sisi identik
   (1,2949). Jadi bukan "dua temuan", melainkan **satu efek yang dikenai biaya di sisi yang
   salah**: hanya satu arah yang membayar biaya itu setelah arah momentum ditemukan negatif.

**Konsekuensi (tidak diperhalus):**
- Sisi `−MOM_L21` (reversal) **sudah terpakai** sebagai salah satu dari 21 trial PRAREG-1.
  Yang **belum** pernah diukur adalah (a) pemisahan waktu IS/OOS, dan (b) perilakunya pada
  **dirinya sendiri** sebagai hipotesis tunggal — bukan sebagai anggota keluarga 21.
- Karena itu verdict di sini tidak boleh diklaim sebagai "penemuan arah baru". Ia adalah
  **uji daya** atas satu mekanisme yang sudah diketahui, dengan angka IS/OSS yang belum pernah saya lihat.

---

## 1. Hipotesis (satu, terkunci)

**Sinyal reversal 21 jam**: `S_t = −(close_t / close_{t−21} − 1)` pada bar 1 jam.
Long nama dengan `S` tinggi (return 21 jam terburuk), short nama dengan `S` rendah.
Bobot: **peringkat lintas-seksi, dollar-neutral, Σ|w| = 1** (konstruksi identik PRAREG-1 agar
dapat dibandingkan langsung; **bukan** konstruksi kuintil — kuintil sudah dipakai PRAREG-3 versi
Divisi Riset dan tidak diduplikasi di sini).

**Tanda dideklarasikan eksplisit: REVERSAL (negatif terhadap momentum 21 jam).**
Tidak boleh dibalik setelah melihat hasil.

## 2. Spesifikasi BEKU

```
panel    : SoDEX klines 1h, 95 simbol, data venue (READ-ONLY)
sinyal   : S = -pct_change(21 bar)                      [momen t dipakai, bar t+1..t+hold]
bobot    : peringkat lintas-seksi, dollar-neutral, Σ|w| = 1
lantai   : minimal 20 nama per bar (sama seperti harness laporan)
hold     : 24 bar dan 48 bar  (keluarga = 2 sel)
biaya    : 1x   = 4 bps/sisi  (taker SoDEX resmi, = 8 bps round-trip @ turnover 1)
           real = 4,86 bps/sisi (+slippage 0,86 bps/sisi, AUDIT_BIAYA_AKUN_2026-10-05)
           2x   = 8 bps/sisi   (16 bps round-trip)
turnover : DIUKUR, tidak diasumsikan
kontrol  : sinyal diacak dalam baris (seed 20261007), konstruksi identik;
           dinilai pada BRUTO (neto kontrol tercemar biaya turnover acak)
statistik: t Newey-West lag = hold (deret waktu portofolio, BUKAN t gabungan lintas aset)
```

## 3. Pemisahan waktu (BEKU)

- **IS  = 60% periode terawal** panel (indeks bar 0 … 0,60·T) → hanya untuk **mengukur tanda
  dan besaran**, tanpa menyetel ulang apa pun.
- **OOS = 40% periode terakhir** (indeks bar 0,60·T … T) → **diuji apa adanya**.
- Batas terakhir IS dihitung dari **sinyal yang tersedia** (`pct_change(21)` → bar ke-21),
  lalu dibulatkan; nilainya ditulis di laporan hasil dan tidak boleh digeser.
- Sensitivitas N ∈ {10, 20, 40, 60} (jendela lookback) dilaporkan **sebagai stabilitas,
  bukan pemilihan**; N utama tetap **21** (kartu menyebut "21 jam").

## 4. Ambang lulus (BEKU — sama dengan kartu)

| # | Syarat |
|---|---|
| g1 | **S_ann OOS ≥ 2,30** pada biaya 1× |
| g2 | **S_ann OOS ≥ 1,80** pada biaya 2× |
| g3 | **t_NW OOS ≥ 2,0** |
| g4 | tanda IS = tanda OOS |
| g5 | **3/3 segmen waktu OOS positif** |
| g6 | kontrol negatif **tidak lulus** (|t| < 2, pada bruto) |
| g7 | turnover **diukur** dan dilaporkan (bukan syarat, tapi wajib angka) |

Semua terpenuhi = kandidat mesin, **BUKAN** berarti target 0,8%/48 jam tercapai.

## 5. Aritmetika daya (jujur, sebelum hasil)

| | Nilai |
|---|---:|
| Periode OOS 1h (40% dari 8.533 bar, hold 48) | ≈ 71 bar rebalance |
| Periode OOS 1h (hold 24) | ≈ 142 bar rebalance |
| t yang dibutuhkan | ≥ 2,0 |
| t terukur pada baseline penuh (hold 48) | 2,82 (neto) / 4,71 (bruto) |

**Peringatan:** OOS hold 48 hanya ≈71 observasi — **di bawah** lantai 90 yang membuat segmen
3/3 bisa dihitung. Untuk hold 48 saya tetap melaporkan segmen **hanya jika ≥90 observasi**;
kalau tidak, g5 ditandai `TIDAK-DAPAT-DIHITUNG` (bukan "lulus"). Saya tidak akan menggeser
batas IS demi mendapatkan lebih banyak bar OOS.

## 6. Yang TIDAK dilakukan

- Tidak menyetel ulang tanda, N, hold, atau ambang setelah melihat OOS.
- Tidak menghapus trial gagal dari registry.
- Tidak menaikkan leverage untuk mengejar target; tidak mengubah angka target.
- Tidak mengklaim alpha dari jendela < 6 bulan (aturan #4 `PERINTAH_1_SoDEX.md`).
- Tidak menyebut hasil apa pun sebagai alpha jika kontrol negatifnya lolos.

## 7. Berkas

- `prereg3_is_oos.py` (workspace kartu) — uji IS/OOS + sensitivitas N + kontrol.
- `PRAREG3_HASIL.json` + `PRAREG3_HASIL.md` (workspace kartu).
- Salinan protokol ini: `docs/sodex/PRAREG_3_REVERSAL21_IS_OOS_2026-10-07.md` (repo, docs —
  satu-satunya pengecualian write di luar workspace, murni dokumen protokol).

— DIBEKUKAN 2026-10-07T14:10:05Z · Divisi project SoDEX (kartu t_8e776d73)