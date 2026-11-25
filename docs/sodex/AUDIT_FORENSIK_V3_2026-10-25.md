# AUDIT FORENSIK v3 — Koreksi Total Atas v2

**Tanggal:** 25 Oktober 2026 · 19:20 WIB (rev.2 — koreksi mode eksekusi)
**Menggantikan:** `AUDIT_FORENSIK_V2_2026-10-25.md`
**Alasan:** v2 salah besar. Bukan salah kecil — arah kesimpulannya terbalik.
**Rev.2 menambah koreksi yang lebih penting:** 97,9% baris ledger ternyata **simulasi**,
bukan uang nyata. Lihat §3b.

---

## 1. Ringkasan koreksi

| Klaim v2 | Fakta v3 | Selisih |
|---|---|---|
| 15.647 RT | **15.291 RT** | −356 (2,3%) |
| Volume $5,24 jt | **$1,11 jt** | 4,7× lebih kecil |
| Gross +$222,60 (0,42 bps) | **+$488,15 (4,41 bps)** | 22× lebih besar |
| Fee $814,64 (1,55 bps) | **$455,55 (4,12 bps)** | 1,8× lebih kecil |
| Net **−$592,04** | **+$32,60** | **tanda berbalik** |
| "Edge kalah 3,7× dari biaya" | **Edge 4,41 bps vs fee 4,12 bps → net +0,29 bps** | edge menang tipis |
| "15.291 RT uang nyata" (klaim v3 awal) | **Hanya 325 RT (3,5 hari, 26–29 Sep) terbukti live** | **97,9% simulasi** |

Vonis v2 — *"edge 2–4× lebih kecil dari biaya"* — **salah**. Yang benar untuk
**data gabungan**: edge kotor 4,41 bps menutup fee 4,12 bps, sisa 0,29 bps.

Vonis yang **lebih penting** (rev.2): pada **satu-satunya sampel live yang bisa
dibuktikan** (325 RT, 26–29 Sep), gross hanya **2,9 bps** sementara fee **10,0 bps**
→ **net −7,1 bps**. Sampel simulasi tidak boleh dipakai mengklaim profitabilitas.


---

## 2. Dua bug yang menyebabkan v2 salah

### Bug 1 — menjumlahkan window bergulir

`scripts/capital_report.py:262`:

```sql
SELECT COUNT(*), SUM(net_pnl), SUM(volume) FROM rts
WHERE ts_close > datetime('now','-6 hours')
```

`rt_6h` adalah **window 6 jam bergulir**, dan laporan ditulis jauh lebih sering
dari tiap 6 jam. Bukti dari 227 record ber-`rt_6h`:

- 25 record berjarak **<1 jam** dari record sebelumnya
- 193 record berjarak **<5 jam**
- 3 record pertama: `113 RT` pada 23:07:46, `113` pada 23:07:52 (6,5 detik), `113` pada 23:08:53

Menjumlahkan semuanya = **menghitung trade yang sama berkali-kali**. Hasilnya
volume membengkak 4,7× dan gross terdistorsi.

### Bug 2 — fee dikurangkan dua kali

`anantara/sodex_twin_engine.py:2511`:

```python
pnl = (o.price - bpx) * take - vol * self.cfg.spot_maker_fee
```

`net_pnl` **sudah net-of-fee**. Tapi `capital_report.py:296`:

```python
"net_6h": round((pnl6 or 0) - fee6, 4)
```

mengurangkan fee **lagi**. Jadi setiap laporan menghitung biaya dua kali:
sekali di ledger, sekali di agregator.

Efek gabungan: gross terlihat 0,42 bps dan net −$592, padahal gross 4,41 bps
dan net +$32,60.

---

## 3. Sumber kebenaran baru: `twin_engine.db` (dengan satu syarat besar)

Tabel `rts` (append-only sejak insiden 28-Sep) adalah ledger transaksi, bukan
agregat. 15.291 baris, `net_pnl` sudah bersih dari fee; `fills` menyimpan fee
mentah (70.194 fill). **Syaratnya: kolom mode tidak ada** — lihat §3b.

### Per bulan

| Bulan | RT | Volume $ | Net $ | Net bps | Mode terbukti |
|---|---:|---:|---:|---:|---|
| Jun 2026 | 13.877 | 618.621 | **+48,45** | +0,78 | simulasi |
| Jul 2026 | 1.089 | 485.385 | **−14,02** | −0,29 | simulasi |
| Agu 2026 | 0 | 0 | 0,00 | — | — |
| Sep 2026 | 325 | 2.569 | **−1,83** | −7,13 | **LIVE (26–29 Sep)** |
| **Total** | **15.291** | **1.106.575** | **+32,60** | **+0,29** | 97,9% simulasi |

