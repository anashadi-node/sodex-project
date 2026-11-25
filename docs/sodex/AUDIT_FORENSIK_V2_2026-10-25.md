# AUDIT FORENSIK v2 — 5,6 Bulan Bukti, 9 Bulan Klaim

> **DIGANTIKAN oleh `AUDIT_FORENSIK_V3_2026-10-25.md`.**
> v2 salah: `capital_report` menjumlahkan window 6 jam **bergulir** dan
> mengurangkan fee **dua kali**. Angka v2 (15.647 RT, net −$592,04) tidak
> boleh dipakai. v3: 15.291 RT, net **+$32,60**. Dokumen ini disimpan
> sebagai jejak, bukan referensi.

**Tanggal:** 25 Okt 2026 · **Pengganti:** AUDIT_FORENSIK_7BULAN (v1)
**Prinsip:** setiap angka di bawah bisa dilacak ke berkas; yang tidak bisa, ditandai.

---

## 0. Tiga koreksi terhadap audit v1 (dilakukan sendiri)

| # | Klaim v1 | Yang benar | Kenapa v1 salah |
|---|---|---|---|
| 1 | "Edge kotor ≈ 0 di semua era" | **Tiga era berbeda tanda**: Jun −0,51 bps; Jul **+0,65 bps**; Sep +0,09%; Okt **−0,40%** (t=−3,48) | v1 hanya membaca track paper, mengabaikan ledger uang nyata |
| 2 | "Tidak ada catatan uang nyata" | Ada: **15.647 round-trip**, volume $5,24 jt, gross **+$222,60**, fee **$814,64**, net **−$592,04** | v1 hanya memindai `data/paper_test_*`, tidak `capital_report.jsonl` |
| 3 | "23 track, 1.638 trade" | Benar, tetapi **733 trade tidak punya tag bulan**; total tepatnya 1.639 | v1 memakai agregat tanpa memisahkan era |

Koreksi ini tidak mengubah arah kesimpulan, tetapi **mengubah derajatnya**: bukan "nol",
melainkan **edge ada tetapi 2–4× lebih kecil daripada biaya, dan memburuk seiring waktu.**

---

## 1. Batas bukti — 9 bulan tidak bisa diaudit dari mesin ini

| Artefak | Tanggal paling awal | Isi |
|---|---|---|
| Dokumen riset | **9 Mei 2026** | `Downloads/RISET_AI_AGENT_AUTOMATION_CRYPTO_TRADING.md` |
| Repo / commit pertama | **17 Mei 2026** | `5b6cc97 Day 1: Foundation Docker stack` |
| Catatan modal pertama | **24 Jun 2026** | `data/capital_report.jsonl` |
| Track paper pertama | **Agustus 2026** | `paper_test_*_state.json` |

Hari ini 25 Okt 2026 → **169 hari = 5,6 bulan** sejak artefak tertua yang ditemukan.
Pencarian di seluruh home (nama berkas sodex/anantara/trading, Jan–Mei) **tidak menemukan
apa pun sebelum 9 Mei**. Jika 3,5 bulan pertama (Jan–Apr) ada di mesin/akun lain
(Notion, ChatGPT, laptop lain, kertas), audit ini **tidak mencakupnya** — dan saya tidak
akan mengarang isinya.

**Konsekuensi:** setiap klaim "9 bulan gagal" harus dibaca sebagai
**"5,6 bulan yang terekam, semuanya gagal"**.

---

## 2. Timeline dengan angka (bukan narasi)

| Periode | Aktivitas | Hasil terukur |
|---|---|---|
| 9–16 Mei | Riset & rencana (dokumen) | 0 trade |
| 17 Mei–23 Jun | Bangun stack (Docker, FreqTrade, HMM, data lake, daemon, bridge) | 0 trade, 490 commit |
| 24–30 Jun | Live spot farm mulai | 4.350 RT · gross **−0,51 bps** · fee **2,87 bps** · **−$285,57** |
| **Juli** | Live spot farm, biaya turun (maker) | 9.909 RT · gross **+0,65 bps** · fee **1,29 bps** · **−$281,79** |
| Agustus | Live berhenti; track paper mulai | 73 trade paper · gross **+0,72%** · biaya **0,06%** (terlalu optimistis) |
| September | Live terakhir; model biaya dikoreksi | 1.388 RT · gross **−13,95 bps** · net **−18,99 bps** · 519 trade paper · gross +0,09% · biaya 0,23% |
| Oktober | Paper + audit + carry + P3 | 314 trade paper · gross **−0,40%** (t=−3,48) · 1.080 grid, 0 lolos |

**Titik tertinggi sepanjang proyek:** Juli 2026, SOL-USD.
**Gross +$367,65 dari 2.939 RT** — sementara **seluruh pasangan lain digabung −$145,05**.
Bahkan pada bulan terbaik, gross ($283,85) < fee ($565,64).

---

## 3. Tiga ledger yang saling bertentangan (akar kebingungan)

