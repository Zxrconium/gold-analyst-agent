"""
Telegram bot interface.
Handles:
  - Sending formatted signal messages to the configured chat
  - /status command — returns current AMT state and bias
  - /help command — usage reminder
"""

import logging
import os
from typing import TYPE_CHECKING

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

if TYPE_CHECKING:
    from agent import AnalysedSignal, GoldAMTAnalyser

logger = logging.getLogger(__name__)


# ─── Telegram Message Formatter ───────────────────────────────────────────────

class SignalFormatter:
    """Converts an AnalysedSignal into a Telegram-ready message string."""

    DIRECTION_EMOJI = {
        "LONG":    "🟢",
        "SHORT":   "🔴",
        "NEUTRAL": "⚪",
    }

    STRENGTH_EMOJI = {
        "STRONG":   "⚡⚡⚡",
        "MODERATE": "⚡⚡",
        "WEAK":     "⚡",
    }

    def format_signal(self, signal: "AnalysedSignal") -> str:
        d_emoji  = self.DIRECTION_EMOJI.get(signal.direction, "⚪")
        s_emoji  = self.STRENGTH_EMOJI.get(signal.strength, "⚡")

        lines = [
            f"{d_emoji} *GOLD {signal.direction} SIGNAL — {signal.strength}* {s_emoji}",
            "",
            f"💰 *Price:* `{signal.price:.2f}`",
            f"📍 *Location:* {signal.signal_type}",
            f"🔄 *AMT State:* {signal.amt_state}",
            f"📊 *CVD:* {signal.cvd_label}",
            f"🧲 *Absorption:* {signal.absorption_label}",
            f"🎯 *Confluence Score:* `{signal.confluence_score}/5`",
            "",
            f"📌 *Bias:* {signal.bias}",
            f"⚠️ *Invalidation:* {signal.invalidation}",
            "",
            "───────────────────────",
            f"🧠 *Think like Fabervaale:*",
            f"_{signal.fabervaale_note}_",
            "───────────────────────",
            "",
            f"📏 *VP Levels*",
            f"  VAH: `{signal.vah:.2f}`",
            f"  POC: `{signal.poc:.2f}`",
            f"  VAL: `{signal.val:.2f}`",
        ]
        return "\n".join(lines)

    def format_status(self, status: dict) -> str:
        lines = [
            "📡 *GOLD — CURRENT AMT STATUS*",
            "",
            f"🔄 *AMT State:* {status['amt_state']}",
            f"📍 *Last Signal:* {status['signal_type']}",
            f"🎯 *Last Bias:* {status['bias']}",
            f"⚡ *Last Score:* `{status['score']}/5` ({status['strength']})",
            "",
            f"📏 *VP Reference Levels*",
            f"  VAH: `{status['vah']:.2f}`",
            f"  POC: `{status['poc']:.2f}`",
            f"  VAL: `{status['val']:.2f}`",
            f"  Last Price: `{status['price']:.2f}`",
            "",
            "_Type /help for available commands._",
        ]
        return "\n".join(lines)


# ─── Bot Application ──────────────────────────────────────────────────────────

class GoldAnalystBot:
    """
    Wraps python-telegram-bot Application.
    Call start_polling() to run the bot standalone,
    or use send_signal() / send_message() from Flask.
    """

    def __init__(self, token: str, chat_id: str, analyser: "GoldAMTAnalyser"):
        self.token     = token
        self.chat_id   = chat_id
        self.analyser  = analyser
        self.formatter = SignalFormatter()
        self._app: Application | None = None

    # ── Bot commands ────────────────────────────────────────────────────────

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /status command."""
        status = self.analyser.current_status()
        text   = self.formatter.format_status(status)
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /help command."""
        text = (
            "🤖 *Gold Analyst Bot — Commands*\n\n"
            "/status — Current AMT state, bias and VP levels\n"
            "/help   — This message\n\n"
            "_Signals are sent automatically when TradingView fires a webhook._"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    # ── Outbound helpers (called from Flask) ────────────────────────────────

    async def send_signal(self, signal: "AnalysedSignal") -> bool:
        """Format and send a signal to the configured chat. Returns True on success."""
        text = self.formatter.format_signal(signal)
        return await self._send(text)

    async def _send(self, text: str) -> bool:
        try:
            app = self._get_app()
            await app.bot.send_message(
                chat_id    = self.chat_id,
                text       = text,
                parse_mode = ParseMode.MARKDOWN,
            )
            logger.info("Telegram message sent to %s", self.chat_id)
            return True
        except Exception as exc:
            logger.error("Failed to send Telegram message: %s", exc)
            return False

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def _get_app(self) -> Application:
        if self._app is None:
            self._app = (
                Application.builder()
                .token(self.token)
                .build()
            )
            self._app.add_handler(CommandHandler("status", self.cmd_status))
            self._app.add_handler(CommandHandler("help",   self.cmd_help))
        return self._app

    async def initialize(self) -> None:
        """Must be called once before send_signal() when running inside Flask."""
        app = self._get_app()
        await app.initialize()

    async def start_polling(self) -> None:
        """Run the bot in polling mode (for standalone / development use)."""
        app = self._get_app()
        logger.info("Starting Telegram bot polling...")
        await app.run_polling()
