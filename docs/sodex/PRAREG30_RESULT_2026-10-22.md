# PRAREG-30 — HASIL UJI: **GAGAL**

**Crowding reversal berbasis open interest · 20 simbol · 1.048 trade**
Dijalankan pada dataset yang dibekukan: `b4b2425a06fbaa847b8883e90e3563ccec6ff3abafdf4944734bd1d3ee9b81b6`
(32.577 file, 1,31 GB). Tanggal uji: 22-Okt-2026. Modal berisiko: **$0**.

---

## 1. Putusan

> **Hipotesis salah.** Menumpuknya open interest tanpa kemajuan harga **tidak** diikuti
> pembalikan harga. Yang terukur justru sebaliknya — arah sinyal **lebih buruk daripada
> arah acak**, dan sudah rugi **sebelum** biaya.

Ini bukan "hampir lolos". Tidak ada satu pun gerbang inti yang lolos.

| # | Gerbang | Syarat | Hasil | Putusan |
|---|---|---|---|---|
| a | Daya statistik | n(OOS) ≥ 300 | **363** | ✅ LULUS |
| b | Expectancy bersih | net E > 0 di OOS | **−16,84 bps** | ❌ GAGAL |
| c | Kalahkan arah acak | ΔWR ≥ +3,0 pp, p<0,025 | **−3,58 pp**, p=0,4455 | ❌ GAGAL |
| d | Konsistensi IS/OOS | keduanya positif | **−20,80 / −16,84** | ❌ GAGAL |
| e | Replikasi 2021+2023 | tanda sama | −5,15 bps net (17 simbol; **gross +6,85**) | ⚠️ tanda sama, tapi negatif setelah biaya |
| f | Signifikansi | t ≥ +3,6 | **t = −3,58** (arah salah) | ❌ GAGAL |
| g | Bukan 3 simbol terbaik | tetap positif tanpanya | −27,07 bps | ❌ tetap negatif |

---

## 2. Angka utama (biaya 12 bps round-trip)

| Arm | n | Expectancy | Win rate | t-stat |
|---|---|---|---|---|
| **P — sinyal** | 1.048 | **−19,43 bps** | **46,66%** | **−3,58** |
| C — kontrol (arah acak) | 1.048 | −10,41 bps | 49,43% | −1,92 |
| Selisih P−C | — | −9,01 bps (p=0,30) | **−2,77 pp** (p=0,27) | — |

**Bacaan sederhana:** kalau Anda membalik koin untuk menentukan arah pada entry yang sama,
hasilnya **lebih baik** daripada mengikuti sinyal ini. Sinyal ini bukan netral — ia sedikit
merugikan.

### Bukti bahwa ini bukan kebetulan satu undian
Kontrol dijalankan ulang dengan **50 seed** berbeda:

| Metrik | Nilai |
|---|---|
| Rata-rata kontrol (50 seed) | **−11,64 ± 4,75 bps** |
| Rentang | −23,53 … −2,07 bps |
| ΔWR rata-rata | **−2,07 ± 1,48 pp** |
| Run yang ΔWR-nya positif | **10%** (5 dari 50) |

Jadi dalam 9 dari 10 dunia acak, sinyal ini tetap kalah dari koin.

---

## 3. Kegagalan bukan karena biaya

| Skenario biaya | Expectancy | WR |
|---|---|---|
| Gross (tanpa biaya) | **−7,43 bps** | 47,71% |
| Maker 4 bps RT | −11,43 bps | 47,14% |
| **Primer 12 bps RT** | **−19,43 bps** | 46,66% |
| Stress 20 bps RT | −27,43 bps | 45,90% |

Bahkan pada biaya nol, sinyal sudah rugi. Biaya hanya memperbesar kerugian yang sudah ada.

---

## 4. Di mana tepatnya ia gagal

| Pembelahan | n | Expectancy | WR |
|---|---|---|---|
| LONG | 493 | −12,24 bps | 46,65% |
| **SHORT** | 555 | **−25,81 bps** (t=−3,72) | 46,67% |
| 2024 | 362 | **−30,54 bps** | 43,65% |
| 2025 | 323 | −9,88 bps | 47,99% |
| 2026 | 363 | −16,84 bps | 48,48% |

Komposisi exit: **TP 443 (42,3%) · SL 496 (47,3%) · time-stop 109 (10,4%)**.
Dengan TP = SL, titik impas ada di 50%; realisasinya 46,7% — defisit ~3,3 pp.

**Simbol terburuk:** ARB −73,7 · XRP −60,6 · SOL −52,6 · AVAX −50,3 bps.
**Simbol terbaik:** OP +37,1 · BCH +21,9 · HYPE +19,8 bps — tetapi hanya **5 dari 20** yang positif.

---

## 5. Apa artinya (hati-hati, jangan melompat)

Pola yang konsisten: ketika OI melonjak sementara harga datar dan posisi top-trader
menumpuk di satu sisi, harga **tidak** berbalik — ia cenderung **melanjutkan** arah
crowding. Ini konsisten dengan mekanisme *squeeze/continuation*, bukan *mean reversion*.

**Tetapi:** membalik sinyal sekarang untuk mengklaim "momentum continuation" adalah
**data mining**. Itu hipotesis baru, harus lewat PRAREG baru (PRAREG-31) dengan hash
sendiri, diuji pada data yang belum dipakai menyusunnya. Saya **tidak** akan
mempresentasikan versi terbalik sebagai temuan.

---

## 6. Batasan yang harus dibaca jujur

1. **Ambang gerbang (b) sangat ketat secara desain.** Aturan "SL didahulukan bila TP dan SL
   tersentuh di bar yang sama" menciptakan bias struktural **−11,6 bps** (terukur dari 50 seed
   kontrol). Artinya edge sejati di bawah ~12 bps **tidak akan terdeteksi** oleh uji ini.
   Ini konsekuensi protokol yang dibekukan, bukan alasan mengubahnya sekarang.
2. **Biaya 12 bps = ~15% dari target 1 ATR** (ATR 1 jam ≈ 0,8%). Untuk strategi hold-8-jam,
   biaya adalah pecahan besar dari edge yang dikejar.
3. **OOS hanya 9 bulan** (n=363, lulus gerbang a tetapi tipis).
4. **Replikasi 2021+2023 hanya 17 simbol** (HYPE, ONDO, ENA belum terdaftar) dan **tanpa 2022**
   (kolom ratio kosong 87% — celah venue, terdokumentasi). Di era ini gross **+6,85 bps**
   tetapi net **−5,15 bps**: biaya 12 bps menghabiskan seluruh edge. Di 2024–2026 gross
   berbalik menjadi **−7,43 bps**. Arahnya memburuk seiring waktu, bukan acak.

---

## 7. Jejak audit

| Item | Nilai |
|---|---|
| Dokumen beku | `ddac7c11…` (tidak diubah) |
| Amandemen-1 | `31eaa8ea…` (celah 2022 + guard gap>24 jam) |
| Dataset | `b4b2425a…` (32.577 file, 1,31 GB) |
| Hasil mentah | `data/prereg30/results_primary.json`, `_is`, `_oos`, `_repl` |
| Registry trial | 135 → **138** entri (3 uji PRAREG-30 dicatat, semuanya gagal) |
| Kode | `scripts/research/prereg30_oi.py` (menolak jalan bila hash dokumen berubah) |

**Yang tidak dilakukan:** tidak ada parameter yang diubah setelah melihat hasil; tidak ada
simbol/jam yang dibuang; tidak ada promosi ke paper/live arm.

---

*PRAREG-30 · hasil final · 22-Okt-2026 · Hermes Anantara v3*
