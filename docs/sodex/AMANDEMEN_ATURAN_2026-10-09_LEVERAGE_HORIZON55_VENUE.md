# AMANDEMEN ATURAN & TARGET — KEPUTUSAN MAS ANAS — 2026-10-09
Status: **disetujui Mas Anas** (jawaban atas memo `MEMO_KEPUTUSAN_TARGET_UTAMA_2026-10-09.md`).
Ini perubahan aturan fundamental → wajib lewat amandemen terdokumentasi (dokumen ini), bukan edit senyap.

## 1. Keputusan (kutipan langsung, tidak ditafsirkan)
> "fokus D kumpulkan tetapi tetap C pertahankan 0,8% izinkan leverage, ijinkan horizon sampai maximal 55 jam, venue tetap utama di sodex tetapi boleh di ijinkan melakukan testing simulasi papertest untuk vanue lainnya"

Diterjemahkan menjadi aturan operasional:
| # | Aturan | Sebelum | Sesudah (berlaku) |
|---|---|---|---|
| R1 | Target | 0,8% total wallet / 48 jam | **0,8% total wallet / 48 jam — TIDAK BERUBAH** |
| R2 | Leverage | dilarang | **DIIZINKAN** |
| R3 | Horizon maksimum | 48 jam | **≤ 55 jam** (48 jam tetap grid pelaporan utama; 48–55 jam grid sekunder) |
| R4 | Venue | SoDEX saja | **SoDEX utama** + **simulasi/papertest** venue lain (bukan live) |
| R5 | Mode kerja | — | **D: kumpulkan bukti** — jalankan mesin terbaik, kumpulkan sampel forward |

## 2. Konsekuensi matematis (karena leverage berubah, argumen lama tidak lagi berlaku)
Dengan leverage diizinkan, `mean_portofolio ≤ max(mean_mesin)` **tidak lagi mengikat** — leverage mengalikan mean DAN ekor. Edge bersih per mesin per 48 jam yang dibutuhkan:
| Leverage | Butuh edge bersih/48j | Jarak likuidasi (mmr 1%) |
|---|---|---|
| 1× | 80,0 bps | ~99% |
| 2× | 40,0 bps | ~49% |
| 3× | 26,7 bps | ~32% |
| 3,5× | 22,9 bps | ~27,6% |
| 4× | 20,0 bps | ~24,0% |
| 5× | 16,0 bps | ~19,0% |
Mekanisme terbaik yang lolos BH-FDR sejauh ini = **20–23 bps/48 jam** (rangepos kuintil; Binance; 7 thn; 245 nama; t=3,75).
→ **Titik impas leverage = 3,48×–4,0×.** Artinya target 0,8%/48 jam menjadi *aritmetis mungkin* pada leverage ≈3,5–4× — tetapi hanya dengan mekanisme terbaik itu, dan mekanisme itu belum disertifikasi forward dan belum diuji di SoDEX.

## 3. Peringatan risiko (tidak dikurangi oleh keputusan ini)
Ekor kiri per 48 jam yang terdokumentasi: persentil-5 = **−5,4% s/d −10,7%**. Dikalikan leverage:
| Leverage | Periode buruk −5,4% | Periode buruk −10,7% |
|---|---|---|
| 2× | −11% | −21% |
| 3× | −16% | −32% |
| 4× | **−22%** | **−43%** |
Pada 3,5–4× (leverage impas), satu periode ekor buruk setara −19% s/d −43% modal. Karena itu leverage **tidak boleh** dipakai sebagai jalan pintas menutup celah: ia menggeser kebutuhan edge, tetapi sekaligus memindahkan titik impas ke sekitar ekor likuidasi.

## 4. Pagar wajib (usulan agen, untuk disetujui menyusul — bukan wewenang agen)
1. **Tangga leverage**: mulai 1× → naik hanya setelah sertifikasi forward tahap sebelumnya lulus. Tidak ada lompatan langsung ke 3,5–4×.
2. **Lantai jarak likuidasi**: tidak ada posisi dengan jarak likuidasi < 30% (membatasi leverage efektif ≈3× pada ekor terekam).
3. **Stop-loss wajib** pada setiap mesin ber-leverage; tanpa SL, ekor −43% tidak terlindungi.
4. **Leverage dilarang pada mekanisme tanpa sertifikasi forward** (rangepos saat ini belum).
5. **Dua grid pelaporan**: 48 jam (target resmi) dan 48–55 jam (sekunder, tidak boleh menggantikan grid utama).

## 5. Batas yang tetap berlaku (tidak diubah oleh keputusan ini)
- Lane uang SoDEX **masih freeze** (30-Sep): `anantara-spot-livetest` & `anantara-realwide-livetest` inactive+disabled; `LIQ_DRY=1`. **Unfreeze tetap butuh syarat terdokumentasi: satu execution arbiter (satu pemilik exit per simbol) + persetujuan.** `docs/MONITOR_HANDOFF_2026-09-30.md` §67–71.
- Karena itu "mode D" dijalankan lewat **paper/forward simulasi** dulu; live tetap menunggu arbiter.
- Venue lain: **simulasi/papertest saja**, tanpa order nyata (Red Line: dry_run tidak diubah tanpa GO-LIVE).
- Tidak ada ambang pra-registrasi yang diubah; R2/R3/R4 mengubah ruang pencarian, bukan ambang uji yang sudah beku.

## 6. Implikasi ke langkah berikutnya
Mode D + R2/R3/R4 → prioritas: (a) kumpulkan sampel forward mekanisme terbaik (rangepos kuintil) dengan **lever=1×** sambil menyiapkan pagar §4; (b) uji ulang mekanisme terbaik pada data SoDEX dengan horizon ≤55 jam; (c) venue lain hanya sebagai pembanding simulasi. Semua tetap tanpa order nyata sampai arbiter siap.
