# MEMO KEPUTUSAN — Definisi Target Utama SoDEX — 2026-10-09
Langkah 2 yang disetujui Mas Anas. Ini **analisis + opsi**, bukan usulan perubahan yang sudah dijalankan. Target/ambang tidak disentuh; perubahan hanya sah lewat pra-registrasi yang Mas setujui.
Pijakan: `docs/sodex/R4B_PROTOKOL_H6_H10_2026-10-05.md` §3–§4, `docs/sodex/VALIDASI_RANGEPOS_KUINTIL_HASIL_2026-10-07.md` §4–§5, `docs/research/HASIL_LEADERBOARD_ONCHAIN_2026-10-09.md`, `HASIL_LIST1_...2026-10-09.md`.

## 1. Anggaran waktu yang tersisa
- Hari ini → HARD_STOP 20-Nov = **42 hari = 21 periode 48 jam** non-overlap.
- Sertifikasi t=2 untuk horizon 48 jam butuh ≈203 periode = **406 hari (1,11 tahun)**.
→ Bahkan bila ada mesin yang benar-benar ber-edge, **target kelas 48 jam tidak dapat disertifikasi sebelum 20-Nov**. Menunggu = tidak menyertifikasi apa pun saat tenggat.

## 2. Mengapa 0,8%/48 jam tidak bisa "ditambal"
- Diversifikasi **tidak** menaikkan mean: `mean_portofolio = Σ wᵢ·meanᵢ` (kombinasi konveks, w≥0, Σw=1). Dengan leverage dilarang: **mean_portofolio ≤ max(mean_mesin)**. Pengali Sharpe 6 mesin hanya menekan volatilitas (teoretis 2,00×; nyata **1,49×** menurut sensus korelasi 0,595).
- Sharpe ≠ mean: H8 lolos gerbang Sharpe (2,65–3,91 vs syarat 2,3) tetapi hasilnya hanya **0,011–0,022%/48 jam** → ±48× di bawah target.
- Mekanisme terbaik yang lolos BH-FDR (rangepos kuintil; Binance; 7 tahun; 245 nama; t=3,75) = **20–23 bps/48 jam** → **celah ≈3,5×**.
- Definisi "dari TOTAL wallet" memperberat: bila hanya 20% wallet ter-deploy, edge yang dibutuhkan pada modal ter-deploy = **4,0%/48 jam**.
- Setara tahunan: 0,8%/48j = **+328%/tahun**; 25 bps/48j = +58%/tahun; 40 bps/48j = +107%/tahun.

## 3. Bukti eksternal (tiga dataset baru hari ini, plus satu studi pihak ketiga)
| Sumber | Temuan | Implikasi |
|---|---|---|
| Hyperliquid, 800 akun besar (LB-1) | ρ persistensi Sharpe H1→H2 = +0,017 (p=0,39); 0 akun lolos OOS nyata | pemenang tidak bertahan |
| SoDEX, 1.500 ID acak (LB-3) | 99,4% wallet tak pernah ≥$1k; hanya 2 akun eligible; 0 lolos OOS | tak ada populasi pembanding |
| SoDEX, 89 listing (LIST-1) | raw short +318 bps = benchmark jendela sama +328 bps → excess −10 bps | "efek listing" = beta pasar |
| EHL, 825k alamat HL, 365 hari | 23,4% profit; top 100 = 52% laba; hanya HFT/maker positif; agregat 1,4 bp dari nol | edge ada di infrastruktur, bukan retail |
Tidak ada satu kelompok trader pun yang secara empiris menuai ≈328%/tahun dari modalnya.

## 4. Opsi (keputusan Mas Anas; agen tidak berwenang memilih)
**A — Pertahankan 0,8%/48 jam + aturan sekarang.** Jujur secara proses. Konsekuensi: tak ada jalur bukti; sertifikasi mustahil sebelum tenggat; 42 hari berakhir tanpa verdict.
**B — Target berjenjang ber-anchor bukti.** Tier-1 = **25 bps/48 jam** (≈+58%/tahun) dari mekanisme terbaik yang sudah lolos BH; naik ke 40/80 bps hanya setelah sertifikasi forward. Konsekuensi: terukur, bisa disertifikasi; klaim "harga mati 0,8%" dilepas dan diganti tangga.
**C — Pertahankan 0,8%/48 jam, ubah aturan** (izinkan leverage, atau horizon >48 jam, atau kembalikan cross-venue). Konsekuensi: mengubah profil risiko ekor; leverage dilarang aturan proyek; protokol harus direstrukturisasi dan disertifikasi ulang dari nol.
**D — Fokus ulang pada pengumpulan bukti.** Hentikan pengejaran 48 jam; jalankan satu mesin terbaik (rangepos) dengan size kecil untuk mengumpulkan sampel forward; angka target ditetapkan setelah n memadai.

## 5. Penilaian agen (bukan keputusan)
Opsi A paling menjaga integritas proses tetapi praktis membuang sisa anggaran waktu. Opsi B atau D memberi jalur yang bisa disertifikasi; B bila Mas tetap ingin ada satu angka target tunggal, D bila prioritasnya bukti dulu. Opsi C hanya masuk akal bila Mas bersedia mengubah aturan risiko secara eksplisit — dan itu keputusan Mas, bukan agen.
