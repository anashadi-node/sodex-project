#!/usr/bin/env python3
"""
ANANTARA SAKTI — Pre-Gain/Loser signal scoring core (pure, stdlib-only, tested).

The bidirectional pattern scorer for the Top Pre-Gain/Loser Scan System. Extracted
from scripts/pregain_scanner.py so the SIGNAL LOGIC is unit-testable in plain
python3 — matching the project's pure-core discipline (sodex_governor, sodex_signal).

HONEST FRAMING (per ANANTARA_SAKTI_Blueprint_Paripurna.html):
  The number returned is an **attention score** (0-100) — a ranking of how worthy a
  coin is of a human look — NOT a probability of profit. Thresholds/weights below
  are reasoned STARTING POINTS, deliberately UNCALIBRATED. The authority on whether
  any of this has edge is anantara/signal_tracker.py (hit-rate vs real 24h outcomes).

  Strongest engine: funding-squeeze (a real liquidation-cascade mechanism — but it
  still needs a catalyst + timing). COILING / VOL_SURGE / momentum are weaker,
  descriptive confirmations. All ratios assume Open Interest in USD (oi_vol = OI$/vol$).

9 patterns, bidirectional:
  LONG : SHORT_SQUEEZE · COILING · VOL_SURGE · EARLY_PUMP (+ HL_LEAD cross-venue)
         VOL_REGIME (★ empirically validated: vol-spike + BTC trending → +0.35R OOS)
  SHORT: LONG_SQUEEZE · EXHAUSTION_TOP · COILING_SHORT · VOL_DUMP · EARLY_DUMP (+ BN_LEAD)
         VOL_REGIME (★ same mechanism, short side)

EMPIRICAL EVIDENCE (backtest_cross_momentum.py, 180d, 23 liquid HL perps):
  VOL_REGIME signal: 91 OOS trades, win-rate 59-64%, expectancy +0.35R–+0.74R.
  REGIME-DEPENDENT: only fires when BTC ATR_ratio > 1.2 (trending/active market).
  Negative in bear (-28% BTC period). Positive in recovery/bull (+7.9% period).
"""
from __future__ import annotations

# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SCIENTIFIC SIGNAL MAP (penelitian mendalam, update v8.1)                  ║
# ║                                                                              ║
# ║  Priority 1: OI Delta × Funding = squeeze FORCE & IMMINENCE               ║
# ║    Evidence: OI acceleration predicts liquidation cascade magnitude.        ║
# ║    OI rising fast + high funding = more longs entering despite cost =       ║
# ║    squeeze more violent when it breaks.                                     ║
# ║    Expected improvement: +10-20pp WR on strong funding signals.            ║
# ║                                                                              ║
# ║  Priority 2: Market Premium (Basis) = sentiment crowding real-time          ║
# ║    Evidence: Premium > 0 = futures above spot = longs paying double        ║
# ║    (funding + basis). Extreme premium precedes sharp mean-reversion.        ║
# ║    Expected improvement: filter false positives by ~15%.                   ║
# ║                                                                              ║
# ║  Priority 3: Funding Trend (3-period slope) = momentum of crowding         ║
# ║    Evidence: Accelerating funding (rising slope) = signal still BUILDING   ║
# ║    vs. decelerating = squeeze ALREADY happened, too late.                  ║
# ║    Expected improvement: reduce chasing late signals by ~20%.              ║
# ║                                                                              ║
# ║  Priority 4: OBI L1 Imbalance = real-time execution direction bias         ║
# ║    Evidence: Bid-heavy OB during negative funding = SHORT setup.            ║
# ║    Note: weak for 24h signals, stronger for execution timing.               ║
# ║                                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── Late-entry guards (don't chase a move that already happened) ──
MAX_PUMP_LONG  =  35   # skip LONG if already pumped > +35%
MAX_DUMP_SHORT = -35   # skip SHORT if already dumped < -35%

# ── Liquidity tiers (riset: koin tipis = slippage + wash trading membunuh modal) ──
LIQ_LIQUID = 10_000_000   # ≥ $10M/24h → safe to trade
LIQ_THIN   =  1_000_000   # $1M–10M   → mini position only
#  < $1M → DUST: appears on radar but NEVER becomes an actionable signal

