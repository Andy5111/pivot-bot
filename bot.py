"""
FINAL BOT - TWELVE DATA VERSION - FAST, NEVER BLOCKS
+ CORE LOGIC - PURE SUPPLY / DEMAND PULLBACK - MULTI-TF
1. Best Zone = Pullback Only (Demand below / Supply above)
2. TP Never Empty (FVG -> Next Zone -> Liquidity -> Round Number)
3. One Distance Everywhere (Price to Entry Edge)
4. Two TPs (TP1 + TP2)
5. Confluence Bonus (+10)
6. Clean Multi-TF Display (5m, 15m, 30m, 1h, 4h - 1 Quality Zone Each)
7. SL = Zone Broken
NO BREAKOUT. NO CEILING. NO FLOOR.
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
        [InlineKeyboardButton("5m", callback_data="tf:5m"),
         InlineKeyboardButton("15m", callback_data="tf:15m"),
         InlineKeyboardButton("30m", callback_data="tf:30m"),
         InlineKeyboardButton("1h", callback_data="tf:1h"),
         InlineKeyboardButton("4h", callback_data="tf:4h"),
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
    min_gap = 1.0 * atr_val if atr_val else 0
    for z in zones:
        too_close = False
        for kept in filtered:
            if z.low <= kept.high and kept.low <= z.high:
                gap = 0
            elif z.low > kept.high:
                gap = z.low - kept.high
            else:
                gap = kept.low - z.high
            if gap < min_gap:
                too_close = True
                break
        if not too_close:
            filtered.append(z)
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

# FIXED: Only if REALLY inside zone, no 0.5% tolerance
def round_number_bonus(price, zone):
    for rn in [round(price / 100) * 100, round(price / 50) * 50]:
        if zone.low <= rn <= zone.high:
            return f"🎯 Round Number {rn:,.0f} in zone"
    return None

# --- ONE DISTANCE EVERYWHERE ---
def distance_to_entry(current, zone):
    if zone.low <= current <= zone.high:
        return 0.0
    if zone.type == "demand":
        return abs(current - zone.high) / current * 100
    else:
        return abs(current - zone.low) / current * 100

def entry_edge(zone):
    return zone.high if zone.type == "demand" else zone.low

# --- CONFLUENCE BONUS ---
def confluence_bonus(zone, fvgs, current, htf_zones):
    hits = 0
    labels = []
    for f in (fvgs or []):
        if not (f.high < zone.low or f.low > zone.high):
            hits += 1; labels.append("FVG"); break
    rn = round_number_bonus(current, zone)
    if rn:
        hits += 1; labels.append("Round Number")
    for z4 in (htf_zones or []):
        if not (z4.high < zone.low or z4.low > zone.high):
            hits += 1; labels.append("HTF Overlap"); break
    if hits >= 2:
        return 10.0, labels
    return 0.0, labels

# --- BEST ZONE = PULLBACK ONLY ---
# Main Trade ONLY from:
# - Demand BELOW price (BUY pullback)
# - Supply ABOVE price (SELL rally)
# - Inside zone = valid
# Demand ABOVE / Supply BELOW are NEVER best. They are ignored for main trade.
def pick_best_zone(zones, current, fvgs, htf_zones):
    pullback = []
    for z in zones:
        if z.type == "demand" and z.high < current:
            pullback.append(z)
        elif z.type == "supply" and z.low > current:
            pullback.append(z)
        elif z.low <= current <= z.high:
            pullback.append(z)
    candidates = pullback if pullback else zones
    best = None; best_score = -9999; best_bonus = 0; best_labels = []
    for z in candidates:
        bonus, labels = confluence_bonus(z, fvgs, current, htf_zones)
        adj_conf = min(95.0, z.confidence + bonus)
        dist = distance_to_entry(current, z)
        score = adj_conf - (dist * 5)
        if score > best_score:
            best_score = score; best = z; best_bonus = bonus; best_labels = labels
    return best, best_score, best_bonus, best_labels

# --- TP NEVER EMPTY + TWO TPs + SL = ZONE BROKEN ---
def calc_trade_plan(current, zone, zones, fvgs, liq_notes, atr_val):
    is_buy = (zone.type == "demand")
    entry = zone.high if is_buy else zone.low
    # SL = Zone broken: just beyond zone + small ATR buffer
    sl = zone.low - atr_val * 0.2 if is_buy else zone.high + atr_val * 0.2
    risk = abs(entry - sl) if abs(entry - sl) > 0 else atr_val * 0.5
    liq_levels = []
    for n in (liq_notes or []):
        try:
            part = n.split("~")[1].split(" ")[0].replace(",", "")
            liq_levels.append(float(part))
        except: pass
    def next_round_number(price, direction):
        if direction > 0:
            for step in [50, 100]:
                rn = (int(price // step) + 1) * step
                if abs(rn - price) / price > 0.001:
                    return float(rn)
            return price * 1.01
        else:
            for step in [50, 100]:
                rn = (int(price // step)) * step
                if abs(rn - price) / price > 0.001:
                    return float(rn)
            return price * 0.99
    tp1 = None; tp1_label = ""
    if is_buy:
        fvg_above = sorted([f for f in (fvgs or []) if f.type == "bullish" and f.low > entry], key=lambda f: f.low)
        if fvg_above:
            tp1 = fvg_above[0].low; tp1_label = "FVG"
        else:
            sup_above = sorted([z for z in zones if z.type == "supply" and z.low > entry], key=lambda z: z.low)
            if sup_above:
                tp1 = sup_above[0].low; tp1_label = "Next Supply"
    else:
        fvg_below = sorted([f for f in (fvgs or []) if f.type == "bearish" and f.high < entry], key=lambda f: f.high, reverse=True)
        if fvg_below:
            tp1 = fvg_below[0].high; tp1_label = "FVG"
        else:
            dem_below = sorted([z for z in zones if z.type == "demand" and z.high < entry], key=lambda z: z.high, reverse=True)
            if dem_below:
                tp1 = dem_below[0].high; tp1_label = "Next Demand"
    if tp1 is None:
        if is_buy:
            liq_above = [x for x in liq_levels if x > entry]
            if liq_above:
                tp1 = min(liq_above); tp1_label = "Liquidity"
            else:
                tp1 = next_round_number(entry, 1); tp1_label = "Round Number"
        else:
            liq_below = [x for x in liq_levels if x < entry]
            if liq_below:
                tp1 = max(liq_below); tp1_label = "Liquidity"
            else:
                tp1 = next_round_number(entry, -1); tp1_label = "Round Number"
    tp2 = None; tp2_label = ""
    if is_buy:
        sup_above = sorted([z for z in zones if z.type == "supply" and z.low > entry], key=lambda z: z.low)
        if tp1_label == "Next Supply" and len(sup_above) >= 2:
            tp2 = sup_above[1].low; tp2_label = "Next Supply 2"
        elif sup_above:
            tp2 = sup_above[0].low; tp2_label = "Next Supply"
        else:
            liq_above = [x for x in liq_levels if x > entry and abs(x - tp1) / entry > 0.002]
            if liq_above:
                tp2 = min(liq_above); tp2_label = "Liquidity"
            else:
                tp2 = next_round_number(tp1, 1); tp2_label = "Round Number"
    else:
        dem_below = sorted([z for z in zones if z.type == "demand" and z.high < entry], key=lambda z: z.high, reverse=True)
        if tp1_label == "Next Demand" and len(dem_below) >= 2:
            tp2 = dem_below[1].high; tp2_label = "Next Demand 2"
        elif dem_below:
            tp2 = dem_below[0].high; tp2_label = "Next Demand"
        else:
            liq_below = [x for x in liq_levels if x < entry and abs(x - tp1) / entry > 0.002]
            if liq_below:
                tp2 = max(liq_below); tp2_label = "Liquidity"
            else:
                tp2 = next_round_number(tp1, -1); tp2_label = "Round Number"
    if is_buy and tp2 <= tp1:
        tp2 = tp1 + max(atr_val * 0.5, abs(tp1 - entry) * 0.5); tp2_label = "ATR Extension"
    if (not is_buy) and tp2 >= tp1:
        tp2 = tp1 - max(atr_val * 0.5, abs(entry - tp1) * 0.5); tp2_label = "ATR Extension"
    rr1 = abs(tp1 - entry) / risk if risk > 0 else 0
    rr2 = abs(tp2 - entry) / risk if risk > 0 else 0
    return entry, sl, tp1, tp1_label, tp2, tp2_label, rr1, rr2

def confidence_verdict(conf):
    if conf >= 75:
        return "✅ HIGH Confidence - Take it"
    if conf >= 65:
        return "⚠️ MEDIUM Confidence - Manage size"
    return "❌ LOW Confidence - Wait for better zone"

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
    if current > ema50 > ema200: trend = "🟢 STRONG UPTREND"; note = "Above EMA50 > EMA200"
    elif current > ema50: trend = "🟢 UPTREND"; note = "Above EMA50"
    elif current < ema50 < ema200: trend = "🔴 STRONG DOWNTREND"; note = "Below EMA50 < EMA200"
    elif current < ema50: trend = "🔴 DOWNTREND"; note = "Below EMA50"
    else: trend = "🟡 RANGING"; note = "Stuck at EMAs"
    inside = None
    for z in zones:
        if z.low <= current <= z.high: inside = z
    if inside:
        if inside.type == "demand": bias = "🟢 BUYS - INSIDE Demand"; plan = f"SL Below {inside.low:,.2f}"
        else: bias = "🔴 SELLS - INSIDE Supply"; plan = f"SL Above {inside.high:,.2f}"
    else:
        bias = "🟡 NO SETUP"; plan = "Patience is a trade."
    return trend, note, bias, plan, inside

# --- NEW: Build one TF block for MULTI-TF view ---
def build_tf_block(symbol_key, tf_key):
    ticker = SYMBOLS.get(symbol_key.upper())
    df, display = fetch_df(ticker, tf_key)
    if df is None:
        return f"🕐 {display} — No data\n"
    zones = detect_zones(df, symbol=symbol_key.upper(), timeframe=display)
    if not zones:
        return f"🕐 {display} — No quality zone\n"
    current = float(df["close"].iloc[-1])
    atr_val = float(calculate_atr(df).iloc[-1])
    fvgs = detect_fvg(df); liq = detect_liquidity(df)
    # HTF zones for confluence: for 1h use 4h, for others use 1h
    htf_zones = []
    try:
        if tf_key in ["5m", "15m", "30m", "1h"]:
            df_htf, _ = fetch_df(ticker, "4h" if tf_key == "1h" else "1h")
            if df_htf is not None:
                htf_zones = detect_zones(df_htf, symbol=symbol_key.upper(), timeframe="HTF")
    except: pass
    best, _, best_bonus, best_labels = pick_best_zone(zones, current, fvgs, htf_zones)
    best_conf = min(95.0, best.confidence + best_bonus)
    best_dist = distance_to_entry(current, best)
    entry, sl, tp1, tp1_label, tp2, tp2_label, rr1, rr2 = calc_trade_plan(current, best, zones, fvgs, liq, atr_val)
    inside = best.low <= current <= best.high
    if inside:
        action = "🟢 INSIDE - Entry Now" if best.type == "demand" else "🔴 INSIDE - Entry Now"
    elif best.type == "demand":
        action = "⏳ WAIT PULLBACK TO BUY"
    else:
        action = "⏳ WAIT RALLY TO SELL"
    emoji = "🟢 DEMAND" if best.type == "demand" else "🔴 SUPPLY"
    block = f"🕐 {display} — {emoji} {best.low:,.2f} - {best.high:,.2f} | {best_conf:.0f}% | {best_dist:.2f}% away"
    if best.is_flip: block += " | 🔄 FLIP"
    if best_bonus > 0: block += f" | ✨ +{best_bonus:.0f} ({' + '.join(best_labels)})"
    block += f"\n{action}\n"
    block += f"Entry: {entry:,.2f} | SL: {sl:,.2f} (Zone Broken) | TP1: {tp1:,.2f} ({tp1_label}) | TP2: {tp2:,.2f} ({tp2_label}) | R:R 1:{rr2:.1f}\n"
    return block

# --- NEW: MULTI-TF ANALYSIS - 5m, 15m, 30m, 1h, 4h ---
def build_all_tf_analysis(symbol_key):
    ticker = SYMBOLS.get(symbol_key.upper())
    if not ticker: return f"Unknown {symbol_key}"
    # Get price from 1h for header
    df1, _ = fetch_df(ticker, "1h")
    if df1 is None:
        return f"Not enough data for {symbol_key} - Try again in 30 sec"
    current = float(df1["close"].iloc[-1])
    trend, note, _, _, _ = get_market_thinking(df1, detect_zones(df1, symbol=symbol_key.upper(), timeframe="1H"))
    line = "━━━━━━━━━━━━━━━━━━"
    msg = f"🧠 {symbol_key.upper()} | Price: {current:,.2f} | {get_session()}\n"
    msg += f"{trend} — {note}\n"
    msg += f"{line}\n\n"
    for tf in ["5m", "15m", "30m", "1h", "4h"]:
        msg += build_tf_block(symbol_key, tf)
        msg += f"\n{line}\n\n"
    msg += "⚡ FVG + 💧 Liquidity are inside each TF calculation (Confluence Bonus).\n"
    msg += "⚠️ Not financial advice. No trade 30min before NFP / CPI / FOMC."
    return msg

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
    fvgs = detect_fvg(df); liq = detect_liquidity(df)
    htf_zones = []
    htf_warn = ""
    if tf_key == "1h":
        try:
            df4, _ = fetch_df(ticker, "4h")
            if df4 is not None:
                htf_zones = detect_zones(df4, symbol=symbol_key.upper(), timeframe="4H")
        except: pass
    best, best_score, best_bonus, best_labels = pick_best_zone(zones, current, fvgs, htf_zones)
    best_conf = min(95.0, best.confidence + best_bonus)
    best_dist = distance_to_entry(current, best)
    trend, note, _, _, inside = get_market_thinking(df, zones)
    # CLEAN PULLBACK ONLY BIAS - NO BREAKOUT
    if inside is not None and inside == best:
        if best.type == "demand": bias = "🟢 BUYS - INSIDE Demand"; plan = f"Entry now - SL Below {best.low:,.2f} (Zone Broken)"
        else: bias = "🔴 SELLS - INSIDE Supply"; plan = f"Entry now - SL Above {best.high:,.2f} (Zone Broken)"
    elif best.type == "demand":
        bias = "⏳ WAIT PULLBACK TO BUY"; plan = f"Wait {best.low:,.2f}-{best.high:,.2f} ({best_dist:.2f}% away)"
    else:
        bias = "⏳ WAIT RALLY TO SELL"; plan = f"Wait {best.low:,.2f}-{best.high:,.2f} ({best_dist:.2f}% away)"
    if htf_zones:
        for z4 in htf_zones:
            if z4.type != best.type and z4.low <= (best.high + best.low) / 2 <= z4.high:
                htf_warn = f"\n⚠️ HTF WARNING: Your {best.type} zone is INSIDE a 4H {z4.type} zone {z4.low:,.2f}-{z4.high:,.2f} - Low probability!"
    entry, sl, tp1, tp1_label, tp2, tp2_label, rr1, rr2 = calc_trade_plan(current, best, zones, fvgs, liq, atr_val)
    conf_verdict = confidence_verdict(best_conf)
    rn = round_number_bonus(current, best)
    JOURNAL.append({"symbol": symbol_key.upper(), "tf": display, "bias": bias, "price": current, "best": f"{best.low:,.2f}-{best.high:,.2f}", "conf": round(best_conf), "rr": round(rr2, 2), "time": datetime.datetime.utcnow().strftime("%H:%M")})
    if len(JOURNAL) > 20: JOURNAL.pop(0)
    trend_emoji = "🟢" if "UPTREND" in trend else ("🔴" if "DOWNTREND" in trend else "🟡")
    line = "━━━━━━━━━━━━━━━━━━"
    msg = f"🧠 {symbol_key.upper()} | {display} | {trend_emoji} {trend}\n"
    msg += f"💰 Price: {current:,.2f} | {get_session()}\n"
    msg += f"{line}\n\n"
    msg += f"🎯 BIAS\n{bias}\n📋 {plan}\n"
    msg += f"\n{line}\n"
    msg += f"🏆 BEST ZONE\n"
    msg += f"{'🟢 DEMAND' if best.type == 'demand' else '🔴 SUPPLY'} {best.low:,.2f} - {best.high:,.2f}\n"
    msg += f"⭐ {best_conf:.0f}% | {'🆕 FRESH' if best.is_fresh else f'Tested {best.tested}x'} | {best_dist:.2f}% away"
    if best.is_flip: msg += " | 🔄 FLIP"
    msg += "\n"
    if best_bonus > 0:
        msg += f"✨ Confluence +{best_bonus:.0f} ({' + '.join(best_labels)})\n"
    if rn: msg += f"{rn}\n"
    if htf_warn: msg += f"{htf_warn}\n"
    msg += f"\n{line}\n"
    msg += f"💰 TRADE PLAN\n"
    msg += f"Entry: {entry:,.2f}\n"
    sl_pct = abs(entry - sl) / entry * 100 if entry else 0
    msg += f"SL:    {sl:,.2f}  (-{sl_pct:.2f}%) ← Zone Broken\n"
    msg += f"TP1:   {tp1:,.2f}  (+{abs(tp1-entry)/entry*100:.2f}%) ← {tp1_label} - Take partial, SL to BE\n"
    msg += f"TP2:   {tp2:,.2f}  (+{abs(tp2-entry)/entry*100:.2f}%) ← {tp2_label} - Let rest run\n"
    msg += f"R:R TP1 = 1:{rr1:.1f} | TP2 = 1:{rr2:.1f}\n"
    msg += f"Ver:   {conf_verdict}\n"
    msg += f"\n{line}\n"
    msg += f"⚡ FVG / 💧 LIQUIDITY\n"
    if fvgs:
        for f in fvgs: msg += f"{'🟢 Bullish' if f.type == 'bullish' else '🔴 Bearish'} {f.low:,.2f} - {f.high:,.2f}\n"
    else:
        msg += "No recent FVG\n"
    if liq: msg += f"{chr(10).join(liq)}\n"
    msg += f"\n{line}\n"
    msg += f"📋 ALL ZONES\n"
    for z in zones:
        emoji = "🟢" if z.type == "demand" else "🔴"
        dist = distance_to_entry(current, z)
        tag = " ← PRICE HERE" if inside == z else ""
        star = " ⭐ BEST" if z == best else ""
        msg += f"{emoji} {z.low:,.2f}-{z.high:,.2f} | {min(95.0, z.confidence + confluence_bonus(z, fvgs, current, htf_zones)[0]):.0f}% | {dist:.2f}% away{tag}{star}\n"
    msg += f"\n{line}\n"
    msg += "⚠️ Not financial advice. No trade 30min before NFP / CPI / FOMC."
    return msg

def get_confluence(symbol_key):
    # Now = Multi-TF Clean View
    return build_all_tf_analysis(symbol_key)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USER_STATE[update.effective_user.id] = "GOLD"
    await update.message.reply_text("👋 PRO Pivot Bot - TWELVE DATA FAST ⚡\n\n1️⃣ Pick Symbol (Row 1)\n2️⃣ Pick Timeframe (Row 2)\n🌐 ALL = 5m + 15m + 30m + 1h + 4h zones together 👇", reply_markup=main_keyboard())

async def zones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not context.args:
            await update.message.reply_text("Tap a button 👇", reply_markup=main_keyboard()); return
        symbol = context.args[0].upper()
        tf = context.args[1].lower() if len(context.args) > 1 else "1h"
        USER_STATE[update.effective_user.id] = symbol
        await update.message.reply_text(f"🧠 Thinking {symbol} {tf.upper()}...")
        text = build_all_tf_analysis(symbol) if tf == "all" else build_analysis(symbol, tf)
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
        msg += f"{j['time']} | {j['symbol']} {j['tf']} | {j['bias'][:30]} | {j['price']:,.2f} | Conf {j['conf']}% | R:R 1:{j['rr']}\n"
    msg += f"\n✅ High Confidence: {sum(1 for j in JOURNAL if j['conf'] >= 75)}/{len(JOURNAL)}"
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
            text = build_all_tf_analysis(sym) if tf == "all" else build_analysis(sym, tf)
            await context.bot.send_message(chat_id=uid, text=text, reply_markup=main_keyboard())
            return
        if data == "action:score":
            if not JOURNAL:
                await context.bot.send_message(chat_id=uid, text="📓 No trades yet.", reply_markup=main_keyboard()); return
            msg = "📓 JOURNAL:\n\n"
            for j in JOURNAL[-10:]:
                msg += f"{j['time']} | {j['symbol']} {j['tf']} | {j['bias'][:30]} | Conf {j['conf']}%\n"
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
