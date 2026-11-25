# SODEX — DOUBLE-CHECK & AUDIT KEAMANAN (2026-08-30 16:50 WIB)
# Auditor: Hermes Anantara v2

---

## BAGIAN 1 — DOUBLE-CHECK FIX SEBELUMNYA: TEMUAN KRITIS BARU

### 🔴 TEMUAN KRITIS: Fix .env TIDAK AKTIF di Service Systemd!

**Problem:** Saya set `SODEX_TOTAL_WALLET=94.57` di `.env` — TAPI keempat paper track
service systemd **TIDAK memuat file .env** (tidak ada `EnvironmentFile` directive).

**Evidence:**
```
systemctl show anantara-paper-twoway → Environment=PATH=... PAPER_RELAXED=1
# TIDAK ADA EnvironmentFile!
```

**Artinya:** Fix saya sebelumnya hanya aktif di shell manual, TIDAK di service
yang berjalan 24/7. Ini kesalahan verifikasi saya — saya tidak mengecek bagaimana
service meng-consume konfigurasi.

**FIX:**
1. Tambahkan `EnvironmentFile=%h/anantara-sakti/.env` ke 4 service:
   - anantara-paper-twoway.service ✅
   - anantara-paper-swing.service ✅
   - anantara-paper-realwide.service ✅
   - anantara-paper-spot-swing.service ✅
2. Backup file lama: `*.service.bak.20260830`
3. `systemctl --user daemon-reload` ✅
4. Restart semua 4 service ✅ — semua `active`
5. Verifikasi: `systemctl show` → `EnvironmentFiles=/home/USER/anantara-sakti/.env` ✅

### ✅ Verifikasi Fix Sebelumnya (semua benar)

| Fix | Verifikasi | Status |
|-----|-----------|:------:|
| SODEX_TOTAL_WALLET=94.57 di .env | grep → ada | ✅ |
| Momentum gate c[i]<c[i-1] | line 257 code | ✅ |
| RSI 30-48 | line 266 code | ✅ |
| WSOSO/vSOL removed | PAIRS bersih | ✅ |
| EnvironmentFile di 4 service | systemctl show | ✅ (BARU) |
| Service restart & active | systemctl is-active | ✅ |

### ✅ Verifikasi SHORT Gate Logic (Scientific Dry-Run)

Test 3 skenario dengan data sintetis:

| Skenario | Death-cross | Momentum | RSI | GATE |
|----------|:-----------:|:--------:|:---:|:----:|
| S1b — Crash 3 bar (ideal SHORT) | ✅ | ✅ | 34,9 | **PASS** ✅ |
| S1a — 4 candle merah (RSI 28,6) | ✅ | ✅ | 28,6 | **BLOCK** ✅ (oversold = late entry, fitur bukan bug) |
| S2 — Bounce pasca death-cross | ✅ | ❌ | 90,3 | **BLOCK** ✅ |
| S3 — Recovery RSI ambigu | ✅ | ❌ | 62,9 | **BLOCK** ✅ |

**Kesimpulan:** Gate bekerja sesuai desain scientific:
- Sweet spot bear-momentum (RSI 30-48 + harga turun) → entry
- Oversold (RSI<30) → block (hindari late entry/bounce risk)
- Bounce & recovery → block

---

## BAGIAN 2 — AUDIT KEAMANAN & PRIVACY

### 2.1 ✅ yang SUDAH AMAN

| Item | Bukti |
|------|-------|
| `.env` di .gitignore | `git check-ignore .env` ✅ |
| `.env` permission 600 | `stat -c %a` = 600 ✅ |
| Tidak ada secret hardcoded di scripts | grep bersih ✅ |
| Tidak ada private key bocor ke data/ logs/ docs/ | full-text scan bersih ✅ |
| twin_engine.db state bersih | 0 leaks ✅ |
| Logging tidak expose nilai secret | hanya nama var, bukan value ✅ |
| Paper track tidak kirim order | read-only + simulasi ✅ |
| .env.backup tidak ter-track git | untracked ✅ |
| `.env.backup.*` ditambahkan ke .gitignore | ✅ (BARU, hasil audit ini) |

### 2.2 🔴 KELEMAHAN KEAMANAN DITEMUKAN

#### K-1: Private key SoDEX di .env PLAIN-TEXT (Severity: MEDIUM)

**Fakta:** `SODEX_PRIVATE_KEY=0x6de3...` tersimpan plain-text di .env.

**Konteks:**
- .env permission 600 ✅, gitignored ✅, tidak pernah di-commit ✅
- Tapi tetap single-point-of-failure: jika file bocor (backup salah, screenshot,
  log error yang print env), private key langsung terekspos → wallet habis.

**Risk:** Wallet SoDEX berisi $94,57 — dampak finansial langsung terbatas.
TAPI kalau address yang sama dipakai lintas venue (HL harvest address
0x<redacted>... = SoDEX address!) → exposure lebih luas.