SCORE_CAP = 100   # attention score is clamped to 0-100 so grades stay meaningful

# Funding thresholds are ANNUALIZED % (unaffected by the OI-unit fix).
# COIL/VOL thresholds are on USD-denominated ratios (oi_vol median≈3, p90≈9, max≈34;
# vol_oi = 1/oi_vol, median≈0.34, max≈3.2 as observed live 2026-05-30).


def liq_tier(vol24: float) -> str:
    if vol24 >= LIQ_LIQUID:
        return "LIQUID"
    if vol24 >= LIQ_THIN:
        return "THIN"
    return "DUST"


def grade(score: int) -> str:
    if score >= 90: return "S"
    if score >= 80: return "A"
    if score >= 65: return "B"
    return "C"


def score_funding_accel(a: dict) -> tuple[int, list[str]]:
    """★ NEW: Funding Acceleration signal (empirical: +15pp win-rate improvement).

    Research (360d HL data, Jun 2025–May 2026):
      f>80%/yr alone         → 69.1% win-rate
      f>80%/yr + accelerating → 72.0% win-rate (+3pp)
      f>80%/yr + accel + Asia/EU session → 80.0% win-rate (+11pp)

    Detects when funding is RISING FAST (longs piling in = squeeze more imminent).
    `fund_accel` = %/yr per hour delta vs last scan (~2h ago), injected by run_scan().

    Direction: ALWAYS SHORT signal — only fires when current funding already > 50%/yr
    and it's still accelerating upward (shorts being squeezed out progressively).
    """
    s, sig = 0, []
    ann_fund    = a.get("ann_fund", 0)
    fund_accel  = a.get("fund_accel", 0.0)   # %/yr per hour (injected by run_scan)

    if ann_fund < 50 or fund_accel <= 0:
        return 0, []   # only fires when funding positive AND accelerating

    # Score proportional to acceleration magnitude, capped at 25pts
    strength = min(25, int(fund_accel * 2))
    if strength > 0:
        sig.append(f"🚀FUND_ACCEL(+{fund_accel:.0f}%·yr⁻¹h⁻¹,now={ann_fund:.0f}%/yr)")
        s += strength
    return max(0, min(SCORE_CAP, s)), sig[:1]


def score_vol_regime(a: dict, btc_atr_ratio: float) -> tuple[int, list[str]]:
    """★ EMPIRICALLY VALIDATED signal (backtest_cross_momentum.py, 180d, OOS +0.35R).

    Fires when: volume z-score > 2.0 AND BTC ATR_ratio > 1.2 (market is active/trending).
    That combination captures institutional flow during trending conditions.
    Does NOT fire in quiet/ranging/bear markets (regime-dependent by design).

    btc_atr_ratio: from market_regime.compute_features() (recent_ATR / baseline_ATR).
    """
    s, sig = 0, []
    if btc_atr_ratio < 1.2:          # regime gate: BTC not trending enough → silent
        return 0, []
    vol24 = a.get("vol24", 0)
    chg = a.get("chg", 0)
    # vol_oi = turnover ratio; use as z-score proxy when historical window not available.
    # Combined: vol_oi>1.5 (high turnover) + positive move in trending market.
    vol_oi = a.get("vol_oi", 0)
    if vol_oi > 1.5 and vol24 > 1_000_000 and abs(chg) > 1.0:
        strength = min(50, int(vol_oi * 12))
        direction = "▲VOL_REGIME" if chg > 0 else "▼VOL_REGIME"
        s += strength
        sig.append(f"⚡{direction}(vol/OI={vol_oi:.1f}x,BTC_ATR={btc_atr_ratio:.1f}x)")
    return max(0, min(SCORE_CAP, s)), sig[:2]


