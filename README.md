# Gold Futures AMT Analyst Agent
### Powered by Fabervaale's (Fabio Valentini) Methodology

A personal AI trading analyst for **XAUUSD / GC1!** that thinks and acts like world-ranked scalper Fabio Valentini — using **Auction Market Theory**, **Volume Profile**, and **Order Flow** to send real-time signals via Telegram.

---

## Architecture

```
TradingView (Pine Script)
      │  webhook (JSON)
      ▼
Flask Server (app.py)
      │  WebhookPayload
      ▼
AMT Analysis Engine (agent.py)
  ├── AMT State Classifier
  ├── Signal Classifier
  ├── Confluence Scorer
  ├── Bias & Invalidation Builder
  └── Fabervaale Note Generator
      │  AnalysedSignal
      ▼
Telegram Bot (telegram_bot.py)
      │  formatted message
      ▼
Your Telegram Chat
```

---

## Quick Start

### 1. Clone & Install

```bash
git clone <repo-url>
cd gold-analyst-agent
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | Your Telegram user/chat ID (get it from [@userinfobot](https://t.me/userinfobot)) |
| `WEBHOOK_SECRET` | A random string you choose — added as `?secret=` in TradingView alert URL |
| `FLASK_SECRET_KEY` | Random string for Flask session security |
| `PORT` | Server port (default: `5000`) |

### 3. Create Your Telegram Bot

1. Open Telegram → search **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the token into `TELEGRAM_BOT_TOKEN`
4. Send your bot a message, then visit:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Find `"chat":{"id":XXXXXXX}` — that's your `TELEGRAM_CHAT_ID`

### 4. Run the Server

**Development (local):**
```bash
python app.py
```

**Expose to TradingView with ngrok:**
```bash
# In a second terminal:
ngrok http 5000
# Copy the https:// URL — you'll need it for TradingView
```

**Production (gunicorn + systemd):**
```bash
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```
See [Deployment](#deployment) below for a full systemd unit.

---

## TradingView Setup

### 5. Add the Pine Script Indicator

1. Open TradingView → **Pine Script Editor**
2. Paste the entire contents of `indicator.pine`
3. Click **Add to chart** — apply to **XAUUSD** or **GC1!** on your preferred timeframe (5m recommended for scalping)
4. In the indicator settings, set **VP Lookback** and **Value Area %** to your preference

### 6. Create the Alert

1. Right-click the chart → **Add Alert**
2. **Condition:** `AMT Gold` → `alert()` function calls
3. **Message:** Leave as `{{strategy.order.alert_message}}` — Pine Script fills this automatically with the JSON payload
4. **Webhook URL:**
   ```
   https://your-ngrok-or-server.com/webhook?secret=YOUR_WEBHOOK_SECRET
   ```
   Replace with your actual URL and the `WEBHOOK_SECRET` value from `.env`
5. Set **Expiry** to an open-ended date
6. **Save alert**

> **Tip:** Create one alert per signal type, or use the consolidated `alert()` call in the Pine Script which fires on any qualifying signal.

---

## Telegram Commands

Once the server is running and the bot is polling:

| Command | Description |
|---|---|
| `/status` | Current AMT state, VP levels, last signal bias |
| `/help` | List of available commands |

**Start bot polling (development):**
```bash
# Option A: POST to the server
curl -X POST http://localhost:5000/start-bot

# Option B: run standalone polling
python -c "import asyncio; from telegram_bot import GoldAnalystBot; from agent import GoldAMTAnalyser; import os; from dotenv import load_dotenv; load_dotenv(); asyncio.run(GoldAnalystBot(os.environ['TELEGRAM_BOT_TOKEN'], os.environ['TELEGRAM_CHAT_ID'], GoldAMTAnalyser()).start_polling())"
```

For production, run polling as a separate systemd service (see below).

---

## Signal Format

Signals arrive in Telegram like this:

```
🟢 GOLD LONG SIGNAL — STRONG ⚡⚡⚡

💰 Price: 2341.50
📍 Location: VAL Bounce Long
🔄 AMT State: In Balance — Price Below POC, Bearish Lean
📊 CVD: Bullish Confirmation ▲ (+1847)
🧲 Absorption: Detected at 2341.5
🎯 Confluence Score: 4/5

📌 Bias: Long back to POC at 2348.00
⚠️ Invalidation: Break below VAL at 2330.00

───────────────────────
🧠 Think like Fabervaale:
Value area support holding. Absorption visible. Responsive activity
suggests the auction is balanced here. Trade the rejection, not the
anticipation.
───────────────────────

📏 VP Levels
  VAH: 2360.00
  POC: 2348.00
  VAL: 2330.00
