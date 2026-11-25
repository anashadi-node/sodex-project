# PROBE MIKRO MAINNET — 30 Okt 2026

**Dasar:** opsi A disetujui pengguna ("Approve A & B secara pararel"). Testnet perps
`BLOCKED_BY_PLATFORM` (API key dimatikan di testnet), jadi satu-satunya cara memvalidasi
jalur fill nyata adalah order minimum di mainnet.

**Pagar:** `secrets/LIVE_ARMED_PROBE.json` (kedaluwarsa 4 jam, `max_notional_usd=13`,
hanya BTC-USD, 1 BUY + 1 CLOSE reduce-only, tanpa retry, wajib flat). File terpisah dari
`LIVE_ARMED.json` 01-Des.

## Hasil eksekusi

| Item | Nilai |
|---|---|
| Simbol | BTC-USD |
| Qty | 0,00016 BTC |
| Notional | $12,30 |
| BUY | orderID `31427415575`, **FILLED**, avg 76.898 |
| CLOSE (reduce-only) | orderID `31427417243`, **FILLED**, avg 76.782 |
| Posisi akhir | **flat** (diverifikasi `positions` = `[]`) |
| Gross PnL | −$0,00992 |
| Perubahan `av` | 186,8174 → 186,8082 (−$0,0092) |

Biaya nyata (fee 4 bps × 2 + spread) ≈ $0,009, sesuai estimasi pra-trade ($0,01).

## Tiga temuan yang mengubah eksekutor

1. **Respons `orders place` tidak memuat status/fill.**
   Bentuk nyata: `{"orderID":31427415575,"clOrdID":"...","status":""}`.
   `verify_fill()` versi lama membaca `status`/`filledQuantity` dari respons itu →
   **setiap order nyata akan dianggap AmbiguousFill**. Bug kelas "fill phantom" versi
   terbalik: bukan mengarang sukses, tapi menolak semua sukses. Diperbaiki: status wajib
   dibaca dari `GET /api/v1/perps/accounts/{addr}/orders/history` (`executedQty`), dan
   tes baru menolak respons place yang mengaku FILLED padahal history bilang NEW.

2. **IOC pada harga ask bisa CANCELED (`executedQty=0`) saat harga bergerak.**
   Percobaan pertama: orderID `31427308362`, status **CANCELED**, 0 fill. Tidak ada
   posisi terbuka. Perbaikan: harga agresif +5 bps pada entry, −5 bps pada exit, dan
   jalur `NoFill` yang memeriksa posisi (jika partial → close paksa, exit 4).

3. **`orders place` perps butuh `SODEX_ADDRESS` (bukan hanya private key) dan
   bertabrakan dengan rate limit 429.** Skrip memuat `.env` sendiri dan tidak melakukan
   retry otomatis.

## Artefak
- `scripts/research/mode_a_20261026/lev_20261026/probe_live_micro.py`
- `probe_ledger.jsonl` (open/close/summary, bukti orderID)
- `test_perp_exec.py` — 16 tes lulus, termasuk regresi "place FILLED vs history NEW".

## Konsekuensi untuk 01-Des
Jalur order → fill → reconcile → flat sudah **terbukti end-to-end di venue nyata**.
Sisa risiko bukan pada mekanika order, melainkan pada strategi (edge) — yang tetap
diputuskan oleh PRAREG-23b/26/36, bukan oleh probe ini.
