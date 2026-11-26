"""
FINAL BOT - TWELVE DATA VERSION - FAST, NEVER BLOCKS - FIXED
"""
from dataclasses import dataclass
from typing import List, Dict
import os, threading, datetime, requests

from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running TWELVE!"

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

threading.Thread(target=run_web, daemon=True).start()

import pandas as pd
import numpy as np
import yfinance as yf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TWELVE_KEY = os.environ.get("TWELVE_API_KEY")

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
    tested: int = 0
    is_fresh: bool = True
    is_flip: bool = False

@dataclass
class FVG:
    type: str
    high: float
    low: float
    index: int

ALERTS: Dict[int, List[dict]] = {}
JOURNAL: List[dict] = []
USER_STATE: Dict[int, str] = {}

SYMBOLS = {
    "GOLD": "GC=F", "XAUUSD": "GC=F", "XAU": "GC=F",
    "BTC": "BTC-USD", "BITCOIN": "BTC-USD",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "US30": "^DJI", "NAS100": "^NDX", "SPX500": "^GSPC",
}

TIMEFRAMES = {
    "5m": ("5m", "2d", "5M"), "15m": ("15m", "5d", "15M"), "30m": ("30m", "5d", "30M"),
    "1h": ("1h", "10d", "1H"), "4h": ("1h", "1mo", "4H"), "1d": ("1d", "3mo", "1D"), "1w": ("1wk", "1y", "1W"),
}

def norm_tf(t):
    t = t.lower().replace("m15", "15m").replace("h1", "1h").replace("h4", "4h").replace("d1", "1d")
    return t if t in TIMEFRAMES else "1h"

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🥇 GOLD", callback_data="sym:GOLD"),
         InlineKeyboardButton("₿ BTC", callback_data="sym:BTC"),
         InlineKeyboardButton("💶 EURUSD", callback_data="sym:EURUSD"),
         InlineKeyboardButton("💷 GBPUSD", callback_data="sym:GBPUSD")],
        [InlineKeyboardButton("15m", callback_data="tf:15m"),
         InlineKeyboardButton("1h", callback_data="tf:1h"),
         InlineKeyboardButton("4h", callback_data="tf:4h"),
         InlineKeyboardButton("1d", callback_data="tf:1d"),
         InlineKeyboardButton("🌐 ALL", callback_data="tf:all")],
        [InlineKeyboardButton("🔔 Set Alert", callback_data="action:alert_help"),
         InlineKeyboardButton("📓 Score", callback_data="action:score"),
         InlineKeyboardButton("🔄 Refresh 1h", callback_data="action:refresh")],
    ])

def normalize_df(df):
    df = df.copy()
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).lower().strip() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    return df

