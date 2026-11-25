# DECISIONS REQUIRED — SoDEX (menunggu persetujuan Mas Anas)

Status: **terbuka**. Tidak ada perubahan parameter/target yang dijalankan sebelum dijawab.
Acuan: `GAP_ANALYSIS_V2.md`, `AUDIT_2026-10-21.md`.

| # | Keputusan | Opsi | Dampak bila tidak dijawab |
|---|---|---|---|
| D1 | Model risiko target 0,8% | (a) leverage 7,4× seperti sekarang; (b) cap eksposur ≤1× E₀; (c) ukur per eksposur | verdict 25-Nov mengukur leverage, bukan edge |
| D2 | Panjang window | tetap **30 jam** / uji 48 jam lewat PRAREG-28 (ambang pro-rata) | 48 jam menurunkan ambang per hari 1,6× |
| D3 | Floor 0,4% (V2) | tidak diadopsi / diadopsi sebagai target kedua | dua target = dua peluang lolos (multiple testing) |
| D4 | Sealed holdout | kunci 20% data terakhir **sekarang**, buka sekali 25-Nov | tidak ada OOS murni tersisa |
| D5 | Isolasi kredensial teknis | unit riset tanpa akses `.env` | agen riset & kredensial live satu OS-user |

**Default yang disarankan (boleh disetujui sekaligus):**
- D1 → **(b)** cap 1× E₀, dengan (c) sebagai metrik diagnostik.
- D2 → **tetap 30 jam**.
- D3 → **tidak diadopsi**; 0,4% hanya dilaporkan sebagai diagnostik.
- D4 → **ya**, potong 14 hari terakhir sebagai holdout.
- D5 → **ya**, sebelum uji live apa pun.

*Ditulis 21-Okt-2026. Setiap keputusan dicatat di sini + di-hash saat disetujui.*