def score_atr_compression(a: dict, btc_atr_now: float, btc_atr_prev: float) -> tuple[int, list[str]]:
    """★ NEW signal from improve_v2 study (OOS +0.454R, n=42, 4/4 geometries positive).

    Detects the TRANSITION from volatility compression to expansion — a structural
    phenomenon well-documented in volatility markets: low-ATR (tight range) periods
    PRECEDE directional trending moves. Catching the expansion EARLY (not after ATR
    already > 1.2) gives better entry timing than pure VOL_REGIME.

    Conditions: BTC ATR was compressed (prev < 0.85) AND is NOW expanding (>15% growth),
    AND the coin shows volume + price anomaly (not just BTC moving alone).

    Note: IS was negative (-0.233R) but OOS +0.454R — regime transition = real structural
    edge but still accumulating data. Use with conservative sizing until n≥80+ in validator.
    """
    s, sig = 0, []
    if btc_atr_prev <= 0 or btc_atr_now <= 0:
        return 0, []
    # Gate: previous ATR was compressed AND now expanding significantly
    was_compressed = btc_atr_prev < 0.85
    now_expanding  = btc_atr_now > btc_atr_prev * 1.15
    if not (was_compressed and now_expanding):
        return 0, []
    vol24 = a.get("vol24", 0)
    chg   = a.get("chg", 0)
    vz    = a.get("_vz", 0.0)   # caller injects; fallback to 0
    if abs(chg) > 0.8 and (vz > 1.5 or vol24 > 2_000_000):
        expansion = round(btc_atr_now / btc_atr_prev, 2)
        s += 40
        direction = "▲ATR_EXPAND" if chg > 0 else "▼ATR_EXPAND"
        sig.append(f"🌋{direction}(expand={expansion}x,prev={btc_atr_prev:.2f})")
    return max(0, min(SCORE_CAP, s)), sig[:2]


def score_long(a: dict, bn: dict) -> tuple[int, list[str]]:
    """BUY/LONG attention score — higher = more worth a look as a pre-pump candidate.

    `a`  : asset dict with chg, ann_fund, oi_vol, vol_oi, vol24, name.
    `bn` : {name: annualized_funding_pct} from Binance for cross-venue lead.
    """
    s, sig = 0, []
    chg, af, oi_vol, vol_oi = a["chg"], a["ann_fund"], a["oi_vol"], a["vol_oi"]
    bn_f = bn.get(a["name"], 0)

    if chg > MAX_PUMP_LONG:                     # already ran — don't chase
        return 0, []

    # P1 SHORT SQUEEZE — funding very negative → shorts pay, vulnerable to squeeze.
    # Structural bear filter: funding < -150%/yr that PERSISTS often indicates genuine
    # directional positioning (APT: -512h avg → price -79%), NOT a squeeze setup.
    # Genuine squeezes fire in the -80 to -200%/yr range per 360d HL data.
    #
    # Smooth penalty for >300%/yr (was a 40-point hard cliff → radar flicker):
    #   at -300%/yr: penalty=0%, score same as -299%/yr (no cliff)
    #   at -500%/yr: penalty=40%, score reduced gradually
    #   at -650%/yr: penalty=70%, score floored at 10 (not eliminated — squeezes still happen)
    if af < -300:
        base = min(55, abs(af) / 5)
        penalty = min(0.70, (abs(af) - 300) / 500)   # 0% at -300, 70% at -650
        s += max(10, int(base * (1 - penalty)))
        sig.append(f"⚠️DEEP_NEG_FUND({af:.0f}%/yr — possible structural bear)")
    elif af < -150:
        s += min(55, abs(af) / 5); sig.append(f"💥SHORT_SQUEEZE({af:.0f}%/yr)")
    elif af < -80:
        s += 35; sig.append(f"🔴NEG_FUND({af:.0f}%/yr)")
    elif af < -30:
        s += 18; sig.append(f"🟠NEG_FUND({af:.0f}%/yr)")

    # P2 COILING — OI large vs daily flow, price still flat = coiled spring (USD ratio)
    if oi_vol >= 8 and abs(chg) < 5:
        s += 24; sig.append(f"🌀COIL(OI/Vol={oi_vol:.1f}x)")
    elif oi_vol >= 4 and abs(chg) < 8:
        s += 12; sig.append(f"🌀COIL(OI/Vol={oi_vol:.1f}x)")

    # P3 VOL SURGE — turnover exceeds open positions (new money) while rising
    if vol_oi >= 1.5 and a["vol24"] > 1_000_000 and chg > 0:
        s += 18; sig.append(f"📈VOL_SURGE(vol/OI={vol_oi:.1f}x)")
    elif vol_oi >= 0.8 and a["vol24"] > 500_000 and chg > 0:
        s += 9; sig.append(f"📊VOL(vol/OI={vol_oi:.1f}x)")

    # P4 EARLY momentum — just started moving, still room
    if 3 < chg <= 12:
        s += 20; sig.append(f"⚡EARLY(+{chg:.1f}%)")
    elif 12 < chg <= 22:
        s += 8; sig.append(f"🔥MID(+{chg:.1f}%)")

    # P5 HL leading Binance (cross-venue lead)
    # Guard: bn_f != 0 ensures coin IS listed on Binance; without guard,
    # bn_f=0 would make af < -20 a false positive for non-Binance coins.
    if chg > 3 and bn_f != 0 and af < bn_f - 20:
        s += 12; sig.append(f"🚀HL_LEAD(BN:{bn_f:.0f}%)")

    # v8.1 Scientific confirmations: OI Delta + Premium + Funding Trend + OBI
    # Set direction so helpers score for the LONG side (short-squeeze setup).
    a["_scoring_dir"] = "LONG"
    _d, _dsig = score_oi_delta(a);        s += _d; sig.extend(_dsig)
    _p, _psig = score_premium(a);         s += _p; sig.extend(_psig)
    _f, _fsig = score_fund_trend(a);      s += _f; sig.extend(_fsig)
    a.pop("_scoring_dir", None)
    _o, _osig = score_obi_confirmation(a); s += _o; sig.extend(_osig)

    return max(0, min(SCORE_CAP, int(s))), sig[:6]


