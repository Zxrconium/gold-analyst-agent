"""
Gold Futures AMT Analysis Engine
Implements Fabervaale's (Fabio Valentini) Auction Market Theory framework:
  - Volume Profile levels (POC, VAH, VAL, HVN, LVN)
  - Cumulative Volume Delta (CVD)
  - Balance vs Imbalance detection
  - Initiative vs Responsive activity classification
  - Confluence scoring and signal generation
"""

from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class WebhookPayload:
    """Normalised payload arriving from TradingView Pine Script alerts."""
    ticker: str
    price: float
    poc: float            # Point of Control
    vah: float            # Value Area High
    val: float            # Value Area Low
    cvd: float            # Cumulative Volume Delta (positive = net buying)
    cvd_trend: str        # "bullish" | "bearish" | "neutral"
    volume: float         # bar volume
    avg_volume: float     # average volume for absorption check
    balance_state: str    # "in_balance" | "breaking_high" | "breaking_low" | "imbalanced_bullish" | "imbalanced_bearish"
    signal_type: str      # raw Pine Script signal label
    absorption: bool      # True if high volume / low price movement at VP level
    delta_divergence: str # "bearish_div" | "bullish_div" | "none"
    hvn_near: bool        # price within 0.3% of a High Volume Node
    lvn_near: bool        # price within 0.3% of a Low Volume Node (fast moves expected)
    timeframe: str = "5m"
    extra: dict = field(default_factory=dict)


@dataclass
class AnalysedSignal:
    """Fully analysed signal ready for the Telegram formatter."""
    direction: str              # "LONG" | "SHORT" | "NEUTRAL"
    signal_type: str            # human-readable label
    amt_state: str              # human-readable AMT context
    cvd_label: str              # human-readable CVD description
    absorption_label: str       # human-readable absorption description
    confluence_score: int       # 0-5
    strength: str               # "STRONG" | "MODERATE" | "WEAK"
    bias: str                   # target description
    invalidation: str           # invalidation description
    fabervaale_note: str        # Fabervaale-style reasoning note
    price: float
    poc: float
    vah: float
    val: float
    should_send: bool           # False for WEAK signals


# ─── AMT State Classifier ─────────────────────────────────────────────────────

class AMTStateClassifier:
    """Maps raw balance_state + price location into a human-readable AMT context."""

    STATE_MAP = {
        "in_balance":          "In Balance — Rotational Auction",
        "breaking_high":       "Breaking Balance High — Potential Initiative Buying",
        "breaking_low":        "Breaking Balance Low — Potential Initiative Selling",
        "imbalanced_bullish":  "Imbalanced Bullish — Trend Mode, Long Bias Only",
        "imbalanced_bearish":  "Imbalanced Bearish — Trend Mode, Short Bias Only",
    }

    DIRECTIONAL_BIAS = {
        "in_balance":          "neutral",
        "breaking_high":       "bullish",
        "breaking_low":        "bearish",
        "imbalanced_bullish":  "bullish",
        "imbalanced_bearish":  "bearish",
    }

    def classify(self, balance_state: str, price: float, poc: float) -> tuple[str, str]:
        """Return (human_label, directional_bias)."""
        label = self.STATE_MAP.get(balance_state, "Unknown AMT State")
        bias  = self.DIRECTIONAL_BIAS.get(balance_state, "neutral")

        # Refine in-balance bias by price vs POC
        if balance_state == "in_balance":
            if price > poc:
                label = "In Balance — Price Above POC, Bullish Lean"
                bias  = "bullish"
            elif price < poc:
                label = "In Balance — Price Below POC, Bearish Lean"
                bias  = "bearish"

        return label, bias


# ─── Signal Classifier ────────────────────────────────────────────────────────

