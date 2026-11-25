# ARAH BARU — BERHENTI BERBURU SINYAL, SERANG BIAYA & CAPTURE

> ## ⚠️ KOREKSI (audit ulang 09-Okt-2026 malam — baca ini dulu; menggantikan bagian yang bertentangan)
> Setelah "double-check semuanya", empat klaim di bawah **terbukti salah/terlalu kuat** dan dicabut:
> 1. **§4.2 "capture exit = tuas terkuat" — DICABUT.** `reports/sodex/D11_PRIORITY0_EXIT_CAPTURE_FALSIFIED_2026-10-05.md`
>    sudah **memfalsifikasinya**: MFE>realized adalah profil lotere (33 trade = 336% profit; membuang 33 terbaik → −117%);
>    memanen MFE membunuh ekor. Saya tidak membaca D11 sebelum menulis dokumen ini — itu kesalahan proses saya.
> 2. **§4.1 "maker-RT hemat +5,6 bps" — DICABUT sebagai klaim.** Mengasumsikan fill maker dilarang kerangka bukti (§6);
>    penghematan harus DIUKUR dari fill-rate nyata. Juga biaya tidak konsisten antar sumber (D05 8 bps/step vs 2,80/1,14 bps-leg).
> 3. **Tabel track §3 salah sebagian** (n dan nama track tidak cocok data). Angka terverifikasi 09-Okt 22:16Z dari state:
>    TWOWAY n=422 +$178,14 · REALWIDE n=269 +$92,36 · SWING n=535 −$107,83 · DONCHIAN n=221 −$87,99 ·
>    ASTER n=221 −$135,28 · HYPERLIQUID n=191 −$174,68 · PORTFOLIO n=78 −$48,27 · PASAR_ANANTARA n=47 −$140,18 ·
>    SHORTBEAR n=36 −$14,75 · SPOT_SWING_v2 n=232 −$3,66 (varian shortbear lain n=0).
> 4. **"TWOWAY +75% wallet" menyesatkan.** Metrik gate RESMI (`data/sodex_maturation_status.json`): TWO-WAY **median window
>    −1,77%**, window-hit 40% (20/50), terburuk −28,6% → **NO-GO**; REAL-WIDE median 0,00%, hit 40,7% (11/27) → **NO-GO**.
>    Target 0,8%/48j adalah target **MEDIAN/hit-rate**; semua mesin lolos MEAN (+1,16..+1,47%) tapi median ≤ 0 = **lotere**.
>
> **Yang tetap berdiri:** jebakan ratchet; "nilai BUKU bukan mesin"; diagnostik daya PRAREG-25 (gap Sharpe S-A +0,116 vs
> perlu 0,734; alpha OLS S-A +0,0125%/hari t=1,95 β=0,056, S-B +0,0546%/hari t=1,27 β=0,476 → tidak ada alpha signifikan).
>
> **Audit `mv_funding` (satu-satunya kandidat nyata D15, carry delta-neutral, 106 trade, 06-Sep→08-Okt, paper):**
> mean +0,1966%/trade tetapi **median −0,003%**, WR 47,2%; PnL mingguan: −0,01, +0,02, +0,07, +0,30, **+1,49%** (minggu terakhir
> = $111,61 = 73% dari total $153,56; pasangan Binance↔dYdX n=8 = $89,66 = 58%). Ukuran posisi naik $100→$750 sehingga $ ikut
> membesar. Artinya: **bentuk yang sama — ekor, bukan edge stabil** (belum terbukti persisten; P9 RERUN 15-Okt sudah terjadwal,
> ambang tidak boleh diubah). Venue: Binance/OKX/Bybit/dYdX × Hyperliquid — dYdX/eksekusi lintas venue belum terverifikasi.

**Tanggal:** 09-Okt-2026 · **Pemicu:** kritik Mas Anas *"coba ubah sudut pandang… kalau begini semua yang diajukan pasti gagal, terus dan terus"*.
**Status:** dokumen arah (bukan pra-registrasi uji). Tidak ada order, tidak ada posisi, tidak ada flag live.

---

## 1. Kritik itu benar — dan saya bisa menamai jebakannya

Selama sesi ini saya menjalankan pola yang **secara struktural menjamin kegagalan**. Empat jebakan, semuanya bisa dibuktikan dari artefak program sendiri:

