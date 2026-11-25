# STUDI MENDALAM — TauricResearch/TradingAgents

Sumber: `github.com/TauricResearch/TradingAgents` (clone `--depth 1`, 9,2 MB),
paper arXiv:2412.20138v7 (28-Des-2024, rev 3-Jun-2025). Inti Python ±3.315 baris.

## 1. Apa yang sebenarnya dibangun

Bukan "bot trading". Ini **kerangka pengambilan keputusan** berbasis LLM yang meniru
struktur firma: analis → debat riset → trader → debat risiko → portfolio manager.
Orkestrasi: LangGraph (`StateGraph`), state bersama `AgentState`.

Alur graph (`graph/setup.py`):
1. **Analyst team** (paralel, masing-masing subgraph dengan riwayat pesan terpisah):
   market, social/sentiment, news, fundamentals. Tiap analis punya tool sendiri dan
   dipaksa menulis laporan setelah `max_tool_rounds` — pagar anti-loop.
2. **Bull vs Bear researcher** — debat beberapa ronde, dipandu `ConditionalLogic`.
3. **Research Manager** — merangkum debat jadi rencana investasi.
4. **Trader** — menerjemahkan rencana jadi keputusan.
5. **Risk team** — aggressive / neutral / conservative berdebat.
6. **Portfolio Manager** — `with_structured_output(PortfolioDecision)`, satu call,
   menghasilkan rating final + markdown keputusan.

Yang jarang dimiliki repo sejenis dan justru paling berharga:
- **Memory log + settlement** (`memory/`): setiap keputusan disimpan, lalu *diselesaikan*
  setelah jendela holding lewat — dihitung `raw_return` dan **alpha vs benchmark**
  (SPY default, benchmark per bursa). Baru setelah itu `Reflector` menulis 2–4 kalimat
  pelajaran yang di-inject ke prompt run berikutnya.
- **Backtest sebagai evaluasi kualitas keputusan, bukan simulator portofolio.**
  `backtest.py` menyatakan eksplisit: *"Turning a rating into a filled order needs a
  quantity, a fill price and a cash ledger... inventing them here would put an execution
  model behind an evaluation tool."* Ini sejalan persis dengan disiplin PRAREG kita:
  jangan mengarang fill.
- **Portfolio context tiga keadaan** (`portfolio.py`): posisi, flat, dan *tidak diberi* —
  "not provided" tidak boleh diperlakukan sebagai "flat", karena itu mengarang fakta
  tentang akun pengguna. Prinsip yang sama kita pakai untuk `av` vs `null`.

## 2. Kritik jujur (jangan telan mentah)

1. **118k bintang ≠ alpha.** Popularitas mengukur kegunaan sebagai kerangka, bukan edge.
2. **Evaluasi paper pada saham harian**, horizon harian, dan bukan pasar 24/7 dengan
   funding, likuidasi, dan spread yang berubah. Generalisasi ke perp kripto tidak otomatis.
3. **Biaya & slippage tidak dimodelkan** di lapisan keputusan; backtest-nya mengevaluasi
   rating, bukan PnL bersih. Untuk target kita (0,8%/window setelah fee) ini krusial.
4. **Latensi & biaya LLM**: satu run = puluhan call (4 analis + debat + 3 risk + PM),
   detik sampai menit, biaya per keputusan jauh di atas edge satu trade kecil. Tidak layak
   di jalur eksekusi; layak sebagai lapisan **offline/post-hoc**.
5. **Tidak ada kontrol falsifikasi**: tidak ada SPA/BH-FDR, tidak ada negative control,
   tidak ada uji "apakah debat menambah alpha dibanding satu agen". Klaim superioritas
   belum diuji dengan disiplin multiple-testing.

## 3. Yang saya adopsi untuk SoDEX (dan yang tidak)

**Adopsi (murah, deterministik, bisa diuji):**
- **Settlement + alpha**: setiap entry PRAREG dicatat dengan horizon, lalu di-settle
  terhadap **BTC buy-and-hold** (bukan raw PnL). Ini menutup lubang kita: kemenangan saat
  BTC naik tidak boleh dihitung sebagai edge.
- **Reflection terkurung**: maksimal 3 baris pelajaran per episode, disimpan terpisah,
  di-inject hanya ke gate pemilihan — bukan ke sizing, bukan ke eksekusi.
- **Semantik "tidak ada data" ≠ "flat"** untuk `av`, posisi, dan funding.

**Tolak:**
- LLM di hot path order (latency + biaya + non-determinisme).
- Debat multi-agen sebagai sumber sinyal tunggal (tidak ada bukti OOS untuk kripto 24/7).
- "Rating" gaya ekuitas tanpa biaya, funding, dan likuidasi.

