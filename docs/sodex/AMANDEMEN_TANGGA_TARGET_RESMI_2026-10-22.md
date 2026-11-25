# AMANDEMEN — TANGGA TARGET RESMI SoDEX (menggantikan "0,8% harga mati tunggal")

**Tanggal:** 22-Okt-2026 · **Disetujui:** Mas Anas ("Approve dan jalankan Opsi 2 + 3 secara bersamaan")
**Pijakan:** `VERDICT_KELAYAKAN_2026-10-22.md` §5 Opsi 2; tangga sendiri sudah disetujui prinsipnya 09-Okt-2026 (dipakai sebagai alat ukur kandidat mekanisme di PRAREG-23/24/25) — amandemen ini **mempromosikannya** jadi definisi sukses resmi proyek, bukan sekadar alat ukur internal.
**Sifat:** definisi tingkat keberhasilan (BUKAN mengubah aturan A&B, grid 30 jam, universe mesin, atau jadwal verdict PRAREG-26 25-Nov/30-Nov — semua itu tetap).

---

## 1. Keputusan

Target SoDEX **tidak lagi tunggal pass/fail di 0,8%**. Mulai 22-Okt-2026, setiap verdict (termasuk PRAREG-26 25-Nov) **wajib melaporkan tingkat tertinggi yang tercapai** dari tangga berikut:

| Tingkat | Ambang (%/window atau %/48 jam) | Makna |
|---|---|---|
| **Belum lantai** | < 0,10% | belum ada bukti kelayakan minimum |
| **Lantai** | ≥ 0,10% | kandidat hidup — layak dikembangkan lebih lanjut, belum layak modal nyata |
| **Sasaran** | ≥ 0,25% | layak uji forward lebih luas / pertimbangan modal kecil |
| **Stretch** | ≥ 0,40% | layak pertimbangan serius untuk skala naik |
| **Penuh** | ≥ 0,80% | target awal proyek — tetap level TERTINGGI, bukan dihapus |

## 2. Yang TIDAK berubah

1. Definisi A&B (`mean≥ambang_tingkat` DAN `median>0` DAN `hit≥50%`), grid 30 jam tetap, jangkar 2026-08-03Z — **tetap berlaku**, hanya ambang `0,8%` di kriteria A sekarang dievaluasi di SETIAP tingkat tangga, dilaporkan sebagai tingkat tertinggi yang lolos A&B-nya.
2. Jadwal PRAREG-26: verdict **25-Nov-2026**, give-up **30-Nov-2026**, t-crit 3,80 — tidak berubah.
3. Universe 10 mesin beku, aturan seleksi (≥20 trade/14 hari, net PnL>0) — tidak berubah.
4. **0,8% tetap level tertinggi dan tetap menjadi tujuan akhir** — tangga TIDAK berarti "menyerah dari 0,8%". Tangga berarti: kemajuan menuju 0,8% sekarang terukur dan dilaporkan jujur, bukan binary gagal/sukses yang menyembunyikan progres nyata di antaranya.

## 3. Implikasi pelaporan (perubahan implementasi)

`scripts/sodex_maturation_tracker.py` akan dilaporkan dengan tambahan field `tingkat_tangga` (lantai/sasaran/stretch/penuh/belum_lantai) di samping gate lama yang sudah ada — gate lama (`window_mean>=0.8%` dst.) **tetap dihitung apa adanya**, tidak dihapus, hanya ditambah konteks.

## 4. Alasan (berbasis bukti, bukan pelonggaran standar)

Data 22-Okt menunjukkan buku aktif (TWO-WAY) berada di **mean +1,272%** (lolos kriteria A di 0,8%) tapi **median −0,320%** dan **hit 46,6%** (gagal B). Tanpa tangga, status ini hanya tercatat "NO-GO" — tidak membedakan antara "dekat lolos" vs "jauh dari lolos". Dengan tangga, publik/pencatatan internal bisa melihat **progres relatif terhadap 0,10%/0,25%/0,40%** sambil tetap jujur bahwa 0,8% penuh belum tercapai. Ini **menambah informasi, tidak mengurangi standar** — kriteria A&B di 0,8% tetap dihitung dan tetap jadi rujukan utama verdict PRAREG-26.

## 5. Verifikasi

- Tidak ada kode produksi/trading yang berubah (eksekusi, posisi, order).
- Perubahan terbatas pada skrip pelaporan (`sodex_maturation_tracker.py`) — ditinjau lewat Pre-Deploy Review Protocol sebelum commit.

*Amandemen · Hermes Anantara v3 · 22-Okt-2026 · hash tercatat di `AMANDEMEN_TANGGA_TARGET_RESMI_2026-10-22.md.sha256`*