class SignalClassifier:
    """
    Maps raw Pine Script signal_type strings to structured signal metadata.
    Mirrors Fabervaale's signal taxonomy.
    """

    # (signal_type_key): (display_name, preferred_direction)
    SIGNAL_MAP = {
        "poc_rejection_long":       ("POC Rejection Long",        "LONG"),
        "poc_rejection_short":      ("POC Rejection Short",       "SHORT"),
        "val_bounce_long":          ("VAL Bounce Long",           "LONG"),
        "vah_rejection_short":      ("VAH Rejection Short",       "SHORT"),
        "initiative_breakout_long": ("Initiative Breakout Long",  "LONG"),
        "initiative_breakout_short":("Initiative Breakout Short", "SHORT"),
        "delta_div_short":          ("Delta Divergence Short",    "SHORT"),
        "delta_div_long":           ("Delta Divergence Long",     "LONG"),
        "range_extension_long":     ("Range Extension Long",      "LONG"),
        "range_extension_short":    ("Range Extension Short",     "SHORT"),
        "absorption_long":          ("Absorption Long",           "LONG"),
        "absorption_short":         ("Absorption Short",          "SHORT"),
    }

    def classify(self, signal_type: str) -> tuple[str, str]:
        """Return (display_name, direction). Falls back gracefully."""
        key = signal_type.lower().replace(" ", "_")
        display, direction = self.SIGNAL_MAP.get(key, (signal_type.replace("_", " ").title(), "NEUTRAL"))
        return display, direction


# ─── Confluence Scorer ────────────────────────────────────────────────────────

class ConfluenceScorer:
    """
    Scores each signal on Fabervaale's five confluence factors.
    Each factor contributes 1 point (max score = 5).
    """

    # Tolerance: price is "at" a level if within this many points
    LEVEL_PROXIMITY_POINTS = 2.0

    def score(self, payload: WebhookPayload, direction: str, amt_bias: str) -> tuple[int, list[str]]:
        """
        Returns (score, [reason_strings]).
        reason_strings are used in the Telegram message breakdown.
        """
        score   = 0
        reasons = []

        # 1. CVD confirms direction
        if (direction == "LONG"  and payload.cvd_trend == "bullish") or \
           (direction == "SHORT" and payload.cvd_trend == "bearish"):
            score += 1
            reasons.append("CVD confirms direction")

        # 2. Price at key VP level (POC, VAH, VAL)
        at_poc = abs(payload.price - payload.poc) <= self.LEVEL_PROXIMITY_POINTS
        at_vah = abs(payload.price - payload.vah) <= self.LEVEL_PROXIMITY_POINTS
        at_val = abs(payload.price - payload.val) <= self.LEVEL_PROXIMITY_POINTS
        if at_poc or at_vah or at_val:
            score += 1
            level = "POC" if at_poc else ("VAH" if at_vah else "VAL")
            reasons.append(f"Price at key VP level ({level})")

        # 3. AMT state aligns with signal direction
        if (direction == "LONG"  and amt_bias in ("bullish", "neutral")) or \
           (direction == "SHORT" and amt_bias in ("bearish", "neutral")):
            score += 1
            reasons.append("AMT state aligns with signal")

        # 4. Absorption detected at level
        if payload.absorption:
            score += 1
            reasons.append("Absorption detected at level")

        # 5. Delta divergence present (adds conviction to fade signals)
        if payload.delta_divergence != "none":
            score += 1
            if payload.delta_divergence == "bearish_div":
                reasons.append("Bearish delta divergence (price high / CVD low)")
            else:
                reasons.append("Bullish delta divergence (price low / CVD high)")

        return score, reasons

    @staticmethod
    def strength_label(score: int) -> str:
        if score >= 4:
            return "STRONG"
        elif score >= 2:
            return "MODERATE"
        return "WEAK"


# ─── Bias & Invalidation Builder ─────────────────────────────────────────────

