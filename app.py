"""
Gold Futures AI Analyst Agent — Flask Entry Point

Receives TradingView webhook alerts, runs them through the AMT analysis
engine (Fabervaale's framework), and dispatches qualifying signals to
Telegram.

Endpoints:
  POST /webhook?secret=<WEBHOOK_SECRET>  — TradingView alert payload
  GET  /health                           — uptime check
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from agent import GoldAMTAnalyser, WebhookPayload
from telegram_bot import GoldAnalystBot

load_dotenv()

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
WEBHOOK_SECRET     = os.environ.get("WEBHOOK_SECRET", "")
PORT               = int(os.environ.get("PORT", 5000))

# ─── Singletons ───────────────────────────────────────────────────────────────

analyser = GoldAMTAnalyser()
bot      = GoldAnalystBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, analyser)
app      = Flask(__name__)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_payload(data: dict) -> WebhookPayload:
    """
    Converts the raw JSON from TradingView into a typed WebhookPayload.

    Expected TradingView alert message (JSON format):
    {
      "ticker":        "XAUUSD",
      "price":         2341.5,
      "poc":           2338.0,
      "vah":           2350.0,
      "val":           2330.0,
      "cvd":           1250.0,
      "cvd_trend":     "bullish",
      "volume":        4800,
      "avg_volume":    3200,
      "balance_state": "in_balance",
      "signal_type":   "val_bounce_long",
      "absorption":    true,
      "delta_divergence": "none",
      "hvn_near":      false,
      "lvn_near":      false,
      "timeframe":     "5m"
    }
    """
    return WebhookPayload(
        ticker           = str(data.get("ticker", "XAUUSD")),
        price            = float(data["price"]),
        poc              = float(data["poc"]),
        vah              = float(data["vah"]),
        val              = float(data["val"]),
        cvd              = float(data.get("cvd", 0)),
        cvd_trend        = str(data.get("cvd_trend", "neutral")).lower(),
        volume           = float(data.get("volume", 0)),
        avg_volume       = float(data.get("avg_volume", 1)),
        balance_state    = str(data.get("balance_state", "in_balance")).lower(),
        signal_type      = str(data.get("signal_type", "unknown")),
        absorption       = bool(data.get("absorption", False)),
        delta_divergence = str(data.get("delta_divergence", "none")).lower(),
        hvn_near         = bool(data.get("hvn_near", False)),
        lvn_near         = bool(data.get("lvn_near", False)),
        timeframe        = str(data.get("timeframe", "5m")),
    )


def _run_async(coro):
    """Run an async coroutine from a sync Flask route."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result(timeout=15)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "gold-analyst-agent"}), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    # ── Auth ──────────────────────────────────────────────────────────────
    if WEBHOOK_SECRET:
        provided = request.args.get("secret", "")
        if provided != WEBHOOK_SECRET:
            logger.warning("Webhook auth failed — bad secret from %s", request.remote_addr)
            return jsonify({"error": "Unauthorized"}), 401

    # ── Parse ─────────────────────────────────────────────────────────────
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    required_fields = ["price", "poc", "vah", "val", "signal_type"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 422

    try:
        payload = _parse_payload(data)
    except (KeyError, ValueError, TypeError) as exc:
        logger.error("Payload parse error: %s | data=%s", exc, data)
        return jsonify({"error": f"Payload error: {exc}"}), 422

    # ── Analyse ───────────────────────────────────────────────────────────
    signal = analyser.analyse(payload)

    logger.info(
        "Signal | %s %s | Score %d/5 | %s | send=%s",
        signal.direction, signal.signal_type,
        signal.confluence_score, signal.strength, signal.should_send,
    )

    # ── Dispatch ──────────────────────────────────────────────────────────
    sent = False
    if signal.should_send:
        sent = _run_async(bot.send_signal(signal))
    else:
        logger.info("Signal below threshold (%s) — not sent to Telegram", signal.strength)

    return jsonify({
        "received":   True,
        "direction":  signal.direction,
        "signal":     signal.signal_type,
        "score":      signal.confluence_score,
        "strength":   signal.strength,
        "sent":       sent,
    }), 200


# ─── Bot polling (development shortcut) ──────────────────────────────────────

@app.route("/start-bot", methods=["POST"])
def start_bot():
    """
    POST /start-bot to start Telegram polling in a background thread.
    For production, run polling via a separate process or systemd unit.
    """
    import threading

    def _poll():
        asyncio.run(bot.start_polling())

    t = threading.Thread(target=_poll, daemon=True, name="telegram-polling")
    t.start()
    return jsonify({"status": "polling started"}), 200


# ─── Startup ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting Gold Analyst Agent on port %d", PORT)
    logger.info("Initialising Telegram bot...")
    asyncio.run(bot.initialize())
    logger.info("Telegram bot ready.")
    app.run(host="0.0.0.0", port=PORT, debug=False)
