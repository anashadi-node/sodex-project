# PENUTUPAN JALUR RISET: CROSS-SECTIONAL SODEX 1 JAM

**Status: DITUTUP (bukan "ditunda"). Disetujui Mas Anas 2026-10-09 (butir 1 dari 3).**
Commit bukti: `4b698a9` (sapuan 108 sel + baterai stabilitas), `44faf1b` (staleness + kontra-uji Binance).

---

## Mengapa ditutup

Jalur ini **menjanjikan** — kandidat terkuat yang pernah muncul di proyek ini lolos **seluruh** gerbang beku:

| Sel | net/48j | S_ann | t | to | t_ctrl |
|-----|---------|-------|---|----|--------|
| `sodex_1h \| MOM_L21 \| H48 \| dibalik` | +25,09 bps | 2,61 | +4,59 | 1,30 | −0,43 |
| `sodex_1h \| MOM_L21 \| H24 \| dibalik` | +18,92 bps | 3,41 | +4,63 | 1,32 | −0,15 |

Lalu **dibunuh oleh empat uji independen**:

| Uji | Hasil |
|-----|-------|
| Baterai stabilitas (4 saringan, 36 sel) | **0 penyintas** — 20 tanda berbalik, 12 outlier-driven, 4 gagal di nama likuid |
| Potongan sampel `-MOM_L21` H24 | +8,2 / **−9,4** / +5,8 / **−7,3** |
| Kontribusi 5 window terbaik | **58%** dari total net (buang 10 → **−0,40**) |
| Kripto murni (51 nama) vs setengah likuid | **−6,35** (t=−0,90) dan **−4,46** (t=−0,61) |
| Staleness (bukti langsung) | tokenized equity 16–22% bar **return nol** vs median 1,3% (12–15×) |
| Kontra-uji Binance 1h | `MOM_L21` H48 **+7,85** (t=1,20) — tanda berlawanan, tidak signifikan |
| Kapasitas | volume $2,4 jt/jam, top-5 **93,1%**; edge hidup justru di 95% nama tanpa likuiditas |

**Sebab kematian:** edge itu **mean-reversion mekanis dari harga basi** pada kelas aset yang tidak diperdagangkan terus-menerus, di kolam yang tidak punya kapasitas.

## Aturan penutupan (mengikat agen berikutnya)

1. **Jangan ulangi** keluarga 108 sel (10 mekanisme × 3 panel × 2 hold × 2 arah) di SoDEX 1h.
   Kalau ada yang mengusulkan ulang, tunjuk `reports/sodex/STABILITY_BATTERY.json` dan `MOM_L21_LIKUIDITAS.json`.
2. **Jangan promosikan** sel mana pun dari keluarga ini ke paper/live, meski lolos gerbang beku.
3. **Alokasi riset cross-sectional SoDEX 1h = 0.**
4. Kalau metodologi berubah mendasar (mis. data tick, order book penuh, atau universe berbeda),
   buka **PRAREG baru** dengan keluarga sinyal yang benar-benar baru — bukan mendaur ulang yang ini.

## Yang TIDAK ditutup (dan mengapa penting)

- **Studi directional majors** (BTC/ETH/SOL) — dibuka sebagai PRAREG-19, karena: kapasitas ada ($2,2 jt/jam di BTC+ETH), volatilitas cukup untuk leverage aman (L 1,5×), dan riwayat Binance 2,8 tahun sah dipakai (korelasi 0,999 vs venue eksekusi).
- **Instrumen forward PRAREG-17** tetap berjalan (read-only, `bar_fwd` mulai terisi) sebagai bukti jalur forward.
- **Pelajaran metodologis** yang berlaku untuk semua jalur berikutnya:
  baterai stabilitas 4-saringan, uji staleness, dekomposisi kelas aset, uji kapasitas likuiditas,
  sidik-jari data, dan **kontrol drift pasar** (tahun sampel turun → short-bias terlihat bagus tanpa alpha).