```

### Signal Types

| Signal | Description |
|---|---|
| `POC Rejection Long/Short` | Price dips to/rallies to POC, shows responsive activity |
| `VAL Bounce Long` | Price hits VAL, absorbed, bouncing back to POC |
| `VAH Rejection Short` | Price hits VAH, absorbed, returning to POC |
| `Initiative Breakout Long/Short` | Price breaking out of value area with CVD confirmation |
| `Delta Divergence Long/Short` | Price making new extreme but CVD not confirming — fade signal |
| `Absorption Long/Short` | High volume, low range at key level — institutional activity |

### Confluence Scoring

Each signal is scored 0–5:

| Factor | Points |
|---|---|
| CVD confirms direction | +1 |
| Price at key VP level (POC/VAH/VAL) | +1 |
| AMT state aligns with signal | +1 |
| Absorption detected at level | +1 |
| Delta divergence present | +1 |

- **Score 4–5 → STRONG** — sent to Telegram ✅
- **Score 2–3 → MODERATE** — sent to Telegram ✅
- **Score 0–1 → WEAK** — filtered out ❌

---

## AMT States (Fabervaale Framework)

| State | Meaning | Action |
|---|---|---|
| `In Balance` | Price between VAH and VAL | Expect rotation; trade responsive signals |
| `Breaking Balance High` | Price pushing above VAH | Potential initiative buying beginning |
| `Breaking Balance Low` | Price pushing below VAL | Potential initiative selling beginning |
| `Imbalanced Bullish` | Clear uptrend | Only look for longs |
| `Imbalanced Bearish` | Clear downtrend | Only look for shorts |

> **Core Fabervaale Rule:** Never trade against the dominant order flow. When imbalanced, the engine automatically marks counter-trend signals as NEUTRAL and does not send them.

---

## Webhook Payload Reference

The Pine Script sends this JSON on every qualifying bar close:

```json
{
  "ticker":           "XAUUSD",
  "price":            2341.5,
  "poc":              2348.0,
  "vah":              2360.0,
  "val":              2330.0,
  "cvd":              1847.0,
  "cvd_trend":        "bullish",
  "volume":           5200,
  "avg_volume":       3100.0,
  "balance_state":    "in_balance",
  "signal_type":      "val_bounce_long",
  "absorption":       true,
  "delta_divergence": "none",
  "hvn_near":         false,
  "lvn_near":         false,
  "timeframe":        "5"
}
```

You can also POST this manually to test:
```bash
curl -X POST "http://localhost:5000/webhook?secret=YOUR_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "ticker":"XAUUSD","price":2341.5,"poc":2348.0,
    "vah":2360.0,"val":2330.0,"cvd":1847.0,
    "cvd_trend":"bullish","volume":5200,"avg_volume":3100,
    "balance_state":"in_balance","signal_type":"val_bounce_long",
    "absorption":true,"delta_divergence":"none",
    "hvn_near":false,"lvn_near":false,"timeframe":"5"
  }'
```

---

## Deployment

### Systemd (Ubuntu / Debian VPS)

**Flask webhook server** — `/etc/systemd/system/gold-analyst.service`:
```ini
[Unit]
Description=Gold AMT Analyst — Flask Webhook Server
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/gold-analyst-agent
EnvironmentFile=/home/ubuntu/gold-analyst-agent/.env
ExecStart=/home/ubuntu/gold-analyst-agent/venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Telegram polling bot** — `/etc/systemd/system/gold-analyst-bot.service`:
```ini
[Unit]
Description=Gold AMT Analyst — Telegram Bot Polling
After=network.target gold-analyst.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/gold-analyst-agent
EnvironmentFile=/home/ubuntu/gold-analyst-agent/.env
ExecStart=/home/ubuntu/gold-analyst-agent/venv/bin/python -c "\
import asyncio, os; from dotenv import load_dotenv; load_dotenv(); \
from agent import GoldAMTAnalyser; from telegram_bot import GoldAnalystBot; \
asyncio.run(GoldAnalystBot(os.environ['TELEGRAM_BOT_TOKEN'], os.environ['TELEGRAM_CHAT_ID'], GoldAMTAnalyser()).start_polling())"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable gold-analyst gold-analyst-bot
sudo systemctl start  gold-analyst gold-analyst-bot
```

### Reverse Proxy (nginx)

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    location /webhook {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
    }

    location /health {
        proxy_pass         http://127.0.0.1:5000;
    }
}
```

---

## File Structure

```
gold-analyst-agent/
├── app.py              # Flask server — receives webhooks, dispatches signals
├── agent.py            # AMT analysis engine — Fabervaale's full framework
├── telegram_bot.py     # Telegram bot — formatting, /status, /help commands
├── indicator.pine      # TradingView Pine Script v5 — VP, CVD, signals
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
└── README.md           # This file
```

---

## Notes on CVD Accuracy

TradingView's Pine Script does **not** provide tick-level bid/ask data. The CVD in `indicator.pine` uses an OHLC-based estimation:

```
buy_vol  ≈ volume × (close − low) / (high − low)
sell_vol ≈ volume × (high − close) / (high − low)
delta    = buy_vol − sell_vol
```

This is a well-known approximation (similar to the Kaufman approach) and is accurate enough for directional bias on liquid markets like XAUUSD. For true tick-level CVD, use Bookmap, Sierra Chart, or Quantower — then send the CVD value via webhook alongside the price data.

---

## Disclaimer

This tool is for **educational and informational purposes only**. It does not constitute financial advice. Trading futures involves substantial risk of loss. Past performance is not indicative of future results. Always use proper risk management.
