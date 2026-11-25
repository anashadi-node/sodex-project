# PRAREG-19 — HASIL & PENUTUPAN: 0 dari 24 sel lolos

**Status: DITUTUP (09-Okt-2026).** Hasil historis = **DESKRIPTIF**. Sesuai protokol §6, "0 sel lolos"
adalah hasil yang **sah dan berharga** — dicatat, lanjut ke keluarga berikutnya lewat PRAREG baru.

| Item | Nilai |
|------|-------|
| Protokol (beku) | sha256 `eab1ea9b02e833a7…`, bar **α ≥ 32 bps/48j**, t≥1,96, BH-FDR q=0,10 |
| Runner | `scripts/research/prereg19_directional_majors.py` |
| Hasil | `reports/sodex/PRAREG19_HASIL.json` (fingerprint data `f23ce4c2bef5056c`) |
| IS | 2024-01-01 → 2026-07-31 (22.632 bar per aset) |
| **Holdout** | **1-Agu-2026 → 9-Okt-2026 (1.644 bar) — TIDAK DISENTUH** |
| Sel diuji | 24 (4 mekanisme × 2 arah × 3 aset) |
| **Lolos gerbang** | **0 / 24** |
| **Lolos baterai stabilitas** | **0 / 24** |
| α median 24 sel | **−0,51 bps/48j** |
| α terbaik | **+7,63 bps/48j** (M1 BRK_DONCHIAN · ETH · long, t=1,65) |

## 1. Enam sel teratas

| Mekanisme | Aset | Arah | α net | σ | eksposur | β | t |
|-----------|------|------|------:|---:|---------:|--:|--:|
| M1 BRK_DONCHIAN | ETH | long | +7,6 bps | 140 bps | 0,07 | 0,02 | 1,65 |
| M2 MA_SLOPE | ETH | short | +6,5 | 466 | 0,83 | 0,10 | 0,41 |
| M2 MA_SLOPE | BTC | short | +3,0 | 301 | 0,83 | 0,04 | 0,26 |
| M2 MA_SLOPE | SOL | long | +2,4 | 514 | 0,82 | −0,06 | 0,14 |
| M3 FADE_Z48 | BTC | short | +1,1 | 192 | 0,32 | 0,01 | 0,15 |
| M1 BRK_DONCHIAN | SOL | long | +0,9 | 161 | 0,07 | −0,00 | 0,16 |

## 2. Empat temuan

1. **Keluarga ini tidak punya keunggulan sama sekali.** α median **−0,51 bps** — nol.
   Bukan "hampir lolos": setengah sel bernilai negatif setelah biaya.
2. **Sel terbaik tetap 4,2× di bawah bar** (+7,6 vs 32 bps). Eksposurnya hanya 0,07 →
   sinyal breakout nyaris tidak pernah aktif; yang "terbaik" justru yang paling jarang trading.
3. **Kontrol drift BERSIH — hasil ini bukan artefak pasar.** |β| ≤ 0,10 di seluruh 24 sel,
   artinya tidak ada sel yang menunggang drift. Jadi angka di atas adalah **ukuran kualitas sinyal
   murni**, bukan efek tahun turun. (Ini yang membuat hasil kosong ini bisa dipercaya.)
4. **Biaya memakan mekanisme yang lincah.** M2 (turnover 0,81) membayar ±4,5 bps/observasi hanya
   untuk pembalikan posisi — pada horizon 48 jam, itu sendirian sudah melebihi seluruh edge.

## 3. Jarak ke target (α bps/48 jam)

| Target | Butuh α | Terbaik terukur | Kurang |
|--------|--------:|----------------:|-------:|
| Lantai **0,4%** | 29,1 | 7,6 | **3,8×** |
| Atas **0,8%** | 43,4 | 7,6 | **5,7×** |
| Garis "jangan deploy" | 10,0 | 7,6 | 1,3× |

**Penyumbat nyata bukan data, bukan target, bukan leverage.** Pada σ sel terbaik (140 bps),
mencapai α=29,1 bps hanya butuh **n≈90 window** (data kita 550 window — berlimpah), tetapi
menuntut **Sharpe tahunan 2,80** (untuk 0,8%: **4,17**). Sharpe yang berhasil diukur hari ini: **0,74**.
Jadi yang harus naik **4–6× adalah mutu sinyal**, bukan apa pun yang lain.

## 4. Temuan generalisasi

Dua keluarga sudah mati, dengan **cara mati yang berbeda**:

| Keluarga | Cara mati |
|----------|-----------|
| Cross-sectional (108 sel) | lolos gerbang 2 sel → **baterai stabilitas 0/36** (likuiditas, equity-tokenized) |
| Directional majors (24 sel) | **α mentah jauh di bawah bar** (0/24), drift bersih |

Polanya jelas dan layak diingat: **alpha 48 jam di majors itu langka.** Menambah nama, menambah
mekanisme klasik (breakout/slope/fade), atau menambah leverage tidak menciptakannya.

## 5. Yang TIDAK dilakukan (disiplin protokol)

- Tidak ada ambang yang disetel setelah melihat hasil.
- Tidak ada sel baru yang ditambahkan (kalau perlu → PRAREG baru).
- Holdout 1-Agu→9-Okt-2026 **tidak disentuh** (tidak ada peek).
- Lapisan half-Kelly tidak pernah diuji karena lapisan α sudah gagal lebih dulu.

## 6. Keluarga berikutnya (belum dijalankan — butuh PRAREG baru)

Kandidat terkuat: **carry funding/basis lintas-venue pada majors** — punya mekanisme ekonomi nyata
(pembayaran funding), market-neutral, dan likuiditasnya sudah terbukti (`HL-Harvest`).
**Peringatan:** ukuran Sharpe keluarga itu wajib diukur ulang di PRAREG sendiri — jangan
diasumsikan cukup hanya karena mekanismenya masuk akal. PRAREG-19 mengajarkan tepat itu.

*Artefak: `PRAREG19_HASIL.json`, `prereg19_directional_majors.py`, `PRAREG19_BEKU.json`.*
