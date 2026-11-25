# HASIL SAPUAN EKSTREM PRAREG-18 — SoDEX — 2026-10-09

Sidik-jari data: `reports/sodex/PANEL_FINGERPRINT.json` (`content_sha256_16`, `mtime_max`) —
wajib dicek sebelum membandingkan angka mana pun di dokumen ini.

---

## TL;DR — VONIS

| # | Uji | Hasil | Arti |
|---|-----|-------|------|
| 1 | Sapuan 108 sel (10 mekanisme × 3 panel × 2 hold × 2 arah), BH-FDR q=0,10 | **2 sel lolos** gerbang beku | ada kandidat — keduanya `-MOM_L21` (momentum 21 jam dibalik) di SoDEX 1h |
| 2 | Baterai stabilitas (4 saringan) atas 36 sel SoDEX 1h | **0 penyintas** | kandidat terbaik **MATI** |
| 3 | Dekomposisi kelas aset | kripto murni **−6,35** (t=−0,90); edge hanya di tokenized equity | artefak, bukan edge |
| 4 | Dekomposisi likuiditas | setengah likuid **−4,46** (t=−0,61); edge hanya di setengah illikuid | tidak bisa dieksekusi |
| 5 | Kapasitas venue | volume $2,4 jt/jam; **top-5 = 93,1%**; hanya 3 nama ≥$100 rb/jam | tujuan edge = kolam tanpa air |
| 6 | Integritas data | klines **ditulis ulang tiap ~1 jam** oleh armada service | angka riset bergeser tanpa perubahan kode — **diperbaiki** |

**Kesimpulan: arah riset cross-sectional (market-neutral 95 nama) di SoDEX 1 jam DITUTUP.**
Bukan "bukti belum cukup" — dibunuh tiga uji independen (stabilitas, kelas aset, kapasitas).
Target 0,8% tetap harga mati; yang berubah adalah **di mana** edge itu masih mungkin datang.

---

## 1. K1 — Sapuan 108 sel

Keluarga penuh dibayar BH-FDR q=0,10 atas **108 sel**. Hanya 2 lolos gerbang beku
(net>0, to≤1,5, |t_ctrl|<2, t≥1,96, S_ann≥2,3, S_fee2x≥1,8):

| Sel | net (bps) | S_ann | t | to | t_ctrl | S2x |
|-----|-----------|-------|---|----|--------|-----|
| `sodex_1h \| MOM_L21 \| H48 \| dibalik` | **+25,09** | +2,61 | +4,59 | 1,30 | −0,43 | +3,15 |
| `sodex_1h \| MOM_L21 \| H24 \| dibalik` | **+18,92** | +3,41 | +4,63 | 1,32 | −0,15 | +4,36 |

Ini 32% dan 24% dari target 80 bps/48 jam — kandidat terkuat yang pernah muncul di proyek ini.
Momen penting: sinyal momentum yang **sudah ada** di modul ternyata **bertanda salah**;
`MOM_L21` as-is = −24,91 (t=−2,47). Pembalikan arah sah diuji karena keluarga arah diumumkan
di muka dan dibayar BH.

**Lalu saya bunuh kandidat itu sendiri.** Bukan karena tidak lulus gerbang, tapi karena
gerbang itu terlalu lemah untuk pertanyaan yang benar.

## 2. K2 — Sensitivitas biaya

| Sinyal | bruto (bps) | to | net @1,14 bps/sisi | net @4,0 bps/sisi | biaya impas |
|--------|------------|----|--------------------|-------------------|-------------|
| `-MOM_L21` H48 | +19,91 | 1,30 | +18,43 | +14,72 | 15,37 bps/sisi |
| `RANGEPOS` H48 (arah reversi) | **−16,42** | 1,31 | +14,93 | +11,20 | mustahil (bruto negatif) |

