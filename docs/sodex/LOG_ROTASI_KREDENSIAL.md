# LOG ROTASI KREDENSIAL

Isi satu baris per kredensial setelah dirotasi. **JANGAN tulis nilai kredensial di sini** — hanya tanggal, jenis, lokasi simpan, dan hasil uji.

| Tanggal (WIB) | Kredensial | Tindakan | Disimpan di | Uji pasca-rotasi | Hasil |
|---|---|---|---|---|---|
| _(belum)_ | Binance API key+secret | hapus + buat baru, permission minimal + IP whitelist | `secrets/binance.env` (600) | layanan konsumen restart → log tanpa error auth | — |
| _(belum)_ | OpenRouter key | revoke + create | `secrets/infra.env` (600) | 1 permintaan LLM bukan 401 | — |
| _(belum)_ | Telegram bot token | revoke via BotFather | `secrets/infra.env` (600) | kirim pesan uji | — |

## Verifikasi yang dijalankan agen setelah Anda selesai

```bash
cd ~/anantara-sakti
/usr/bin/python3 ~/.hermes/skills/software-development/github/scripts/audit-secrets.py --repo .
git ls-files | grep -iE '\.env$|secret|\.pem$|\.key$'    # harus kosong
# kesehatan layanan konsumen (isi sesuai unit yang memakai kredensial)
journalctl --user -u <unit> -n 50 --no-pager | grep -iE "auth|401|403|invalid api|signature"
```

Kriteria selesai: audit ulang **0 temuan bernilai tinggi**, dan semua layanan konsumen jalan tanpa error auth selama ≥30 menit.

## Tindak lanjut opsional (setelah rotasi)

- `docs/SECURITY_AUDIT_20260607.md` masih memuat nilai kredensial **lama** — setelah rotasi isinya tidak lagi berbahaya. Bila repo berpotensi jadi publik, jadwalkan pembersihan riwayat (rewrite) — **hanya atas perintah eksplisit**, karena rewrite memutus SHA commit yang sudah dipublikasi.
- Hapus/arsipkan `.env.bak.*` lama (13 berkas, mode 600, gitignored) untuk mengurangi jumlah salinan kunci privat wallet di disk.

*Hermes Anantara v3 · dibuat 2026-10-11 · tanpa nilai rahasia*
