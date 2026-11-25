# SODEX F2 — Struktur-Mikro Maker: DITUTUP pada Tahap Desain (Evaluasi #43)

**Tanggal:** 06-Okt-2026 · **Status:** DITUTUP-GAGAL sebelum pra-registrasi forward. Tidak ada uji forward, tidak ada lockbox baru, F1 (#42) tidak tersentuh.
**Discovery:** `scripts/sodex_micro_discovery.py` · **Simulator fill:** `scripts/sodex_prereg_f2.py` (mode smoke, data 22 Mei–31 Agu 2026) · **Fee resmi:** taker 0,040%/leg, maker 0,012%/leg (whitepaper SoDEX, dikonfirmasi 2 sumber).

## Rangkaian falsifikasi (semua sebelum komitmen apa pun)

**1. Discovery (OBI nyata, 101 hari, gap 4 jam):**
- Balon OBI20 ≥0,35 (n=1.007): drift +2,0 bp/1m, +2,8 bp/15m — sinyal arah ADA, bukan artefak.
- Spread melebar ≥2× (n=1.279): drift NEGATIF (−0,9 bp/15m) → ditolak.
- Keduanya gagal menutup biaya taker bulat 8–28 bp → satu-satunya jalan: maker.

**2. Varian maker v1 (post-only di best bid saat onset, keluar 45m):** fill 97–99% tetapi net **−41…−55 bp**/episode (BTC −55,0 / ETH −49,3 / SOL −40,7). Penyebab: fill hanya terjadi saat harga menembus bid = **adverse selection penuh**.

**3. Varian revisi (tahan 60 detik tanpa penetrasi bid sebelum menganggap aman):** n=83, mean **−53,4 bp**, median −54,2, **WR 0–8%**, homogen antar simbol. Filter tidak menyelamatkan; malah mengonfirmasi mekanismenya. Laju setelah filter 5/hari/20-simbol — jauh dari kebutuhan.

**4. Aritmetika spread-capture pasif (spread median 5–6 Okt, maker RT 2,4 bp):**

| Simbol ter-lebar | Spread median | Net RT pasif |
|---|---|---|
| PONS | 2,65 bp | **+0,25 bp** (sebelum adverse selection) |
| BNB | 1,27 bp | −1,13 bp |
| UNI | 1,12 bp | −1,28 bp |
| … semua 17 lainnya | ≤1,05 bp | negatif |

Tidak ada satu simbol pun yang spread-nya melebihi fee maker RT. Jalan pasif mati di level aritmetika.

## Putusan

**H2 (struktur-mikro maker) TIDAK LANJUT ke pra-registrasi forward.** Tiga bukti independen (adverse selection dua varian + aritmetika spread vs fee) konsisten. Ini evaluasi #43: **desain-gagal, tanpa biaya forward.**

## Artinya untuk jalur menuju Target Utama

- Jalan aktif yang tersisa: **F1 momentum (frozen #42, menunggu data forward, prior ≤15%)** — satu-satunya uji yang sudah dikomit.
- Kandidat arah berikut yang belum teruji: (a) **funding lintas venue** — SoDEX settlement 1 jam vs Binance 8 jam; perlu recorder funding SoDEX (read-only) agar data forward mulai terkumpul sejak sekarang; (b) sinyal amplifikasi loser+funding (`sodex_e2dir_amplifier.py`) — butuh pra-registrasi sendiri; (c) hasil review `sodex_twin_engine.py`.
- Pelajaran tercatat: pada venue dengan spread tipis (0,1–2,7 bp) dan fee maker 1,2 bp, **strategi maker struktural tidak punya ruang** di SoDEX tanpa rebate tier tinggi (butuh 14D maker-share >0,5% → −0,1 bp; tidak realistis untuk ukuran kita).
