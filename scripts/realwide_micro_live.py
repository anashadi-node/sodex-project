#!/usr/bin/env python3
"""REAL-wide MICRO-LIVE v2 - uang nyata kecil, sinyal 100% sama dgn paper.

REV 2026-09-04: v1 pakai sinyal reimplementasi manual usang (3 pair, tanpa
regime-gate/ADX/15m-confirm). v2 IMPORT LANGSUNG paper_test_realwide.py
sbg single source of truth - zero divergence risk, 23 pair penuh.

SAFETY ENVELOPE (hardcoded):
  SIZE_NOTIONAL=$120/trade @3x, MAX_POSITIONS_TOTAL=2 with dynamic Level-2
  risk gate, SESSION_LOSS_CAP=-$9, DAILY_TRADE_CAP=6, KILL switch file,
  DRY by default.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_test_realwide as PT  # single source of truth utk sinyal LONG
import paper_test_shortbear as SB  # validated SHORT-BEAR paper signal
from sodex_realtime_sync import real_perps_positions, real_perps_orders

PROJECT = Path(__file__).resolve().parents[1]
STATE_FILE = PROJECT / "data" / "realwide_micro_live_state.json"
# PORTFOLIO GUARD (28-Sep) — rem lintas-track (R1-R3/R5) + sensor regime cepat
# (R4, nowcast 2 menit). UANG NYATA -> fail_closed=True: data gagal = no entry.
sys.path.insert(0, str(PROJECT / "anantara"))
import portfolio_guard as PGUARD  # noqa: E402
# BIAYA NYATA (audit 30-Sep-2026): lane ini memakai `--type market --tif ioc` = TAKER
# di KEDUA sisi (entry :604, exit :412). Biaya round-trip nyata = taker 2 sisi (8 bps)
# + spread 2 sisi + funding ≈ 14,3 bps (BTC). JANGAN pakai asumsi maker utk lane ini —
# model lama (maker + 1x spread) terbukti 2,97x terlalu murah.
from cost_model import round_trip_frac as _rt_cost  # noqa: E402
from sodex_maker_order import place_maker_first  # noqa: E402
# Guard mode (incident 2026-09-25): True hanya bila dijalankan --live (service).
# Proses dry/manual menulis ke _DRY_STATE_FILE, tidak pernah menyentuh state live.
_LIVE_MODE = False
_DRY_STATE_FILE = PROJECT / "data" / "realwide_micro_live_state.DRY.json"
LOG_FILE = PROJECT / "data" / "realwide_micro_live.jsonl"
KILL_FILE = PROJECT / "data" / "REALWIDE_LIVE_KILL"
GATE_FILE = PT.GATE_FILE  # sama persis dgn paper - satu writer, satu pembaca

SODEX_CLI = str(PROJECT / "bin" / "sodex")
TICKERS = "https://mainnet-gw.sodex.dev/api/v1/perps/markets/tickers"

# Universe = PERSIS sama dgn paper (23 pair). Qty precision per pair, verified
# via `bin/sodex markets perps --format json` 2026-09-04 (semua 23 TRADING).
QTY_PREC = {"BTC": 5, "ETH": 4, "XRP": 1, "SOL": 3, "HYPE": 2, "DOGE": 0,
            "BCH": 3, "ONDO": 1, "LINK": 1, "AAVE": 2, "SUI": 1, "ADA": 1,
            "TRX": 0, "UNI": 1, "ENA": 0, "XAUT": 4, "SILVER": 2, "ARB": 1,
            "AVAX": 0, "ASTER": 0, "PUMP": 0, "LIT": 1, "BNB": 3}
# ASTER dikecualikan dari LIVE (2026-09-06, approved user): user sedang
# testing manual posisi ASTER-USD di exchange — sistem tidak boleh entry
# pair yang sedang dipegang manual (hindari tabrakan posisi/gate).
ASTER_MANUAL_EXCLUDE = {"ASTER"}
SODEX_SYM = {p: f"{p}-USD" for p in PT.PAIRS if p not in ASTER_MANUAL_EXCLUDE}
MIN_NOTIONAL = 10.0  # semua pair sama, verified dari markets perps

TP_PCT, SL_PCT = 0.06, 0.03    # RISET A2 27-Sep (approved user 28-Sep): align
# paper geometri baru TP6%/SL3%/TIME24h — walk-forward IS&OOS winner (WR 53,7%
# PF 1,83 vs lama 48,8% PF 1,64). SL1,5% terbukti mati kena noise di live
# (ETH −1,89% exit SL padahal tesis belum mati).
TIME_STOP_H = PT.TIME_STOP_H                 # 24 — ikut paper (Riset A2)
LEVERAGE = PT.LEVERAGE                       # 3
COOLDOWN_H = 4   # PROMO 2026-09-08 (approved user): 12 -> 4, match paper.
# Akselerasi CD12->CD4 terbukti: replay 5-minggu +34% throughput, PF naik
# 1,98 -> 2,16, net +54%, forward WR 67%. Live ikut karena GO achieved.
SIZE_NOTIONAL = float(os.environ.get("RL_SIZE_NOTIONAL", "140"))
# RISET 28-Sep (keputusan owner delegated): 120→140 = maks aman dalam
# SESSION_LOSS_CAP $9 dg geo SL3% 2 posisi: 2×(0,03×140)=$8,40 < $9.
# Margin/check: 140/3x=$47/posisi, 2 pos=$94 < 70%×avail $213=$149. OK.
# SIZE_NOTIONAL = USD notional target, BUKAN margin dan BUKAN dikali leverage lagi.
# Margin approx SIZE_NOTIONAL/LEVERAGE = $40 pada 3x. PnL dihitung dari
# actual notional (qty*entry), sehingga sizing tidak double-count leverage.
MAX_POSITIONS_TOTAL = 2
# LEVEL-2 AGGRESSION (approved user 2026-09-23): hard cap naik 1 -> 2, tetapi
# effective cap tetap dinamis: hanya BULL, margin-util <=70%, existing posisi
# tidak merah, dan max 1 entry baru per cycle. Leverage/TP/SL TIDAK dinaikkan.
LEVEL2_MARGIN_UTIL_CAP = 0.70
LEVEL2_MIN_EXISTING_GROSS = 0.0
LEVEL2_MAX_NEW_ENTRIES_PER_CYCLE = 1
SESSION_LOSS_CAP = -12.00   # Opsi C disetujui owner 28-Sep (dari -9,00). Plafon size = 12/(2*0,03) = $200.
                            # Guard (portfolio_guard) tetap fail-closed: CHOP -> entry diblokir, jadi cap ini hanya aktif di TREND.
# worst/trade = 1,5% x $120 notional = -$1,80. Cap -$9,00 = room untuk
# beberapa attempt kecil, tapi dynamic Level-2 gate + watchdog tetap gate utama.
DAILY_TRADE_CAP = 6
# CLAMP KESELAMATAN (2026-09-28): size tidak boleh melebihi plafon yang masih
# tertutup SESSION_LOSS_CAP bila SEMUA posisi kena SL bersamaan. Tanpa ini,
# menaikkan RL_SIZE_NOTIONAL lewat env bisa menembus cap loss sesi diam-diam
# (jalur safety tidak boleh rusak karena perubahan konfigurasi size).
# Plafon = |SESSION_LOSS_CAP| / (MAX_POSITIONS_TOTAL x SL_PCT) = 9/(2x0,03) = $150.
SIZE_NOTIONAL_SAFE_MAX = abs(SESSION_LOSS_CAP) / (MAX_POSITIONS_TOTAL * SL_PCT)
if SIZE_NOTIONAL > SIZE_NOTIONAL_SAFE_MAX:
    print(f"[SIZE-CLAMP] RL_SIZE_NOTIONAL=${SIZE_NOTIONAL:.0f} melebihi plafon aman "
          f"${SIZE_NOTIONAL_SAFE_MAX:.0f} (SESSION_LOSS_CAP {SESSION_LOSS_CAP}, "
          f"{MAX_POSITIONS_TOTAL} posisi x SL {SL_PCT*100:.1f}%) -> dipakai "
          f"${SIZE_NOTIONAL_SAFE_MAX:.0f}", flush=True)
    SIZE_NOTIONAL = SIZE_NOTIONAL_SAFE_MAX
# INTENSIFIKA 2026-09-09: 4 -> 6. COOLDOWN 4h suport sampai 6 slot/hari;
# session cap -$9 halt otomatis walau daily cap belum kena (protection double).


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def sodex(args, timeout=25):
    return subprocess.run([SODEX_CLI] + args, capture_output=True, text=True,
                          timeout=timeout, env={**os.environ})


def get_balance_usd():
    """Saldo vUSDC PERPS via `bin/sodex balance perps`."""
    r = sodex(["balance", "perps", "--format", "json"])
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout or "[]")
        for row in data:
            if row.get("coin") == "vUSDC":
                return float(row.get("total") or 0)
    except Exception:
        pass
    return None


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"created": now_iso(), "open": {}, "closed": [], "last_entry": {},
            "session_pnl": 0.0, "day": "", "trades_today": 0}


def _num(value):
    try:
        return float(str(value).replace("x", ""))
    except Exception:
        return None


UNVERIFIED_MIN_MISS = 3        # cycle berturut-turut exchange benar-benar flat
UNVERIFIED_MIN_AGE_MIN = 30    # umur minimum sebelum auto-resolve (menit)


def should_autoresolve_unverified(pos, sym, real_syms, order_syms, now_ts,
                                  min_miss=UNVERIFIED_MIN_MISS, min_age_min=UNVERIFIED_MIN_AGE_MIN):
    """True bila entry provisional (UNVERIFIED_AFTER_ORDER) sudah TERBUKTI tidak ada
    di exchange: exchange flat untuk `sym` DAN tidak ada open order, sudah terjadi
    `min_miss` kali berturut-turut DAN umur entry >= min_age_min menit.

    Guard fail-closed: selama ragu (posisi/order terlihat, atau belum cukup bukti)
    entry DIBIARKAN tercatat -> tidak ada exposure nyata yang dilupakan.
    Root cause insiden 2026-09-25: entry UNVERIFIED_AFTER_ORDER menggantung permanen
    -> reconcile HALT setiap cycle -> live entry mati berhari-hari (3.386 HALT).
    """
    if pos.get("verification_status") != "UNVERIFIED_AFTER_ORDER":
        return False
    if sym in real_syms or sym in order_syms:
        return False
    miss = int(pos.get("_unverified_miss", 0))
    age_min = (now_ts - float(pos.get("entry_ts") or now_ts)) / 60.0
    return miss >= min_miss and age_min >= min_age_min


def autoresolve_unverified(st):
    """Naikkan hitungan miss entry provisional & bersihkan yang terbukti tidak ada.
    Return daftar pair yang dibersihkan (audit + alert)."""
    resolved = []
    try:
        real_syms = {str(p.get("symbol")) for p in real_perps_positions()
                     if abs(float(p.get("size") or 0)) > 0}
        order_syms = {str(o.get("symbol")) for o in real_perps_orders()}
    except Exception as e:
        print(f"  [UNVERIFIED] cek exchange gagal ({e}) — tidak ada auto-resolve cycle ini")
        return resolved
    now_ts = time.time()
    for pair, pos in list(st.get("open", {}).items()):
        if pos.get("verification_status") != "UNVERIFIED_AFTER_ORDER":
            continue
        sym = SODEX_SYM.get(pair)
        if not sym:
            continue
        if sym in real_syms or sym in order_syms:
            pos["_unverified_miss"] = 0
            continue
        pos["_unverified_miss"] = int(pos.get("_unverified_miss", 0)) + 1
        if should_autoresolve_unverified(pos, sym, real_syms, order_syms, now_ts):
            resolved.append(pair)
            del st["open"][pair]
            st.get("last_entry", {}).pop(pair, None)
            print(f"  [UNVERIFIED-RESOLVED] {pair}: terbukti tidak ada di exchange "
                  f"(miss={pos.get('_unverified_miss')}, umur {((now_ts - pos['entry_ts'])/60):.0f} mnt) "
                  f"— state provisional dibersihkan, entry live kembali normal")
    return resolved


def live_entry_reconciled(st):
    """Allow no new live entry unless exchange and local perps state match."""
    try:
        real = real_perps_positions()
        real_by_sym = {}
        for p in real:
            size = _num(p.get("size")) or 0.0
            if abs(size) > 0:
                real_by_sym[str(p.get("symbol"))] = p

        expected = {SODEX_SYM[pair]: (pair, pos)
                    for pair, pos in st.get("open", {}).items()
                    if pair in SODEX_SYM}
        if set(real_by_sym) != set(expected):
            return False, f"exchange={sorted(real_by_sym)} local={sorted(expected)}"
        for sym, (pair, local) in expected.items():
            real_pos = real_by_sym[sym]
            real_size = _num(real_pos.get("size"))
            local_qty = _num(local.get("qty"))
            if real_size is None or local_qty is None or local_qty <= 0:
                return False, f"qty_parse_mismatch {pair}: exchange={real_pos.get('size')} local={local.get('qty')}"
            local_side = str(local.get("side", "long")).lower()
            real_side = "short" if real_size < 0 else "long"
            if real_side != local_side:
                return False, f"side_mismatch {pair}: exchange={real_side} local={local_side}"
            qty_tol = max(1e-8, local_qty * 0.05)
            if abs(abs(real_size) - local_qty) > qty_tol:
                return False, f"qty_mismatch {pair}: exchange={abs(real_size)} local={local_qty} tol={qty_tol}"
            # BUGFIX audit 2026-09-27: leverage BUKAN identitas posisi — exit PnL
            # = qty*(exit-entry), tidak bergantung leverage; SL 1,5% jauh dari likuidasi
            # (≥20%). Venue bisa mengubah leverage isolated posisi kapan saja (BTC
            # exchange=5 vs lokal=3 → 107 siklus HALT permanen, entry live mati).
            # Field identitas (size/side/entry) TETAP fail-closed. Leverage kini
            # di-re-sync ke kebenaran exchange + warning, bukan blokade.
            real_lev = _num(real_pos.get("leverage"))
            if real_lev is not None and abs(real_lev - LEVERAGE) > 1e-9:
                prev_lev = _num(local.get("verified_leverage"))
                if prev_lev is None or abs(real_lev - prev_lev) > 1e-9:
                    local["verified_leverage"] = real_lev
                    save_state(st)
                    print(f"  [LEVERAGE-RESYNC] {pair}: exchange={real_lev}x "
                          f"≠ asumsi {LEVERAGE}x — state di-sync, entry TETAP dibuka")
            real_entry = _num(real_pos.get("avgEntryPrice"))
            local_entry = _num(local.get("entry_price"))
            if real_entry and local_entry:
                entry_tol = max(0.01, local_entry * 0.03)
                if abs(real_entry - local_entry) > entry_tol:
                    return False, f"entry_mismatch {pair}: exchange={real_entry} local={local_entry} tol={entry_tol}"
        return True, "match"
    except Exception as e:
        return False, f"reconcile_error={e}"


def verify_open_position_stable(sym, confirmations=3, delay_s=5):
    """Return matched exchange position only if it persists across polls.

    Real-money canary 2026-09-19 showed a position visible right after order,
    then absent on the next watchdog check. Saving local state after one poll
    creates a PHANTOM. Require stable exchange truth before state write.
    """
    matched = None
    for i in range(confirmations):
        real_pos = real_perps_positions()
        matched = next((p for p in real_pos
                        if p.get("symbol") == sym and abs(float(p.get("size") or 0)) > 0), None)
        if not matched:
            return None, f"missing_on_poll_{i + 1}/{confirmations}"
        if i < confirmations - 1:
            time.sleep(delay_s)
    return matched, "stable"


def save_state(st):
    """Tulis state. GUARD (incident 2026-09-25): proses NON-LIVE (dry/manual run)
    TIDAK BOLEH menulis state live — dua proses (dry manual + service) menulis file
    yang sama = last-writer-wins, dan posisi nyata (SOL 24 Sep… 25 Sep) hilang dari
    state sehingga jadi untracked di exchange. Dry run menulis ke file terpisah.
    """
    if not _LIVE_MODE:
        _DRY_STATE_FILE.write_text(json.dumps(st, indent=2, default=str))
        return
    STATE_FILE.write_text(json.dumps(st, indent=2, default=str))


def kill_check(st):
    if KILL_FILE.exists():
        return "KILL_SWITCH"
    d = datetime.now(timezone.utc).strftime("%Y%m%d")
    if st.get("day") != d:
        st["day"] = d; st["trades_today"] = 0; st["session_pnl"] = 0.0
    if st.get("session_pnl", 0) <= SESSION_LOSS_CAP:
        return "SESSION_LOSS_CAP"
    if st.get("trades_today", 0) >= DAILY_TRADE_CAP:
        return "DAILY_TRADE_CAP"
    return None


def position_notional(pos):
    """Actual USD notional. Leverage is already expressed by qty, do not multiply twice."""
    try:
        qty = abs(float(pos.get("qty") or 0))
        entry = float(pos.get("entry_price") or 0)
        if qty > 0 and entry > 0:
            return qty * entry
    except Exception:
        pass
    return SIZE_NOTIONAL


def entry_qty(pair, px):
    """Qty for target notional. SIZE_NOTIONAL is USD notional, not margin."""
    return round(SIZE_NOTIONAL / px, QTY_PREC.get(pair, 4))


def margin_required_for_positions(n):
    return float(n) * SIZE_NOTIONAL / LEVERAGE


def level2_existing_positions_ok(st):
    """Second slot only if every existing position is not red.

    Fetch failure = fail-closed to Level 1; we do not add exposure when we cannot
    measure current unrealized risk.
    """
    for pair, pos in st.get("open", {}).items():
        try:
            d = PT.fetch_ohlcv(PT.BN[pair])
            px = float(d["c"][-1])
            if side_gross(pos, px) < LEVEL2_MIN_EXISTING_GROSS:
                return False
        except Exception:
            return False
    return True


def effective_max_positions(st, market_mode, balance_usd=None):
    """Dynamic exposure cap for Level-2 measured aggression.

    Hard cap is 2, but effective cap falls back to 1 unless all scientific risk
    conditions pass. UNKNOWN/SIDEWAYS/BEAR stay Level 1 until enough data says
    otherwise; BULL can use second slot if margin and current PnL state are safe.
    """
    hard_cap = min(int(MAX_POSITIONS_TOTAL), 2)
    if hard_cap <= 1:
        return hard_cap
    if str(market_mode or "UNKNOWN").upper() != "BULL":
        return 1
    if st.get("session_pnl", 0.0) < 0:
        return 1
    if not level2_existing_positions_ok(st):
        return 1
    bal = get_balance_usd() if balance_usd is None else balance_usd
    if bal is None:
        return 1
    if margin_required_for_positions(hard_cap) > float(bal) * LEVEL2_MARGIN_UTIL_CAP:
        return 1
    return hard_cap


def side_gross(pos, px):
    """Signed gross return: positive means profit for the stored side."""
    entry = float(pos["entry_price"])
    if str(pos.get("side", "long")).lower() == "short":
        return (entry - px) / entry
    return (px - entry) / entry


def long_gate_allows_measured_short(blocked, reason):
    """Backward-compatible: old regime block maps to non-long-only scan."""
    if not blocked:
        return False
    r = str(reason).lower()
    return "regime not ok" in r or "bear" in r or "sideways" in r


def btc_market_mode():
    """Classify BTC regime for live direction planning.

    BULL: trend-up, LONG priority. BEAR: trend-down, SHORT priority.
    SIDEWAYS: no strong trend; scan both, no forced trade. UNKNOWN: fail-closed.
    """
    try:
        import backtest_swing_gate1_v3 as v3
        d = PT.fetch_ohlcv(PT.BN["BTC"])
        c, h, l = d["c"], d["h"], d["l"]
        i = len(c) - 2
        if i < 200:
            return "UNKNOWN"
        adx = v3.adx(h, l, c)
        s50 = v3.sma(c, 50)
        s200 = v3.sma(c, 200)
        if adx[i] > 22 and c[i] > s50[i] and s50[i] > s200[i]:
            return "BULL"
        if adx[i] > 22 and c[i] < s50[i] and s50[i] < s200[i]:
            return "BEAR"
        return "SIDEWAYS"
    except Exception:
        return "UNKNOWN"


def direction_plan(market_mode):
    mode = str(market_mode or "UNKNOWN").upper()
    if mode == "BEAR":
        return ["short", "long"]
    if mode in {"BULL", "SIDEWAYS"}:
        return ["long", "short"]
    return []


def _best_bid_ask(sym: str) -> tuple[float, float] | None:
    """(best_bid, best_ask) dari ticker perps venue. None bila tak terbaca (fail-closed).

    MENGAPA ada: eksekusi maker-first butuh harga touch nyata. Kalau tak terbaca,
    pemanggil TIDAK boleh menebak — lebih baik taker (biaya) daripada harga karangan.
    """
    r = sodex(["tickers", "perps", "--format", "json"])
    if getattr(r, "returncode", 1) != 0:
        return None
    try:
        rows = json.loads(getattr(r, "stdout", "") or "[]")
    except Exception:
        return None
    for row in rows if isinstance(rows, list) else []:
        if str(row.get("symbol")) == str(sym):
            try:
                b = float(row.get("bidPx") or 0)
                a = float(row.get("askPx") or 0)
            except Exception:
                return None
            if b > 0 and a > 0:
                return (b, a)
    return None


def place_entry(sym: str, side: str, qty: float, ref_px: float) -> bool:
    """Entry MAKER-FIRST (gtx limit) + fallback market bila perlu.

    Dipakai lane uang nyata; gagal = False (pemanggil wajib `continue`, fail-closed).
    """
    bk = _best_bid_ask(sym)
    if bk is None:
        print(f"  [MAKER] {sym}: buku tak terbaca -> fallback taker langsung")
        b, a = ref_px, ref_px
        allow = True
        wait = 0.0
    else:
        b, a = bk
        allow = True
        wait = float(os.environ.get("RL_MAKER_WAIT_S", "20"))
    res = place_maker_first(sodex, symbol=sym, side=side, qty=qty,
                            best_bid=b, best_ask=a,
                            entry_ref_px=ref_px,
                            max_slip_pct=float(os.environ.get("RL_MAKER_MAX_SLIP", "0.0015")),
                            max_wait_s=wait, poll_s=1.5,
                            allow_taker_fallback=allow)
    if not res.filled:
        print(f"  [MAKER-SKIP] {sym}: {res.detail}")
        return False
    print(f"  [MAKER] {sym} {side} qty={qty} via={res.via} px={res.price}")
    return True


def verify_position_closed(sym, confirmations=3, delay_s=3):
    """True HANYA bila posisi benar-benar hilang di venue — bukan asumsi `rc=0`.

    Cermin dari verify_open_position_stable(): satu poll terlalu rapuh. Bila venue
    masih menampilkan posisi sesaat karena lag, close yang SAH dianggap gagal ->
    local open dipertahankan -> siklus berikutnya mengirim close lagi + watchdog
    alert palsu. Konfirmasi berulang menghapus keraguan itu.
    Gagal membaca venue = fail-closed (dianggap BELUM tertutup, local open aman).
    """
    last = None
    for i in range(confirmations):
        try:
            real_pos = real_perps_positions()
        except Exception as e:
            return False, f"verify_error={e}"
        last = next((p for p in real_pos
                     if p.get("symbol") == sym and abs(float(p.get("size") or 0)) > 0), None)
        if last is None:
            return True, f"closed_{i + 1}/{confirmations}"
        if i < confirmations - 1:
            time.sleep(delay_s)
    return False, f"residual_size={last.get('size') if last else 'unknown'}"


def place_exit(sym: str, close_side: str, qty: float, urgent: bool) -> tuple:
    """Exit: SL/KILL = market langsung (taker). TP/TIME = maker-first.

    MENGAPA: keamanan > biaya. Menahan posisi merugi demi menghemat bps = salah.
    Exit TIDAK boleh ditinggalkan kalau maker tak terisi -> fallback selalu aktif.

    Return (ok, rc) — `rc` NYATA dari venue, supaya ledger tidak melaporkan rc
    palsu (audit 30-Sep-2026: `rec["close_rc"]` sebelumnya di-hardcode 0 padahal
    order bisa gagal). `rc=0` SENDIRI bukan bukti posisi tertutup — pembuktian
    ada di verify_position_closed() (pelajaran nyata: rc=0 + orderID=0 -> fill
    phantom, rugi -$0,10).
    """
    if urgent:
        r = sodex(["orders", "place", "perps", "--symbol", sym, "--side", close_side,
                   "--type", "market", "--tif", "ioc", "--qty", str(qty), "--reduce-only"])
        oid = _oid_of(getattr(r, "stdout", "") or "")
        rc = int(getattr(r, "returncode", 1))
        err = (getattr(r, "stderr", "") or "").strip()[:140]
        print(f"  [EXIT-URGENT] {sym} market reduce-only rc={rc} oid={oid or '-'}"
              + (f" err={err}" if err else ""))
        return (bool(oid) or rc == 0), rc
    bk = _best_bid_ask(sym)
    if bk is None:
        return place_exit(sym, close_side, qty, urgent=True)
    res = place_maker_first(sodex, symbol=sym, side=close_side, qty=qty,
                            best_bid=bk[0], best_ask=bk[1], reduce_only=True,
                            max_wait_s=float(os.environ.get("RL_MAKER_EXIT_WAIT_S", "15")),
                            poll_s=1.5, allow_taker_fallback=True)
    print(f"  [EXIT-MAKER] {sym} via={res.via} px={res.price} filled={res.filled}")
    return bool(res.filled), (0 if res.filled else 1)


def _oid_of(out: str) -> str:
    import re
    m = re.search(r"orderID[=:\s]+(\d+)", str(out))
    return m.group(1) if m and m.group(1) != "0" else ""


def close_position(st, pair, px, reason, live):
    t = st["open"][pair]
    gross = side_gross(t, px)
    # BUGFIX (30-Sep-2026): baris ini masih memakai model biaya LAMA (maker + 1x
    # spread) padahal lane = TAKER. Sekarang pakai sumber tunggal cost_model.
    cost = float(_rt_cost(venue="perps", order_type="taker", pair=pair,
                          hold_hours=float(t.get("hold_h") or 12)))
    net = gross - cost
    pnl_usd = net * position_notional(t)
    rec = {**t, "exit_price": px, "exit_time": now_iso(), "exit_reason": reason,
           "net_pct": net, "pnl_usd": pnl_usd, "position_notional": position_notional(t)}
    if live:
        sym = SODEX_SYM[pair]
        qty = t["qty"]
        close_side = "buy" if str(t.get("side", "long")).lower() == "short" else "sell"
        # MAKER-FIRST (approval user 30-Sep-2026): SL/KILL tetap taker (urgent),
        # TP/TIME pakai maker (hemat ~5,6 bps/RT). Fallback taker selalu aktif.
        _urgent = str(reason).upper().startswith(("SL", "KILL"))
        # rc NYATA dari venue (audit 30-Sep-2026: dulu di-hardcode 0 = field audit
        # palsu; ledger melaporkan sukses padahal order bisa gagal).
        ok, rc = place_exit(sym, close_side, qty, urgent=_urgent)
        rec["close_rc"] = rc
        if not ok:
            print(f"  [LIVE-CLOSE-ERR] {pair}: exit gagal rc={rc} ({reason}) — local open DIPERTAHANKAN")
            return False
        time.sleep(2)
        # Bukti = venue, bukan rc. Berulang (cermin verify_open_position_stable):
        # satu poll rapuh terhadap lag venue -> close sah dianggap gagal.
        closed, detail = verify_position_closed(sym)
        if not closed:
            print(f"  [HALT] {pair}: exit tidak terkonfirmasi ({detail}) — local open DIPERTAHANKAN")
            return False
    st["closed"].append(rec)
    st["session_pnl"] = st.get("session_pnl", 0) + pnl_usd
    del st["open"][pair]
    if not _LIVE_MODE:
        return  # dry run: tidak menulis audit log live (guard 2026-09-25)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"  [EXIT] {pair} {reason}: net {net*100:+.2f}% (${pnl_usd:+.2f})")
    return True


def macro_btc_long_blocked():
    """Reuse fungsi paper via regime_filter. FIX 2026-09-06: FAIL-CLOSED.
    Sebelumnya fail-open (return False saat error) — ini memungkinkan entry
    ETH di 04:01 UTC saat regime_filter error sesaat, padahal market bear.
    Sekarang: error = BLOCKED (aman), bukan izinkan."""
    try:
        import regime_filter as rf
        ok = rf.entry_regime_ok("BTCUSDT")
        return (not ok), ("BTC regime not ok (regime_filter)" if not ok else "lolos")
    except Exception as e:
        # FAIL-CLOSED: error gate = jangan entry (keamanan #1).
        return True, f"gate_error_blocks ({e})"


def cycle(st, live=False):
    reason = kill_check(st)
    if reason:
        print(f"[{now_iso()}] HALT: {reason}")
        if reason == "KILL_SWITCH":
            for pair in list(st["open"]):
                try:
                    d = PT.fetch_ohlcv(PT.BN[pair])
                    px = float(d["c"][-1])
                    close_position(st, pair, px, "KILL_FLATTEN", live)
                except Exception:
                    pass
            save_state(st)
        return
    # exits (pakai TP/SL/TIME_STOP identik paper; harga live dari Binance sama
    # sumber dgn paper, karena signal & exit dievaluasi di harga sinyal yg sama)
    for pair in list(st["open"].keys()):
        try:
            d = PT.fetch_ohlcv(PT.BN[pair])
            px = float(d["c"][-1])
        except Exception:
            continue
        t = st["open"][pair]
        hold_h = (time.time() - t["entry_ts"]) / 3600.0
        gross = side_gross(t, px)
        # high-water tracking identik paper (PEAK_TRAIL konsistensi 2026-09-25)
        t["peak_g"] = max(t.get("peak_g", gross), gross)
        reason = None
        if gross >= TP_PCT:
            reason = "TP"
        elif gross <= -SL_PCT:
            reason = "SL"
        elif hold_h >= TIME_STOP_H:
            reason = f"TIME_{TIME_STOP_H}h"
        elif int(os.environ.get("PEAK_TRAIL_ENABLED", "1")) == 1 and t["peak_g"] >= PT.peak_trail_bands(TP_PCT, SL_PCT)[0] and gross <= PT.peak_trail_bands(TP_PCT, SL_PCT)[1]:
            reason = "PEAK_TRAIL"
        elif t["peak_g"] >= PT.peak_trail_bands(TP_PCT, SL_PCT)[2] and gross <= PT.peak_trail_bands(TP_PCT, SL_PCT)[3]:
            reason = "SL_PROTECT"
        if reason:
            close_position(st, pair, px, reason, live)

    # FIX (2026-09-07, audit real-money phantom): persist SEGERA setelah exits
    # selesai — sebelum early-return apa pun. Bug lama: save_state(st) hanya
    # dipanggil di akhir cycle() (setelah entries), jadi kalau gate macro-BTC
    # atau MAX_POSITIONS block return dini, posisi yang SUDAH close di-memory
    # (del st["open"][pair] di close_position) TIDAK PERNAH tersimpan ke disk.
    # Root cause terverifikasi: ETH exit TIME_30h 2026-09-07T10:02:47Z tercatat
    # benar di realwide_micro_live.jsonl (audit log per-baris, auto-flush) dan
    # dikonfirmasi silang oleh balance-drop alert watchdog (-$1.45, 10:05:14Z),
    # tapi state.json tetap menunjukkan ETH "open" karena cycle berikutnya
    # selalu kena gate macro-BTC (return sebelum baris save_state() lama).
    save_state(st)

    if live:
        # Bersihkan entry provisional yang TERBUKTI tidak ada di exchange sebelum
        # reconcile — mencegah deadlock HALT permanen (insiden 2026-09-25).
        if autoresolve_unverified(st):
            save_state(st)
        reconciled, detail = live_entry_reconciled(st)
        if not reconciled:
            print(f"  [HALT] live entry diblokir: state/exchange mismatch ({detail})")
            return

    # entries — PERSIS pakai signal_now() dari paper (single source of truth)
    mb, mr = macro_btc_long_blocked()
    market_mode = btc_market_mode()
    plan = direction_plan(market_mode)
    if not plan:
        print(f"  [GATE] market mode UNKNOWN — entry baru diblokir ({mr})")
        save_state(st)
        return
    max_positions = effective_max_positions(st, market_mode)
    if len(st["open"]) >= max_positions:
        return
    print(f"  [LEVEL2] mode={market_mode} effective_max={max_positions}/{MAX_POSITIONS_TOTAL} "
          f"margin_cap={LEVEL2_MARGIN_UTIL_CAP:.0%} new_entries_cap={LEVEL2_MAX_NEW_ENTRIES_PER_CYCLE}")
    entered_or_candidate = False
    entries_opened_this_cycle = 0
    for pair in PT.PAIRS:
        if len(st["open"]) >= max_positions or entries_opened_this_cycle >= LEVEL2_MAX_NEW_ENTRIES_PER_CYCLE:
            break
        if pair in st["open"]:
            continue
        le = st["last_entry"].get(pair, 0)
        if time.time() - le < COOLDOWN_H * 3600:
            continue
        if pair not in SODEX_SYM:
            continue  # tidak tradeable di SoDEX perps
        try:
            d = PT.fetch_ohlcv(PT.BN[pair])
        except Exception:
            continue
        if PT.pair_gate_blocks("REAL-wide", pair):
            continue

        sig = None
        side = None
        for candidate_side in plan:
            if candidate_side == "long":
                candidate_sig = PT.signal_now(d, PT.BN[pair])
                if not candidate_sig:
                    continue
                if PT.direction_gate_blocks("REAL-wide", "LONG"):
                    print(f"  [GATE] {pair} LONG diblokir edge-gate")
                    continue
                side = "long"
                sig = candidate_sig
                break
            if candidate_side == "short" and pair in SB.BN:
                if not SB.short_signal(d, sym_bn=SB.BN[pair]):
                    continue
                if PT.direction_gate_blocks("REAL-wide", "SHORT"):
                    print(f"  [GATE] {pair} SHORT diblokir edge-gate")
                    continue
                side = "short"
                sig = {"regime": f"{market_mode}_SHORT", "conviction": "SHORTBEAR"}
                break
        if not side or not sig:
            continue

        # PORTFOLIO GUARD (28-Sep): rem lintas-track + regime nowcast.
        # Alasan ada di sini: sl 24 jam 28-Sep = BTC dipegang 15 posisi & ETH 13
        # posisi serentak lintas-track -> satu gerakan turun = belasan SL.
        _px_chk = float(d["c"][-1])
        if _px_chk > 0:
            _risk_usd = entry_qty(pair, _px_chk) * _px_chk * SL_PCT
            if not PGUARD.guard_entry(PT.BN[pair], pair, side, "realwide_micro_live",
                                      risk_per_trade_usd=_risk_usd,
                                      track_state_file=str(STATE_FILE),
                                      fail_closed=True):
                continue

        entered_or_candidate = True
        px = float(d["c"][-1])
        if px <= 0:
            continue
        qty = entry_qty(pair, px)
        if qty * px < MIN_NOTIONAL:
            print(f"  [SKIP] {pair}: qty*px=${qty*px:.2f} < min notional ${MIN_NOTIONAL}")
            continue
        pos = {"pair": pair, "side": side, "entry_price": px,
               "entry_time": now_iso(), "entry_ts": time.time(),
               "qty": qty, "regime": sig.get("regime"), "conviction": sig.get("conviction")}
        if live:
            sym = SODEX_SYM[pair]
            lev = sodex(["leverage", sym, str(LEVERAGE), "--mode", "isolated"])
            if lev.returncode != 0:
                print(f"  [LIVE-LEVERAGE-ERR] {pair}: rc={lev.returncode} {lev.stdout[:80]}{lev.stderr[:80]} — entry diblokir")
                continue
            order_side = "sell" if side == "short" else "buy"
            # MAKER-FIRST (approval user 30-Sep-2026): hemat ~5,6 bps/RT vs taker.
            if not place_entry(sym, order_side, qty, px):
                print(f"  [LIVE-ENTRY-SKIP] {pair}: maker gagal & fallback tak layak — entry dibatalkan")
                continue
            try:
                matched, verify_reason = verify_open_position_stable(sym)
            except Exception as e:
                matched, verify_reason = None, f"verify_error={e}"
            if not matched:
                # Order command already succeeded; prefer false-open/fail-closed
                # over unmanaged real exposure. Reconciliation will halt entries
                # if exchange later proves flat/mismatched.
                pos["verification_status"] = "UNVERIFIED_AFTER_ORDER"
                pos["verification_reason"] = verify_reason
                pos["verified_leverage"] = None
                print(f"  [UNVERIFIED_FILL] {pair}: {verify_reason} — provisional local open DISIMPAN fail-closed")
            else:
                real_leverage = matched.get("leverage")
                real_lev_num = _num(real_leverage)
                if real_lev_num is not None and abs(real_lev_num - LEVERAGE) > 1e-9:
                    print(f"  [WARNING] {pair}: leverage exchange={real_leverage}x != asumsi {LEVERAGE}x")
                pos["qty"] = abs(float(matched.get("size", qty)))
                pos["entry_price"] = float(matched.get("avgEntryPrice", px))
                pos["verified_leverage"] = real_leverage
        else:
            print(f"  [ENTRY-DRY-SIM] {pair} {side.upper()} @{px:.4f} qty={qty} (simulasi, tidak disimpan)")
            continue
        st["open"][pair] = pos
        st["last_entry"][pair] = time.time()
        st["trades_today"] = st.get("trades_today", 0) + 1
        entries_opened_this_cycle += 1
        print(f"  [ENTRY{'-LIVE' if live else '-DRY'}] {pair} {side.upper()} @{px:.4f} qty={qty} "
              f"regime={sig.get('regime')}")
    if not entered_or_candidate:
        print(f"  [GATE] {market_mode}: belum ada setup {plan} yang lolos terukur")
    save_state(st)


def edge_gate_blocked():
    try:
        g = json.loads(GATE_FILE.read_text())
        return ((g.get("_AGGREGATE") or {}).get("LONG") == "PAUSE"
                or ((g.get("gate") or {}).get("REAL-wide") or {}).get("LONG") == "PAUSE")
    except Exception:
        return False


def preflight():
    print("=== PREFLIGHT realwide_micro_live v2 (23-pair, signal=paper_test_realwide) ===")
    bal = get_balance_usd()
    print(f"  balance: ${bal}")
    need = SIZE_NOTIONAL / LEVERAGE
    print(f"  margin minimal disarankan: ${need:.0f} -> {'OK' if (bal or 0) >= need else 'KURANG'}")
    print(f"  kill switch: {'ADA (hapus dulu!)' if KILL_FILE.exists() else 'tidak ada OK'}")
    print(f"  edge gate LONG: {'PAUSE (blokir!)' if edge_gate_blocked() else 'boleh OK'}")
    mb, mr = macro_btc_long_blocked()
    mode = btc_market_mode()
    plan = direction_plan(mode)
    print(f"  macro-BTC legacy LONG gate: {'BLOKIR' if mb else 'lolos'} ({mr})")
    print(f"  measured-aggression mode: {mode} -> scan {plan if plan else 'BLOCK'}")
    st = load_state()
    eff_cap = effective_max_positions(st, mode)
    print(f"  level-2 cap: effective {eff_cap}/{MAX_POSITIONS_TOTAL} posisi; "
          f"margin_need_2=${margin_required_for_positions(2):.2f}; util_cap={LEVEL2_MARGIN_UTIL_CAP:.0%}")
    print(f"  universe: {len(PT.PAIRS)} pair (identik paper_test_realwide.py)")
    print("  posisi REAL di exchange (endpoint terverifikasi):")
    try:
        real_pos = real_perps_positions()
        if not real_pos:
            print("    0 posisi (bersih)")
        else:
            for p in real_pos:
                print(f"    {p['symbol']} size={p['size']} entry={p['avgEntryPrice']} "
                      f"leverage={p['leverage']}x")
    except Exception as e:
        print(f"    GAGAL cek posisi real: {e} — JANGAN lanjut live sampai ini fixed")
    print("  dry cycle:")
    st = load_state()
    cycle(st, live=False)
    print("=== PREFLIGHT SELESAI ===")


def demo():
    assert TP_PCT == 0.06 and SL_PCT == 0.03 and LEVERAGE == 3
    assert SESSION_LOSS_CAP == -9.00 and DAILY_TRADE_CAP == 6 and MAX_POSITIONS_TOTAL == 2
    worst = SL_PCT * SIZE_NOTIONAL
    worst_level2 = worst * MAX_POSITIONS_TOTAL
    assert abs(worst - 4.20) < 1e-9, worst   # $140 notional x -3% = -$4.20 (geo A2 + size 28-Sep)
    assert worst_level2 < abs(SESSION_LOSS_CAP), "2-position worst-case harus di bawah session cap"
    assert len(PT.PAIRS) == 23, f"universe harus 23 pair (paper), dapat {len(PT.PAIRS)}"
    assert abs(entry_qty("BTC", 80000) * 80000 - SIZE_NOTIONAL) < 1.0, "qty harus target notional, bukan notional*leverage"
    # Geometri live = paper (RISET A2 27-Sep, approved user): TP6%/SL3%.
    assert TP_PCT == 0.06 and SL_PCT == 0.03, "live harus align paper geom"
    wallet = float(os.environ.get("SODEX_TOTAL_WALLET", "279.74"))  # live akun riil 27-Sep (spot+perps)
    required_net = wallet * 0.008 / SIZE_NOTIONAL
    print(f"demo OK — worst case per trade ${worst:.2f}; universe {len(PT.PAIRS)} pair "
          f"(identik paper); target butuh net {required_net*100:.3f}% pada notional ${SIZE_NOTIONAL:.0f}; "
          f"caps: sesi {SESSION_LOSS_CAP}, harian {DAILY_TRADE_CAP} trade")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="once")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--preflight", action="store_true")
    a = ap.parse_args()
    global _LIVE_MODE
    _LIVE_MODE = bool(a.live)   # guard: hanya mode --live yang menulis state/jsonl live
    if a.cmd == "demo":
        demo(); return
    if a.preflight:
        preflight(); return
    if a.loop:
        _n = 0
        while True:
            _n += 1
            try:
                # HEARTBEAT (audit 29-Sep-2026): lane sehat tapi tanpa event membuat log senyap
                # >8 jam → liveness TIDAK terverifikasi (tak bisa bedakan "tidur" vs "hang"
                # tanpa inspeksi file state). 1 baris/siklus = bukti hidup yang murah & jujur.
                print(f"[{now_iso()}] HEARTBEAT #{_n} — lane hidup (interval={a.interval}s)", flush=True)
                # Reload every loop so external reconciliation/backup fixes are
                # not overwritten by a long-lived in-memory phantom position.
                st = load_state()
                cycle(st, live=a.live)
            except Exception as e:
                print(f"[{now_iso()}] ERR {e}", flush=True)
            time.sleep(a.interval)
    else:
        st = load_state()
        cycle(st, live=a.live)


if __name__ == "__main__":
    main()
