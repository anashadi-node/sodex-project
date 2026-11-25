# SPEC4 — VERIFIKASI REPRODUKSIBILITAS & PENUTUPAN 2 CRASH — 2026-10-07

**Tujuan:** membuktikan bahwa skrip SPEC4 yang **sudah di-commit** (`scripts/sodex_spec4_micro.py`
@ `5c6c8cc`) benar-benar berjalan dan mereproduksi hasil, sekaligus menutup **dua crash trace**
yang ditemukan pada batch proses latar. Crash trace itu **historis** (dari sebelum perbaikan),
tetapi saya rekam di sini karena mendiamkannya akan melebih-lebihkan kerapian kerja ini.

---

## 1. Dua crash trace yang ditemukan

| # | Proses | Situs | Pesan | Diagnosis |
|---|---|---|---|---|
| C1 | `proc_3c443b25b58e` | `stationary_bootstrap_p`, `means[done:done+c] = net[idx].mean(axis=1)` | `index 36176 is out of bounds for axis 0 with size 36176` | **Off-by-one**: `starts ∈ [0, n-1]` lalu ditambah `off ∈ [0, L-1]` **tanpa modulo** → indeks bisa mencapai `n-1+L-1 ≥ n` |
| C2 | `proc_76e4f171b23c` | `r = np.log(cs[x] / cs[e])` | `index 29660634 is out of bounds for axis 0 with size 195462` | **Epoch dipakai sebagai indeks posisi**: `x` = nilai menit epoch (29.660.634) dipakai untuk mengindeks array panjang 195.462 — inilah bug alignment grid (deviasi D1) |
| C1 tambahan | `proc_3c443b25b58e` | — | `binance: []` + `scratch/binance_1m/` **kosong** | Proses ini berjalan **sebelum** unduhan Binance 1m selesai → bukan bug, tapi bukti urutan waktu |

Kedua crash adalah **cara kerja yang benar**: harness gagal keras dan berisik, bukan diam-diam
menghasilkan angka salah. Itu lebih baik daripada bug D9 (yang senyap).

## 2. Perbaikan yang terkonfirmasi ADA di versi ter-commit

| Situs | Baris (versi ter-commit) | Kode | Jaminan |
|---|---:|---|---|
| C1 | 119–120 | `idx = ((starts[:,:,None] + off[None,None,:]) % n).reshape(c,-1)[:, :n]`<br>`means[done:done+c] = net[idx].mean(axis=1)` | `% n` menahan indeks di `[0, n-1]`; `.reshape(...)[:, :n]` memotong tepat `n` |
| C2 | 285–287 | `Hc = int(idx[1] - idx[0])`<br>`pos = idx - int(idx[0])   # idx kini = NILAI MENIT; posisi = menit - menit awal`<br>`e, x = pos + 1, pos + 1 + Hc` | Nilai menit **dikonversi** ke posisi 0-based sebelum mengindeks |

## 3. Uji reproduksibilitas (empiris, bukan pembacaan kode)

### 3a. Perintah yang **persis** dulu crash

```
.venv-research/bin/python3 scripts/sodex_spec4_micro.py --synthetic --nperm 400
```

| | Hasil |
|---|---|
| exit code | **0** |
| jumlah `Traceback` di log | **0** ✅ |
| `VERDICT: lulus =` | **TIDAK ADA** (benar — panel random-walk wajib gagal) |
| Kontrol F-a | **0/13 fade positif → OK** |
| Kontrol F-b | **6/6 p > 0,05 → LULUS** |
| Sel `_MN` | ≈ −15,1 … −15,9 bp (biaya 4 sisi) — konsisten |

### 3b. Hasil utama (mode real)

```
.venv-research/bin/python3 scripts/sodex_spec4_micro.py --nperm 2000
```

| | Hasil |
|---|---|
| exit code | **0** |
| jumlah `Traceback` | **0** ✅ |
| `reports/sodex/sodex_spec4_20261007.json` vs HEAD | **TIDAK TERMODIFIKASI** → output **byte-identik** |
| sel dibandingkan | **35/35 `net_bp` identik** (toleransi 1e-9) |
| verdict | 35/35 `False` |

Byte-identik termasuk p-value dan CI karena `SEED` tetap. **Ini bukti terkuat yang tersedia:
run segar menghasilkan berkas yang sama persis.**

## 4. Higiene artefak (tidak ada bukti yang tertimpa)

Run ulang menulis ke **nama berkas kanonik** yang sama, sehingga berpotensi menimpa artefak
beku. Ditangani begini:

| Berkas | Status |
|---|---|
| `sodex_spec4_20261007.json` | run ulang **identik** → tidak perlu dipulihkan (git bersih) |
| `sodex_spec4_20261007_SYNTHETIC.json` | **dipulihkan** ke versi beku (`git checkout`) — git bersih |
| `sodex_spec4_20261007_SYNTHETIC_REVERIFY.json` | **baru**, menyimpan run ulang nperm=400 (perintah yang dulu crash) sbg bukti |

## 5. Kesimpulan

1. Skrip SPEC4 ter-commit **berjalan bersih di kedua mode** dan **mereproduksi hasil byte-identik**.
2. Dua crash trace yang ditemukan adalah **historis, dari sebelum perbaikan** — keduanya sudah mati.
3. Verdict **0/13 (35/35 baris gagal)** tetap berdiri, kini **dengan bukti reproduksibilitas**.
4. Tidak ada ambang, target, atau kesimpulan yang berubah karena verifikasi ini.

— Hermes Anantara v3 — 2026-10-07