| # | Jebakan | Bukti |
|---|---|---|
| 1 | **Ratchet**: registry trial tumbuh (72 → 76 → 78) sehingga t_kritis naik **setiap kali gagal**. Satu kandidat menghadapi ambang yang makin tinggi → gagal adalah hasil desain, bukan temuan tentang pasar. | registry kanonik + catatan N trial |
| 2 | **Menuntut satu mesin memikul seluruh target.** Target 0,8%/48j adalah keluaran **BUKU** (aturan yang sudah disetujui: `w = 0,5·Σ⁻¹·α`), bukan keluaran satu mesin. Saya menuntut satu mesin lolos t ≥ 3,6 sendirian — padahal buku dari k edge lemah tak berkorelasi menaikkan t ≈ √k. | PRAREG-23/24/25 semua single-engine |
| 3 | **Menguji di venue/data yang salah.** 3 percobaan terakhir: Binance **spot**, bar **harian**, 6–20 majors, 2017–2025 (historis). Venue yang benar: **SoDEX perps**, dan catatan forward SoDEX sudah ada di meja. | PRAREG-23/24/25 runner |
| 4 | **Mengabaikan kerangka bukti program sendiri** (skill `anantara-master-evidence-framework`) — yang sudah memuat §4 (daya statistik), §11b (IC), §11f (kontrol negatif dinilai pada BRUTO), dan **H1: bottleneck = CAPTURE exit, bukan sinyal (n=732)**. | skill §4, §11, §Bukti empiris |

**Konsekuensi jujur:** PRAREG-24 dan PRAREG-25 menguji **lever yang salah**. Keduanya sah secara protokol, tetapi tidak akan pernah menjawab pertanyaan yang menentukan.

---

## 2. Terhadap jebakan #4: apa yang sudah terdokumentasi di program ini

**H1 (CONFIRMED, n=732 trade SoDEX):** median MFE **+1,087R** vs median realized **−0,125R**; 52,2% posisi menyentuh +1R; **11,3% posisi yang akhirnya RUGI sempat menyentuh +1R**.
→ **Kebocoran terbesar yang sudah terukur = CAPTURE exit, bukan sinyal entry.**

**D05 Edge-Leak Audit (lengan twoway, fee 8 bps/step):**
| Metrik | Nilai |
|---|---|
| Gross (beta-neutral, lengan sinyal) | **10,74 bps** |
| Net setelah 1× fee (8 bps) | +2,74 bps |
| Net setelah 2× fee (16 bps) | **−5,26 bps** |
| CI95 (cluster bootstrap) | [−22,71 ; +43,62] · **p(excess>0) = 0,733** |
| TP (n=120) / SL (n=160) kontribusi | +57,49 / −45,47 bps |
| WR aktual | 42,8% |
| **WR impas:** tanpa fee / 1× / 2× | 38,7% / 40,1% / **41,5%** |

**Bacaannya:** edge ini hanya **1,3 poin persen** di atas titik impas biaya-2×. Gross (10,74 bps) hanya **1,34× biaya** (8 bps). Ini bukan alpha yang bisa dikejar dengan menambah daya statistik — **ini alpha yang dimakan biaya.**

**D05B Exit Geometry:** TP terealisasi 3,50% (rencana 3,57% → capture TP bagus) tetapi **SL terealisasi 2,21% vs rencana 2,00%** → **overshoot SL +21 bps** setiap kali kalah; R:R terealisasi 1,585 (rencana 1,786).

## 3. Catatan forward yang sudah ada (dan mengapa saya TIDAK mengklaimnya sebagai temuan)

`data/paper_test_*_state.json` (track SoDEX, sudah termasuk `cost_model` teraudit + slippage sisi merugikan):

| Track | n | Window | Sum wallet-ROI | PnL |
|---|---|---|---|---|
| TWOWAY | 418 | 06-Agu → 08-Okt (63 hari) | +75,0% | +$182,43 |
| REALWIDE | 268 | 06-Agu → 09-Okt | +37,2% | +$90,66 |
| SWING | 528 | — | negatif | −$99,09 |
| SWING_PARTIAL | 568 | — | negatif | −$119,13 |
| **DONCHIAN** | 221 | — | **negatif** | −$87,99 |
| SPOT_SWING_v4 | 232 | — | negatif | −$3,66 |

**DUA HAL YANG WAJIB DILAPORKAN SEKALIGUS — dan keduanya melarang saya mengklaim kemenangan:**

1. **Jendela 63 hari = ±2,3 SE untuk Sharpe.** Menurut kerangka program sendiri (§4): *"hasil < 6 bulan tidak boleh jadi dasar promosi ATAU penolakan."* Jadi TWOWAY **tidak** membuktikan alpha.
2. **Eksposur bersamaan MAKSIMUM = $2.400 = 9,88× wallet** ($243), rata-rata ~4–5 posisi terbuka (hold rata-rata 15,2 jam × 6,63 trade/hari). Artinya return tingkat-wallet itu **diperbesar leverage**. Per kerangka: Kelly bukan default; leverage pada inti dilarang.
3. Bonus jujur: **64% trade (266/418) tidak mencapai target 0,8%.**
4. **Kontrol negatif (RANDOM_CONTROL n=30, −0,68%/trade) TIDAK boleh dibaca sebagai bukti sinyal** — per §11f kontrol acak membayar biaya jauh lebih besar sehingga t-nya selalu negatif secara sistematis. Bruto vs biaya harus dipisah.
5. **Semua track berorientasi TREN negatif** — termasuk DONCHIAN (n=221, ROI −0,164%). Keluarga yang saya tambang selama sesi ini justru **tercatat negatif** di venue nyata.

