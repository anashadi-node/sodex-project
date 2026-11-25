# PAPER ARENA — 25 Okt 2026 (modal $250 / $1.000 / $10.000)

**Tujuan:** menguji banyak kandidat sekaligus pada modal yang jauh lebih besar dari
akun nyata ($243), dengan biaya sadar-ukuran, sampai **15 Des 2026** tanpa henti.

**Putusan hari ini:** tidak ada kandidat yang lolos ambang bukti (t≥4,11).
Satu kandidat berstatus **PROMISING** di sejarah panjang dan **WATCH** di forward —
itu hipotesis, bukan hasil.

---

## 1. Desain (dibekukan)

| Komponen | Nilai |
|---|---|
| Modal uji | $250, $1.000, $10.000 (tiga tingkat) |
| Hold | 30 jam, entry di open bar berikutnya (anti look-ahead) |
| Biaya | fee **6,49 bps** + slippage `2 + 18×(partisipasi/5%)` bps |
| Batas partisipasi | **5% volume jam** — di atas itu trade **ditolak**, bukan dihargai murah |
| Evaluasi | window non-overlap 30 jam; split 60/40; target 0,8%/window |
| Fail-closed | <30 window → INSUFFICIENT; uji <15 window → INSUFFICIENT |
| Parameter | beku di kode; tidak ada fitting di dalam run |

## 2. Hasil SoDEX (era-real 12 Jun – 25 Okt, 95 simbol, 44 window uji)

| Strategi | $250 | $1.000 | $10.000 | Status |
|---|---|---|---|---|
| reversal6 (beli jatuh 6 jam >2σ) | **+2,00%** (t 0,98) | **+1,62%** (t 1,08) | **+0,81%** (t 1,22) | WATCH |
| xs_mom30 (long top2 / short bottom2) | +0,05% (t 0,16) | −0,20% (t −0,84) | −0,20% (t −1,84) | NO-GO |
| xs_rev30 | −0,10% | +0,15% | +0,19% (t 1,76) | campur |
| donchian30 | −1,70% | −0,21% | −1,16% | NO-GO |
| trend30 | −0,27% | −0,27% | −0,60% | NO-GO |

**Kurva kapasitas (temuan utama):** pada $10.000, **97% trade XS ditolak** karena
partisipasi >5% dari volume jam. Biaya rata-rata naik 6,49 → **15–16 bps**. Artinya
SoDEX hanya bisa menyerap modal besar pada segelintir nama; strategi yang butuh
4 leg sekaligus **tidak bisa dijalankan** di venue ini pada $10k.

## 3. Hasil Binance (pembanding lintas-venue)

| Panel | Strategi | Uji | mean/window | t | Verdict |
|---|---|---|---|---|---|
| 2024–2026, 54 simbol, 324 window | **xs_mom30** | OOS | **+0,78%** | **2,86** | **PROMISING** |
| 2024–2026 | xs_rev30 | OOS | −0,95% | −3,49 | NO-GO |
| 2024–2026 | reversal6 | OOS | −1,14% | −0,32 | NO-GO |
| 180 hari terakhir | xs_mom30 | OOS | +0,23% | 1,12 | WATCH |

**Dua pembacaan jujur:**
1. `xs_mom30` satu-satunya kandidat dengan t>2,5 di sejarah panjang — tetapi **melemah**
   di 180 hari terakhir dan **datar di SoDEX**. Efeknya bergantung rezim dan kedalaman buku.
2. `reversal6` **berpindah tanda**: +2,00% di SoDEX, −1,14% di Binance. Sinyal yang
   berbalik tanda antar-venue adalah sinyal rapuh, bukan edge — jangan dipercaya
   sebelum lolos forward di venue tempat ia akan dipakai.

## 4. Protokol berkelanjutan (aktif sampai 15 Des 2026)

- `sodex-paper-arena.timer` — harian 09:10 WIB; menjalankan 3 tier SoDEX + panel Binance
  (refresh 180 hari), menambah satu baris ke `reports/sodex/PAPER_ARENA_LEDGER.jsonl`.
- Fail-closed: data >3 hari basi → `STALE`, exit 2 (bukan PASS diam-diam).
- `sodex-venue-7d.service` diperpanjang **7 → 51 hari** (sampai 15 Des) untuk data
  buku/trade asli; config baru `bc368669cc0ccf20`.
- Ambang promosi tidak berubah: **t≥4,11** dengan N registry yang diperbarui.

## 5. Yang TIDAK diklaim

- `xs_mom30` belum layak dana nyata: t=2,86 < 4,11, dan hasil 180 hari hanya t=1,12.
- `reversal6` bukan temuan: tandanya berbalik antar-venue.
- Angka $10k bukan bukti strategi gagal — itu bukti **venue** tidak mampu menyerap ukuran.
- Tidak ada parameter yang dioptimalkan pada data uji.

---

**Langkah berikutnya (otomatis):** setiap hari arena menambah bukti; verdict hanya
berubah bila satu kandidat mencapai t≥4,11 pada window uji baru, bukan pada data yang
sudah dilihat.
