# D06 — Breakdown per-Sisi: Constraint T1 adalah BIAYA, bukan Ukuran Sampel

**Tanggal:** 2026-10-04
**Divisi:** SoDEX
**Alat:** `scripts/sodex_side_breakdown.py` (read-only, reproducible)
**Acuan:** `docs/handover/RISET_TO_DIVISI_2026-10-01/PERINTAH_1_SoDEX.md`
**Registry:** 4 trial baru dicatat → `n_trials_total = 10`

---

## 1. Mengapa analisis ini ada

Harness `sodex_harness_reeval.py` menilai tiap track **secara agregat** (LONG + SHORT
dicampur), dengan satu pengecualian: blok khusus `twoway SHORT`. Akibatnya
pertanyaan paling menentukan tidak pernah dijawab dengan angka:

> **Kaki mana yang membawa edge — LONG atau SHORT?**

Tanpa jawaban ini, verdict agregat `twoway` menyesatkan: ia mencampur satu kaki
tanpa edge dengan satu kaki ber-edge besar, dan hasilnya tampak "hampir nol".

---

## 2. Hasil (harness beku, fee RT = 8 bps, n_trials = 7)

| track | sisi | n | WR | edge | cost 1× | cost 2× | fee impas @2× | Sharpe | PASS |
|---|---|---:|---:|---:|---:|---:|---:|---:|:--:|
| swing | LONG | 387 | 36,18% | −12,26 bps | −20,26 bps | −28,26 bps | −6,13 bps | −1,43 | ❌ |
| **twoway** | **LONG** | **325** | **45,23%** | **+8,05 bps** | **+0,05 bps** | **−7,95 bps** | **4,03 bps** | **0,70** | ❌ |
| **twoway** | **SHORT** | **42** | **33,33%** | **+60,94 bps** | **+52,94 bps** | **+44,94 bps** | **30,47 bps** | **5,31** | ❌ |
| realwide | LONG | 235 | 48,51% | −3,68 bps | −11,68 bps | −19,68 bps | −1,84 bps | −0,34 | ❌ |

*(swing SHORT dan realwide SHORT: n = 0 — kedua track itu LONG-only.)*

### Definisi "fee impas @2×"

Fee RT di mana hasil bersih **tepat nol** pada stress 2× biaya:

```
fee_impas = (edge / 2) × 10.000     [bps]
```

Kaki dengan `fee_impas > 8 bps` akan **lulus** stress 2× pada fee sekarang.

---

## 3. Temuan

### 3.1 Constraint T1 adalah BIAYA

Kaki LONG `twoway` — satu-satunya dengan **n besar (325)** — punya edge
**+8,05 bps**, sementara fee RT = **8,00 bps**.

```
edge   +8,05 bps
fee    -8,00 bps   (cost 1x)
-------------------
net    +0,05 bps   <-- praktis NOL
```

Pada cost 2× (fee 16 bps): **−7,95 bps**. Gagal **hanya karena biaya**.

Ini bukan masalah ukuran sampel, bukan masalah jendela 30 hari, dan bukan
masalah funding. Yang membatasi adalah **selisih tipis antara edge dan fee**.

### 3.2 Kaki ber-edge besar digerbangi rezim

Kaki SHORT `twoway` punya edge **+60,94 bps = 7,6× fee**; bahkan fee bisa
**naik 3,8× (8 → 30,47 bps)** sebelum gagal. Tetapi ia digerbangi **death-cross
(SMA50 < SMA200)** — gate struktural di `scripts/paper_test_twoway.py`:

> *"SHORT now requires death-cross (SMA50 < SMA200) as hard structural gate.
> Root cause of SHORT WR=44%: entries fired on any c<SMA50 including in bull
> uptrends where the bear leg is a pullback, not a real downtrend."*

Akibatnya:

```
sebaran SHORT twoway : 2026-08 = 37 trade | 2026-09 = 5 trade
SHORT terakhir       : 2026-09-01
sejak itu            : 31 HARI -- NOL SHORT
```

### 3.3 Karena itu, 27 hari runway forward TIDAK akan menghasilkan T1-PASS

- Kaki **LONG** akan terus terkumpul (≈ 5–6 trade/hari), tapi edge-nya nol
  bersih → **verdict tidak berubah**.
- Kaki **SHORT** tidak akan muncul **tanpa death-cross** → **nol bukti baru**.

Kedua event itu **tidak dapat dijadwalkan**. Menunggu bukan strategi.

### 3.4 Dua track lain tidak punya harapan sama sekali

`swing LONG` (−12,26 bps) dan `realwide LONG` (−3,68 bps) **negatif sebelum
biaya**. Bahkan pada fee nol keduanya rugi. Tidak ada perbaikan eksekusi yang
menolong.

---

## 4. Implikasi terhadap T1

| gate T1 | status | alasan |
|---|---|---|
| beta-netral | ✅ terukur | harness |
| biaya 1× & 2× | ❌ | LONG di garis nol; SHORT tak muncul |
| funding/borrow lengkap | ⚠️ | historis mustahil; forward OK tapi 0 SHORT |
| n ≥ 30 | ✅ LONG (325) / ❌ SHORT (42, beku) | — |

**Kesimpulan:** T1 **tidak dapat dilampaui** oleh track yang tersedia pada rezim
BULL/CHOP saat ini. Ini **bukan** kegagalan data atau bug — ini temuan struktural.

---

## 5. Opsi (SEMUA butuh approval Owner — tidak ada yang dijalankan)

| # | opsi | angka | catatan |
|---|---|---|---|
| **A** | **Turunkan fee ke ≤ 4,03 bps** (maker/rebate) | LONG lulus @2× pada 4,03 bps | Jalur **pengukuran/eksekusi** — diizinkan dokumen riset. `E1 maker` saat ini **DIBEKUKAN** |
| B | Tunggu death-cross (BEAR) | SHORT hidup lagi (fee impas 30,47 bps) | Tidak dapat dijadwalkan; deadline 03-Nov berisiko |
| C | Bangun mesin dengan edge struktural > 2× fee | butuh edge ≥ 16 bps | **DILARANG** dokumen riset sampai gate lulus |
| D | Longgarkan gate (cost 2× → 1×) | LONG "lulus" @1× (+0,05 bps) | **Perubahan parameter fundamental → HARGA MATI dipertanyakan** |

**Rekomendasi analisis terbaik: opsi A.** Ia mengubah masalah dari "menunggu
pasar" (tak terkendali) menjadi **target teknis terukur** (fee ≤ 4,03 bps), tanpa
menyentuh target, tanpa leverage, dan tepat berada di ruang lingkup yang
diizinkan dokumen riset ("measurement/funding/capital validation pipeline only").

---

## 6. Reproduksi

```bash
# read-only, tidak menulis registry
python3 scripts/sodex_side_breakdown.py --no-log

# menulis 4 trial ke registry (memperketat penalti multiple-testing semua trial)
python3 scripts/sodex_side_breakdown.py
```

**Fail-closed dipertahankan:** gate SHORT di `paper_test_twoway.py` **TIDAK**
disentuh. Track non-lolos **tidak** dipromosikan. `unfreeze = NO`.

---

*D06 — Hermes Anantara v3 | SoDEX | 2026-10-04*