### Per engine

| Engine | RT | Volume $ | Gross $ | Fee $ | Net $ | Net bps |
|---|---:|---:|---:|---:|---:|---:|
| E1 (spot maker) | 13.092 | 142.733 | +350,05 | 264,80 | **+85,25** | **+5,97** |
| E2 (perp maker) | 605 | 356.366 | +70,74 | 106,64 | −35,90 | −1,01 |
| PVE (perp volume) | 1.594 | 607.476 | +67,36 | 84,12 | −16,76 | −0,28 |
| **Total** | **15.291** | **1.106.575** | **+488,15** | **455,55** | **+32,60** | **+0,29** |

Ekonomi sebenarnya: **gross 4,41 bps − fee 4,12 bps = net 0,29 bps**.
Fee menyerap **93,3%** dari edge kotor.

### 3b. Temuan rev.2 — 97,9% ledger adalah simulasi, bukan uang nyata

`twin_engine.db` tidak punya kolom mode. Karena itu klasifikasi harus dari bukti
luar, dan buktinya sepihak:

| Bukti | Isi |
|---|---|
| Header `sodex_twin_engine.py` | `DRY_RUN` adalah default; live butuh `--live` + `CONFIRM_LIVE=YES` + konfirmasi manual |
| `logs/twin_live.log`, `logs/e1_microlive.log` | Banner `Non-interactive LIVE start` dan `Twin-Engine start [LIVE]` **hanya 26–29 Sep 2026** (146 start; 49 di antaranya 26 Sep) |
| Presisi harga fill | Jun: `0.0000028011389139929120023` (25 desimal → simulator). Sep: `0.000004447252125` (presisi venue) |
| `.env` | `SODEX_SPOT_FARM_LIVE=0` |

| Mode | RT | Volume $ | Gross $ | Fee $ | Net $ | Gross bps | Fee bps | Net bps |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **LIVE** (26–29 Sep) | 325 | 2.569 | **+0,75** | 2,58 | **−1,83** | **2,9** | **10,0** | **−7,1** |
| Simulasi (Jun–Jul) | 14.966 | 1.104.006 | +487,40 | 452,97 | +34,43 | 4,41 | 4,10 | +0,31 |

Konsekuensi yang harus diterima:

1. **Kisah "PEPE launch +$87 dalam 2 hari" adalah hasil simulasi.** Ia tidak
   membuktikan mesin pernah mencetak uang nyata.
2. **Bukti live = 3,5 hari, 325 RT, net −$1,83.** Dengan gross 2,9 bps < fee 10,0 bps,
   sampel live konsisten dengan **edge negatif setelah biaya**, bukan nol.
3. Klaim "5,6 bulan rekam jejak" harus dibaca **5,6 bulan pengembangan +
   3,5 hari eksekusi nyata**.

4. 319 baris `rts` bertanggal 28-Sep adalah **backfill** (timestamp menumpuk di
   detik yang sama, `rt_id` berurutan), tetapi `fills` tersebar 26–29 Sep →
   perdagangan live nyata, hanya stempel waktunya yang rusak.

**Perbaikan struktural (25 Okt 19:15 WIB).** Kolom `mode` kini ada di `rts` dan
`fills`; mesin mencap `live` hanya setelah tiga kunci live lolos, default
`dry_run`. Baris lama di-backfill dari bukti yang sama: **325 RT live / 14.966
dry_run**, `fills` 934 live / 69.260 dry_run. `ledger_truth.summarize()` memakai
kolom itu sebagai bukti primer dan hanya jatuh ke klasifikasi tanggal bila kolom
masih NULL (DB lama).

Untuk mencegah kekeliruan ini terulang, `scripts/research/ledger_truth.py`
sekarang mengembalikan blok `live`, `sim`, dan `live_window`, dan
`tests/test_audit_ledger_reconciliation.py` menguji pemisahan itu.

---

## 4. Di mana laba simulasi benar-benar berasal

E1 terlihat paling sehat (+$85,25; 5,97 bps), tetapi terkonsentrasi ekstrem:

