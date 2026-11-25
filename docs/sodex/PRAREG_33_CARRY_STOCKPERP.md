# PRAREG-33 — Carry funding saham-perp SoDEX (hedge saham asli)

Beku: 26-Okt-2026. Paper-forward 26-Okt → 25-Nov-2026, evaluasi 26-Nov. DRY-RUN, tanpa order, tanpa kredensial.
Target yang diuji: **M ≥ 0,010 %/5 jam atas modal** (sama dengan PRAREG-23b). Keputusan live tetap milik pengguna.

## 1. Mengapa jalur ini ada (dan batasnya)
- Funding SoDEX diselesaikan **per jam** (arsip 374 jam, 100% selang 1 jam kecuali celah koleksi).
- Mode A rata-rata 62% kas (2022+). Kas itu tidak menghasilkan apa-apa; carry bisa mengisinya.
- Aritmetika (`combo_scenarios.json`, **bukan bukti**): A butuh kupon **3,06 bps/hari per modal sleeve** agar M=0,010; B2 butuh 1,11. Kontrol kupon 0 = M murni (0,00606 / 0,00906) ✔.
- **Preseden negatif:** A1 (carry crypto, 25-Okt) NO-GO karena basis menelan funding. Jalur ini bisa gagal dengan cara yang sama.
- Data funding saham-perp hanya **~24 hari** (2–25 Okt, celah 162 jam 11–18 Okt). Tidak ada riwayat panjang → semua angka di bawah deskriptif.

## 2. Temuan deskriptif PRA-BEKU (jendela sudah terlihat → bukan verdict)
| Ukuran | Nilai | Catatan |
|---|---|---|
| Funding rata-rata saham-perp | berbeda per nama; BTC 1,23, ETH 1,43 bps/hari | persisten ke arah positif (79–85% jam > 0) |
| Δbasis perp−saham (22 nama Yahoo, 40–183 hari bursa/nama) | median sd 38,6 bps/hari (p25–p75: 27,7–50,5) | `basis_desc.json`; **12** nama sd ≤ 40 |
| Portofolio 5 nama acak dari universe | sd Δbasis **16,4** bps/hari (p10–p90: 12,0–24,0) | optimistis: universe dipilih dari sd in-sample (regresi ke rata-rata); 3 nama hanya 40 hari |
| Daya uji 22 hari bursa | SE 3,5 bps/hari → kupon bersih minimum untuk t=2 ≈ **5,25 bps/hari modal** | > impas A (3,06) |
| Replay retro aturan beku (14 hari, **in-sample**) | M = −0,00195, p(M≤0)=0,986, biaya 46 bps, cakupan funding 34,7% | INVALID: data funding bolong; bukan bukti, tapi bukan pertanda baik |

Kesimpulan jujur: **jendela 31 hari tidak cukup bertenaga** untuk membuktikan carry sekecil impas A. Hanya kupon ≥ ~5 bps/hari modal yang bisa terdeteksi. Maka vonis "tidak terbukti, perpanjang" disediakan (G3b) dan **bukan** disamakan dengan lulus.

## 3. Hipotesis (falsifiable)
- **H1:** short perp saham dengan funding 7-hari tertinggi (>0) + long saham asli menghasilkan M ≥ 0,010 %/5 jam atas modal setelah funding, basis, dan biaya.
- **H0 (kontrol negatif):** kupon nol → M = 0 → TIDAK boleh lulus (dites: `test_gerbang_gagal_tidak_positif_noise_nol`).
- Dibantah jika G3 gagal (bootstrap p(M≤0) ≥ 0,05) pada data forward valid.

## 4. Parameter BEKU (hash di registry)
Universe 13 nama: NBIS, LITE, SMCI, GOOGL, MRVL, TSLA, META, AAPL, TSM, CRCL, INTC, HOOD, NVDA. Dipilih dari sd Δbasis ≤ 40 bps/hari (12 nama) **ditambah NVDA** (sd 42,0; dimasukkan karena paling likuid, vol 24 jam tertinggi — deviasi dari kriteria dicatat jujur). Bukan dipilih dari funding atau PnL. LITE/NBIS/SMCI hanya 40 hari data basis → sd rendahnya belum andal.
Seleksi tiap minggu (mark pertama minggu ISO): K=5 nama, funding rata-rata 168 jam terakhir ≥ 0,10 bps/jam, min 120 observasi; tidak ada kandidat → kas.
Biaya 8 bps per masuk/keluar per nama (perp taker 4 + ½ spread perp 2 + saham 2). Faktor modal 4/3 (saham tanpa leverage + 1/3 margin perp L=3).
Mark = penutupan sesi AS (bar jam penuh terakhir 17–22 UTC, ≥4 bar/hari). Sumber saham: Yahoo publik; perp: klines SoDEX 1h; funding: arsip collector.
**Gerbang (urutan tetap):**
- G1 data: mark ≥ 90% hari bursa dan cakupan funding ≥ 90% → jika gagal `INVALID_DATA_TIDAK_CUKUP` (bukan lulus/gagal).
- G3 positif: bootstrap 10.000×, p(M≤0) < 0,05. Jika M>0 dan 0,05 ≤ p < 0,30 → `TIDAK_TERBUKTI_PERPANJANG` (satu kali, +31 hari, parameter tetap). Selain itu `GAGAL_TIDAK_POSITIF`.
- G4 risiko: periode terburuk ≥ −1,5% modal dan DD kumulatif ≥ −2,5% modal.
- G2 target: M ≥ 0,010 → `LULUS_SEMUA_LAYAK_UJI_BROKER`; selain itu `POSITIF_DI_BAWAH_TARGET`.
Lulus hanya berarti **layak diuji dengan broker kecil**; bukan izin live.

## 5. Hambatan yang TIDAK bisa diselesaikan oleh paper
1. **Kaki saham butuh broker** (Alpaca/IBKR) atau kaki-spot lain. Belum ada kredensial/akun; tanpa itu carry ini tidak bisa dieksekusi live pada 01-Des. Alternatif hedge indeks (US500/USTECH100 di SoDEX) menambah residu beta spesifik-saham dan **tidak diuji di sini**.
2. **Kedalaman tipis:** top-of-book saham-perp ≈ $80–380; spread ada yang 7,7–25 bps (LITE, META). Ukuran > ±$100/nama belum tervalidasi.
3. Jam kerja pasar AS: kaki saham tidak bisa diperdagangkan di luar sesi; funding tetap berjalan 24 jam, basis bisa melebar semalam/akhir pekan (sudah termasuk di return mark-ke-mark, tetapi gap kejutan tidak).
4. Funding bisa berbalik negatif; seleksi mingguan bereaksi lambat (lag 168 jam).
5. Data funding 24 hari + celah koleksi → bahkan dengan 31 hari forward, N efektif ≈ 22 hari bursa.

## 6. Verifikasi
`test_carry_forward.py`: 13 tes (tanda funding, hedge netral, basis melebar, mark hilang fail-closed, biaya rotasi, kontrol nol, semua gerbang, parameter beku). Operasi: `carry_forward.py record|eval|retro <fwd>`; recorder harian 00:45 UTC (`sodex-carry-record.timer`).
