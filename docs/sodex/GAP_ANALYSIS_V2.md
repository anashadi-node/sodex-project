# GAP ANALYSIS — Master Research Spec V2 vs Project SoDEX (kondisi 21-Okt-2026)

**Dokumen acuan:** `ANANTARA_SAKTI_SoDEX_Master_Research_Spec_V2.html` (11-Okt-2026, status: rekomendasi, belum backtest).
**Metode:** setiap klaim dokumen diuji terhadap kode & data repo (`file:line`), bukan diterima sebagai benar.
**Kesimpulan satu baris:** V2 benar pada **kerangka ilmiah & disiplin risiko**, tetapi **definisi targetnya (0,4–0,8% per 1–48 jam) ambigu dan justru membuka celah goalpost** yang baru saja terukur di audit 21-Okt; proyek kita sudah lebih maju pada data & biaya, tetapi **tertinggal pada tata kelola risiko, registri trial, dan holdout**.

---

## 1. Ringkasan penilaian

| Dimensi | Status kita vs V2 |
|---|---|
| Model biaya (fee+spread+funding) | **Sudah sesuai** (lebih baik dari dokumen) |
| Integritas data & anti-feed-butaan | **Sudah sesuai** (autoheal, self-heal) |
| Denominasi target (E₀ per siklus) | **MELANGGAR** — memakai wallet hari ini untuk semua window historis |
| Kebijakan risiko (exposure/leverage/DD cap) | **TIDAK ADA** di seluruh mesin SoDEX |
| Registri trial & koreksi multiple-testing | **TIDAK ADA** (20 arm diuji, 0 tercatat) |
| Sealed holdout | **TIDAK ADA** |
| Tata kelola (mandate/gates/decisions) | **TIDAK ADA** |
| Eksekusi live & rekonsiliasi state machine | Ada, tetapi **tidak** mengikuti state machine V2; masih terkunci `LIQ_DRY=1` |
| Batas keamanan kredensial | **TIDAK sesuai** — agen riset satu OS-user dengan `.env` live |

---

## 2. Yang sudah kita penuhi (bukti)

| Requirement V2 | Bukti di repo |
|---|---|
| Biaya nyata: fee 2 sisi + spread 2 sisi + funding | `scripts/paper_test_twoway.py:507–513` → `_rt_cost(venue="perps", order_type="taker", include_funding=True)`; `paper_test_realwide.py:673–676` |
| Model fill memakai harga level, bukan close | `paper_test_twoway.py:518` (`fill_model: level/poll`) |
| Anti look-ahead pada sinyal | `paper_test_twoway.py:232–244` (bar 15m terakhir yang **sudah tutup**, lag ~65 menit) |
| Deteksi data buta & pemulihan otomatis | `scripts/paper_autoheal.py` (`FEED_BLIND_RATIO=0.60`), `paper_test_twoway.py` `EMPTY_STREAK_LIMIT=3` |
| Eksekusi live terkunci | `LIQ_DRY=1`, `SODEX frozen 30-09` (memori proyek) |
| Pra-registrasi + hash sebelum data | `PRAREG_26`, `AMANDEMEN_PRAREG26`, `PRAREG_27`, `AMANDEMEN_PRAREG27_1` (hash `e25d3f34`) |

---

## 3. Gap yang harus ditutup (berurut dampak)

### G1 — KRITIS: tidak ada kebijakan risiko; eksposur 7,4× ekuitas
V2 §6 mewajibkan **max risk per cycle, max daily loss, max aggregate exposure, max leverage** sebagai human decision. Di kode SoDEX **tidak ada satu pun** variabel itu (`grep -rn "MAX_EXPOSURE|MAX_LEVERAGE|MAX_DAILY_LOSS" anantara/ scripts/` → hanya `scripts/asymmetric_sizing.py`, di luar jalur SoDEX).
Kondisi terukur: E₀ = **$243,37**; eksposur per posisi **$300** (q=1,23); buku 6 slot **$1.800 = 7,4× E₀**.

**Konsekuensi (rumus V2 §4.1, R = q(m−c), c = 6,68 bp terukur):**

| q (eksposur/E₀) | Gerak harga favorable yang dibutuhkan untuk 0,8% wallet |
|---|---|
| 7,4× (sekarang) | **0,175%** |
| 3,0× | 0,333% |
| 1,0× | **0,867%** |

Target "tercapai" karena ambang harganya **5× lebih ringan** daripada perdagangan tanpa leverage. V2 §9 eksplisit: *"A candidate that reaches target only by excessive leverage or unacceptable tail loss must be rejected."* → **arm saat ini gagal syarat itu.**

### G2 — KRITIS: E₀ tidak disimpan per siklus
V2 §4.1: denominator = E₀ **pada awal siklus**, dan *"jangan mengubah denominator setelah hasil diketahui"*.
Kita: `sodex_maturation_tracker.py:80–81, 196–210` memakai `_read_live_wallet()` **saat ini** untuk semua window historis. Bila wallet berubah (deposit, PnL, transfer), mean/median/hit historis **berubah** → verdict tidak reproducible. Ini pelanggaran langsung, bukan sekadar catatan.

