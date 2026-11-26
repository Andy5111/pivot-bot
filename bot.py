"""
Supply & Demand Zone Detector - SMART + TIMEFRAME VERSION
Usage: /zones GOLD 15m  |  /zones GOLD 1h  |  /zones GOLD 4h  |  /zones GOLD 1d
"""
from dataclasses import dataclass
from typing import List
import os
import threading

from flask import Flask
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot is running!"
def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
threading.Thread(target=run_web, daemon=True).start()

import pandas as pd
import numpy as np
import yfinance as yf
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")

@dataclass
class Zone:
    type: str
    high: float
    low: float
    index: int
    confidence: float
    reasons: List[str]
    timeframe: str = ""
    symbol: str = ""

def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).lower().strip() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    return df

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    df = normalize_df(df)
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def is_strong_up_move(df: pd.DataFrame, start: int, atr: pd.Series) -> bool:
    if start + 2 >= len(df):
        return False
    total_move = 0
    strong_candles = 0
    for j in range(start, min(start + 4, len(df))):
        body = df["close"].iloc[j] - df["open"].iloc[j]
        full_range = df["high"].iloc[j] - df["low"].iloc[j]
        if body > 0 and body > 0.45 * atr.iloc[j] and full_range > 0.7 * atr.iloc[j]:
            strong_candles += 1
            total_move += body
        else:
            break
    return strong_candles >= 2 and total_move > 1.6 * atr.iloc[start]

def is_strong_down_move(df: pd.DataFrame, start: int, atr: pd.Series) -> bool:
    if start + 2 >= len(df):
        return False
    total_move = 0
    strong_candles = 0
    for j in range(start, min(start + 4, len(df))):
        body = df["open"].iloc[j] - df["close"].iloc[j]
        full_range = df["high"].iloc[j] - df["low"].iloc[j]
        if body > 0 and body > 0.45 * atr.iloc[j] and full_range > 0.7 * atr.iloc[j]:
            strong_candles += 1
            total_move += body
        else:
            break
    return strong_candles >= 2 and total_move > 1.6 * atr.iloc[start]

def detect_zones(df: pd.DataFrame, symbol: str = "UNKNOWN", timeframe: str = "1H", lookback: int = 120, min_confidence: float = 55.0) -> List[Zone]:
    df = normalize_df(df)
    if len(df) < 40:
        return []
    df = df.copy().reset_index(drop=True)
    atr = calculate_atr(df)
    zones: List[Zone] = []
    start = max(14, len(df) - lookback)
    for i in range(start, len(df) - 4):
        if pd.isna(atr.iloc[i]) or atr.iloc[i] == 0:
            continue
        if is_strong_up_move(df, i + 1, atr):
            zone_high = float(df["high"].iloc[i])
            zone_low = float(df["low"].iloc[i])
            confidence = 52.0
            reasons = []
            move_size = df["close"].iloc[min(i + 3, len(df)-1)] - df["open"].iloc[i + 1]
            if move_size > 2.8 * atr.iloc[i]:
                confidence += 18
                reasons.append("Very strong buying move")
            elif move_size > 2.0 * atr.iloc[i]:
                confidence += 12
                reasons.append("Strong buying move")
            else:
                reasons.append("Clear buying move")
            body = abs(df["close"].iloc[i] - df["open"].iloc[i])
            full_range = zone_high - zone_low
            if full_range > 0 and body / full_range < 0.5:
                confidence += 10
                reasons.append("Clean starting candle")
            if confidence >= min_confidence:
                zones.append(Zone(type="demand", high=zone_high, low=zone_low, index=i, confidence=confidence, reasons=reasons, timeframe=timeframe, symbol=symbol))
        if is_strong_down_move(df, i + 1, atr):
            zone_high = float(df["high"].iloc[i])
            zone_low = float(df["low"].iloc[i])
            confidence = 52.0
            reasons = []
            move_size = df["open"].iloc[i + 1] - df["close"].iloc[min(i + 3, len(df)-1)]
            if move_size > 2.8 * atr.iloc[i]:
                confidence += 18
                reasons.append("Very strong selling move")
            elif move_size > 2.0 * atr.iloc[i]:
                confidence += 12
                reasons.append("Strong selling move")
            else:
                reasons.append("Clear selling move")
            body = abs(df["close"].iloc[i] - df["open"].iloc[i])
            full_range = zone_high - zone_low
            if full_range > 0 and body / full_range < 0.5:
                confidence += 10
                reasons.append("Clean starting candle")
            if confidence >= min_confidence:
                zones.append(Zone(type="supply", high=zone_high, low=zone_low, index=i, confidence=confidence, reasons=reasons, timeframe=timeframe, symbol=symbol))
    zones = sorted(zones, key=lambda z: z.index, reverse=True)[:5]
    return zones