| Tanggal | RT | Volume $ | Net $ | Net bps |
|---|---:|---:|---:|---:|
| 12 Jun | 5.699 | 56.657 | **+41,38** | +7,30 |
| 13 Jun | 6.439 | 64.459 | **+45,85** | +7,11 |
| 14 Jun | 252 | 2.578 | +1,88 | +7,30 |
| 21–23 Jun | 377 | 16.471 | −2,02 | −1,23 |
| 28–29 Sep (backfill) | 325 | 2.569 | −1,83 | −6,97 |

**+$87,23 dari dua hari pertama** (12–13 Jun) = 102% dari seluruh laba E1.
Setelah itu E1 mendekati nol lalu negatif. 12.652 dari 13.092 RT E1 adalah
**PEPE/USDC** — ini **market making saat peluncuran**, bukan strategi yang
bertahan.

Kesimpulan yang lebih tajam dari v2 (**dan hanya berlaku untuk data simulasi**):
yang pernah menghasilkan uang **di simulator** bukan sinyal arah, bukan AI, dan
bukan timing — melainkan **menyediakan likuiditas di jendela peluncuran aset**,
lalu edge itu hilang dalam ~48 jam. Pada eksekusi live 3,5 hari, pola itu belum
terbukti dan hasilnya negatif (−7,1 bps).

Catatan integritas: 319 baris bertanggal 28-Sep adalah **backfill** dari insiden
`INSERT OR REPLACE` yang menimpa riwayat (didokumentasikan di `rt_close`), bukan
trading baru. Tidak ada `rt_id` duplikat; tidak ada sufiks `~`.

---

## 5. Kalau net +$32,60, kenapa equity turun $502?

Jawaban jujur: **dari data lokal, pertanyaan ini tidak bisa dijawab.** Equity yang
tersedia bukan oracle yang layak dipercaya.

| Fakta | Angka |
|---|---|
| Snapshot `capital_report` | 618 (24 Jun – 25 Okt) |
| Snapshot dengan `equity_valid=True` | **53 (8,6%)**; 590 tanpa flag, 21 `False` |
| Rentang nilai | **$4,07 – $1.183,22** |
| Equity awal → akhir | 746,78 → 244,78 (**−502,00**) |
| Lompatan >$25 antar snapshot | **88**, termasuk −278,40 lalu **+714,84 dalam 60 detik** |

Pola itu adalah **artefak valuasi** (spot+perp memakai harga estimasi dan
fail-open; pernah understate 21% saat endpoint spot 429), bukan kurva PnL.
Tidak ada catatan deposit/withdraw, dan `ground_truth.py` tidak menemukan akun
HL yang bisa dibaca (0 akun, 0 posisi) sehingga tidak ada oracle wallet kedua.

Kandidat penjelas — penarikan, valuasi inventori, migrasi wallet — **semuanya
belum terbukti**. Yang bisa dinyatakan: **equity tidak boleh dipakai sebagai
sumber PnL, dan penurunan $502 tidak boleh diklaim sebagai kerugian trading.**
Satu-satunya angka PnL yang dapat diaudit adalah `rts`, dengan batas mode di §3b.

---

## 6. Akar masalah versi v3

| # | Akar | Angka | Sifat |
|---|---|---|---|
| R1 | **Fee > edge pada sampel live** | live gross 2,9 vs fee 10,0 bps → net −7,1 | Struktural |
| R2 | **Edge hanya ada di jendela peluncuran — dan hanya di simulator** | +$87 dari 2 hari simulasi; live 3,5 hari −$1,83 | Waktu-terbatas |
| R3 | **Agregator PnL salah 2×** | window bergulir + fee ganda | Pengukuran (diperbaiki) |
| R4 | **Churn** | PVE $607k volume → −$16,76 (simulasi) | Proses |
| R5 | **Horizon sertifikasi > horizon proyek** | 8,5 tahun pada t=4,11 | Metodologis |
| R6 | **Mode tidak tercatat di ledger** | 1 tabel mencampur 14.966 RT simulasi + 325 RT live | Pengukuran (diperbaiki) |

R1 sekarang dihitung pada sampel live, bukan gabungan. R2 turun status: bukti
laba peluncuran berasal dari simulator. R3 dan R6 sudah diperbaiki; R4 dan R5 tetap.

---

## 7. Riset baru: 18 listing era-real

Deteksi dari bar pertama `data/sodex_klines/1h` (≥12 Jun 2026):

