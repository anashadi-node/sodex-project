# AMANDEMEN_2 PRAREG-32 — operasionalisasi adverse selection (AS)

Tanggal: 25-Okt-2026, SEBELUM forward pertama (batas amandemen: 2026-10-27T00:00Z).
Ambang A/B/C/D **TIDAK diubah**. Amandemen ini hanya menetapkan cara mengukur metrik
yang sudah ada, karena rumusan protokol tidak terukur apa adanya dengan data OHLC 1h.

## Masalah
Protokol (baris `design.eksekusi`) menulis: adverse selection = `(fill_price -
signal_price_at_touch)` per trade, gate `AS median > 13,4 bps = gagal otomatis`.

Dua cacat pada rumusan literal:
1. "harga saat sentuh" (mid pada instan limit tersentuh) **tidak dapat direkonstruksi**
   dari bar 1 jam (kita hanya punya open/high/low/close/volume).
2. Untuk entry MAKER LONG, limit selalu dipasang **di bawah** harga sinyal
   (`limit = close_sinyal x (1 - 1/2 spread)`), sehingga `fill_price - signal_price`
   **secara struktur negatif** (~-0,75 bps = konsesi setengah spread). Dengan rumusan
   itu gate 13,4 bps tidak akan pernah bisa gagal = gate hampa, tidak memenuhi tujuan
   falsifikasi protokol.

## Keputusan (lebih ketat, bukan lebih longgar)
Dua definisi diukur dan dilaporkan **keduanya**, per trade dan per simbol:

| Metrik | Rumus | Arti |
|---|---|---|
| `median_fill_minus_signal` | (limit - close_bar_sinyal)/close_bar_sinyal x 1e4 | literal protokol; selalu negatif utk LONG |
| `median_touch_close` | (limit - close_bar_sentuh)/close_bar_sentuh x 1e4 | **adverse sesungguhnya**: >0 berarti bar yang memenuhi limit TUTUP di bawah harga fill (pasar terus turun setelah kita terisi) |
| `diag_terisi_minus_tidak_terisi` | mean(gross_bps terisi) - mean(gross_bps counterfactual taker) | diagnostik gaya PRAREG-5 §6.2 / `diag_maker_vs_taker.py` |

Gerbang D: `fill_rate >= 60%` **DAN** `median_touch_close <= 13,4` **DAN**
`median_fill_minus_signal <= 13,4`. Keduanya wajib lulus; nilai `None` (tidak terukur)
= gagal (fail-closed). Tidak ada ambang yang dilonggarkan.

## Konsekuensi yang harus diketahui pembaca
Dengan konvensi ini gate D **tidak hampa**: pada data IN-SAMPLE Agustus-Oktober 2026
(bukan verdict beku) `median_touch_close = 18,18 bps > 13,4` sementara
`median_fill_minus_signal = -0,75 bps` — artinya tesis "maker entry bebas adverse
selection" **sudah terbantah in-sample**; per simbol nilai `median_touch_close` berkisar
-23,4 (QNT) s.d. +97,2 bps (ARB). Verdict resmi tetap hanya dari jendela forward
27-Okt s.d. 26-Nov-2026.

## Jejak
- Evaluator: `scripts/research/prereg32_maker_eval.py` (sha256 dicatat di registry event
  `AMANDEMEN_2`).
- Registry: `reports/sodex/PRAREG31_REGISTRY.jsonl`.
- Uji: `tests/test_sodex_prereg32_eval.py::test_gate_D_ketat_dan_tidak_vacuous`.