### G3 — KRITIS: 20 arm diuji, 0 tercatat → verdict bias seleksi
`ls scripts/paper_test_*.py` = **20**, `data/paper_test_*_state.json` = **18**, `research/trials.csv` **tidak ada**, tidak ada DSR/PBO. Memilih arm terbaik dari 20 tanpa koreksi multiple-testing menggelembungkan hasil. V2 Kill 5 mensyaratkan registry + DSR. **Tanpa ini, angka "terbaik" kita tidak sah untuk keputusan 25-Nov.**

### G4 — TINGGI: tidak ada sealed holdout
Tidak ada direktori/data yang dikarantina. Semua data (03-Agu → sekarang) sudah "terlihat" oleh proses pemilihan strategi → tidak ada lagi virgin OOS. V2 §5 menuntut hash dataset, commit beku, dan satu protokol evaluasi final.

### G5 — TINGGI: artefak tata kelola tidak ada
`governance/mandate.yaml`, `governance/gates.yaml`, `governance/decisions_required.md`, `docs/source_register.md`, `docs/assumptions.md` — **semuanya tidak ada**. Tanpa ini, keputusan target/risiko hidup hanya di chat & memori, rawan berubah tanpa jejak.

### G6 — TINGGI: metrik path-dependent belum dihitung
V2 §4.4 menuntut **P(hit +0,4% sebelum stop, sebelum 48 jam)**. Engine punya `high`/`low` (`paper_test_twoway.py:223–225`) sehingga MFE/MAE **bisa** dihitung, tetapi tidak pernah dihitung/dicatat. Yang ada hanya exit final → tidak bisa menjawab "berapa peluang mencapai target sebelum kena stop".

### G7 — TINGGI (keamanan): batas kredensial belum dipisah
V2 §6: *"Hermes research agents tidak boleh memiliki akses live credentials"*. Kenyataan: proses riset berjalan sebagai user yang sama dengan `.env` live (mode 600). Isolasi saat ini hanya **prosedural** (aturan "jangan sentuh"), bukan **teknis**. Ini risiko tertinggi menurut prinsip #1 user (keamanan di atas segalanya).

### G8 — SEDANG: rekonsiliasi eksekusi belum mengikuti state machine
V2 §6 mensyaratkan `PROPOSED → … → UNKNOWN → RECONCILE_BY_CLIENT_ID`. `sodex_farming.py` punya jalur order nyata (EIP-712), tetapi tidak ada jurnal submission persisten + rekonsiliasi saat restart. Selama `LIQ_DRY=1` dampaknya nol; menjadi blocker sebelum live.

### G9 — SEDANG: source register belum ada
Dokumen V2 sendiri menganjurkan verifikasi ulang fee/limit "pada hari implementasi". Kita memakai angka terukur 05-Okt (taker 2,80 bp/leg) — **lebih rendah** dari tabel V2 (taker 4,0 bp/sisi). Perlu register yang menyatakan mana yang dipakai dan kapan diukur.

---

## 4. Kritik terhadap V2 (tidak ditelan mentah)

1. **Rentang 0,4–0,8% + horizon 1–48 jam = dua derajat kebebasan.** Hasil riset saya (21-Okt): mean per hari konstan di semua panjang window, sehingga memilih 48 jam **menurunkan ambang per hari 1,6×**. Bila target boleh "0,4–0,8%" dan window boleh "1–48 jam", maka lolos/gagal bisa diatur dengan memilih kombinasi paling longgar. **V2 seharusnya mengunci satu angka & satu panjang window sejak awal** — persis yang sudah kita lakukan (0,8% / 30 jam).
2. **Contoh E₀ = $7.000 menyesatkan untuk kasus kita.** Dengan E₀ $7.000, q = 1 wajar. Dengan E₀ $243, q = 7,4 adalah taruhan ekstrem. Rumusnya benar; contohnya menyembunyikan masalah utama.
3. **Tabel fee V2 (taker 4,0 bp/sisi) lebih tinggi dari biaya terukur kita (2,80 bp/leg).** Memakai tabel akan **overcharge** 43% → menolak strategi yang sebenarnya lolos biaya. V2 sendiri benar: pakai *effective account fee* dari API.
4. **Tidak ada power analysis.** Dengan n=57 window, CI95 mean = **±3,98 pp** (mean 1,34%), artinya **belum bisa dibedakan dari nol**. V2 menuntut interval ketidakpastian, tapi tidak menetapkan n minimum per horizon — akibatnya bisa "lolos" secara titik tapi gagal secara keyakinan (kondisi kita sekarang).
5. **"Boleh NO TRADE 48 jam"** bagus secara disiplin, tetapi bertabrakan dengan target throughput yang kita pakai (min ~0,273 window/hari). Perlu dinyatakan mana yang menang: kualitas (no trade) atau kuantitas (window). Rekomendasi: kualitas menang, throughput jadi **diagnostik**, bukan syarat.
6. **Klaim "LLM optional"** benar; namun `hermes_bridge` (LLM veto) masih berada di jalur CEX. Untuk SoDEX jangan pernah menaruh LLM di jalur risiko (V2 §7) — pastikan tidak ada pemanggilan LLM di `sodex_*` (saat ini tidak ada; pertahankan).

