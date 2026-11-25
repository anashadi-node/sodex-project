#!/bin/bash
# TWIN-ENGINE WATCHDOG — auto-restart daemon if dead
# Run: nohup bash scripts/watchdog_twin.sh > logs/watchdog.log 2>&1 &
# Safety: max 5 restarts per hour, cooldown after 3 rapid failures

set -e
cd "$(dirname "$0")/.."

MAX_RESTARTS_PER_HOUR=5
COOLDOWN_SEC=300
RESTART_COUNT=0
LAST_RESTART_TS=0
CHECK_INTERVAL=60
MAX_RESTART_SIGNAL_AGE_SEC=300

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

mkdir -p data logs
WATCHDOG_LOCK_DIR="data/watchdog_twin.lock"
if mkdir "$WATCHDOG_LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$WATCHDOG_LOCK_DIR/pid"
    trap 'rm -rf "$WATCHDOG_LOCK_DIR"' EXIT INT TERM
else
    OLD_PID=$(cat "$WATCHDOG_LOCK_DIR/pid" 2>/dev/null || true)
    OLD_CMD=$(ps -p "$OLD_PID" -o cmd= 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && printf '%s' "$OLD_CMD" | grep -q 'watchdog_twin.sh'; then
        log "⚠️ another watchdog already active pid=$OLD_PID — exiting"
        exit 0
    fi
    rm -rf "$WATCHDOG_LOCK_DIR"
    if ! mkdir "$WATCHDOG_LOCK_DIR" 2>/dev/null; then
        log "⚠️ watchdog lock busy — exiting"
        exit 0
    fi
    echo "$$" > "$WATCHDOG_LOCK_DIR/pid"
    trap 'rm -rf "$WATCHDOG_LOCK_DIR"' EXIT INT TERM
fi

# Load .env penuh (F1 overhaul 2026-06-29): sebelumnya hanya export 4 key SODEX_*,
# TE_* (termasuk TE_PVE_MAKER_PATH baru) tidak ter-pass ke daemon child → maker path
# tak pernah aktif meski .env benar. Sekarang `set -a; source .env` export SEMUA,
# hardcoded TE_* export di bawah jadi override opsional (sudah di-comment untuk .env-kanonik).
set -a
source .env
set +a
# NOTE: semua variabel .env sekarang ter-export ke daemon child (single source of truth).

# ═══════════════════════════════════════════════════════════
# 4-JAM DEADLINE TEST (2026-06-20 ~12:30-16:30 WIB)
# E2 BTC-USD diaktifkan untuk validasi volume.
# Rollback: kembalikan TE_E2_ENABLED=0 jika gagal.
# ═══════════════════════════════════════════════════════════
# E1: FULL FOKUS (2026-06-21) — satu-satunya engine net-POSITIF (+0.015-0.039%/vol)
#   → modal BERTAHAN/TUMBUH + ratio NO-LOSS terpenuhi (profit E1 > fee E1).
# 3 stream: PEPE (0.35%) + SHIB (0.21%) + AVAX (0.16%).
#   AVAX menggantikan XLM — spread 0.16% > threshold 0.15%.
# cap 250/pair, ladder 50-80-120. E2 OFF (kode disimpan utk event/market lain).
# ═══════════════════════════════════════════════════════════
# AUDIT 2026-07-02: .env IS THE SINGLE SOURCE OF TRUTH.
# All TE_E1_* / TE_PVE_* / TE_CAPITAL_* overrides below were
# REMOVED — they were defeating .env after source, causing:
#   - TE_E1_MIN_SPREAD=0.0035 (3.5 bps) > actual spread 1.6 bps → 0 fills
#   - TE_E1_SIZE_LADDER=50,80,120 → too small for volume target
#   - TE_E1_HEDGE_ENABLED=1 → XLM hedge WR=37.9% draining PnL
#   - TE_SPOT_PAIR_2="" → SHIB disabled despite .env enabling it
# These are now set correctly in .env; do NOT re-add here.
# ═══════════════════════════════════════════════════════════

# ── Only override vars NOT present in .env ────────────────
export TE_E1_COOLDOWN=3
export TE_E1_PAUSE_FLOOR=-0.002
export TE_E1_RESUME_FLOOR=-0.001
export TE_HEDGE_PERP=1000PEPE-USD  # SoDEX pair name (not overrideable via .env key)
# E1 RE-ENABLED with v3.6 ROOT-CAUSE FIX (2026-06-26): empirically proven via live
# diagnostic orders — SoDEX spot REJECTS GTC-limit SELL placed AT the touch (best ask)
# → oid=0 silent; SELL at ask+1 tick rests as valid maker (oid 2986748412 confirmed);
# market-IOC SELL also works (oid 2986654056). Old clamp forced sell to bk.ask (touch)
# → permanent oid=0. Fix: quote+flush sell at ask+1 tick; flush has market-IOC fallback.
# E1 = profit engine (maker both sides → offsets fees → ratio ≥1:9100). Hedge active for
# bear. Safety: G4 halt re-armed; monitor confirms valid sell oids before unattended run.
#
# F1 OVERHAUL (2026-06-29): TE_E1_ENABLED DIHAPUS dari watchdog → baca .env (=0).
# Sebelumnya watchdog force E1=1 meski .env=0 → daemon jalan E1 spot (PEPE dead-locked
# SELL block, noise log 13.3jam, inv nyangkut). Sekarang .env kontrol. E1 re-enable saat
# SPOT SELL block resolved (RC-4). Comment baris di bawah untuk override .env lagi.
# export TE_E1_ENABLED=1
# v3.7 (2026-06-26) E1 BEAR-SAFE + flush double-count fix:
#   - REGIME-ADAPTIVE: di BEAR → E1 SELL-ONLY (kuras inventory, tanpa beli baru) →
#     cegah akumulasi satu-arah (root cause re-akumulasi 88.5M). Ranging/bull = MM penuh.
#   - FLUSH FIX: cancel resting sells dulu (bebaskan qty) sebelum flush → tak jual >free.
#   - SELL FIX (v3.6): ask+1tick (SoDEX tolak sell di touch) + fresh-book retry +2tick.
#   Profit (ratio ≥1:9100) tercapai di ranging/bull; di bear E1 aman (drain-only).
# PVE v2 PRE-STAGED (2026-06-26): regime-adaptive SHORT/LONG, multi-pair, $130 notional.
# Bear-proof: BEAR→SHORT (captures downtrend), BULL/NEUTRAL→LONG. Math: 8×$130×1RT/5min=$1.4M/wk.
# STILL GATED OFF: sodex-target-policy returns BLOCK_E2_E1_RESEARCH_ONLY (WR<target, signal stale).
# Flip to =1 only after sodex-target-policy returns CAPPED_CATCH_UP_ALLOWED (or explicit operator override).
# PVE ACTIVATED bounded (2026-06-26): perps = viable volume route (E1 spot struktural
# unviable). Perps orders fill reliably (no touch-rejection). Bounded ke margin perps
# (~$60): 2 pair × $100 notional. Regime-adaptive (NEUTRAL→LONG spread, BEAR→SHORT).
# PnL-safe: daily-loss $5/pair (=$10/day max), historis PVE +$1.57/85RT (breakeven).
# Scale-up: tambah pairs/notional saat margin perps ditambah (transfer dari spot $749).
# PVE SCALED (2026-06-26): user transfer +$107 → perps margin ~$166. 4 pair × $120 @5x
# isolated (CHZ/HBAR/WLD set; SPCX proven). 4×$120×1RT/5min ≈ $1.9M/wk (> target $1.3M).
# Hindari 1000PEPE (= pair hedge E1, cegah konflik). PnL-aman: daily-loss $5/pair ($20/day
# max), breakeven engine, margin util ~$96/$166 (58%, buffer cukup utk konkurensi+adverse).
# BUG-B fix (2026-07-06): respect guardian's PVE_PAUSE_FILE. Previously hardcoded =1
# overrode .env, making check_e1_coverage/check_ratio_floor/check_weekly_pve_floor
# gates illusory — engine always restarted with PVE on regardless of guardian signals.
# Now: if data/PVE_PAUSE exists, engines stay alive in close-only mode. The Python
# engine blocks new opens from the pause file while continuing to drain exposure.
apply_pve_pause_gate() {
    if [[ -f "data/PVE_PAUSE" ]]; then
        log "INFO PVE_PAUSE gate active — starting PVE close-only (new opens blocked)"
    fi
}
apply_pve_pause_gate
# 2026-06-28: Trim ke 2 winner. Perp margin starved (am=$19.70 usable; $164 orphaned
# isolated im, 0 posisi) → oid=0 systemic. WLD (−$3.03/WR50%) + HBAR (−$1.55/WR48%)
# drag; SPCX (+$6.50/RT194) + CHZ winner. Konsentrasi margin langka ke volume profit.
#
# F1 OVERHAUL (2026-06-29): TE_PVE_PAIRS + TE_PVE_MAX_NOTIONAL DIHAPUS dari watchdog.
# Sebelumnya watchdog override .env (root cause: .env=SPCX-USD tapi watchdog=SPCX,CHZ →
# daemon pakai config lama + maker path tak terbaca). Sekarang .env = single source of truth.
# .env saat ini: TE_PVE_PAIRS=SPCX-USD, TE_PVE_MAKER_PATH=1 (maker micro-live test).
# Rollback: uncomment baris export di bawah untuk override .env lagi.
# export TE_PVE_PAIRS=SPCX-USD,CHZ-USD
# export TE_PVE_MAX_NOTIONAL=120
export TE_PVE_DIRECTION=auto
export TE_PVE_COOLDOWN=300
export TE_PVE_DAILY_LOSS=5
# B39 (2026-06-27): Turunkan threshold dari 0.03% → 0.01% agar HBAR (0.014%) dan
# WLD (0.022%) aktif — pasangan ini SUDAH di-TRANSFER modalnya ($107) tapi silent-skip
# akibat gate default 0.03%. PVE regime-directional (bukan pure-spread): alpha arah
# mengimbangi spread tipis (terbukti SPCX 0.026% masih +$6 profit). 4 pair → target $1.9M/wk.
#
# F1 OVERHAUL (2026-06-29): TE_PVE_MIN_SPREAD DIHAPUS dari watchdog → baca .env (0.005
# untuk maker micro-live). Comment jika perlu override.
# export TE_PVE_MIN_SPREAD=0.01

# E2: UJI ILMIAH TERKONTROL (2026-06-20 ~17:00 WIB) — root cause 4h-test DITEMUKAN.
# Temuan: orderID=0 di 4h-test BUKAN exchange rejection permanen — tapi MARGIN
#   perps kosong (~$14). Setelah transfer user → margin $52, uji manual XPL-USD
#   BUY @0.0960 qty=120 → orderID 9272517658 VALID & rest. Placement perps WORKS.
# Uji terkontrol: XPL-USD SAJA (hindari konflik posisi ENA E2Dir), clip kecil
#   $12-20 (aman utk margin $52), TON OFF (orderbook kosong → ghost).
# Budget guard: treasury allowance ~$74 (E1 7d profit $44 + kalibrasi $30).
# E2 CHURN (maker) = DEAD END (terbukti 2026-06-20). Uji 1-tick (XPL) DAN multi-tick
#   (SPCX): churn maker blocking selalu oid=0 — 1-tick tak ada ruang, multi-tick
#   stale-book crossing (SPCX gerak 10 tick/detik). 20 attempt → 0 RT.
# PIVOT ILMIAH: volume engine = E2Dir (direksional TAKER, funding edge) yang TERBUKTI
#   PROFITABLE (n=30 WR 63.3% +$0.325). "Volume adalah HASIL profitabilitas." Churn OFF.
export TE_E2_ENABLED=0
export TE_E2_CLIP_MIN=12
export TE_E2_CLIP_MAX=20
export TE_CHURN_PERP_2=
export TE_CHURN_PERP_3=

# FASE 2 / PHASE 2: Engine-2 Direksional (funding rate + OBI signal)
# FASE 1 VERDICT (2026-06-18): H1 TERFALSIFIKASI.
#   Spread PEPE selalu 34-35 bps (n=48, 0% waktu ≥ 40 bps) → quote saat spread
#   lebar MUSTAHIL karena spread tidak pernah melebar. E1 maker pasif = edge GAGAL.
#   Tidak perlu eksperimen B19 (kondisi prasyarat tidak terpenuhi).
#
# PHASE 2 PAPER MODE AKTIF (2026-06-18): mengumpulkan sinyal jujur (nol-risiko).
# Gate WR aktif saat n≥30; live butuh TE_E2_DIR_LIVE=1 + WR>50% terbukti.
# Budget keras: $10 rugi kumulatif → auto-HALT (tidak bisa override tanpa reset DB).
export TE_E2_DIR_ENABLED=0   # 2026-06-28: DISABLE. Paper budget-halted (−$25.07), WR memburuk ~27.8%, spam oid=0/HALT tiap ~47s membebani perp margin yg sudah starved. Re-enable saat margin sehat + sinyal bear berkualitas.
# B23: pair="" → scan DINAMIS semua 78 pair SoDEX perps, pilih |funding| tertinggi.
# Survey (2026-06-19, n=78): SoDEX max funding ~0.008%/8h (TRUMP-USD -0.0078%).
# ENA-USD flat (0.0013%) → hardcode pair TIDAK EFEKTIF.
export TE_E2_DIR_PAIR=
# LEVERAGED SCALP (2026-06-21): volume engine ke target. size=NOTIONAL.
#   leverage 10x (mulai aman; ramp 20x saat WR terbukti) → $120 notional = $12 margin
#   → $240/RT volume. Isolasi variabel leverage: hold 1800s (WR 63% terbukti) DULU,
#   optimasi turnover kemudian. SL 1% (= 10% margin @10x) ketat — likuidasi jauh.
#   Budget keras $15 rugi kumulatif → auto-HALT (lindungi modal). Guardian jaga margin.
export TE_E2_DIR_LEVERAGE=10
export TE_E2_DIR_SIZE=120.0
export TE_E2_DIR_SL=0.01
export TE_E2_DIR_TP=0.02
export TE_E2_DIR_HOLD_S=1800
export TE_E2_DIR_BUDGET=25.0   # B39 (2026-06-27): 15→25 — stop HALT spam, enable fresh accumulation
export TE_E2_DIR_MIN_N=30
# E2 MOMENTUM/OFI (2026-06-21): DIFALSIFIKASI secara ilmiah → DIMATIKAN.
#   Uji paper sistematis: momentum kontinuasi 37.5%, reversi 38.9%, OFI kontinuasi
#   31.2%, OFI reversi 42.9% (n=56, Wilson CI [30.8%,55.9%] straddle 50%). TIDAK ada
#   edge arah signifikan (efisiensi pasar horizon-pendek). Mengejar lanjut = overfit
#   noise. Fokus ke edge TERBUKTI: E2Dir funding-squeeze (63.3% WR) × leverage.
#   Kode tetap ada (re-enable utk riset masa depan via TE_E2_MOM_ENABLED=1).
export TE_E2_MOM_ENABLED=0
export TE_E2_MOM_LIVE=0
# B23: dikalibrasi ke skala SoDEX. Lama 0.05% TIDAK PERNAH tercapai (SoDEX max ~0.008%).
# Baru: 0.003%/8h → ambil pair ≥3× modus SoDEX (modus=0.0013%). Survey: TRUMP/SKHX/HYPE.
export TE_E2_DIR_FUNDING_THR=0.00003
export TE_E2_DIR_OBI_THR=0.15
# B38: minNotional SoDEX = $10 untuk semua 81 pairs → size $8 GAGAL (notional invalid).
# Fix: naik ke $11 (margin $1 di atas minimum). SAMSUNG-USD ~$233: $11/233=0.047 qty → $10.95 ✓
# Budget $15 = max total rugi sebelum auto-HALT (lindungi modal)
export TE_E2_DIR_LIVE=0   # 2026-06-26: FORCE PAPER. n=30 +$0.0108/sig stale = belum robust. Live only when n≥50 + WR>target + EV>0 after-fee (operator promote).

# Spot pairs (v3.4 2026-06-24) — SCIENTIFIC PAIR SELECTION
# HANYA PEPE/USDC — satu-satunya pair dengan edge terbukti (+0.0097% net all-time)
# SHIB/USDC DI-DISABLE (2026-06-24): 306 RTs, net -0.0375%, 17.7K waste fills
# ARB/USDC DI-DISABLE (2026-06-24): 27 RTs, net -0.1037%, 91% fills are non-RT waste
# Single-pair focus = less complexity, less flush waste, better monitoring
# TE_SPOT_PAIR_2/3/4 intentionally NOT overridden here — read from .env
export TE_EVENT_GUARD_UTC=""
export CONFIRM_LIVE=YES

source .venv-research/bin/activate

log "🛡️ WATCHDOG STARTED — check every ${CHECK_INTERVAL}s | max ${MAX_RESTARTS_PER_HOUR}/h"

RESTART_SIGNAL_FILE="data/GUARDIAN_RESTART_SIGNAL"
PNL_HALT_FILE="data/PNL_HALT"
SAFETY_HALT_FILE="data/SAFETY_HALT"

halt_active() { [ -f "$PNL_HALT_FILE" ] || [ -f "$SAFETY_HALT_FILE" ]; }

while true; do
    if halt_active; then
        if [ -f "$RESTART_SIGNAL_FILE" ]; then
            rm -f "$RESTART_SIGNAL_FILE"
            log "🛑 HALT active — restart suppressed and signal consumed"
        else
            log "🛑 HALT active — restart suppressed"
        fi
        sleep $CHECK_INTERVAL
        continue
    fi

    # ═══════════════════════════════════════════════════════════
    # CHECK 0: RESTART SIGNAL from guardian/autopilot
    # Guardian v3 + Autopilot v3 write this file when daemon
    # stuck detected. Watchdog reads, logs, kills daemon,
    # then normal restart logic brings it back.
    # ═══════════════════════════════════════════════════════════
    if [ -f "$RESTART_SIGNAL_FILE" ]; then
        NOW_TS=$(date +%s)
        SIG_TS=$(stat -c %Y "$RESTART_SIGNAL_FILE" 2>/dev/null || echo 0)
        SIG_AGE=$((NOW_TS - SIG_TS))
        if [ "$SIG_AGE" -gt "$MAX_RESTART_SIGNAL_AGE_SEC" ]; then
            log "⚠️ stale restart signal ignored age=${SIG_AGE}s: $(cat $RESTART_SIGNAL_FILE 2>/dev/null)"
            rm -f "$RESTART_SIGNAL_FILE"
            sleep $CHECK_INTERVAL
            continue
        fi
        if halt_active; then
            rm -f "$RESTART_SIGNAL_FILE"
            log "🛑 HALT active — restart signal consumed before daemon kill"
            sleep $CHECK_INTERVAL
            continue
        fi
        # B56: heartbeat-aware restart gating. Signal types driven by "no/stale fills"
        # (monitor-eval-repair, stuck-idle, zero-fill, stuck-rt) are MARKET conditions on a
        # thin low-cap maker — a restart cannot create takers; it only cancels the resting
        # SELL orders and resets their queue priority, so the "stuck" state self-perpetuates.
        # Honor these ONLY if the engine is genuinely hung (no fresh log activity). A truly
        # dead PROCESS is still caught by the pgrep check below. Capital-protection signals
        # (pnl-emergency, deadman, manual) are always honored.
        SIG_TYPE=$(grep -o '"type"[^,}]*' "$RESTART_SIGNAL_FILE" 2>/dev/null | head -1 | sed 's/.*: *"//; s/".*//' || true)
        case "$SIG_TYPE" in
            monitor-eval-repair|stuck-idle|zero-fill|stuck-rt)
                HB_AGE=999
                LOG_TS=$(stat -c %Y logs/twin_live.log 2>/dev/null || echo 0)
                HB_AGE=$((NOW_TS - LOG_TS))
                # B60 (29-Sep-2026): ambang 90s → 900s. AKAR −$8,6/hari: maker engine di pasar
                # tipis WAJAR tidak log fill >90s, tapi dianggap "hang" → kill → engine SIGTERM
                # membatalkan SEMUA order (138 restart/24j) → queue priority hancur =
                # adverse selection murni. Proses benar-benar mati tetap tertangkap pgrep di bawah.
                if [ "$HB_AGE" -lt 900 ]; then
                    log "🟢 restart signal type=$SIG_TYPE IGNORED — engine quoting (log age ${HB_AGE}s < 900s). Stale-fill is a thin-market condition, not an engine hang; restart would only cancel resting maker orders."
                    rm -f "$RESTART_SIGNAL_FILE"
                    sleep $CHECK_INTERVAL
                    continue
                fi
                log "⚠️ restart signal type=$SIG_TYPE honored — engine heartbeat STALE (log age ${HB_AGE}s ≥ 900s) → possible hang"
                ;;
        esac
        log "🚨 RESTART SIGNAL DETECTED: $(cat $RESTART_SIGNAL_FILE 2>/dev/null)"
        # Kill daemon — normal loop below will restart it
        DAEMON_PID=$(ps aux | grep "sodex_twin_engine.py run" | grep -v grep | awk '{print $2}')
        if [ -n "$DAEMON_PID" ]; then
            kill $DAEMON_PID 2>/dev/null
            sleep 2
            # Force kill if still alive
            kill -9 $DAEMON_PID 2>/dev/null || true
            log "🛡️ Daemon killed (PID $DAEMON_PID) — restarting per guardian/autopilot signal"
        fi
        rm -f "$RESTART_SIGNAL_FILE"
    fi
    
    # Check if daemon is alive
    PID=$(ps aux | grep "sodex_twin_engine.py run" | grep -v grep | awk '{print $2}')
    
    if [ -z "$PID" ]; then
        NOW_TS=$(date +%s)
        
        # Kill any zombie daemon processes first
        ZOMBIES=$(ps aux | grep "sodex_twin_engine.py run" | grep -v grep | awk '{print $2}')
        if [ -n "$ZOMBIES" ]; then
            for zp in $ZOMBIES; do
                kill -9 $zp 2>/dev/null
            done
            sleep 2
        fi
        
        # Rate limiting
        if [ $((NOW_TS - LAST_RESTART_TS)) -lt 60 ]; then
            RESTART_COUNT=$((RESTART_COUNT + 1))
        else
            RESTART_COUNT=1
        fi
        
        if [ $RESTART_COUNT -gt $MAX_RESTARTS_PER_HOUR ]; then
            log "🚨 TOO MANY RESTARTS ($RESTART_COUNT/h) — COOLDOWN ${COOLDOWN_SEC}s"
            sleep $COOLDOWN_SEC
            RESTART_COUNT=0
            continue
        fi
        
        if [ $RESTART_COUNT -gt 3 ]; then
            log "⚠️ Rapid restart #$RESTART_COUNT — waiting 30s before retry"
            sleep 30
        fi

        if halt_active; then
            log "🛑 HALT active before restart — restart suppressed"
            sleep $CHECK_INTERVAL
            continue
        fi
        
        log "🔴 DAEMON DEAD — restarting (attempt #$RESTART_COUNT this hour)..."
        # Re-source .env sebelum setiap restart — watchdog startup source SATU KALI saja,
        # sehingga perubahan .env setelah startup (misal: disable/enable pair) tidak ter-pick-up.
        # Dengan re-source di sini, setiap restart selalu pakai nilai .env TERKINI.
        # Penting: ini fixes root-cause SHIB/AVAX masih aktif meski .env sudah dikosongkan.
        set -a; source .env; set +a
        # Strategy sizing and pair selection remain canonical in .env.
        # Non-interactive: daemon skips input() when stdin is not TTY
        apply_pve_pause_gate
        CONFIRM_LIVE=YES nohup python3 -u anantara/sodex_twin_engine.py run --live \
            < /dev/null >> logs/twin_live.log 2>&1 &
        NEW_PID=$!
        log "✅ RESTARTED — PID $NEW_PID"
        LAST_RESTART_TS=$NOW_TS
        
        # Wait for startup
        sleep 10
        if ps -p $NEW_PID > /dev/null 2>&1; then
            log "✅ Daemon stable after restart"
        else
            log "❌ Daemon died immediately after restart"
        fi
    fi
    
    sleep $CHECK_INTERVAL
done