Catatan penting: **`RANGEPOS` bruto NEGATIF** pada panel yang lebih baru — net positifnya
sepenuhnya bergantung pada… tidak ada. Angka ini berubah tanda antar-run karena panel bergerak
(lihat §7). Biaya bukan penyumbat utama: `-MOM_L21` masih untung bahkan di biaya 15 bps/sisi.
Penyumbatnya adalah **keberadaan edge itu sendiri** (§3–§5).

## 3. K3 — Pengondisian pra-perdagangan

| Mekanisme | pemisah | bawah (net) | atas (net) |
|-----------|---------|-------------|------------|
| `RANGEPOS` as-is | dispersi | **+22,80** | −0,57 |
| `RANGEPOS` as-is | jumlah nama | +13,56 | +8,22 |
| `-MOM_L21` | jumlah nama | **+19,60** | +8,57 |

`RANGEPOS` menaruh seluruh profitnya di window dengan dispersi rendah — persis pola yang
diharapkan dari **harga basi/quote bounce**, bukan dari salah harga yang bisa dipanen.
Pemisah "jumlah nama" juga menunjuk arah yang sama: makin banyak nama (makin banyak nama tipis),
makin besar "edge".

## 4. K4 — Korelasi portofolio (jadi tidak relevan)

9 kandidat net>0, ρ rata-rata **−0,049** → multiplier N=6 = 2,79×, N=8 = 3,57×.
Matematikanya bagus (spec North Star ρ≤0,1 tercapai!), **tetapi tidak ada satu pun mesin
yang lulus baterai stabilitas.** Portofolio dari mesin yang gugur = memperbesar artefak.

## 5. Baterai stabilitas — 36 sel, 0 penyintas

Saringan (post-hoc, **hanya untuk membunuh**, tidak pernah untuk mempromosikan):
S1 tanda net konsisten di 4 potongan sampel · S2 |t|≥2,0 · S3 kontribusi 5 window terbaik <35%
· S4 net>0 & t≥1,5 di setengah nama **paling likuid** (likuiditas = median volume trailing 720 bar, digeser 1 bar).

Pola vonis: **20 sel** (56%) mati karena tanda berbalik antar-potongan, **12** karena
outlier-driven (5 window terbaik > 35% dari total net), **4** karena gagal di nama likuid.
Tabel lengkap: `reports/sodex/STABILITY_BATTERY.json`.

Kasus terbaik, dibedah:

| Uji pada `-MOM_L21` H24 | Angka | Vonis |
|---|---|---|
| net 4 potongan sampel (penuh/6000/4000/3000 bar) | +8,2 / **−9,4** / +5,8 / **−7,3** | tanda berbalik 2× |
| kontribusi 5 window terbaik | **58%** dari total net; buang 10 teratas → **−0,40** | seluruh edge = 5 window |
| kripto murni (51 nama) | −6,35 (t=−0,90) | tidak ada edge |
| setengah likuid (47 nama) | −4,46 (t=−0,61) | tidak ada edge |
| SD per window | 105,7 bps (p1 −369, p99 +248) | mean 8 bps ditentukan outlier |

## 6. Kapasitas & anatomi venue SoDEX

Median volume/jam (90 hari, dari field `q` klines): **$2.399.002/jam** untuk seluruh venue.

| Peringkat | Nama | Bagian kumulatif |
|---|---|---|
| 1 | BTC ($1,42 jt/jam) | 59,0% |
| 2 | ETH ($0,62 jt/jam) | 85,0% |
| 3–5 | SOL, XAUT, ZEC | **93,1%** |
| 10 teratas | — | 98,2% |
| 20 teratas | — | 99,3% |

Nama dengan volume ≥ $10 rb/jam: **9 dari 99**. ≥ $100 rb/jam: **3**.
⇒ Semua mekanisme cross-sectional 95 nama beroperasi di kolam yang 99,3% airnya ada di
20 nama pertama. Edge yang hidup di setengah *illikuid* secara struktural tidak dapat dieksekusi.
**Di mana ada edge, di situ tidak ada likuiditas; di mana ada likuiditas, di situ tidak ada edge.**