class BiasBuilder:
    """Produces the target bias and invalidation strings for a signal."""

    def build(self, direction: str, signal_type_key: str,
              price: float, poc: float, vah: float, val: float) -> tuple[str, str]:
        key = signal_type_key.lower().replace(" ", "_")

        if direction == "LONG":
            if "poc" in key:
                bias         = f"Long continuation toward VAH at {vah:.1f}"
                invalidation = f"Break & close below VAL at {val:.1f}"
            elif "val" in key or "absorption" in key:
                bias         = f"Long back to POC at {poc:.1f}"
                invalidation = f"Break below VAL at {val:.1f}"
            elif "initiative" in key or "range_extension" in key:
                bias         = f"Initiative long, target next resistance above {vah:.1f}"
                invalidation = f"Reclaim back inside value area below VAH {vah:.1f}"
            elif "delta_div" in key:
                bias         = f"Fade long — price low not confirmed by CVD, target POC {poc:.1f}"
                invalidation = f"New low below recent swing with CVD confirming"
            else:
                bias         = f"Long targeting POC at {poc:.1f}"
                invalidation = f"Sustained break below VAL at {val:.1f}"

        elif direction == "SHORT":
            if "poc" in key:
                bias         = f"Short continuation toward VAL at {val:.1f}"
                invalidation = f"Break & close above VAH at {vah:.1f}"
            elif "vah" in key or "absorption" in key:
                bias         = f"Short back to POC at {poc:.1f}"
                invalidation = f"Break above VAH at {vah:.1f}"
            elif "initiative" in key or "range_extension" in key:
                bias         = f"Initiative short, target next support below {val:.1f}"
                invalidation = f"Reclaim back inside value area above VAL {val:.1f}"
            elif "delta_div" in key:
                bias         = f"Fade short — price high not confirmed by CVD, target POC {poc:.1f}"
                invalidation = f"New high above recent swing with CVD confirming"
            else:
                bias         = f"Short targeting POC at {poc:.1f}"
                invalidation = f"Sustained break above VAH at {vah:.1f}"

        else:
            bias         = "No directional bias — wait for clarity"
            invalidation = "N/A"

        return bias, invalidation


# ─── Fabervaale Note Generator ────────────────────────────────────────────────