SYMBOLS = {
    "GOLD": "GC=F",
    "XAUUSD": "GC=F",
    "XAU": "GC=F",
    "BTC": "BTC-USD",
    "BITCOIN": "BTC-USD",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "US30": "^DJI",
    "NAS100": "^NDX",
    "SPX500": "^GSPC",
}

# --- TIMEFRAMES YOU CAN CHOOSE ---
# key: (yfinance interval, yfinance period, display name)
TIMEFRAMES = {
    "5M": ("5m", "2d", "5M"),
    "5m": ("5m", "2d", "5M"),
    "15M": ("15m", "5d", "15M"),
    "15m": ("15m", "5d", "15M"),
    "M15": ("15m", "5d", "15M"),
    "30M": ("30m", "5d", "30M"),
    "30m": ("30m", "5d", "30M"),
    "1H": ("1h", "10d", "1H"),
    "1h": ("1h", "10d", "1H"),
    "H1": ("1h", "10d", "1H"),
    "4H": ("1h", "1mo", "4H"),
    "4h": ("1h", "1mo", "4H"),
    "H4": ("1h", "1mo", "4H"),
    "1D": ("1d", "3mo", "1D"),
    "1d": ("1d", "3mo", "1D"),
    "D1": ("1d", "3mo", "1D"),
    "1W": ("1wk", "1y", "1W"),
    "1w": ("1wk", "1y", "1W"),
}

def get_market_thinking(df, zones):
    df = normalize_df(df)
    close = df["close"]
    current = float(close.iloc[-1])
    ema50 = float(close.ewm(span=50).mean().iloc[-1])
    ema200 = float(close.ewm(span=200).mean().iloc[-1]) if len(close) >= 200 else ema50
    if current > ema50 > ema200:
        trend = "🟢 STRONG UPTREND"
        trend_note = "Price above EMA50 above EMA200. Buyers in control."
    elif current > ema50:
        trend = "🟢 UPTREND"
        trend_note = "Price above EMA50. Lean bullish."
    elif current < ema50 < ema200:
        trend = "🔴 STRONG DOWNTREND"
        trend_note = "Price below EMA50 below EMA200. Sellers in control."
    elif current < ema50:
        trend = "🔴 DOWNTREND"
        trend_note = "Price below EMA50. Lean bearish."
    else:
        trend = "🟡 RANGING"
        trend_note = "Price stuck around EMAs. Wait for breakout."
    nearest = None
    nearest_dist = 999999
    inside_zone = None
    for z in zones:
        if z.low <= current <= z.high:
            inside_zone = z
        centre = (z.high + z.low) / 2
        dist = abs(current - centre) / current * 100
        if dist < nearest_dist:
            nearest_dist = dist
            nearest = z
    if inside_zone:
        if inside_zone.type == "demand":
            bias = "🟢 LOOK FOR BUYS - Price is INSIDE a Demand Zone"
            plan = f"Entry: Now / on bullish confirmation in zone\nStop Loss: Below {inside_zone.low:,.2f}\nTake Profit: Next Supply Zone above"
        else:
            bias = "🔴 LOOK FOR SELLS - Price is INSIDE a Supply Zone"
            plan = f"Entry: Now / on bearish confirmation in zone\nStop Loss: Above {inside_zone.high:,.2f}\nTake Profit: Next Demand Zone below"
    elif nearest and nearest.type == "demand":
        if current > nearest.high:
            bias = "⏳ WAIT FOR PULLBACK TO BUY"
            plan = f"Wait for price to drop to {nearest.low:,.2f} - {nearest.high:,.2f} ({nearest_dist:.2f}% away)\nDo NOT chase here.\nEntry: On retest + bullish candle\nStop Loss: Below {nearest.low:,.2f}"
        else:
            bias = "👀 PRICE APPROACHING DEMAND FROM BELOW"
            plan = f"Price is {nearest_dist:.2f}% below Demand {nearest.low:,.2f} - {nearest.high:,.2f}\nWait for price to ENTER the zone, then look for bullish bounce.\nIf it breaks below {nearest.low:,.2f} with force, zone is broken - do NOT buy."
    elif nearest and nearest.type == "supply":
        if current < nearest.low:
            bias = "⏳ WAIT FOR RALLY TO SELL"
            plan = f"Wait for price to rise to {nearest.low:,.2f} - {nearest.high:,.2f} ({nearest_dist:.2f}% away)\nDo NOT chase here.\nEntry: On retest + bearish candle\nStop Loss: Above {nearest.high:,.2f}"
        else:
            bias = "👀 PRICE APPROACHING SUPPLY FROM ABOVE"
            plan = f"Price is {nearest_dist:.2f}% above Supply {nearest.low:,.2f} - {nearest.high:,.2f}\nWait for price to ENTER the zone, then look for bearish rejection.\nIf it breaks above {nearest.high:,.2f} with force, zone is broken - do NOT sell."
    else:
        bias = "🟡 NO CLEAR SETUP - WAIT"
        plan = "Price is far from any fresh zone. Patience is a trade."
    return trend, trend_note, bias, plan, nearest, nearest_dist, inside_zone