| Sumber | Cakupan | Gross | Fee | Net |
|---|---|---|---|---|
| `capital_report.jsonl` (harian) | Jun–Sep, 22 pair | +$222,60 | $814,64 | **−$592,04** |
| Dokumen `LEDGER_KEGAGALAN` (9 Okt) | s/d 5 Okt | profit $32,60 | fee $455,55 | rasio 14:1 |
| `paper_test_*_state.json` | Agu–Okt | gross −0,10% | biaya 0,18–0,23% | **−$1.094,61** |

Ketiganya mengukur hal berbeda (spot vs perp vs paper; periode berbeda), tetapi
**tidak ada satu sumber kebenaran**. Inilah sebabnya "kita pernah profit" dan
"kita selalu rugi" bisa sama-sama diucapkan tanpa berbohong. **Ini cacat tata kelola,
bukan sekadar bug.**

---

## 4. Aritmetika yang menentukan (dan belum pernah ditembus)

### 4.1 Era uang nyata (spot, $335 per round-trip)

| Ukuran | Nilai |
|---|---|
| Gross per RT | **+$0,0142** (0,42 bps) |
| Fee per RT | **$0,0521** (1,55 bps) |
| Net per RT | **−$0,0378** (−1,13 bps) |
| **Rasio gap** | **butuh 3,7× lipat gross, atau fee turun 73%** |

Juli (bulan terbaik): gross 0,648 bps vs fee 1,291 bps → **butuh tepat 2,0×**.

### 4.2 Era paper perp

| Bulan | Gross | Biaya | Net | t |
|---|---|---|---|---|
| Agu | +0,719% | 0,058% | +0,661% | +2,07 (n=73) |
| Sep | +0,090% | 0,230% | −0,140% | +0,86 (n=519) |
| Okt | −0,395% | 0,181% | −0,575% | **−3,48** (n=314) |

**Perhatikan Agustus:** net terlihat +0,66% karena biaya dicatat 5,8 bps. Setelah biaya
dikoreksi ke 23 bps di September, tanda berbalik. **"Profit" Agustus adalah artefak
model biaya, bukan edge.** Ini kesalahan yang paling mahal karena menyuap keputusan.

### 4.3 Target di level dolar

0,8% × $243 = **$1,95 per window 30 jam**. Satu posisi $335 yang bergerak 0,58% sudah
menghasilkan $1,95. **Target itu tidak gila secara absolut di ukuran akun ini** —
yang tidak pernah ada adalah **frekuensi dan konsistensi** untuk mencapainya ≥50% window.
(Di skala besar, 234%/tahun majemuk menjadi mustahil; di $243, secara aritmetika masih
mungkin. Yang gagal adalah edge-nya, bukan angkanya.)

---

## 5. Statistik: apa yang benar-benar terbukti

| Uji | Hasil | Tafsir |
|---|---|---|
| Gross Okt (n=314) | t = **−3,48** | **secara statistik lebih buruk dari acak** |
| Gross Agu (n=73) | t = +2,07 | tidak berarti: dengan 1.277 uji, t maksimum acak ≈3,5 |
| Grid 1.080 | 0 lolos, t terbaik 2,38 | di bawah ekspektasi acak |
| Neff (verifikasi independen, 81 simbol, 107 hari) | **6,7**; PC1 35,7%; ρ 0,298 | 81 simbol ≈ **7 taruhan**, bukan 81 |
| Power @ 0,8%/window, sd 9,69% | t=4,11 → **2.478 window = 8,5 tahun**; t=2,5 → 3,1 tahun | sertifikasi tidak mungkin dalam horizon proyek |
| Ledger 9-Okt | 132 window = 265 hari untuk **satu** mesin (BH) | konsisten dengan di atas |

**Neff 6,7 adalah temuan struktural:** diversifikasi lintas simbol hampir tidak menambah
taruhan independen. Menambah 50 koin tidak menambah 50 peluang — menambah ~1.

---

## 6. Lima akar, diurutkan menurut dampak terukur

| # | Akar | Angka kunci | Sifat |
|---|---|---|---|
| **R1** | **Inversi biaya–edge** | gross 0,42 bps vs fee 1,55 bps (nyata); 0,65 vs 1,29 (bulan terbaik) | Struktural — tidak bisa diakali dengan parameter |
| **R2** | **Model biaya understated 4×** | Agu: 5,8 bps → Sep: 23 bps; tanda PnL berbalik | Pengukuran — bisa diperbaiki, sudah diperbaiki |
| **R3** | **Horizon sertifikasi > horizon proyek** | 265 hari/mesin; 8,5 tahun di level window | Metodologis — ambang tidak cocok dengan unit target |
| **R4** | **Churn tanpa akumulasi** | 23 track, **13 nol trade**; hanya 2 track ≥100 trade; 163 entri registry; 1.080 dari satu grid | Perilaku proses |
| **R5** | **Likuiditas vs edge berbanding terbalik** | BTC 59% volume, ETH 85%; edge hanya di token illikuid | Struktur pasar |