class FabervaaleNoteGenerator:
    """
    Generates the Fabervaale-style reasoning note at the bottom of every signal.
    Mirrors the way Fabio Valentini narrates his trade reasoning.
    """

    RESPONSIVE_NOTES = {
        "LONG": [
            "Price returned to value. Responsive buyers are stepping in at a known auction reference. "
            "Wait for confirmation candle before entry — let the market show its hand.",
            "Value area support holding. Absorption visible. Responsive activity suggests the auction "
            "is balanced here. Trade the rejection, not the anticipation.",
        ],
        "SHORT": [
            "Price rallied into overhead supply. Responsive sellers are defending the level. "
            "High volume with muted price movement = absorption. Let price confirm the rejection.",
            "VAH / POC acting as supply. CVD diverging from price = weak hands. "
            "Responsive shorts favoured while price stays below the level.",
        ],
    }

    INITIATIVE_NOTES = {
        "LONG": [
            "Initiative buying activity detected. Institutions pushing price into NEW territory above VAH. "
            "This is NOT a fade — trail stops and ride the imbalance.",
            "Balance broken to the upside. LVN above = fast price discovery. "
            "Only look for longs on pullbacks to the broken VAH (now support).",
        ],
        "SHORT": [
            "Initiative selling detected. Price driving into new lows below VAL. "
            "Do NOT buy into this — the dominant order flow is bearish.",
            "Balance broken to the downside. LVN below = fast price discovery. "
            "Only look for shorts on pullbacks to the broken VAL (now resistance).",
        ],
    }

    DIVERGENCE_NOTES = {
        "LONG":  "Delta divergence present: price printed a lower low but CVD did NOT confirm. "
                 "Sellers are exhausted. Fade the low with tight risk.",
        "SHORT": "Delta divergence present: price printed a new high but CVD did NOT confirm. "
                 "Buyers are losing conviction. Fade the high — this is a Fabervaale classic setup.",
    }

    def generate(self, signal_type_key: str, direction: str, amt_state: str) -> str:
        key = signal_type_key.lower()

        if "delta_div" in key:
            return self.DIVERGENCE_NOTES.get(direction, "Delta divergence detected. Proceed with caution.")

        if "initiative" in key or "range_extension" in key or "breaking" in amt_state.lower():
            notes = self.INITIATIVE_NOTES.get(direction, [])
        else:
            notes = self.RESPONSIVE_NOTES.get(direction, [])

        if not notes:
            return "Analyse order flow before entry. Let the market confirm direction."

        import hashlib, time
        # Deterministic but rotating note selection based on minute-of-hour
        idx = (int(time.time()) // 60) % len(notes)
        return notes[idx]


# ─── Main Analyser ────────────────────────────────────────────────────────────

class GoldAMTAnalyser:
    """
    Orchestrates the full Fabervaale analysis pipeline.
    Call analyse(payload) to get a complete AnalysedSignal.
    """

    def __init__(self):
        self.amt_classifier   = AMTStateClassifier()
        self.signal_classifier = SignalClassifier()
        self.scorer           = ConfluenceScorer()
        self.bias_builder     = BiasBuilder()
        self.note_generator   = FabervaaleNoteGenerator()

        # Mutable state — updated on every webhook
        self._last_signal: Optional[AnalysedSignal] = None

    # ── Public API ──────────────────────────────────────────────────────────

    def analyse(self, payload: WebhookPayload) -> AnalysedSignal:
        """Full analysis pipeline. Returns an AnalysedSignal."""

        # 1. Classify AMT state
        amt_state_label, amt_bias = self.amt_classifier.classify(
            payload.balance_state, payload.price, payload.poc
        )

        # 2. Classify signal
        signal_display, direction = self.signal_classifier.classify(payload.signal_type)

        # 3. Override direction if AMT is fully imbalanced (Fabervaale rule: never trade against dominant flow)
        direction = self._apply_imbalance_override(direction, payload.balance_state)

        # 4. Confluence score
        score, _reasons = self.scorer.score(payload, direction, amt_bias)
        strength = ConfluenceScorer.strength_label(score)

        # 5. CVD label
        cvd_label = self._cvd_label(payload.cvd, payload.cvd_trend)

        # 6. Absorption label
        absorption_label = (
            f"Detected at {payload.price:.1f}" if payload.absorption else "Not detected"
        )

        # 7. Bias & invalidation
        bias, invalidation = self.bias_builder.build(
            direction, payload.signal_type,
            payload.price, payload.poc, payload.vah, payload.val,
        )

        # 8. Fabervaale note
        note = self.note_generator.generate(payload.signal_type, direction, amt_state_label)

        signal = AnalysedSignal(
            direction        = direction,
            signal_type      = signal_display,
            amt_state        = amt_state_label,
            cvd_label        = cvd_label,
            absorption_label = absorption_label,
            confluence_score = score,
            strength         = strength,
            bias             = bias,
            invalidation     = invalidation,
            fabervaale_note  = note,
            price            = payload.price,
            poc              = payload.poc,
            vah              = payload.vah,
            val              = payload.val,
            should_send      = strength in ("STRONG", "MODERATE"),
        )

        self._last_signal = signal
        logger.info(
            "Signal analysed | %s %s | Score %d/5 | %s",
            direction, signal_display, score, strength,
        )
        return signal

    def current_status(self) -> dict:
        """Returns a summary dict for the /status Telegram command."""
        if self._last_signal is None:
            return {
                "amt_state":   "No data yet — waiting for first webhook from TradingView.",
                "bias":        "Unknown",
                "score":       0,
                "strength":    "N/A",
                "price":       0.0,
                "poc":         0.0,
                "vah":         0.0,
                "val":         0.0,
                "signal_type": "N/A",
            }
        s = self._last_signal
        return {
            "amt_state":   s.amt_state,
            "bias":        s.bias,
            "score":       s.confluence_score,
            "strength":    s.strength,
            "price":       s.price,
            "poc":         s.poc,
            "vah":         s.vah,
            "val":         s.val,
            "signal_type": s.signal_type,
        }

    # ── Private helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _apply_imbalance_override(direction: str, balance_state: str) -> str:
        """
        Fabervaale rule: in a full trend, only trade with the dominant flow.
        Never take a long when the market is imbalanced bearish and vice-versa.
        """
        if balance_state == "imbalanced_bullish"  and direction == "SHORT":
            return "NEUTRAL"
        if balance_state == "imbalanced_bearish"  and direction == "LONG":
            return "NEUTRAL"
        return direction

    @staticmethod
    def _cvd_label(cvd: float, trend: str) -> str:
        arrow = "▲" if cvd > 0 else "▼"
        label = trend.capitalize()
        return f"{label} Confirmation {arrow} ({cvd:+.0f})"
