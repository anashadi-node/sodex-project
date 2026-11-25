# HASIL PRAREG-LIST-1 — Short perp setelah listing di SoDEX — 2026-10-09

Pra-registrasi beku: `docs/research/PRAREG_LIST1_SODEX_NEWLISTING_SHORT_2026-10-09.md`
commit `4f1ede7` (2026-10-09T09:14:06+07:00), sha256 `b56d05ad1eaeb13f564ff350ea4fca7920a1df260dc39f72f97ec9766e3819ac`. Ambang tidak diubah setelah melihat hasil.
Data: `data/sodex_klines/{1h,1d}` (95 simbol terverifikasi 1h↔1d, selisih ≤48 jam). Read-only. Tidak menyentuh target/ambang/flag/service/order.
Skrip: `~/.hermes/cache/scratch/list1_correct.py`.

## VERDICT: HIPOTESIS TIDAK DIDUKUNG (gagal kelima gerbang)

| entry umur | H | n | G | mean net | t | %>0 | LOMO | LULUS |
|---|---|---|---|---|---|---|---|---|
| 0 | 3d | 86 | 20 | +12,9 bps | +0,09 | 49% | −21,5 bps | tidak |
| 0 | 7d | 86 | 20 | −24,3 bps | −0,12 | 49% | −70,0 bps | tidak |
| 0 | 14d | 85 | 19 | +26,8 bps | +0,09 | 53% | −137,8 bps | tidak |
| 1 | 3d | 89 | 19 | +38,7 bps | +0,64 | 55% | +6,8 bps | tidak |
| **1** | **7d** | **89** | **19** | **−16,4 bps** | **−0,13** | **58%** | **−75,5 bps** | **tidak (PRIMER)** |
| 1 | 14d | 88 | 18 | +115,1 bps | +0,40 | 57% | −125,2 bps | tidak |

BH-FDR q=0,10 intra-keluarga: tidak ada yang lolos. Ambang beku: mean ≥ +30 bps, t ≥ 2,0, n ≥ 30, %>0 ≥ 55%, LOMO ≥ +15 bps.

## Temuan kunci: efek "listing turun" itu BETA, bukan edge listing
Primer (entry umur 1 hari, tahan 7 hari):
- RAW short (harga turun) = **+318 bps** rata-rata; 66% peristiwa harga turun.
- Benchmark pada jendela kalender yang SAMA (median 30 simbol mapan) = **+328 bps**.
- **EXCESS = −10 bps** → dalam sampel ini seluruh "keuntungan" short listing baru berasal dari pasar yang turun, bukan dari sifat listing.
Ini pengulangan temuan LB-1 (Hyperliquid) dan LB-3 (SoDEX leaderboard) pada data ketiga: return mentah pemenang ≈ beta pasar.

## Daya uji (batas kejujuran)
SE = 122 bps → efek terkecil yang bisa dideteksi pada t=2 adalah **244 bps per perdagangan**. Uji ini hanya mampu menangkap efek sangat besar; efek 30–100 bps tidak terlihat di sini. Jadi hasilnya "tidak didukung", bukan "terbukti nol".

## Risiko & kapasitas (wajib, dilaporkan walau gagal)
- Squeeze: adverse excursion median +8,2%, p90 +24,5%, maksimum **+87%**; 17% peristiwa bergerak >20% melawan short, 1% >50%.
- Kapasitas: median volume notional 7 hari pertama = **$851 rb** per simbol → terlalu tipis untuk modal besar.
- Tersensor/tersingkir: 6 dari 95 simbol (kurang bar atau benchmark <10). Di bawah 20% → hasil dinyatakan andal secara struktur data.
- Subgrup (sekunder, daya rendah): kripto n=46 mean +178 bps (t=+0,81); tokenized n=43 mean −225 bps (t=−1,07). Tidak ada gerbang diterapkan; keduanya tidak signifikan.
- Funding tidak dimasukkan: seri `data/sodex_funding/funding_rates_history.jsonl` hanya menutupi ±7 hari terakhir, tidak 12 bulan. Konteks sekarang: median funding 95% simbol positif sebesar ~0,08 bps/8 jam → untuk SHORT bernilai positif tetapi sangat kecil (≪1 bps per minggu). Bukan pengubah kesimpulan.

## Cacat implementasi yang ditemukan & diperbaiki (disclosed)
Versi pertama memakai benchmark lewat **indeks umur** tiap simbol (bar ke-o masing-masing simbol) → itu mengukur "return minggu pertama simbol lain sejak listing MEREKA", bukan pasar pada jendela yang sama. Hasil versi salah: n=79, mean net −275 bps, t=−0,69 (juga gagal). Versi benar (lookup **timestamp absolut**) memberi n=89, mean −16 bps. **Verdict identik pada kedua versi** → kesimpulan tidak bergantung pada cacat itu. Versi benar yang dilaporkan.

## Konsekuensi
- Hipotesis "short listing baru" sebagai aturan sistematis di SoDEX: **DITUTUP**. Tidak ada penyetelan ambang lanjutan.
- Selaras dengan laporan EHL: spesialis mereka melakukan 1,34 juta fill / 319 hari dengan 89% order agresif, median order $2,5 rb — itu operasi eksekusi/latensi, bukan sinyal harian sederhana. Yang tidak bisa direplikasi oleh kita justru bagian itu, bukan arahnya.
- Tidak ada usulan mengubah target. Keputusan definisi target tetap milik Mas Anas (agenda langkah 2).

## Batas yang diakui
95 peristiwa, banyak bertanggal sama (2026-01 = 29) → t cluster-mingguan; daya sedang. `oldest` = proxy tanggal listing. Data historis → kandidat, bukan sertifikasi (sertifikasi hanya dari data forward).