**Satu-satunya hal yang saya ambil dari tabel ini:** sinyal entry-nya **hampir tidak penting** dibanding biaya dan cara keluar. Itu konsisten dengan D05 dan H1.

---

## 4. Sudut pandang baru — tiga perubahan, semuanya terukur

### 4.1 Serang BIAYA dulu (paling besar, tidak butuh alpha baru)
D05: gross **10,74 bps** vs fee **8 bps** (taker). Kerangka §8: **SoDEX maker 1,2 bps vs taker 4,0 bps per sisi**.
→ Berpindah dari taker-RT (8 bps) ke **maker-RT (2,4 bps)** menambah **≈ +5,6 bps netto per trade** — **lebih besar dari separuh seluruh edge bruto**, tanpa satu pun sinyal baru.
→ Ditambah: turunkan frekuensi (6,63 trade/hari × 8 bps = beban biaya besar) dan kendalikan **overshoot SL +21 bps** (D05B).

### 4.2 Serang CAPTURE exit (bukti terkuat yang kita punya: n=732)
Median MFE +1,087R vs realized −0,125R = **≈ 1,2R bocor per trade**. Ini **mekanisme**, bukan hipotesis sinyal baru: mengubah aturan keluar bisa diuji pada rekaman trade yang **sudah ada**, lalu diverifikasi forward. Tidak ada jebakan goalpost: aturan keluar dipraregistrasi sebelum diuji.

### 4.3 Ubah aturan keputusan (mematikan jebakan #1 dan #2)
- **Ganti ratchet dengan ANGGARAN hipotesis**: K uji tetap per periode (mis. 6/kuartal); t_kritis tetap, tidak naik setiap kegagalan.
- **Ambang BERTINGKAT sesuai modal yang dipertaruhkan**, bukan satu dinding 8-gate: *saring murah* (n≥30, E>0 netto biaya venue) → *forward paper* (n≥100, kill rule jelas) → *live mikro*. Evidensi proporsional risiko — begitulah modal dialokasikan.
- **Nilai BUKU, bukan mesin**: `w = 0,5·Σ⁻¹·α` atas k komponen tak berkorelasi; lulus/gagal dinilai di tingkat buku.
- **Backtest historis = deskriptif.** Verdict hanya dari forward (aturan yang sudah berlaku — dan saya melanggarnya dengan menguji 2017–2025).

---

## 5. Urutan kerja yang saya usulkan (murah → mahal)

| # | Langkah | Sifat | Kenapa ini dulu |
|---|---|---|---|
| 1 | **Ledger capture pada rekaman trade yang ADA** (n=732 H1 + 418 twoway): berapa R yang bisa diselamatkan oleh aturan exit alternatif (trailing/ratchet/partial di +1R) — praregistrasi aturan sebelum melihat hasil | read-only, tanpa order | bukti terkuat di program (n=732); menguji mekanisme, bukan sinyal |
| 2 | **Stress biaya**: ulang D05 pada maker-RT (2,4 bps) + 1×/2× taker; pisahkan bruto vs biaya (§11f) | read-only | +5,6 bps netto tanpa alpha baru |
| 3 | **Kurangi frekuensi**: berapa trade/day minimum agar edge per trade > 2× biaya? | read-only | 6,63 trade/hari × 8 bps adalah pembunuh senyap |
| 4 | **Buku**: susun komponen yang lolos langkah 1–3 + track non-tren, ukur %/48j tingkat-buku vs tangga 0,10/0,25/0,40 | perhitungan | target adalah keluaran buku |
| 5 | **Baru** sinyal/keluarga baru — dengan anggaran hipotesis, bukan dinding gate | praregistrasi | sinyal terakhir dalam urutan, bukan pertama |

**Satu hal yang TIDAK akan saya lakukan lagi:** menambah koin, menambah leverage, atau menambah uji demi mengejar p-value.

---

## 6. Yang saya akui salah (tanpa menyembunyikan)

1. Saya menjalankan 3 percobaan (PRAREG-23/24/25) pada lever yang salah tanpa lebih dulu membaca ulang kerangka bukti program (§4, §11, §8, H1).
2. Saya membangun mesin uji yang mengubah ambangnya sendiri setiap kali gagal (registry 72→78).
3. Saya baru menemukan `data/paper_test_*_state.json` (bukti forward venue nyata) **setelah** tiga kegagalan — padahal ada sejak Agustus.
4. Saya sempat akan mengklaim TWOWAY sebagai temuan positif; yang menghentikan saya adalah aturan daya statistik program sendiri (§4). Itu harus dicatat sebagai **kegagalan proses saya**, bukan sebagai kemenangan.

*Dokumen arah · Hermes Anantara v3 · 09-Okt-2026*