| Metrik | +6 jam | +24 jam | +48 jam | +7 hari |
|---|---:|---:|---:|---:|
| Mean | −0,04% | **−0,03%** | +5,44% | −2,82% |
| Median | −0,75% | **−2,84%** | −1,49% | −0,29% |
| Rentang | −9,5…+10,8 | −17,8…**+35,3** | −20,7…**+60,8** | −29,4…+22,2 |

Bacaan jujur: **median negatif, mean nol**. Short semua listing pada +24 jam
tidak menghasilkan apa pun karena ekor kanan (PONS +35%, NIULAI +12%, QNT +8,9%)
menghapus seluruh keuntungan short. Ini **bukan edge satu arah**; ia butuh aturan
kondisional dan n=18 terlalu kecil untuk diklaim. Status: **pra-registrasi
forward-test**, bukan sinyal.

---

## 8. Apa yang berubah untuk keputusan

1. **Tidak ada dasar empiris live untuk target 0,8%/30 jam.** Satu-satunya
   sampel live (3,5 hari, $2.569 volume) menghasilkan **−7,1 bps**. Proyek belum
   punya satu pun periode live yang positif dan terukur.
2. **Jangan kejar sinyal arah baru.** Sapuan 336 sel SoDEX + 84 sel Binance = 0 PASS;
   reversal yang tampak paling kuat (t klaster 1,65) hilang di Binance (0,31).
3. **Jalur yang masih layak diuji:** P3 arbitrase lintas venue (read-only, belum ada
   event), dan **launch-MM dengan size kecil yang dicatat sebagai live** — bukan
   simulasi — minimal 30 hari sebelum klaim apa pun.
4. **Perbaiki pengukuran dulu, sebelum menambah strategi:**
   - tambahkan kolom `mode` (`live`/`dry_run`) ke `rts` dan `fills`;
   - hentikan penjumlahan window bergulir dan fee ganda di `capital_report`;
   - ganti equity snapshot fail-open dengan oracle wallet yang tervalidasi.
5. **Koreksi klaim "5,6 bulan rekam jejak"** di seluruh dokumen menjadi
   **5,6 bulan pengembangan + 3,5 hari eksekusi live**.

---

## 9. Reproduksi

```bash
# ledger mentah
sqlite3 twin_engine.db "select count(*),sum(cast(volume as real)),sum(cast(net_pnl as real)) from rts;"
sqlite3 twin_engine.db "select sum(cast(fee as real)) from fills;"

# bukti net_pnl sudah net-of-fee
grep -n "pnl = (o.price - bpx)" anantara/sodex_twin_engine.py
grep -n "net_6h" scripts/capital_report.py

# bukti mode: hanya 26-29 Sep yang live
grep -h "start \[LIVE\]" logs/twin_live.log logs/e1_microlive.log | cut -c1-10 | sort | uniq -c
sqlite3 twin_engine.db "select substr(ts,1,10),count(*) from fills group by 1;"

# klasifikasi mode + angka live/sim
python3 -c "from scripts.research.ledger_truth import summarize as s; d=s(); print(d['live'], d['sim'])"

# backfill kolom mode untuk DB lama (dry-run dulu, lalu --apply)
python3 scripts/research/migrate_ledger_mode.py twin_engine.db
```

## 10. Keterbatasan

- **Bukti live hanya 3,5 hari / 325 RT / $2.569 volume.** Itu tidak cukup untuk
  menyimpulkan apa pun selain "belum terbukti".
- **Kolom `mode` baru ada sejak 25 Okt 2026.** Baris lama di-backfill dari bukti
  tanggal (325 live), sehingga baris yang salah tanggal tetap bisa salah klasifikasi;
  log banner bisa hilang saat rotasi.
- `rts` mulai 12 Jun 2026; Jan–Mei tetap tidak ada bukti.
- 319 baris 28-Sep adalah backfill; timestamp-nya tidak bisa dipakai untuk
  analisis intraday (gunakan `fills`).
- Fee E1 18,5 bps/volume (gabungan) lebih tinggi dari tarif teoretis 6,68 bps —
  indikasi banyak partial fill per RT; belum diurai per fill.
- Equity tidak dapat direkonsiliasi tanpa mutasi wallet (deposit/withdraw);
  91,4% snapshot tidak tervalidasi.
- Data harga Jun–Jul berasal dari mesin yang sama dengan fill simulasi; akurasi
  harga acuan tidak diverifikasi silang ke venue pada periode itu.