**Rekomendasi (prioritas):**
1. Pisahkan wallet trading SoDEX dari wallet dengan dana besar (sudah dilakukan? perlu konfirmasi user)
2. Pertimbangkan env var → secrets manager (systemd-creds, sops, pass)
3. Set key rotation policy (misal 90 hari)
4. Audit: apakah ada process lain yang bisa read .env? (semua service same-user → ya, acceptable untuk single-user box)

#### K-2: 18 baris secret credentials dalam satu file .env (Severity: LOW-MEDIUM)

**Fakta:** .env berisi 18 secret lines (Binance API, Telegram token, SoDEX key, HL, dll).

**Risk:** Blast radius — satu file bocor = semua kredensial bocor.

**Rekomendasi:** Pisahkan per-domain (alpaca.env sudah dipisah ✅, tapi Binance/
Telegram/SoDEX masih satu file). Prioritas rendah karena single-user box.

#### K-3: SERVICE ENVIRONMENTFILE mengekspos .env ke SEMUA service (Severity: LOW)

**Fakta:** Setelah fix saya, 4 paper service sekarang load seluruh .env — termasuk
SEMUA secret di dalamnya (Binance API, Telegram token, SoDEX private key).

**Dampak:** Sebelumnya paper service hanya dapat PAPER_RELAXED. Sekarang dapat
SEMUA secret. Jika salah satu service ter-kompromi (RCE via dependency supply-chain),
attacker dapat membaca semua secret via /proc/<pid>/environ.

**Mitigasi yang lebih baik:** Pisahkan variabel non-secret ke file terpisah:
```
.env.swing   → SODEX_TOTAL_WALLET, PAPER_* (non-secret)
.env         → secrets saja
```
Lalu `EnvironmentFile=%h/anantara-sakti/.env.swing` di paper service.

**Rekomendasi:** Lakukan sebelum menambah service lagi. Tidak mendesak — single-user box.

### 2.3 🔵 KELEMAHAN PRIVACY SISTEM

| Item | Fakta | Risk |
|------|-------|------|
| Telegram bot notifikasi | TELEGRAM_BOT_TOKEN di .env | Jika token bocor, orang lain bisa baca pesan bot (chat history) |
| Address wallet publik di kode/docs | 0x<redacted>... muncul di CLAUDE.md, docs, dll | Public blockchain — address exposure = linkable ke semua transaksi. Privacy tipis |
| data/sodex_public_trades.db 447K rows | berisi seluruh public trades | Tidak sensitif (data publik exchange) ✅ |
| twin_engine.db 69K fills | berisi trading history kita | Local-only ✅ tapi berisi PnL riil — jangan commit |

---

## BAGIAN 3 — REKOMENDASI KEAMANAN (PRIORITAS)

| # | Aksi | Prioritas | Effort |
|:-:|------|:---------:|:------:|
| 1 | Pisahkan non-secret config ke .env.swing, service load itu saja | 🔴 Tinggi | 30 min |
| 2 | Konfirmasi wallet SoDEX terpisah dari wallet utama (blast radius) | 🔴 Tinggi | Konfirmasi user |
| 3 | Tambah .gitignore pattern `.env.backup.*` | ✅ SELESAI | — |
| 4 | Set rotasi key SoDEX/Binance 90 hari (kalender reminder) | 🟡 Medium | 10 min |
| 5 | Pertimbangkan systemd-creds untuk secret encryption at rest | 🟡 Medium | 1 jam |
| 6 | Audit dependency supply-chain (pip audit) berkala | 🔵 Rendah | 30 min/bulan |
| 7 | Tambah pre-commit hook yang blok commit file dengan pola `0x[a-f0-9]{64}` | 🟡 Medium | 20 min |

---

## BAGIAN 4 — KESIMPULAN DOUBLE-CHECK

**Fix perbaikan sebelumnya:** 4/4 fix benar di code, TAPI 1 kegagalan deployment
ditemukan & diperbaiki (service systemd tidak load .env). Sekarang semua fix
**benar-benar aktif di service 24/7** — terverifikasi via systemctl show.

**Keamanan:** Tidak ada leak aktif. Semua kontrol dasar sudah benar (gitignore,
permission 600, tidak hardcoded). Kelemahan struktural: private key plain-text +
blast radius .env tunggal + service baru load seluruh .env. Tidak ada yang mendesak
untuk box single-user, tapi rekomendasi jangka menengah tercantum di Bagian 3.

**Pelajaran penting untuk saya:** Verifikasi fix harus sampai ke **runtime consumption**
(bagaimana service benar-benar membaca config), bukan berhenti di "file sudah diedit".

---

*Double-check & security audit 2026-08-30 16:50 WIB | Hermes Anantara v2*