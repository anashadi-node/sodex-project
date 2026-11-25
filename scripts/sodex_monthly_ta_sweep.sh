#!/usr/bin/env bash
# SoDEX Pilar 4 - sweep bulanan TA7/TA10/TA11 (historis, deskriptif) + TA12 (forward).
#
# Tujuan : menjalankan ulang keluarga arm BEKU pada data terbaru dan mencatat ringkasan
#          "lolos gerbang" ke reports/sodex/TA_MONTHLY_SWEEP.md, sehingga kandidat yang
#          mulai lolos tertangkap tanpa menunggu dijalankan manual.
# Sifat  : READ-ONLY research. Tidak mengubah skrip studi yang beku, tidak meng-commit,
#          tidak menyentuh berkas proyek lain.
#          Artefak JSON yang ditulis ulang otomatis oleh TA7/TA10/TA11 di-backup ke
#          logs/ta_sweep_artifacts/<stamp>/ lalu dikembalikan (git checkout) agar salinan
#          kanonik hasil yang sudah di-commit tidak teracak oleh sweep.
#          TA12_FORWARD_MACDFADE.json TIDAK dikembalikan: itu artefak forward hidup.
#
# Override: TA_SWEEP_STUDIES="scripts/research/ta12_forward_eval.py" untuk uji cepat.
set -uo pipefail
cd /home/USER/anantara-sakti

PY=/usr/bin/python3
STAMP=$(date +%Y-%m-%dT%H:%M:%S%z)
LOG=logs/sodex_monthly_ta_sweep.log
MD=reports/sodex/TA_MONTHLY_SWEEP.md
BACKUP=logs/ta_sweep_artifacts/$STAMP
FROZEN_JSON=(reports/sodex/TA7_SWING_STUDY.json reports/sodex/TA10_FADE_STUDY.json reports/sodex/TA11_EXIT_STUDY.json)
STUDIES=${TA_SWEEP_STUDIES:-"scripts/research/ta7_swing_study.py scripts/research/ta10_fade_study.py scripts/research/ta11_exit_study.py scripts/research/ta12_forward_eval.py"}

mkdir -p logs "$BACKUP"

# 1) backup artefak beku agar dapat dipulihkan persis
for f in "${FROZEN_JSON[@]}"; do
  [ -f "$f" ] && cp -f "$f" "$BACKUP/$(basename "$f")"
done

# 2) jalankan studi (output penuh ke $RUNLOG; filter peringatan runtime yang tidak relevan)
RUNLOG="$BACKUP/run.log"
: > "$RUNLOG"
for s in $STUDIES; do
  {
    echo "--- $(basename "$s") @ $(date -Is) ---"
    "$PY" "$s" 2>&1 | grep -vE "RuntimeWarning|^[[:space:]]*c /="
    echo "exit_status=${PIPESTATUS[0]}"
  } >> "$RUNLOG" 2>&1
done

# 3) ringkasan gerbang + verdict forward
SUMMARY=$(grep -iE "lolos|TIDAK_KONKLUSIF|verdict|KONKLUSIF" "$RUNLOG" | tail -40 || true)

# 4) append laporan bulanan (berkas ini boleh di-commit; output studi tidak teracak)
{
  echo ""
  echo "## Sweep $STAMP"
  echo '```'
  echo "$SUMMARY"
  echo '```'
} >> "$MD"

# 5) pulihkan artefak beku (versi commit tetap kanonik)
for f in "${FROZEN_JSON[@]}"; do
  if [ -f "$BACKUP/$(basename "$f")" ]; then
    git checkout -- "$f" 2>/dev/null || cp -f "$BACKUP/$(basename "$f")" "$f"
  fi
done

# 6) log utama
{
  echo "=== SWEEP $STAMP ==="
  cat "$RUNLOG"
  echo "=== END $STAMP (backup: $BACKUP) ==="
} >> "$LOG"

echo "sweep selesai $STAMP; ringkasan: $MD; artefak: $BACKUP"
