# bot.py - Pivot Zone Telegram Bot
import os
import yfinance as yf
import pandas as pd
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from zones import get_latest_zones

TOKEN = os.getenv("BOT_TOKEN")

SYMBOLS = {
    "GOLD": "GC=F",
    "XAUUSD": "GC=F",
    "BTC": "BTC-USD",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "US30": "^DJI",
    "NAS100": "^NDX",
}

def get_data(symbol, period="3mo", interval="1h"):
    df = yf.download(symbol, period=period, interval=interval, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    return df

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Pivot Zone Bot!\n\n"
        "Commands:\n"
        "/zones GOLD - Get Gold zones\n"
        "/zones BTC - Get Bitcoin zones\n"
        "/zones EURUSD - Get EURUSD zones\n"
        "/zones GBPUSD\n"
        "/zones US30\n"
        "/zones NAS100\n\n"
        "I find Supply & Demand zones from pivot highs/lows."
    )

async def zones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /zones GOLD  or  /zones BTC")
        return
    key = context.args[0].upper()
    symbol = SYMBOLS.get(key, key)
    await update.message.reply_text(f"🔍 Scanning {key} (1H)... please wait...")
    try:
        df = get_data(symbol)
        if len(df) < 50:
            await update.message.reply_text("Not enough data. Try again.")
            return
        supply, demand = get_latest_zones(df)
        price = float(df['close'].iloc[-1])
        msg = f"📊 *{key} - 1H Pivot Zones*\nCurrent Price: `{price:.2f}`\n\n"
        msg += "🔴 *SUPPLY (Sell Zones):*\n"
        for z in supply:
            msg += f"• {z['bottom']:.2f} - {z['top']:.2f}\n"
        msg += "\n🟢 *DEMAND (Buy Zones):*\n"
        for z in demand:
            msg += f"• {z['bottom']:.2f} - {z['top']:.2f}\n"
        msg += "\n⚠️ Not financial advice. Confirm with price action."
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("zones", zones_cmd))
    print("Bot is running...")
    app.run_polling()