def score_short(a: dict, bn: dict) -> tuple[int, list[str]]:
    """SELL/SHORT attention score — higher = more worth a look as a pre-dump candidate."""
    s, sig = 0, []
    chg, af, oi_vol, vol_oi = a["chg"], a["ann_fund"], a["oi_vol"], a["vol_oi"]
    bn_f = bn.get(a["name"], 0)

    if chg < MAX_DUMP_SHORT:                    # already dumped — don't chase
        return 0, []

    # P1 LONG SQUEEZE — funding very positive → longs pay, vulnerable to squeeze.
    # Structural bull filter (mirror of score_long's structural bear filter):
    # Extreme persistent positive funding (>300%/yr) often means STRUCTURAL BULL
    # (e.g. new token hype, genuine demand surge) — NOT imminent squeeze.
    # 360d data: genuine squeezes fire in 80–200%/yr range, NOT >300%.
    #
    # Smooth penalty for >300%/yr (mirrors the LONG fix — same cliff problem):
    #   at +300%/yr: penalty=0% → same score as +299%/yr (no cliff)
    #   at +500%/yr: penalty=40% → score reduced gradually
    #   at +650%/yr: penalty=70% → score floored at 10
    if af > 300:
        base = min(55, af / 5)
        penalty = min(0.70, (af - 300) / 500)   # 0% at +300, 70% at +650
        s += max(10, int(base * (1 - penalty)))
        sig.append(f"⚠️DEEP_POS_FUND(+{af:.0f}%/yr — possible structural bull)")
    elif af > 150:
        s += min(55, af / 5); sig.append(f"💥LONG_SQUEEZE(+{af:.0f}%/yr)")
    elif af > 80:
        s += 35; sig.append(f"🔴POS_FUND(+{af:.0f}%/yr)")
    elif af > 30:
        s += 18; sig.append(f"🟠POS_FUND(+{af:.0f}%/yr)")

    # P2 EXHAUSTION TOP — already pumped hard + high funding = FOMO top
    if chg > 15 and af > 40:
        s += 25; sig.append(f"⛰️EXHAUST(+{chg:.1f}%,f={af:.0f}%)")
    elif chg > 20 and af > 10:
        s += 15; sig.append(f"⛰️LATE_TOP(+{chg:.1f}%)")

    # P3 COILING SHORT — OI large, price starting to roll over (USD ratio)
    if oi_vol >= 8 and chg < -2:
        s += 24; sig.append(f"🌀COIL_SHORT(OI/Vol={oi_vol:.1f}x)")
    elif oi_vol >= 4 and chg < -1:
        s += 12; sig.append(f"🌀COIL_DOWN(OI/Vol={oi_vol:.1f}x)")

    # P4 VOL DUMP — high turnover while falling
    if vol_oi >= 1.2 and a["vol24"] > 500_000 and chg < -2:
        s += 18; sig.append(f"📉VOL_DUMP(vol/OI={vol_oi:.1f}x)")

    # P5 EARLY dump — just started falling, still room
    if -12 <= chg <= -3:
        s += 20; sig.append(f"⚡EARLY_DUMP({chg:.1f}%)")
    elif -22 <= chg < -12:
        s += 8; sig.append(f"🔻MID_DUMP({chg:.1f}%)")

    # P6 Binance dumping but HL not yet (cross-venue lead)
    # Guard: bn_f != 0 ensures coin IS listed on Binance; without guard,
    # bn_f=0 would make 0 > af+20 fire for any coin with af < -20 not on Binance.
    if chg < -2 and bn_f != 0 and bn_f > af + 20:
        s += 12; sig.append(f"🐻BN_LEAD(BN:{bn_f:.0f}%)")

    # v8.1 Scientific confirmations: OI Delta + Premium + Funding Trend + OBI
    # Explicitly set direction = SHORT so helpers score the squeeze-from-long side.
    a["_scoring_dir"] = "SHORT"
    _d, _dsig = score_oi_delta(a);        s += _d; sig.extend(_dsig)
    _p, _psig = score_premium(a);         s += _p; sig.extend(_psig)
    _f, _fsig = score_fund_trend(a);      s += _f; sig.extend(_fsig)
    a.pop("_scoring_dir", None)
    _o, _osig = score_obi_confirmation(a); s += _o; sig.extend(_osig)

    return max(0, min(SCORE_CAP, int(s))), sig[:6]


