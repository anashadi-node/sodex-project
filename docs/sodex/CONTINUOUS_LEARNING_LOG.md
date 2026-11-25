# Log Pembelajaran Berkesinambungan SoDEX

Dokumen append-only untuk keputusan/temuan stabil. Hasil sementara tetap di registry
PRAREG masing-masing; jangan promosikan menjadi fakta sebelum gerbang forward selesai.

## 31-Okt-2026 — Baseline alpha dan desain forward
- Settlement 1.690 trade/15 track setelah normalisasi alias schema; tidak ada track
  lolos BH q=0,05. Cakupan parsial n=1.424 sempat memberi verdict berbeda — pelajaran:
  verifikasi cakupan schema sebelum statistik.
- Alpha wajib dibersihkan dari BTC dengan beta sisi (+1 long/−1 short), biaya, dan
  hanya bar tertutup. Kekurangan data menjadi UNSETTLED.
- Pilot reflection memblokir 26,4% trade buruk (+8,3 bps) tetapi buku tersisa tetap
  negatif; penyaring tidak menciptakan edge.
- Kerugian terkonsentrasi pada ETH/ASTER/SUI dan dominasi long. SHORT 00–05 UTC
  adalah kandidat kuat, tetapi discovery in-sample → PRAREG-42 forward wajib.
- Market regime sedang DOWN (BTC −2,54% dari MA50h) saat PRAREG-42 dibekukan;
  rezim dicatat sebagai diagnostik, bukan gate yang bisa diubah post-hoc.
- Target operasional 0,01%/5 jam dan target utama 0,8%/30 jam A&B adalah dua lapisan
  berbeda; jangan pernah menyatakan target utama sudah turun.