### Bukti LANGSUNG harga basi (staleness) — penutup lingkaran

Fraksi bar 1 jam dengan return **tepat nol** (`|r| < 1e-12`), yaitu jam di mana harga tidak bergerak sama sekali:

| Nama | fraksi bar nol | Nama | fraksi bar nol |
|------|---------------|------|---------------|
| TON | 31% | META | 19% |
| BASED | 29% | NVDA | 18% |
| NATGAS | 22% | GOOGL | 17% |
| MSFT | 19% | US500 | 16% |
| AMZN | 19% | — | — |
| AAPL | 19% | **median 94 nama** | **1,3%** |

Sepuluh nama teratas hampir seluruhnya **tokenized equity/komoditas** (AAPL, AMZN, GOOGL, META,
MSFT, NVDA, US500, NATGAS) — persis kelas aset tempat "edge" `-MOM_L21` bersembunyi. Nama-nama itu
**12–15× lebih sering tidak bergerak** daripada nama biasa.

⇒ "Reversal 21 jam" di bucket equity adalah **mean-reversion mekanis dari harga yang tidak
diperbarui** (quote bounce), bukan salah harga yang bisa dipanen. Terukur, bukan dugaan.

### Kontra-uji lintas-venue — mengapa ini artefak, bukan efek pasar

`MOM_L21` H48 pada panel **Binance 1h** (venue likuid, tanpa equity-tokenized):
**+7,85 bps, t=1,20 — tidak signifikan, dan bertanda BERLAWANAN** dengan SoDEX (−24,91, t=−2,47).
Efek negatif momentum SoDEX **tidak ada di venue likuid** ⇒ memperkuat vonis: artefak venue,
bukan anomali pasar yang bisa diperdagangkan.

## 7. Temuan teknik: data bergerak = angka bergerak (DIPERBAIKI)

- `-MOM_L21` H24 terbaca **+18,92** (t=4,63) pukul 18:5x, lalu **+8,20** (t=2,04) pukul 19:0x —
  **tanpa perubahan kode**. Bahkan di dalam satu run, K1 (18,92) vs K2 (25,09).
- Sebab: `data/sodex_klines/**` **ditulis ulang berkala** (`anantara-sodex-realsync` tiap ~2 menit,
  puller per jam; MANIFEST mtime 12:05:39Z, saya membaca 12:08Z). Panel yang sedang berubah +
  mean yang ditentukan outlier = hasil tidak reproducible.
- **Perbaikan (selesai):** `scripts/research/klines_snapshot.py` — `fingerprint(interval)` mencatat
  `content_sha256_16`, `manifest_sha256_16`, `mtime_max`, rentang bar; `--freeze` menyalin snapshot.
  Ketiga artefak riset baru sudah mencatat sidik-jari di JSON keluarannya. Riwayat: `reports/sodex/PANEL_FINGERPRINT.json`.
- Uji reproducibility: baterai dijalankan dua kali terpisah → angka **identik** (net 8,19;
  potongan −9,5/+5,7/−7,3) selama mtime data tidak berubah. Discipline ini yang membuat angka bisa dipercaya.

## 8. Konsekuensi — BAR BARU yang terukur (dari target yang sama, bukan target baru)

Karena target adalah **imbal hasil** (80 bps/48 jam), bukan Sharpe, leverage mengalikan mean:
`L = 80 / μ_mentah`. Tetapi ekor ikut terkali, sementara jarak likuidasi menyusut (`1/L − mmr`).

Disiplin usulan (**perlu persetujuan — saya tidak mengubah aturan sepihak**):
*ekor p5 satu window ≤ 1/3 jarak likuidasi (mmr 1%)*.

Dengan disiplin itu, dari data SoDEX (sd return 48 jam empiris):