def get_zones_text(symbol_key: str, tf_key: str = "1h"):
    ticker = SYMBOLS.get(symbol_key.upper())
    if not ticker:
        return f"Unknown symbol {symbol_key}. Try: /zones GOLD  or  /zones BTC"
    tf = TIMEFRAMES.get(tf_key, TIMEFRAMES.get(tf_key.upper(), TIMEFRAMES["1h"]))
    interval, period, display_tf = tf
    try:
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
        if df is None or len(df) < 40:
            return f"Not enough data for {symbol_key} on {display_tf} right now. Try again in a minute."
        df = normalize_df(df)
        # For 4H, resample 1h candles into 4h candles
        if display_tf == "4H":
            df.index = pd.to_datetime(df.index)
            df4 = df.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
            df = df4.reset_index(drop=True)
        zones = detect_zones(df, symbol=symbol_key.upper(), timeframe=display_tf)
        if not zones:
            return f"No high-quality zones found for {symbol_key} on {display_tf} right now."
        current = float(df["close"].iloc[-1])
        trend, trend_note, bias, plan, nearest, nearest_dist, inside_zone = get_market_thinking(df, zones)
        msg = f"🧠 {symbol_key.upper()} - {display_tf} Smart Analysis\n"
        msg += f"Current Price: {current:,.2f}\n\n"
        msg += f"📈 TREND: {trend}\n{trend_note}\n\n"
        msg += f"🎯 BIAS: {bias}\n\n"
        msg += f"📋 TRADE PLAN:\n{plan}\n\n"
        msg += f"--- ZONES (Newest First) ---\n"
        for z in zones:
            emoji = "🟢 DEMAND" if z.type == "demand" else "🔴 SUPPLY"
            dist = abs(current - ((z.high+z.low)/2)) / current * 100
            tag = " ← PRICE HERE" if inside_zone == z else ""
            msg += f"{emoji} {z.low:,.2f} - {z.high:,.2f} | {z.confidence:.0f}% | {dist:.2f}% away{tag}\n"
            msg += f"   {', '.join(z.reasons)}\n"
        msg += "\n⚠️ Not financial advice. Wait for confirmation candle."
        return msg
    except Exception as e:
        return f"Error: {e}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to Pivot Zone Bot!\n\n"
        "How to use:\n"
        "/zones GOLD - Default 1H\n"
        "/zones GOLD 15m - 15 minute zones\n"
        "/zones GOLD 1h - 1 hour zones\n"
        "/zones GOLD 4h - 4 hour zones\n"
        "/zones GOLD 1d - Daily zones\n"
        "/zones BTC 15m - Bitcoin 15m\n\n"
        "Symbols: GOLD, BTC, EURUSD, GBPUSD, USDJPY, US30, NAS100, SPX500\n"
        "Timeframes: 5m, 15m, 30m, 1h, 4h, 1d, 1w"
    )

async def zones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /zones GOLD 1h\nTry: /zones GOLD 15m  or  /zones BTC 4h")
        return
    symbol = context.args[0].upper()
    tf = context.args[1] if len(context.args) > 1 else "1h"
    await update.message.reply_text(f"🧠 Thinking about {symbol} on {tf.upper()}... please wait")
    text = get_zones_text(symbol, tf)
    await update.message.reply_text(text)

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set!")
        return
    print("Bot is running...")
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("zones", zones_cmd))
    app_bot.run_polling()

if __name__ == "__main__":
    main()