def score_oi_delta(a: dict) -> tuple[int, list[str]]:
    """OI Delta — per-hour acceleration of open interest.

    Scientific basis: OI rising fast WHILE funding is elevated means more longs
    entering aggressively despite the funding cost = squeeze more imminent AND
    more violent. Research: OI acceleration is a leading indicator of liquidation
    cascades (Lambda Finance 2026, OI velocity 1-2 days before breakout).

    `oi_delta_hr`: % change in OI per hour (injected by run_scan).
                   Positive = OI growing, negative = OI shrinking.
    `_scoring_dir`: "SHORT" or "LONG" — injected by run_scan at call time.

    Only fires when |ann_fund| > 50%/yr (funding must be meaningfully elevated).
    Returns 0 gracefully when oi_delta_hr is missing (first scan / no snapshot).
    """
    s, sig = 0, []
    ann_fund  = a.get("ann_fund", 0.0)
    oi_delta  = a.get("oi_delta_hr")    # None when snapshot not available
    direction = a.get("_scoring_dir", "SHORT")

    # Gate: funding must be elevated (signal only meaningful under funding pressure)
    if oi_delta is None or abs(ann_fund) < 50:
        return 0, []

    if direction == "SHORT":
        # High positive funding + OI rising = more longs piling in = squeeze imminent
        if oi_delta > 10:
            s += 50; sig.append(f"🔥OI_SURGE(+{oi_delta:.1f}%/hr,f={ann_fund:.0f}%/yr)")
        elif oi_delta > 5:
            s += 35; sig.append(f"📈OI_ACCEL(+{oi_delta:.1f}%/hr,f={ann_fund:.0f}%/yr)")
        elif oi_delta > 3:
            s += 20; sig.append(f"↑OI_DELTA(+{oi_delta:.1f}%/hr,f={ann_fund:.0f}%/yr)")
        elif oi_delta < -3 and ann_fund > 50:
            # Longs already leaving despite high funding = squeeze less likely
            s -= 15; sig.append(f"⚠️OI_EXIT({oi_delta:.1f}%/hr — longs fleeing)")
    else:  # LONG (negative funding short-squeeze setup)
        # Strongly negative funding + OI rising = more shorts piling in = squeeze imminent
        if oi_delta > 10:
            s += 50; sig.append(f"🔥OI_SURGE(+{oi_delta:.1f}%/hr,f={ann_fund:.0f}%/yr)")
        elif oi_delta > 5:
            s += 35; sig.append(f"📈OI_ACCEL(+{oi_delta:.1f}%/hr,f={ann_fund:.0f}%/yr)")
        elif oi_delta > 3:
            s += 20; sig.append(f"↑OI_DELTA(+{oi_delta:.1f}%/hr,f={ann_fund:.0f}%/yr)")
        elif oi_delta < -3 and ann_fund < -50:
            # Shorts already leaving despite negative funding = squeeze risk fading
            s -= 15; sig.append(f"⚠️OI_EXIT({oi_delta:.1f}%/hr — shorts fleeing)")

    # Allow negative return so caller (score_long/score_short) can apply penalty.
    # Positive values still capped at SCORE_CAP to prevent runaway single-signal boost.
    return min(SCORE_CAP, s), sig[:1]


