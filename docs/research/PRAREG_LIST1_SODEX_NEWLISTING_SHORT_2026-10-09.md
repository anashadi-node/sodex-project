# PRAREG-LIST-1 — Short perp setelah LISTING di SoDEX — DIKUNCI 2026-10-09 (sebelum satu return dihitung)
Sumber ide: studi pihak ketiga EHL (Hyperliquid, 365 hari) melaporkan pemenang terbesar satu venue adalah "spesialis short listing baru" (+$140 jt). Itu belum diuji di venue kita. Uji ini menutup atau membuka hipotesis itu untuk SoDEX.
Data: `data/sodex_klines/{1h,1d}/<SYM>.json` (kolektor kanonik, read-only). Tidak menyentuh target, ambang, flag, service, atau order.

## Definisi beku
- Universe: seluruh simbol di `data/sodex_klines/1d` yang punya berkas 1h DAN selisih bar-pertama 1h vs 1d <= 48 jam (= 95 simbol terverifikasi). Simbol tanpa bar dibuang, dilaporkan.
- `t_list` = min(bar pertama 1h, bar pertama 1d). `age_d` = floor((t_bar - t_list)/86400e3).
- Harga = close bar 1d. MASUK = close pada `age=1`. KELUAR = close pada `age=1+H`.
- Return short per simbol: `r_short = -(P(1+H)/P(1) - 1)` (1 unit notional; perp, tanpa pinjam).
- Benchmark = rata-rata `r_short` simbol yang pada saat masuk ber-`age >= 30 hari` (bukan listing baru), pada TIMESTAMP yang sama; wajib >= 10 simbol; bila kurang -> seluruh simbol lain. (Mengurangi beta pasar: pelajaran dari LB-1.)
- `excess = r_short(simbol) - r_short(benchmark)`. `net = excess - 0,000668` (biaya RT repo 6,68 bps).
- Horizon: H = 7 hari (PRIMER); H = 3 dan 14 hari (sekunder). Offset masuk: age=1 (primer), age=0 (varian). KELUARGA = 3 horizon x 2 offset = 6 uji; BH-FDR q=0,10 intra-keluarga.
- Statistik: t cluster-robust ber-cluster MINGGU masuk (menangani tumpang-tindih antar-simbol). n = jumlah peristiwa lengkap.

## Ambang beku (H=7, masuk age=1 harus lulus SEMUA)
1. mean net excess >= +30 bps per perdagangan
2. t_cluster >= 2,0
3. n >= 30 peristiwa lengkap
4. fraksi peristiwa ber-excess positif >= 55%
5. leave-one-month-out mean net >= +15 bps (bukan satu bulan)
Bila lulus lima-limanya -> KANDIDAT, lanjut harness FORWARD (bukan verdict; sertifikasi hanya dari data forward).
Bila gagal -> hipotesis ditutup, tidak ada penyetelan ambang. Anggota keluarga selain primer TIDAK boleh dipromosikan jadi verdict di prareg ini; bila ada yang lolos dan tahan BH, ia menjadi kandidat prareg BARU.
Laporan wajib walau gagal: risiko squeeze = adverse excursion maksimum `-(P_high/P_entry -1)` dalam jendela; fraksi adverse >20% dan >50%; median volume notional 7 hari pertama (kapasitas); jumlah tersensor (simbol berhenti sebelum keluar; bila >20% -> hasil dinyatakan tidak andal).
Subgrup (sekunder, tanpa gerbang karena daya rendah): kripto (punya padanan Binance) vs tokenized (tanpa padanan; proxy, kemungkinan salah kelas: TON-USD).

## Batas yang diakui
- `oldest` = proxy tanggal listing; bila pull awal terlewat, peristiwa salah tanggal (mitigasi: syarat kesepakatan 48 jam).
- Sampel = 95 peristiwa, sebagian tanggal sama (tumpang-tindih) -> cluster minggu; daya sedang.
- Ini data HISTORIS: sah dilabeli deskriptif/kandidat, TIDAK sah sebagai sertifikasi.
- Funding tidak dimasukkan (perp pendek membayar/menerima funding); dilaporkan sebagai suku orde-dua bila seri funding menutupi jendela, jika tidak -> keterbatasan.
