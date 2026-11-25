# AUDIT KEAMANAN — TauricResearch/TradingAgents

Tanggal: 30-Okt-2026 · Metode: **read-only**. Repo **tidak diinstal, tidak dijalankan**,
tidak ada `pip install`, tidak ada eksekusi kode pihak ketiga.

HEAD diaudit: `c4544913a14ed3df5f1ed7b9e8483270ce20682a` (Yijia Xiao, 27-Okt-2026),
clone dari `github.com/TauricResearch/TradingAgents` (kanonis, bukan fork).

## 1. Integritas & riwayat
| Pemeriksaan | Hasil |
|---|---|
| Commit (setelah `--unshallow`) | 515 |
| Penulis | Yijia-Xiao 405, Yijia Xiao 47, Edward Sun 13, CadeYu 12, luohy15 10, Tauric-Research 4 |
| Blob >200 KB | hanya `uv.lock` & PNG dokumentasi |
| File kunci/sertifikat pernah di-commit | tidak ada (`*.pem`, `*.key`, `id_rsa`, `.env`) |
| Binary/`.so`/`.pth`/wheel/zip | **nol** |
| File dengan izin eksekusi | **nol** |
| Perubahan workflow yang menambah `secrets.` | tidak ada |

## 2. Analisis statis
`semgrep scan --config=p/python --config=p/secrets`
- **0 temuan ERROR**, **0 temuan WARNING**.
- `eval(`, `exec(`, `os.system`, `pickle.loads`, `base64.b64decode` di kode library: **0**
  (hanya `graph.compile()` milik LangGraph — bukan eval).
- `subprocess` di library: **1**, yaitu `cli/prompts.py:687` menjalankan
  `sys.executable -P -m cli.main login chatgpt` (alur login resmi, bukan perintah shell).
- `shell=True`, `verify=False`, `trust_env`: **tidak ada**.
- IP literal: hanya `127.0.0.1`. Tidak ada endpoint anonim/IP keras.

## 3. Tujuan jaringan (egress)
Semua domain adalah API resmi: `api.openai.com`, `openrouter.ai`, `api.deepseek.com`,
`api.anthropic.com`, `dashscope(-intl).aliyuncs.com`, `api.mistral.ai`, `api.x.ai`,
`api.z.ai`, `api.moonshot.ai`, `api.minimax.io`, `integrate.api.nvidia.com`,
`api.stlouisfed.org`, `alphavantage.co`, `data.sec.gov`, `github.com`, `tauric.ai`.
**Tidak ada** domain acak, tunneling, atau endpoint pengumpul data.
**Tidak ada telemetri/analytics** (`pypi.org`, `check update`, `telemetry` → 0 hasil).

## 4. Penanganan kredensial
- Kunci LLM dibaca dari environment (`OPENAI_API_KEY` dst.).
- `.env` ditulis dengan mode **0600** lalu `chmod` dipaksa (`cli/prompts.py:738`).
- Bedrock memakai rantai kredensial AWS standar (`~/.aws/credentials`, IAM role) —
  wajar untuk AWS, bukan pencurian kredensial.
- Tidak ada pembacaan `~/.ssh`, keyring, atau wallet. Satu-satunya `expanduser` adalah
  direktori data `~/.tradingagents` dan path log.
- `trading_graph.py:258` menyebut **allowlist endpoint** karena `backend_url` dapat
  membawa kredensial — tanda penanganan yang sadar-risiko.

## 5. Permukaan risiko yang TETAP ada (jujur)
1. **Prompt injection lewat berita/sosial**: agen membaca teks eksternal lalu memberi
   keputusan. Ini risiko nyata bagi siapa pun yang menjalankannya — bukan malware, tapi
   vektor manipulasi. Alasan tambahan untuk **tidak** memakai LLM di jalur order kita.
2. **Data keluar ke provider LLM** (berita, laporan) — by design, bukan kebocoran.
3. **Supply chain**: `pip install tradingagents` menarik 20 paket (langchain*, pandas,
   yfinance, stockstats). Jika suatu saat dipakai, wajib pin versi + hash.
4. **Fork 22,7k**: fork dapat dimodifikasi. Kita hanya memakai repo kanonis, hash HEAD
   dicatat di atas.

## 6. Vonis
**AMAN untuk dipelajari dan diadopsi polanya.** Tidak ditemukan backdoor, malware,
obfuscation, eksfiltrasi, hook instalasi, atau binary tersembunyi. Repo tetap
**tidak diinstal/dijalankan** di mesin ini; kita hanya mengambil pola desain
(settlement + alpha, reflection terkurung, kejujuran backtest).