**Urutan penting:** R1 adalah penyumbat. R3–R4 membuat R1 tidak pernah bisa
dibuktikan/dipatahkan secara bersih, sehingga tim berputar.

---

## 7. Yang **tidak** gagal (counter-ledger, terverifikasi)

- **Integritas data:** korelasi SoDEX vs Binance **0,999–1,000**; 24.276 bar sah.
- **Eksekusi:** 15.647 round-trip, tidak ada posisi telanjang, flag live = 0.
- **Kontrol negatif:** positif palsu ≈3–5% (sesuai harapan) → alat ukur tidak
  menghasilkan ilusi berlebih; karena itu hasil "gagal" bisa dipercaya.
- **Infrastruktur:** 1.155 commit, 183 skrip riset, 183 laporan, timer aktif.
- **Disiplin:** PRAREG beku, ambang tidak diubah setelah melihat hasil (PRAREG-19: 0/24 dilaporkan apa adanya).

---

## 8. Kenapa orang lain "berhasil" — persamaan, bukan cerita

Setiap sistem yang benar-benar profit harus memenuhi:

```
edge_kotor_per_trade (bps)  >  fee_per_trade (bps) + slippage (bps)
```

| Operator | Cara memenuhi |
|---|---|
| Market maker | fee negatif (rebate) atau spread > 2× fee |
| Arbitrase | edge 15–100 bps pada dislokasi, bukan prediksi arah |
| Trend harian | pergerakan 300–500 bps vs biaya 20 bps (rasio 15–25×) |
| Scalper retail | hampir selalu **gagal** karena edge 1–3 bps vs fee 5–10 bps |

Kita berada di baris terakhir: **edge 0,4–0,65 bps vs fee 1,3–1,55 bps**.
Bukan karena AI-nya kurang pintar, tetapi karena **mekanismenya berada di sisi persamaan
yang salah**.

---

## 9. Jalan keluar — masing-masing dengan ambang aritmetika yang harus dilewati

| Jalur | Ambang yang harus dilewati | Status | Catatan jujur |
|---|---|---|---|
| **P3 arb lintas venue** | gross ≥ **17,6 bps**; p99 terukur 18,7 → margin 1,1 bps | berjalan | margin tipis; freq 1,1% jam |
| **Listing/event SoDEX** | gerak hari-1 50–300 bps vs biaya 20 bps | **belum diuji** | satu-satunya kelas dengan rasio >5× |
| **Trend harian** | gerak 300–500 bps vs biaya 20 bps | **belum diuji** | horizon >30 jam; perlu izin definisi target |
| **Carry/funding** | 0,7 bps/hari → butuh modal ≫ $243 | NO-GO di $243 | bisa jalan bila modal naik 100× |
| **Turunkan turnover** | setiap 1 RT harus > fee | **lever paling murah** | bukan alpha baru, tapi memperbaiki rasio |

---

## 10. Keputusan yang menunggu Anda

1. **Arsip Jan–Apr**: apakah ada catatan 3,5 bulan pertama? Tanpa itu, audit sahnya 5,6 bulan.
2. **Bekukan pencarian TA directional** (905 trade sudah menutup pintunya dengan CI).
3. **Prioritas compute 30 hari**: P3 (jalan) + listing-event (uji baru).
4. **Target**: 0,8%/30j tetap, atau izinkan saya hitung horizon jujur per jalur?
5. **Satu sumber kebenaran PnL**: pilih `capital_report` atau trade-ledger, bukan tiga.

---

## 11. Batas jujur dokumen ini

- Saya tidak bisa membuktikan 0,8%/30j mustahil. Saya bisa membuktikan **mekanisme yang
  dipakai sekarang** tidak mencapainya, dengan CI yang mengecualikan target.
- Angka SOL Juli (+$367,65) **belum direkonsiliasi per-fill**. Ledger 9-Okt mencatat
  artefak harga basi di venue ini; sampai direkonsiliasi, angka itu **tidak boleh**
  dijadikan dasar strategi.
- Probabilitas jalur baru adalah penilaian, bukan hasil hitung.

**Kesimpulan satu paragraf:**
Selama 5,6 bulan yang terekam, sistem bekerja secara teknis dan mengukur dirinya dengan
jujur. Kegagalannya tunggal tetapi keras: **edge kotor yang dihasilkan (0,4–0,65 bps)
lebih kecil daripada biaya (1,3–1,55 bps)**, dan penurunan performa Oktober (t=−3,48)
menunjukkan edge itu bahkan memburuk. Semua masalah lain — churn, ambang 4,11, tiga
ledger, target bergeser — adalah **penguat**, bukan penyebab. Jalan keluarnya bukan AI
yang lebih pintar, melainkan **mekanisme yang edge-nya secara struktural lebih besar
daripada biayanya**: arbitrase, event, atau horizon yang lebih panjang.