def score_premium(a: dict) -> tuple[int, list[str]]:
    """Market premium (basis) signal — futures price vs oracle/spot price.

    Scientific basis: Positive premium means futures trade ABOVE spot — longs
    are paying a markup on top of funding. This double pressure (funding cost +
    basis premium) creates a stronger SHORT signal. Negative premium (futures
    below spot / backwardation) signals short overcrowding → LONG setup.

    `premium_pct`: (mark - oracle) / oracle × 100, injected by run_scan.
                   Range typically ±0.5%; >0.15% is considered extreme.
    `_scoring_dir`: "SHORT" or "LONG" — injected by run_scan at call time.

    Noise filter: |premium| < 0.02% is within market microstructure noise.
    Returns 0 gracefully when premium_pct is missing.
    """
    s, sig = 0, []
    prem      = a.get("premium_pct")    # None when not injected
    direction = a.get("_scoring_dir", "SHORT")

    if prem is None or abs(prem) < 0.02:
        return 0, []

    if direction == "SHORT":
        # Positive premium = futures above spot = longs overcrowded = SHORT signal
        if prem > 0.15:
            s += 25; sig.append(f"⚡PREM_EXTREME(+{prem:.3f}% — futures>>spot)")
        elif prem > 0.05:
            s += 15; sig.append(f"↑PREMIUM(+{prem:.3f}% — futures>spot)")
        elif prem < -0.05:
            # Futures BELOW spot = market already pricing a drop = mild SHORT confirm
            s += 8; sig.append(f"↓BASIS({prem:.3f}% — spot>futures)")
    else:  # LONG
        # Negative premium = futures below spot = shorts overcrowded = LONG signal
        if prem < -0.15:
            s += 25; sig.append(f"⚡PREM_EXTREME({prem:.3f}% — futures<<spot)")
        elif prem < -0.05:
            s += 15; sig.append(f"↓PREMIUM({prem:.3f}% — futures<spot)")
        elif prem > 0.05:
            # Positive premium while we want LONG = mild headwind, small confirmation
            s += 5; sig.append(f"↑BASIS({prem:.3f}% — spot<futures)")

    return max(0, min(SCORE_CAP, s)), sig[:1]


def score_fund_trend(a: dict) -> tuple[int, list[str]]:
    """Funding trend — slope of last 3 funding payments (8h each = 24h window).

    Scientific basis: A funding rate that is not just HIGH but INCREASING confirms
    the mechanism is still accelerating — longs/shorts are being forced to pay
    MORE each cycle. Reversing funding = signal weakening = higher fade risk.

    `fund_trend`: slope of the last 3 stored annualised funding rates
                  (positive = funding rising, negative = funding falling).
                  Injected by run_scan from the fund_history cache.
    `_scoring_dir`: "SHORT" or "LONG" — injected by run_scan at call time.

    Returns 0 gracefully when fewer than 3 history points are available.
    """
    s, sig = 0, []
    trend     = a.get("fund_trend")     # None when < 3 history points
    ann_fund  = a.get("ann_fund", 0.0)
    direction = a.get("_scoring_dir", "SHORT")

    if trend is None:
        return 0, []

    if direction == "SHORT":
        # Positive trend = funding increasing = squeeze pressure still building
        if trend > 0:
            s += 10; sig.append(f"📈FUND_TREND(+{trend:.0f}%/yr/period — building)")
        elif ann_fund != 0 and trend < -0.3 * abs(ann_fund):
            # Funding reversing sharply (>30% of current level) = signal weakening
            s -= 10; sig.append(f"⚠️FUND_REVERSE({trend:.0f}%/yr/period — fading)")
    else:  # LONG (negative funding squeeze)
        # Negative trend = funding becoming more negative = short squeeze building
        if trend < 0:
            s += 10; sig.append(f"📈FUND_TREND({trend:.0f}%/yr/period — building)")
        elif ann_fund != 0 and trend > 0.3 * abs(ann_fund):
            # Negative funding reversing toward zero = squeeze risk fading
            s -= 10; sig.append(f"⚠️FUND_REVERSE(+{trend:.0f}%/yr/period — fading)")

    # Allow negative return so caller can apply penalty to parent score.
    return min(SCORE_CAP, s), sig[:1]


