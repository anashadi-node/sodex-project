# CHECKLIST ROTASI KREDENSIAL — 10-Okt-2026

**Sebab:** audit rahasia 10-Okt menemukan kredensial **asli** di berkas yang **sudah ter-publikasi** di repo GitHub (private) `anashadi-node/anantara-sakti`, khususnya `docs/SECURITY_AUDIT_20260607.md` baris 40-41.
**Repo bersifat PRIVATE** → paparan terbatas pada pemegang akses repo. Rotasi tetap disarankan: repo bisa berubah publik, kolaborator bisa ditambah, atau token bisa diakses pihak ketiga.
**Aturan:** agen TIDAK menyentuh kredensial. Semua langkah di bawah dijalankan oleh Mas Anas.

**Yang wajib dirotasi (3):**
| # | Kredensial | Terlihat di | Dampak bila disalahgunakan |
|---|---|---|---|
| 1 | Binance API key + secret | `docs/SECURITY_AUDIT_20260607.md:40-41` (terpublikasi) | order/posisi futures atas nama akun |
| 2 | OpenRouter key (`sk-or-…`) | riwayat commit + dokumentasi | pemakaian kuota LLM berbayar |
| 3 | Telegram bot token | riwayat commit + dokumentasi | kirim/baca pesan sebagai bot |

---

## 1. Binance API key + secret

1. Login Binance → **API Management**.
2. Cocokkan key yang bocor dengan **4 huruf awal** yang tercatat di audit (jangan salin nilai penuh ke chat/mana pun).
3. **Delete** key tersebut.
4. **Create API** baru → centang **hanya**: Enable Futures (perlu), Enable Reading. **JANGAN** Enable Withdrawals.
5. Set **IP whitelist** = IP VPS ini.
6. Simpan nilai baru ke **`/home/USER/anantara-sakti/.env`** (mode `600`, **untracked** ✓, sudah di `.gitignore:113`) — ganti baris `BINANCE_API_KEY` dan `BINANCE_API_SECRET`. Berkas ini dibaca **23 unit systemd** (`EnvironmentFile=`), jadi lokasinya wajib di situ. Jangan simpan di berkas yang di-commit.
7. Restart layanan yang memakainya, lalu cek log: tidak ada error auth.
8. Catat tanggal rotasi di `docs/sodex/LOG_ROTASI_KREDENSIAL.md`.

## 2. OpenRouter key

1. Buka `openrouter.ai` → **Keys**.
2. **Delete** key lama, **Create key** baru (beri nama mis. `hermes-2026-10`).
3. Set limit kredit bila tersedia.
4. Simpan ke **`.env`** di root repo (mode `600`, untracked ✓) — ganti baris `OPENROUTER_API_KEY`. Nama var lain yang dipakai sistem: `HERMES_MODEL`, `HERMES_BRIEFING_MODEL` (bukan rahasia, tidak perlu diubah).
5. Perbarui juga konfigurasi Hermes bila kunci yang sama dipakai di sana; **jangan** pernah di berkas yang di-commit.
6. Uji satu permintaan LLM; pastikan bukan 401.

## 3. Telegram bot token

1. Buka Telegram → **@BotFather** → `/mybots` → pilih bot.
2. **API Token** → **Revoke current token**.
3. Salin token baru ke **`.env`** root repo sebagai `TELEGRAM_BOT_TOKEN` (mode `600`, untracked ✓). `TELEGRAM_CHAT_ID` tidak berubah.
4. Restart daemon notifikasi (`systemctl --user restart anantara-daemon`), lalu kirim 1 pesan uji ke chat ID sendiri.
5. Pastikan `tg_chat` tetap sama (chat ID tidak berubah saat token dicabut).

## 4. Verifikasi setelah rotasi (agen yang menjalankan)

```bash
cd ~/anantara-sakti
/usr/bin/python3 ~/.hermes/cache/scratch/audit_rahasia.py       # audit ulang
git ls-files | grep -iE '\.env$|secret|\.pem$|\.key$'            # tidak boleh ada berkas rahasia terlacak
```
Kriteria selesai: audit ulang **0 temuan rahasia bernilai tinggi** di berkas terlacak, dan layanan (freqtrade/pregain/daemon/notifikasi) jalan tanpa error auth.

## 5. Pengerasan tambahan (sudah/akan dijalankan agen)

- `chmod 600` untuk seluruh `.env.bak.*` (memuat 4 kunci privat: HL, SoDEX, PARADEX, +1) — memastikan hanya pemilik bisa baca.
- Pertimbangkan memindahkan `.env.bak.*` ke luar direktori repo atau menghapus backup lama (setelah backup aman).
- `docs/SECURITY_AUDIT_20260607.md` berisi kredensial asli dan **sudah terpublikasi** → setelah rotasi, isinya tidak lagi berbahaya; bersihkan bila repo berpotensi jadi publik (rewrite riwayat = opsional, agen menunggu perintah).

*Hermes Anantara v3 · 10-Okt-2026 · tidak memuat nilai rahasia apa pun*