def calculate_atr(df, period=14):
    df = normalize_df(df)
    tr = pd.concat([df["high"] - df["low"], abs(df["high"] - df["close"].shift(1)), abs(df["low"] - df["close"].shift(1))], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def is_strong_up(df, start, atr):
    if start + 2 >= len(df): return False
    total = 0; cnt = 0
    for j in range(start, min(start + 4, len(df))):
        body = df["close"].iloc[j] - df["open"].iloc[j]
        rng = df["high"].iloc[j] - df["low"].iloc[j]
        if body > 0 and body > 0.45 * atr.iloc[j] and rng > 0.7 * atr.iloc[j]:
            cnt += 1; total += body
        else: break
    return cnt >= 2 and total > 1.6 * atr.iloc[start]

def is_strong_down(df, start, atr):
    if start + 2 >= len(df): return False
    total = 0; cnt = 0
    for j in range(start, min(start + 4, len(df))):
        body = df["open"].iloc[j] - df["close"].iloc[j]
        rng = df["high"].iloc[j] - df["low"].iloc[j]
        if body > 0 and body > 0.45 * atr.iloc[j] and rng > 0.7 * atr.iloc[j]:
            cnt += 1; total += body
        else: break
    return cnt >= 2 and total > 1.6 * atr.iloc[start]

def filter_overlapping_zones(zones, atr_val):
    if not zones: return []
    zones = sorted(zones, key=lambda z: z.confidence, reverse=True)
    filtered = []
    tol = 0.25 * atr_val if atr_val else 0
    for z in zones:
        overlap = False
        for kept in filtered:
            if not (z.high < kept.low - tol or z.low > kept.high + tol):
                overlap = True; break
        if not overlap: filtered.append(z)
    return filtered

def detect_zones(df, symbol="UNKNOWN", timeframe="1H", lookback=120, min_confidence=55.0):
    df = normalize_df(df)
    if len(df) < 40: return []
    df = df.copy().reset_index(drop=True)
    atr = calculate_atr(df)
    zones = []; flips = []
    start = max(14, len(df) - lookback)
    for i in range(start, len(df) - 4):
        if pd.isna(atr.iloc[i]) or atr.iloc[i] == 0: continue
        zh = float(df["high"].iloc[i]); zl = float(df["low"].iloc[i]); rng = zh - zl
        if rng > 1.5 * atr.iloc[i]: continue
        if is_strong_up(df, i + 1, atr):
            conf = 52.0; reasons = []
            move = df["close"].iloc[min(i + 3, len(df) - 1)] - df["open"].iloc[i + 1]
            if move > 2.8 * atr.iloc[i]: conf += 18; reasons.append("Very strong buying move")
            elif move > 2.0 * atr.iloc[i]: conf += 12; reasons.append("Strong buying move")
            else: reasons.append("Clear buying move")
            body = abs(df["close"].iloc[i] - df["open"].iloc[i])
            if rng > 0 and body / rng < 0.5: conf += 10; reasons.append("Clean starting candle")
            tested = 0; broken = False
            for k in range(i + 1, len(df)):
                if df["low"].iloc[k] <= zh and df["high"].iloc[k] >= zl:
                    tested += 1
                    if df["close"].iloc[k] < zl: broken = True; break
                    else: conf -= 10; reasons.append("Tested and held -10"); break
            if broken:
                flips.append(Zone(type="supply", high=zh, low=zl, index=i, confidence=62.0, reasons=["🔄 FLIP: Demand broken, now Supply"], timeframe=timeframe, symbol=symbol, tested=tested, is_fresh=False, is_flip=True))
                continue
            if tested == 0: conf += 12; reasons.append("🆕 FRESH - Never tested")
            elif tested == 1: conf += 2; reasons.append("Tested 1x - Still valid")
            else: conf -= 15; reasons.append(f"Tested {tested}x - WEAK")
            if conf >= min_confidence:
                zones.append(Zone(type="demand", high=zh, low=zl, index=i, confidence=conf, reasons=reasons, timeframe=timeframe, symbol=symbol, tested=tested, is_fresh=(tested == 0)))
        if is_strong_down(df, i + 1, atr):
            conf = 52.0; reasons = []
            move = df["open"].iloc[i + 1] - df["close"].iloc[min(i + 3, len(df) - 1)]
            if move > 2.8 * atr.iloc[i]: conf += 18; reasons.append("Very strong selling move")
            elif move > 2.0 * atr.iloc[i]: conf += 12; reasons.append("Strong selling move")
            else: reasons.append("Clear selling move")
            body = abs(df["close"].iloc[i] - df["open"].iloc[i])
            if rng > 0 and body / rng < 0.5: conf += 10; reasons.append("Clean starting candle")
            tested = 0; broken = False
            for k in range(i + 1, len(df)):
                if df["low"].iloc[k] <= zh and df["high"].iloc[k] >= zl:
                    tested += 1
                    if df["close"].iloc[k] > zh: broken = True; break
                    else: conf -= 10; reasons.append("Tested and held -10"); break
            if broken:
                flips.append(Zone(type="demand", high=zh, low=zl, index=i, confidence=62.0, reasons=["🔄 FLIP: Supply broken, now Demand"], timeframe=timeframe, symbol=symbol, tested=tested, is_fresh=False, is_flip=True))
                continue
            if tested == 0: conf += 12; reasons.append("🆕 FRESH - Never tested")
            elif tested == 1: conf += 2; reasons.append("Tested 1x - Still valid")
            else: conf -= 15; reasons.append(f"Tested {tested}x - WEAK")
            if conf >= min_confidence:
                zones.append(Zone(type="supply", high=zh, low=zl, index=i, confidence=conf, reasons=reasons, timeframe=timeframe, symbol=symbol, tested=tested, is_fresh=(tested == 0)))
    zones = zones + flips
    atr_val = float(atr.iloc[-1]) if len(atr) > 0 and not pd.isna(atr.iloc[-1]) else 0
    zones = filter_overlapping_zones(zones, atr_val)
    zones = sorted(zones, key=lambda z: z.index, reverse=True)[:6]
    return zones

def detect_fvg(df):
    df = normalize_df(df).reset_index(drop=True)
    fvgs = []
    for i in range(1, len(df) - 1):
        if df["low"].iloc[i + 1] > df["high"].iloc[i - 1]:
            fvgs.append(FVG(type="bullish", high=float(df["low"].iloc[i + 1]), low=float(df["high"].iloc[i - 1]), index=i))
        if df["high"].iloc[i + 1] < df["low"].iloc[i - 1]:
            fvgs.append(FVG(type="bearish", high=float(df["low"].iloc[i - 1]), low=float(df["high"].iloc[i + 1]), index=i))
    return fvgs[-3:]

def detect_liquidity(df):
    df = normalize_df(df).reset_index(drop=True)
    highs = df["high"].tail(30); lows = df["low"].tail(30)
    notes = []
    for i in range(len(highs) - 1):
        for j in range(i + 1, len(highs)):
            if abs(highs.iloc[i] - highs.iloc[j]) / highs.iloc[i] < 0.0015:
                notes.append(f"💧 Liquidity above ~{highs.iloc[j]:,.2f} (Equal Highs)"); break
        if notes and "above" in notes[-1]: break
    for i in range(len(lows) - 1):
        for j in range(i + 1, len(lows)):
            if abs(lows.iloc[i] - lows.iloc[j]) / lows.iloc[i] < 0.0015:
                notes.append(f"💧 Liquidity below ~{lows.iloc[j]:,.2f} (Equal Lows)"); break
        if len(notes) >= 2: break
    return notes[:2]

def get_session():
    h = datetime.datetime.utcnow().hour
    if 7 <= h < 12: return "🇬🇧 LONDON - BEST"
    if 12 <= h < 20: return "🇺🇸 NEW YORK - BEST"
    if 0 <= h < 7: return "🌏 ASIA - Slow"
    return "🌙 LATE NY - Careful"

def round_number_bonus(price, zone):
    for rn in [round(price / 100) * 100, round(price / 50) * 50]:
        if zone.low - (price * 0.005) <= rn <= zone.high + (price * 0.005):
            return f"🎯 Round Number {rn:,.0f} in zone"
    return None

def calc_rr(current, zone, zones, atr_val):
    if zone.type == "demand":
        entry = zone.high; sl = zone.low - atr_val * 0.2; risk = entry - sl
        tps = [z.low for z in zones if z.type == "supply" and z.low > current]
        tp = min(tps) if tps else entry + risk * 3
        rr = (tp - entry) / risk if risk > 0 else 0
        return entry, sl, tp, rr
    else:
        entry = zone.low; sl = zone.high + atr_val * 0.2; risk = sl - entry
        tps = [z.high for z in zones if z.type == "demand" and z.high < current]
        tp = max(tps) if tps else entry - risk * 3
        rr = (entry - tp) / risk if risk > 0 else 0
        return entry, sl, tp, rr

TWELVE_MAP = {"GC=F": "XAU/USD", "BTC-USD": "BTC/USD", "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY", "^DJI": "DJI", "^NDX": "NDX", "^GSPC": "SPX"}

def fetch_df(ticker, tf_key):
    _, _, display = TIMEFRAMES[tf_key]
    if TWELVE_KEY:
        try:
            symbol = TWELVE_MAP.get(ticker, ticker)
            interval_map = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1day", "1w": "1week"}
            interval = interval_map.get(tf_key, "1h")
            url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize=200&apikey={TWELVE_KEY}"
            r = requests.get(url, timeout=10).json()
            if "values" in r:
                df = pd.DataFrame(r["values"])
                df = df.rename(columns={"datetime": "date"})
                for c in ["open", "high", "low", "close"]:
                    df[c] = df[c].astype(float)
                df = df.iloc[::-1].reset_index(drop=True)
                if len(df) >= 40:
                    return normalize_df(df), display
            print(f"Twelve error: {r}")
        except Exception as e:
            print(f"Twelve failed: {e}")
    try:
        interval, period, _ = TIMEFRAMES[tf_key]
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
        if df is None or len(df) < 40: return None, display
        df = normalize_df(df)
        if display == "4H":
            df.index = pd.to_datetime(df.index)
            df = df.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index(drop=True)
        return df, display
    except Exception as e:
        print(f"Yahoo failed: {e}")
        return None, display

def get_market_thinking(df, zones):
    df = normalize_df(df)
    close = df["close"]; current = float(close.iloc[-1])
    ema50 = float(close.ewm(span=50).mean().iloc[-1])
    ema200 = float(close.ewm(span=200).mean().iloc[-1]) if len(close) >= 200 else ema50
    is_up = current > ema50; is_down = current < ema50
    if current > ema50 > ema200: trend = "🟢 STRONG UPTREND"; note = "Above EMA50 > EMA200"
    elif current > ema50: trend = "🟢 UPTREND"; note = "Above EMA50"
    elif current < ema50 < ema200: trend = "🔴 STRONG DOWNTREND"; note = "Below EMA50 < EMA200"
    elif current < ema50: trend = "🔴 DOWNTREND"; note = "Below EMA50"
    else: trend = "🟡 RANGING"; note = "Stuck at EMAs"
    inside = None; demand_below = None; d_dist = 999999; supply_above = None; s_dist = 999999; nearest = None; nd = 999999
    for z in zones:
        if z.low <= current <= z.high: inside = z
        d = abs(current - (z.high + z.low) / 2) / current * 100
        if d < nd: nd = d; nearest = z
        if z.type == "demand" and z.high < current:
            d2 = (current - z.high) / current * 100
            if d2 < d_dist: d_dist = d2; demand_below = z
        if z.type == "supply" and z.low > current:
            d2 = (z.low - current) / current * 100
            if d2 < s_dist: s_dist = d2; supply_above = z
    actionable = inside; adist = 0 if inside else nd
    if not actionable:
        if is_down and supply_above: actionable = supply_above; adist = s_dist
        elif is_up and demand_below: actionable = demand_below; adist = d_dist
        else: actionable = nearest; adist = nd
    if inside:
        if inside.type == "demand": bias = "🟢 BUYS - INSIDE Demand"; plan = f"SL Below {inside.low:,.2f}"
        else: bias = "🔴 SELLS - INSIDE Supply"; plan = f"SL Above {inside.high:,.2f}"
    elif actionable and actionable.type == "demand":
        bias = "⏳ WAIT PULLBACK TO BUY" if current > actionable.high else "👀 APPROACHING DEMAND FROM BELOW"
        plan = f"Wait {actionable.low:,.2f}-{actionable.high:,.2f} ({adist:.2f}% away)"
    elif actionable and actionable.type == "supply":
        bias = "⏳ WAIT RALLY TO SELL" if current < actionable.low else "👀 APPROACHING SUPPLY FROM ABOVE"
        plan = f"Wait {actionable.low:,.2f}-{actionable.high:,.2f} ({adist:.2f}% away)"
    else: bias = "🟡 NO SETUP"; plan = "Patience is a trade."
    return trend, note, bias, plan, actionable, adist, inside

def build_analysis(symbol_key, tf_key):
    ticker = SYMBOLS.get(symbol_key.upper())
    if not ticker: return f"Unknown {symbol_key}"
    tf_key = norm_tf(tf_key)
    df, display = fetch_df(ticker, tf_key)
    if df is None: return f"Not enough data for {symbol_key} on {display} - Try again in 30 sec"
    zones = detect_zones(df, symbol=symbol_key.upper(), timeframe=display)
    if not zones: return f"No high-quality zones for {symbol_key} on {display}"
    current = float(df["close"].iloc[-1])
    atr_val = float(calculate_atr(df).iloc[-1])
    trend, note, bias, plan, best, best_dist, inside = get_market_thinking(df, zones)
    fvgs = detect_fvg(df); liq = detect_liquidity(df)
    entry, sl, tp, rr = calc_rr(current, best, zones, atr_val)
    rr_verdict = "✅ TAKE IT - R:R >= 1:2" if rr >= 2 else "❌ SKIP - R:R too low"
    rn = round_number_bonus(current, best)
    htf_warn = ""
    if tf_key == "1h":
        try:
            df4, _ = fetch_df(ticker, "4h")
            if df4 is not None:
                zones4 = detect_zones(df4, symbol=symbol_key.upper(), timeframe="4H")
                for z4 in zones4:
                    if z4.type != best.type and z4.low <= (best.high + best.low) / 2 <= z4.high:
                        htf_warn = f"\n⚠️ HTF WARNING: Your {best.type} zone is INSIDE a 4H {z4.type} zone {z4.low:,.2f}-{z4.high:,.2f} - Low probability!"
        except: pass
    JOURNAL.append({"symbol": symbol_key.upper(), "tf": display, "bias": bias, "price": current, "best": f"{best.low:,.2f}-{best.high:,.2f}", "rr": round(rr, 2), "time": datetime.datetime.utcnow().strftime("%H:%M")})
    if len(JOURNAL) > 20: JOURNAL.pop(0)
    msg = f"🧠 {symbol_key.upper()} - {display} PRO Analysis\nPrice: {current:,.2f} | Session: {get_session()}\n\n📈 TREND: {trend}\n{note}\n\n🎯 BIAS: {bias}\n📋 {plan}\n\n🏆 BEST ZONE: {'🟢 DEMAND' if best.type == 'demand' else '🔴 SUPPLY'} {best.low:,.2f} - {best.high:,.2f} | {best.confidence:.0f}% | {'🆕 FRESH' if best.is_fresh else f'Tested {best.tested}x'} {'| 🔄 FLIP' if best.is_flip else ''} | {best_dist:.2f}% away{htf_warn}\n"
    if rn: msg += f"{rn}\n"
    msg += f"\n💰 TRADE MATH:\nEntry: {entry:,.2f}\nSL: {sl:,.2f}\nTP: {tp:,.2f}\nR:R = 1:{rr:.1f}\n{rr_verdict}\n"
    if fvgs:
        msg += "\n⚡ FVG:\n"
        for f in fvgs: msg += f"{'🟢 Bullish' if f.type == 'bullish' else '🔴 Bearish'} {f.low:,.2f} - {f.high:,.2f}\n"
    if liq: msg += f"\n{chr(10).join(liq)}\n"
    msg += "\n--- ALL ZONES ---\n"
    for z in zones:
        emoji = "🟢 DEMAND" if z.type == "demand" else "🔴 SUPPLY"
        dist = abs(current - (z.high + z.low) / 2) / current * 100
        fresh = "🆕 FRESH" if z.is_fresh else f"Tested {z.tested}x"
        flip = " | 🔄 FLIP" if z.is_flip else ""
        tag = " ← PRICE HERE" if inside == z else ""
        star = " ⭐ BEST" if z == best else ""
        msg += f"{emoji} {z.low:,.2f}-{z.high:,.2f} | {z.confidence:.0f}% | {fresh}{flip} | {dist:.2f}% away{tag}{star}\n"
    msg += "\n⚠️ Not financial advice. No trade 30min before NFP / CPI / FOMC."
    return msg

def get_confluence(symbol_key):
    results = {}
    for tf in ["15m", "1h", "4h", "1d"]:
        ticker = SYMBOLS.get(symbol_key.upper())
        df, disp = fetch_df(ticker, tf)
        if df is None: continue
        zones = detect_zones(df, symbol=symbol_key.upper(), timeframe=disp)
        if not zones: continue
        trend, _, bias, _, best, _, _ = get_market_thinking(df, zones)
        results[tf] = (trend, bias, best)
    if not results: return "No data - Try again"
    bull = sum(1 for v in results.values() if "UPTREND" in v[0] or "BUY" in v[1])
    bear = sum(1 for v in results.values() if "DOWNTREND" in v[0] or "SELL" in v[1])
    if bull >= 3: verdict = "🟢🟢🟢 STRONG CONFLUENCE BULLISH"
    elif bear >= 3: verdict = "🔴🔴🔴 STRONG CONFLUENCE BEARISH"
    elif bull == 2 and bear == 2: verdict = "🟡 CONFLICT 2 vs 2 - DO NOT TRADE"
    else: verdict = f"🟡 MIXED: {bull} Bull / {bear} Bear"
    msg = f"🌐 {symbol_key.upper()} CONFLUENCE\n{verdict}\n\n"
    for tf, (trend, bias, best) in results.items():
        msg += f"{tf.upper()}: {trend} | {bias}\nBest: {'🟢' if best.type == 'demand' else '🔴'} {best.low:,.2f}-{best.high:,.2f} ({best.confidence:.0f}%)\n\n"
    return msg

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_STATE[update.effective_user.id] = "GOLD"
    await update.message.reply_text("👋 PRO Pivot Bot - TWELVE DATA FAST ⚡\n\n1️⃣ Pick Symbol (Row 1)\n2️⃣ Pick Timeframe (Row 2)\nAll buttons together below 👇", reply_markup=main_keyboard())

async def zones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Tap a button 👇", reply_markup=main_keyboard()); return
        symbol = context.args[0].upper()
        tf = context.args[1].lower() if len(context.args) > 1 else "1h"
        USER_STATE[update.effective_user.id] = symbol
        await update.message.reply_text(f"🧠 Thinking {symbol} {tf.upper()}...")
        text = get_confluence(symbol) if tf == "all" else build_analysis(symbol, tf)
        await update.message.reply_text(text, reply_markup=main_keyboard())
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}", reply_markup=main_keyboard())