---

## 5. Rekonsiliasi angka target

| Definisi | Nilai sekarang | Status vs V2 |
|---|---|---|
| 0,8% / 30 jam, denominator wallet | mean **1,342%**, median +0,167%, hit 27/57 | Lolos **titik**, gagal **keyakinan** (CI95 −2,59…+5,31) |
| 0,8% / 30 jam, paritas risiko (buku 1×) | mean **0,182%**, hit 16/57 | **Jauh di bawah** → butuh 4,4× edge |
| 0,4% floor V2 | belum diukur terpisah | Perlu dihitung; jangan dipakai untuk melonggarkan 0,8% |
| Breakeven WR (W=0,8 / L=0,4) | **33,3%** | WR aktual 40,6% → margin hanya **7,3 pp** |

---

## 6. Rencana penyelarasan (3 fase, tanpa mengubah target)

### Fase A — Integritas keputusan (sebelum 25-Nov, wajib)
| # | Aksi | Acceptance |
|---|---|---|
| A1 | Simpan `E0` per window di tracker (snapshot saat window tutup) + migrasi historis dari snapshot wallet | Re-run menghasilkan angka **identik** dengan run sebelumnya untuk 57 window |
| A2 | Buat `research/trials.csv` untuk 20 arm (nama, tanggal, parameter, hasil, status) | Jumlah baris = jumlah arm; DSR dihitung dari registry |
| A3 | Hitung MFE/MAE per posisi dari `high/low`; laporkan P(hit 0,8% sebelum SL) | Metrik muncul di report; n=469 trade |
| A4 | `governance/mandate.yaml` + `decisions_required.md` (target 0,8/30j, risk caps, larangan) | File ada, di-hash, dirujuk README |

### Fase B — Risiko & keamanan
| # | Aksi | Acceptance |
|---|---|---|
| B1 | Tetapkan cap eksposur (`MAX_GROSS_EXPOSURE = k × E₀`) — **butuh keputusan user** | Engine menolak entry yang melewati cap; unit test |
| B2 | Pisahkan kredensial: unit riset tanpa akses `.env` (systemd `ProtectHome`/user terpisah) | `systemctl show` membuktikan `.env` tak terbaca oleh unit riset |
| B3 | State machine order + jurnal idempoten sebelum live | Tes injeksi: timeout → `UNKNOWN` → reconcile tanpa dobel order |

### Fase C — Validasi ilmiah
| # | Aksi | Acceptance |
|---|---|---|
| C1 | Sealed holdout 20% data terakhir, hash + akses terkunci | Tidak ada kode riset yang bisa membacanya |
| C2 | Walk-forward purged + DSR/PBO untuk arm terpilih | Laporan OOS dengan CI |
| C3 | Source register (fee, limit, dokumentasi, tanggal baca) | Semua angka biaya berlabel sumber |

---

## 7. Keputusan yang masih menunggu user

| # | Pertanyaan | Default yang saya sarankan |
|---|---|---|
| D1 | Model risiko target: (a) leverage 7,4×, (b) cap 1× E₀, (c) ukur per eksposur | **(b)** + laporkan (c) sebagai diagnostik |
| D2 | Window: tetap 30 jam atau uji 48 jam sebagai eksperimen terpisah | **Tetap 30 jam**; 48 jam hanya lewat PRAREG-28 dengan ambang pro-rata |
| D3 | Apakah floor 0,4% V2 diadopsi? | **Tidak** — target tetap 0,8%; 0,4 hanya dilaporkan sebagai diagnostik |
| D4 | Tanggal cut sealed holdout | 20% terakhir (≈14 hari) dikunci **sekarang**, dibuka sekali di 25-Nov |
| D5 | Isolasi kredensial teknis | **Ya**, sebelum ada uji live apa pun |

---

## 8. Kesimpulan

V2 adalah **kerangka yang benar** dan sebagian besar sudah kita jalankan lebih ketat (biaya, anti-look-ahead, pra-registrasi, deteksi data buta). Tiga hal yang membuat kita **belum** memenuhi standar V2 — dan semuanya berdampak langsung pada verdict 25-Nov:

1. **Denominator E₀ tidak dibekukan** → angka historis bisa berubah.
2. **Tidak ada cap risiko** → target dicapai lewat leverage 7,4×, yang oleh V2 sendiri harus **ditolak**.
3. **Tidak ada registri trial/holdout** → pemilihan arm terbaik dari 20 percobaan belum dikoreksi bias seleksi.

Ketiganya bisa diperbaiki **tanpa mengubah target 0,8% / 30 jam** dan tanpa menyentuh arm A. Itu jalur tercepat menuju verdict yang bisa dipertahankan.

*Disusun 21-Okt-2026 · bukti file:line · tanpa mengubah kode produksi.*
