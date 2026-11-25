# PROSEDUR ROTASI API KEY SODEX — AMAN (2026-09-04)
# Hermes Anantara v2 | Keamanan & privacy #1
# PRINSIP: wallet address TIDAK berubah (SOPoints aman). Hanya API key pair diganti.

## LANGKAH 1 — ANDA buat key baru di UI SoDEX (wallet SAMA)
1. Buka app SoDEX (mainnet) → login dengan wallet yang sama (0x0794...)
2. Cari menu API Keys / API Management (biasanya di Settings/Security/Developer)
3. Generate API key BARU
4. Salin & simpan di PASSWORD MANAGER:
   - API Key NAME  (mis. "anantara-v2")
   - API Key PRIVATE KEY  (hex 0x...)
5. Revoke/delete API key LAMA
   → wallet address tetap sama, reward & SOPoints AMAN

## LANGKAH 2 — JANGAN kirim nilai key ke chat
Nilai key = secret TINGGI. Jangan paste di chat, email, atau log.
Simpan di password manager dulu.

## LANGKAH 3 — Update .env dengan aman (saya bantu, atau Anda lakukan)
Ganti 2 baris di .env (permission 600):
```
SODEX_API_KEY=<NAME BARU>
SODEX_PRIVATE_KEY=<PRIVATE BARU>
```
Tanpa print nilainya.

## LANGKAH 4 — Verifikasi
```bash
set -a && source .env && set +a
./bin/sodex orders list perps   # harus balas [] tanpa error auth
./bin/sodex balance perps       # harus tampil balance
```
Jika auth OK → key baru berfungsi. Jika error → rollback ke backup.

## LANGKAH 5 — Hardening
- Backup lama disimpan: .env.backup.pre-rotasi-<timestamp> (mode 600)
- chmod 600 .env
- Verifikasi tidak ada key baru di git/log

## CATATAN KEAMANAN
- JANGAN commit .env (sudah gitignored)
- Pre-commit hook menblokir key 0x64hex
- File .env.bak* sudah semua 600 (audit hari ini)
- No-withdraw defense: SODEX_NO_WITHDRAW=1 (aktif)