## 4. Gap analysis SoDEX vs kerangka ini

| Dimensi | TradingAgents | SoDEX sekarang | Tindakan |
|---|---|---|---|
| Settlement keputusan | ada, alpha vs benchmark | PnL mentah per trade | **tambah alpha vs BTC** |
| Refleksi | LLM, 2–4 kalimat | deep loop ambang statistik | tambah lapisan naratif, terkurung |
| Debat adversarial | bull/bear + risk | tidak ada | uji offline, bukan live |
| Kontrak output | Pydantic ketat | JSON + verifikasi manual | pertahankan |
| Anti-lookahead | `is_historical`, tolak tanggal masa depan | sudah ada di harness | pertahankan |
| Evaluasi | grid kualitas keputusan | PRAREG + bootstrap | pertahankan (lebih ketat) |

## 5. Usulan PRAREG-40 (dibekukan sebelum diuji)

**Hipotesis:** menambahkan *settled-alpha reflection* (maks 3 pelajaran, hanya dari
episode yang sudah selesai) ke gate pemilihan menaikkan WR ≥3 pp dan expectancy ≥5 bps
pada 60 hari paper-forward, dibanding gate yang sama tanpa reflection.

**Desain:** A/B paralel, gate identik, hanya berbeda pada kehadiran blok refleksi.
Metrik: WR, E(R), alpha vs BTC, t-stat; ambang keputusan t ≥ 2,5 (registry).
**Gagal → dibuang**, tanpa penyelamatan post-hoc. Tidak menyentuh PRAREG-23b/36.

**Kenapa bukan sekarang:** butuh ≥60 hari dan data settlement; jalankan mulai 01-Nov
paper, evaluasi 31-Des. Tidak menghambat live 01-Des karena refleksi hanya memengaruhi
pemilihan, bukan eksekusi.

## 6. Kesimpulan satu paragraf

Nilai repo ini bukan pada "agen LLM bisa trading", melainkan pada **tata kelola
keputusan**: setiap keputusan diselesaikan dengan alpha, direnungkan, dan diingat —
plus kejujuran metodologis bahwa backtest bukan simulator. Dua hal itu yang saya ambil.
Klaim performanya tidak saya pakai sebagai bukti, karena tidak diuji dengan disiplin
yang kita pakai sendiri (biaya, funding, multiple testing, kontrol negatif).

## 7. Temuan lapis kedua (setelah baca penuh settlement & reflection)

1. **Entry di close pertama SETELAH tanggal analisis.** `fetch_returns()` masuk di
   "first close after trade_date", bukan di harga saat analisis ditulis. Ini menutup
   lookahead satu bar yang paling sering lolos di backtest swasta.
2. **Tidak ada settlement parsial.** Bila jendela holding belum sepenuhnya traded,
   fungsi mengembalikan `(None, None, None, None)` dan keputusan tetap *pending* —
   bukan diskor dengan harga setengah jalan. Kita adopsi: trade yang exit-nya belum
   lewat satu bar penuh tidak boleh masuk statistik.
3. **Bar hari ini dibuang.** `_by_day()` membuang bar hari berjalan karena close-nya
   masih harga live. Analog di `settle_paper_alpha.py`: hanya bar yang sudah tutup
   (toleransi 2 jam) yang dipakai; di luar itu → `UNSETTLED`.
4. **Reflection hanya untuk keputusan yang SUDAH settled.** Refleksi tidak pernah
   dijalankan pada posisi terbuka — mencegah pelajaran dari tesis yang belum diuji.
   Prompt-nya bahkan menyuruh model mengatakan "window terlalu pendek untuk menilai".
5. **Benchmark per bursa, return per mata uang.** `resolve_benchmark()` memetakan suffix
   (`.T` → `^N225`), dan return dibandingkan dalam mata uang masing-masing — bukan
   konversi kurs yang menambah noise.
6. **Backtest menolak mengarang fill.** `backtest.py` tegas: quantity, fill price, dan
   cash ledger tidak diciptakan; kalau diciptakan, itu "execution model behind an
   evaluation tool". Ini persis alasan probe mikro kita pakai uang nyata.

### Yang kita perbaiki dari desain mereka
- Mereka memakai satu benchmark per ticker; kita memakai **beta per sisi** (+1 long,
  −1 short) sehingga short tidak dihukum dua kali saat BTC turun.
- Mereka tidak memodelkan biaya di lapisan keputusan; kita memotong **8 bps** dan
  melaporkan `alpha_gross` dan `alpha_net` terpisah.
- Mereka mengevaluasi satu strategi; kita menguji **6 track sekaligus** dan karena itu
  mewajibkan **BH q=0,05** — tanpanya, `pasar_anantara_trade` (p=0,0142) akan salah
  diklaim lolos.
