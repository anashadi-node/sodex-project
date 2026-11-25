# Instruksi Kunci SoDEX — menuju live 01-Des-2026

## 1. Jawaban singkat
SoDEX **tidak memakai API key yang kedaluwarsa**. Otorisasi = **kunci wallet (EIP-712)** + address + account ID. Jadi tidak ada "renew", yang ada **buat kunci baru** atau **pakai yang lama**.

Kondisi nyata sekarang: `secrets/sodex.env` **belum ada** (hanya `.template`). Kunci lama hanya tersisa di `.env.bak.*` lama → **jangan dipakai ulang** (pernah tersimpan di berkas backup, dan sebagian repo pernah memuat kredensial asli).

**Keputusan: buat wallet baru khusus bot.**

## 2. Yang Mas Anas lakukan (≈20 menit, sekali saja)

### Langkah 1 — buat wallet khusus bot
- Jangan pakai wallet utama/dompet pribadi.
- Buat wallet baru (SoDEX app, atau `cast wallet new` di mesin lain yang Anda percaya).
- Simpan seed phrase **offline** (kertas), jangan di repo, jangan di chat.

### Langkah 2 — daftar & hubungkan ke SoDEX
- Hubungkan wallet baru → salin **ADDRESS** (`0x…`) dan **ACCOUNT_ID**.
- Isi saldo: testnet dulu (faucet), baru mainnet setelah selftest lolos.

### Langkah 3 — isi berkas rahasia (jangan ditempel di chat)
```
cd ~/anantara-sakti
cp secrets/sodex.env.template secrets/sodex.env
chmod 600 secrets/sodex.env
nano secrets/sodex.env        # isi 3 baris: PRIVATE_KEY, ADDRESS, ACCOUNT_ID
```
Cek: `git status --porcelain secrets/` → **harus kosong** (sudah di `.gitignore:69`).

### Langkah 4 — selftest TESTNET (wajib, tanpa dana nyata)
```
cd ~/anantara-sakti/scripts/research/mode_a_20261026
SODEX_TESTNET=1 .venv/bin/python mode_a_live.py selftest
```
Sukses = ada `saldo_testnet` + respons order berisi `orderID`. Gagal = kirim pesan error-nya (bukan kuncinya).

### Langkah 5 — deposit mainnet (setelah selftest lolos)
| Akun | Isi | Untuk |
|---|---|---|
| Spot | $180 | sel A/spot (Mode A) |
| Perp | $60 | sel P1, Lp 3 → notional ~$180 |

Total **$240**. Ini uang nyata: risiko terburuk per sel dibatasi breaker −15% dari puncak.

## 3. Yang saya kerjakan setelah kunci ada
1. Verifikasi env terbaca tanpa mencetak nilai (`mode_a_live.py status`).
2. `preflight.py` → target 0 FAIL.
3. Tambah **selftest perp** (place/cancel + baca posisi) — belum ada, saya tulis.
4. Dry-run live ukuran minimum ($10 notional) 3 hari, reconcile posisi vs ledger.
5. Bekukan GO 30-Nov + tanda tangan `LIVE_ARMED.json`.

## 4. Jangan
- Jangan tempel kunci/seed di chat, dokumen, atau commit.
- Jangan pakai wallet utama atau kunci dari `.env.bak.*`.
- Jangan aktifkan live sebelum receipt selftest ≤7 hari ada — eksekutor akan menolak (exit 3).