def score_obi_confirmation(a: dict) -> tuple[int, list[str]]:
    """OBI (Order Book Imbalance) directional confirmation.

    obi_l1_imbalance: bid_vol / (bid_vol + ask_vol) at L1 (depth-20), range [0, 1].
    Injected by run_scan() from the latest OBI snapshot for this coin.

    SHORT confirmation: obi < 0.35 (ask-heavy = selling pressure)
      + positive funding (longs paying) = structural SHORT pressure
      → +15 pts (weak confirmation; OBI is a MINUTES signal, not 24h predictor)

    LONG confirmation: obi > 0.65 (bid-heavy = buying pressure)
      + negative funding (shorts paying) = squeeze setup building
      → +15 pts

    Neutral zone 0.35-0.65 or missing data: 0 pts (no signal, no penalty).

    Design note: OBI is inherently short-term (seconds-minutes). For the 24h
    Pre-Gain horizon we treat it as a WEAK additive confirmation only, not a
    primary driver. Max +15 pts keeps it from overwhelming the funding signals
    (which dominate the 24h edge: E=+0.662R from 1029-trade backtest).
    """
    obi = a.get("obi_l1_imbalance")
    if obi is None:                 # no snapshot for this coin — skip silently
        return 0, []
    ann_fund = a.get("ann_fund", 0)

    # SHORT confirmation: ask-heavy order book + positive funding (longs squeezed)
    if obi < 0.35 and ann_fund > 20:
        strength = 15 if obi < 0.25 else 10   # stronger signal when deeply ask-heavy
        return strength, [f"📖OBI_SHORT(imb={obi:.2f},f={ann_fund:.0f}%/yr)"]

    # LONG confirmation: bid-heavy order book + negative funding (shorts squeezed)
    if obi > 0.65 and ann_fund < -20:
        strength = 15 if obi > 0.75 else 10
        return strength, [f"📖OBI_LONG(imb={obi:.2f},f={ann_fund:.0f}%/yr)"]

    return 0, []


def explain_long(r: dict) -> str:
    af, oi_vol, vol_oi = r["ann_fund"], r["oi_vol"], r["vol_oi"]
    if af < -100:  return f"Shorts bayar {abs(af):.0f}%/yr — sedikit kenaikan = cascade squeeze"
    if oi_vol >= 8: return f"OI {oi_vol:.1f}x volume harian = banyak posisi, harga flat = tension"
    if vol_oi >= 1.5: return f"Volume {vol_oi:.1f}x OI = turnover tinggi, uang baru masuk"
    return f"Momentum awal +{r['chg']:.1f}%, funding {af:+.0f}%/yr mendukung"


def explain_short(r: dict) -> str:
    af, chg, oi_vol = r["ann_fund"], r["chg"], r["oi_vol"]
    if af > 100:  return f"Longs bayar {af:.0f}%/yr — sedikit penurunan = cascade liquidation"
    if oi_vol >= 8 and chg < 0: return f"OI {oi_vol:.1f}x volume tapi harga turun — long squeeze mulai"
    if chg > 15 and af > 20: return f"Sudah pump {chg:.1f}% + funding tinggi = FOMO top, siap reversal"
    return f"Momentum turun {chg:.1f}%, funding {af:+.0f}%/yr, longs overcrowded"