| Instrumen | sd 48j | L maks | μ mentah yang perlu | **S_ann yang perlu** | p5 @L | jarak likuidasi |
|-----------|--------|--------|--------------------|----------------------|-------|-----------------|
| BTC | 3,25% | 2,45× | 32,7 bps/48j | **1,36** | −13,1% | 39,8% |
| ETH | 4,53% | 2,05× | 39,0 bps/48j | **1,16** | −15,3% | 47,8% |
| SOL | 4,77% | 2,00× | 40,0 bps/48j | **1,13** | −15,7% | 49,0% |

**Angka tunggal yang harus dikejar: μ_net ≥ ~32 bps per 48 jam pada modal tanpa leverage
(≈ S_ann 1,2–1,4 pada BTC/ETH/SOL bila diukur sebagai Sharpe directional).**

Mengapa ini kabar *baik* meski sapuan tadi gagal:

- Cross-sectional market-neutral menuntut **S_ann ≥ 5,90** untuk tersertifikasi dalam 42 hari —
  dan portofolionya bergantung pada 20 nama illikuid yang tak punya kapasitas. Pintu itu tertutup.
- Strategi **directional pada 3 nama likuid** menuntut bar yang jauh lebih rendah (S_ann ≈ 1,2–1,4),
  pasar yang benar-benar ada ($2,2 jt/jam di BTC+ETH), dan leveragenya **survive** (jarak likuidasi 40–49%).
- Beda sebabnya: cross-sectional dengan μ/σ ≈ 0,08 butuh **L ≈ 7×** → jarak likuidasi 12,7% < ekor p5 15,6% ⇒ mati saat likuidasi. Strategi directional dengan σ 3,25% cukup **L = 2,45×**.
  **Volatilitas rendah adalah musuh leverage** — strategi low-vol tidak bisa dilever ke target tinggi.

Bar ini juga **terukur pada mesin yang sudah ada** (CEX-Binance & Pre-Gain paper, HL) yang
memang bertrading BTC/ETH — bukan laboratorium baru.

## 9. Instrumen forward tetap hidup (mode D)

`rangepos_forward_eval.py` kini menunjukkan **`bar_fwd = 9`** untuk SoDEX (data mulai mengalir
melewati `freeze_ts`); Binance masih 0 (klines Binance belum diperbarui). Verdict tetap
TIDAK_KONKLUSIF — benar, karena jendela forward memang belum punya satu pun periode 48 jam penuh.
Instrumen berjalan read-only lewat `sodex-rangepos-forward.timer` (tiap 6 jam).

## 10. Rekomendasi (menunggu keputusan Mas Anas)

1. **Tutup jalur cross-sectional SoDEX 1h** — hentikan alokasi riset ke keluarga 95-nama.
   (Bukan mengubah target; mengakui satu jalur sudah diuji tuntas dan gagal.)
2. **Setujui disiplin ekor p5 ≤ 1/3 jarak likuidasi** (§8) sebagai aturan leverage —
   tanpa ini, setiap keputusan leverage jadi selera, bukan angka.
3. **Alihkan riset ke arah directional BTC/ETH/SOL** dengan bar μ ≥ 32 bps/48 jam, memakai
   mesin paper yang sudah ada (ukuran keberhasilan: S_ann ≥ 1,35 pada 42 hari forward).
4. **Wajibkan sidik-jari data** pada setiap artefak riset (§7) — sudah diimplementasikan,
   tinggal dijadikan syarat di template laporan.

---

*Artefak: `reports/sodex/SWEEP_EKSTREM_K1K4.json`, `MOM_L21_LIKUIDITAS.json`,
`STABILITY_BATTERY.json`, `PANEL_FINGERPRINT.json`; skrip: `sodex_extreme_sweep.py`,
`sodex_mom_l21_venue_test.py`, `sodex_stability_battery.py`, `klines_snapshot.py`.*