async def alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /alert GOLD 3511", reply_markup=main_keyboard()); return
    symbol = context.args[0].upper()
    try: price = float(context.args[1])
    except: await update.message.reply_text("Price must be a number"); return
    ALERTS.setdefault(update.effective_user.id, []).append({"symbol": symbol, "price": price})
    await update.message.reply_text(f"🔔 Alert set for {symbol} at {price:,.2f}", reply_markup=main_keyboard())

async def alerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lst = ALERTS.get(update.effective_user.id, [])
    if not lst:
        await update.message.reply_text("No alerts. /alert GOLD 3511", reply_markup=main_keyboard()); return
    msg = "🔔 Alerts:\n" + "\n".join([f"{a['symbol']} at {a['price']:,.2f}" for a in lst])
    await update.message.reply_text(msg, reply_markup=main_keyboard())

async def score_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not JOURNAL:
        await update.message.reply_text("📓 No trades yet. Tap GOLD -> 1h first.", reply_markup=main_keyboard()); return
    msg = "📓 JOURNAL:\n\n"
    for j in JOURNAL[-10:]:
        msg += f"{j['time']} | {j['symbol']} {j['tf']} | {j['bias'][:30]} | {j['price']:,.2f} | R:R 1:{j['rr']}\n"
    msg += f"\n✅ Good R:R: {sum(1 for j in JOURNAL if j['rr'] >= 2)}/{len(JOURNAL)}"
    await update.message.reply_text(msg, reply_markup=main_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Working...")
    uid = query.from_user.id
    data = query.data
    sym = USER_STATE.get(uid, "GOLD")
    try:
        if data.startswith("sym:"):
            sym = data.split(":")[1]
            USER_STATE[uid] = sym
            try: await query.edit_message_text(f"✅ Selected {sym}\nNow pick timeframe 👇", reply_markup=main_keyboard())
            except: pass
            return
        if data.startswith("tf:"):
            tf = data.split(":")[1]
            await context.bot.send_message(chat_id=uid, text=f"🧠 Thinking {sym} {tf.upper()}...")
            text = get_confluence(sym) if tf == "all" else build_analysis(sym, tf)
            await context.bot.send_message(chat_id=uid, text=text, reply_markup=main_keyboard())
            return
        if data == "action:score":
            if not JOURNAL:
                await context.bot.send_message(chat_id=uid, text="📓 No trades yet.", reply_markup=main_keyboard()); return
            msg = "📓 JOURNAL:\n\n"
            for j in JOURNAL[-10:]:
                msg += f"{j['time']} | {j['symbol']} {j['tf']} | {j['bias'][:30]} | R:R 1:{j['rr']}\n"
            await context.bot.send_message(chat_id=uid, text=msg, reply_markup=main_keyboard()); return
        if data == "action:alert_help":
            await context.bot.send_message(chat_id=uid, text=f"Type:\n/alert {sym} 3511", reply_markup=main_keyboard()); return
        if data == "action:refresh":
            await context.bot.send_message(chat_id=uid, text=build_analysis(sym, "1h"), reply_markup=main_keyboard()); return
    except Exception as e:
        print(f"BUTTON ERROR: {e}")
        await context.bot.send_message(chat_id=uid, text=f"⚠️ Bot error: {e}\nTry again in 30 sec.", reply_markup=main_keyboard())

async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    for uid, lst in list(ALERTS.items()):
        rem = []
        for a in lst:
            ticker = SYMBOLS.get(a["symbol"])
            if not ticker: continue
            try:
                df, _ = fetch_df(ticker, "15m")
                if df is None: rem.append(a); continue
                cur = float(normalize_df(df)["close"].iloc[-1])
                if abs(cur - a["price"]) / a["price"] < 0.002:
                    await context.bot.send_message(chat_id=uid, text=f"🚨 {a['symbol']} hit {a['price']:,.2f} (Now {cur:,.2f})", reply_markup=main_keyboard())
                else: rem.append(a)
            except: rem.append(a)
        ALERTS[uid] = rem

def main():
    if not BOT_TOKEN:
        print("ERROR BOT_TOKEN"); return
    print("Bot is running TWELVE...")
    app_bot = ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("zones", zones_cmd))
    app_bot.add_handler(CommandHandler("alert", alert_cmd))
    app_bot.add_handler(CommandHandler("alerts", alerts_cmd))
    app_bot.add_handler(CommandHandler("score", score_cmd))
    app_bot.add_handler(CallbackQueryHandler(button_handler))
    if app_bot.job_queue:
        app_bot.job_queue.run_repeating(check_alerts, interval=300, first=10)
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
