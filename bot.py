"""
PIVOT ZONE BOT - PRO 30YR TRADER EDITION - ALL FEATURES
/zones GOLD 1h | /zones GOLD all | /alert GOLD 3511 | /alerts | /score
"""
from dataclasses import dataclass, field
from typing import List, Dict
import os, threading, datetime

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
    tested: int = 0
    is_fresh: bool = True
    is_flip: bool = False

@dataclass
class FVG:
    type: str
    high: float
    low: float
    index: int

# --- MEMORY: Alerts + Journal ---
ALERTS: Dict[int, List[dict]] = {}
JOURNAL: List[dict] = []

SYMBOLS = {
    "GOLD": "GC=F", "XAUUSD": "GC=F", "XAU": "GC=F",
    "BTC": "BTC-USD", "BITCOIN": "BTC-USD",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "US30": "^DJI", "NAS100": "^NDX", "SPX500": "^GSPC",
}
TIMEFRAMES = {
    "5m": ("5m", "2d", "5M"), "15m": ("15m", "5d", "15M"),
    "30m": ("30m", "5d", "30M"), "1h": ("1h", "10d", "1H"),
    "4h": ("1h", "1mo", "4H"), "1d": ("1d", "3mo", "1D"), "1w": ("1wk", "1y", "1W"),
}
def norm_tf(t):
    t = t.lower().replace("m15","15m").replace("h1","1h").replace("h4","4h").replace("d1","1d")
    return t if t in TIMEFRAMES else "1h"

def normalize_df(df):
    df = df.copy()
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.columns = [str(c).lower().strip() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    return df

def calculate_atr(df, period=14):
    df = normalize_df(df)
    tr = pd.concat([df["high"]-df["low"], abs(df["high"]-df["close"].shift(1)), abs(df["low"]-df["close"].shift(1))], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def is_strong_up(df, start, atr):
    if start+2 >= len(df): return False
    total=0; cnt=0
    for j in range(start, min(start+4, len(df))):
        body=df["close"].iloc[j]-df["open"].iloc[j]
        rng=df["high"].iloc[j]-df["low"].iloc[j]
        if body>0 and body>0.45*atr.iloc[j] and rng>0.7*atr.iloc[j]:
            cnt+=1; total+=body
        else: break
    return cnt>=2 and total>1.6*atr.iloc[start]

def is_strong_down(df, start, atr):
    if start+2 >= len(df): return False
    total=0; cnt=0
    for j in range(start, min(start+4, len(df))):
        body=df["open"].iloc[j]-df["close"].iloc[j]
        rng=df["high"].iloc[j]-df["low"].iloc[j]
        if body>0 and body>0.45*atr.iloc[j] and rng>0.7*atr.iloc[j]:
            cnt+=1; total+=body
        else: break
    return cnt>=2 and total>1.6*atr.iloc[start]

def detect_zones(df, symbol="UNKNOWN", timeframe="1H", lookback=120, min_confidence=55.0):
    df = normalize_df(df)
    if len(df)<40: return []
    df = df.copy().reset_index(drop=True)
    atr = calculate_atr(df)
    zones=[]
    start=max(14, len(df)-lookback)
    for i in range(start, len(df)-4):
        if pd.isna(atr.iloc[i]) or atr.iloc[i]==0: continue
        # DEMAND
        if is_strong_up(df, i+1, atr):
            zh=float(df["high"].iloc[i]); zl=float(df["low"].iloc[i])
            conf=52.0; reasons=[]
            move=df["close"].iloc[min(i+3,len(df)-1)]-df["open"].iloc[i+1]
            if move>2.8*atr.iloc[i]: conf+=18; reasons.append("Very strong buying move")
            elif move>2.0*atr.iloc[i]: conf+=12; reasons.append("Strong buying move")
            else: reasons.append("Clear buying move")
            body=abs(df["close"].iloc[i]-df["open"].iloc[i]); rng=zh-zl
            if rng>0 and body/rng<0.5: conf+=10; reasons.append("Clean starting candle")
            # FRESH vs TESTED + FLIP check
            tested=0; broken=False
            for k in range(i+1, len(df)):
                if df["low"].iloc[k] <= zh and df["high"].iloc[k] >= zl: tested+=1
                if df["close"].iloc[k] < zl: broken=True; break
            if tested==0: conf+=12; reasons.append("🆕 FRESH - Never tested")
            elif tested==1: conf+=2; reasons.append("Tested 1x - Still valid")
            else: conf-=15; reasons.append(f"Tested {tested}x - WEAK")
            if broken: conf-=10; reasons.append("⚠️ FLIP RISK - Was broken once")
            if conf>=min_confidence:
                zones.append(Zone(type="demand",high=zh,low=zl,index=i,confidence=conf,reasons=reasons,timeframe=timeframe,symbol=symbol,tested=tested,is_fresh=(tested==0),is_flip=broken))
        # SUPPLY
        if is_strong_down(df, i+1, atr):
            zh=float(df["high"].iloc[i]); zl=float(df["low"].iloc[i])
            conf=52.0; reasons=[]
            move=df["open"].iloc[i+1]-df["close"].iloc[min(i+3,len(df)-1)]
            if move>2.8*atr.iloc[i]: conf+=18; reasons.append("Very strong selling move")
            elif move>2.0*atr.iloc[i]: conf+=12; reasons.append("Strong selling move")
            else: reasons.append("Clear selling move")
            body=abs(df["close"].iloc[i]-df["open"].iloc[i]); rng=zh-zl
            if rng>0 and body/rng<0.5: conf+=10; reasons.append("Clean starting candle")
            tested=0; broken=False
            for k in range(i+1, len(df)):
                if df["low"].iloc[k] <= zh and df["high"].iloc[k] >= zl: tested+=1
                if df["close"].iloc[k] > zh: broken=True; break
            if tested==0: conf+=12; reasons.append("🆕 FRESH - Never tested")
            elif tested==1: conf+=2; reasons.append("Tested 1x - Still valid")
            else: conf-=15; reasons.append(f"Tested {tested}x - WEAK")
            if broken: conf-=10; reasons.append("⚠️ FLIP RISK - Was broken once")
            if conf>=min_confidence:
                zones.append(Zone(type="supply",high=zh,low=zl,index=i,confidence=conf,reasons=reasons,timeframe=timeframe,symbol=symbol,tested=tested,is_fresh=(tested==0),is_flip=broken))
    zones=sorted(zones, key=lambda z: z.index, reverse=True)[:5]
    return zones

def detect_fvg(df):
    df=normalize_df(df).reset_index(drop=True)
    fvgs=[]
    for i in range(1, len(df)-1):
        # Bullish FVG: low[i+1] > high[i-1]
        if df["low"].iloc[i+1] > df["high"].iloc[i-1]:
            fvgs.append(FVG(type="bullish", high=float(df["low"].iloc[i+1]), low=float(df["high"].iloc[i-1]), index=i))
        # Bearish FVG: high[i+1] < low[i-1]
        if df["high"].iloc[i+1] < df["low"].iloc[i-1]:
            fvgs.append(FVG(type="bearish", high=float(df["low"].iloc[i-1]), low=float(df["high"].iloc[i+1]), index=i))
    return fvgs[-3:]

def detect_liquidity(df):
    df=normalize_df(df).reset_index(drop=True)
    highs=df["high"].tail(30); lows=df["low"].tail(30)
    notes=[]
    # Equal highs within 0.15%
    for i in range(len(highs)-1):
        for j in range(i+1, len(highs)):
            if abs(highs.iloc[i]-highs.iloc[j])/highs.iloc[i] < 0.0015:
                notes.append(f"💧 Liquidity above ~{highs.iloc[j]:,.2f} (Equal Highs - Sweep risk)")
                break
        if notes and "above" in notes[-1]: break
    for i in range(len(lows)-1):
        for j in range(i+1, len(lows)):
            if abs(lows.iloc[i]-lows.iloc[j])/lows.iloc[i] < 0.0015:
                notes.append(f"💧 Liquidity below ~{lows.iloc[j]:,.2f} (Equal Lows - Sweep risk)")
                break
        if len(notes)>=2: break
    return notes[:2]

def get_session():
    h=datetime.datetime.utcnow().hour
    if 7 <= h < 12: return "🇬🇧 LONDON - High Volatility - BEST for zones"
    if 12 <= h < 20: return "🇺🇸 NEW YORK - High Volatility - BEST for zones"
    if 0 <= h < 7: return "🌏 ASIA - Low Volatility - Zones may be slow / fake"
    return "🌙 LATE NY - Low Volatility - Be careful"

def round_number_bonus(price, zone):
    # Gold: 3600, 3500 etc. BTC: 100k, 90k etc. Forex: 1.1000
    for rn in [round(price/100)*100, round(price/50)*50]:
        if zone.low- (price*0.005) <= rn <= zone.high + (price*0.005):
            return f"🎯 Round Number {rn:,.0f} inside zone - MAGNET"
    return None

def calc_rr(current, zone, zones, atr_val):
    if zone.type=="demand":
        entry=zone.high; sl=zone.low - atr_val*0.2; risk=entry-sl
        # TP = next supply above
        tps=[z.low for z in zones if z.type=="supply" and z.low>current]
        tp=min(tps) if tps else entry + risk*3
        reward=tp-entry; rr=reward/risk if risk>0 else 0
        return entry, sl, tp, rr
    else:
        entry=zone.low; sl=zone.high + atr_val*0.2; risk=sl-entry
        tps=[z.high for z in zones if z.type=="demand" and z.high<current]
        tp=max(tps) if tps else entry - risk*3
        reward=entry-tp; rr=reward/risk if risk>0 else 0
        return entry, sl, tp, rr

def fetch_df(ticker, tf_key):
    interval, period, display = TIMEFRAMES[tf_key]
    df=yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=False)
    if df is None or len(df)<40: return None, display
    df=normalize_df(df)
    if display=="4H":
        df.index=pd.to_datetime(df.index)
        df=df.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna().reset_index(drop=True)
    return df, display

def get_market_thinking(df, zones):
    df=normalize_df(df); close=df["close"]; current=float(close.iloc[-1])
    ema50=float(close.ewm(span=50).mean().iloc[-1])
    ema200=float(close.ewm(span=200).mean().iloc[-1]) if len(close)>=200 else ema50
    if current>ema50>ema200: trend="🟢 STRONG UPTREND"; note="Price above EMA50 above EMA200. Buyers in control."
    elif current>ema50: trend="🟢 UPTREND"; note="Price above EMA50. Lean bullish."
    elif current<ema50<ema200: trend="🔴 STRONG DOWNTREND"; note="Price below EMA50 below EMA200. Sellers in control."
    elif current<ema50: trend="🔴 DOWNTREND"; note="Price below EMA50. Lean bearish."
    else: trend="🟡 RANGING"; note="Price stuck around EMAs. Wait for breakout."
    inside=None; nearest=None; nd=999999
    for z in zones:
        if z.low<=current<=z.high: inside=z
        d=abs(current-(z.high+z.low)/2)/current*100
        if d<nd: nd=d; nearest=z
    if inside:
        if inside.type=="demand": bias="🟢 LOOK FOR BUYS - INSIDE Demand"; plan=f"Entry: On bullish confirmation\nSL: Below {inside.low:,.2f}"
        else: bias="🔴 LOOK FOR SELLS - INSIDE Supply"; plan=f"Entry: On bearish confirmation\nSL: Above {inside.high:,.2f}"
    elif nearest and nearest.type=="demand":
        if current>nearest.high: bias="⏳ WAIT FOR PULLBACK TO BUY"; plan=f"Wait drop to {nearest.low:,.2f}-{nearest.high:,.2f} ({nd:.2f}% away)"
        else: bias="👀 APPROACHING DEMAND FROM BELOW"; plan=f"Wait ENTER zone {nearest.low:,.2f}-{nearest.high:,.2f}, then bounce. Break below = broken."
    elif nearest and nearest.type=="supply":
        if current<nearest.low: bias="⏳ WAIT FOR RALLY TO SELL"; plan=f"Wait rise to {nearest.low:,.2f}-{nearest.high:,.2f} ({nd:.2f}% away)"
        else: bias="👀 APPROACHING SUPPLY FROM ABOVE"; plan=f"Wait ENTER zone {nearest.low:,.2f}-{nearest.high:,.2f}, then rejection. Break above = broken."
    else: bias="🟡 NO CLEAR SETUP"; plan="Patience is a trade."
    return trend, note, bias, plan, nearest, nd, inside

def build_analysis(symbol_key, tf_key):
    ticker=SYMBOLS.get(symbol_key.upper())
    if not ticker: return f"Unknown {symbol_key}"
    tf_key=norm_tf(tf_key)
    df, display = fetch_df(ticker, tf_key)
    if df is None: return f"Not enough data for {symbol_key} on {display}"
    zones=detect_zones(df, symbol=symbol_key.upper(), timeframe=display)
    if not zones: return f"No high-quality zones for {symbol_key} on {display}"
    current=float(df["close"].iloc[-1])
    atr_val=float(calculate_atr(df).iloc[-1])
    trend, note, bias, plan, nearest, nd, inside = get_market_thinking(df, zones)
    fvgs=detect_fvg(df); liq=detect_liquidity(df)
    # Best zone = freshest + highest confidence
    best = sorted(zones, key=lambda z: (z.is_fresh, z.confidence), reverse=True)[0]
    entry, sl, tp, rr = calc_rr(current, best, zones, atr_val)
    rr_verdict = "✅ TAKE IT - R:R >= 1:2" if rr>=2 else "❌ SKIP - R:R too low, wait for better zone"
    rn = round_number_bonus(current, best)
    # Journal
    JOURNAL.append({"symbol":symbol_key.upper(),"tf":display,"bias":bias,"price":current,"best":f"{best.low:,.2f}-{best.high:,.2f}","rr":round(rr,2),"time":datetime.datetime.utcnow().strftime("%H:%M")})
    if len(JOURNAL)>20: JOURNAL.pop(0)
    msg=f"🧠 {symbol_key.upper()} - {display} PRO Analysis\n"
    msg+=f"Price: {current:,.2f} | Session: {get_session()}\n\n"
    msg+=f"📈 TREND: {trend}\n{note}\n\n"
    msg+=f"🎯 BIAS: {bias}\n📋 {plan}\n\n"
    msg+=f"🏆 BEST ZONE: {'🟢 DEMAND' if best.type=='demand' else '🔴 SUPPLY'} {best.low:,.2f} - {best.high:,.2f} | {best.confidence:.0f}% | {'FRESH 🆕' if best.is_fresh else f'Tested {best.tested}x'}\n"
    if rn: msg+=f"{rn}\n"
    msg+=f"\n💰 TRADE MATH (Best Zone):\nEntry: {entry:,.2f}\nStop Loss: {sl:,.2f}\nTake Profit: {tp:,.2f}\nRisk:Reward = 1:{rr:.1f}\n{rr_verdict}\n"
    if fvgs:
        msg+=f"\n⚡ FVG / IMBALANCE (Price likes to fill these):\n"
        for f in fvgs: msg+=f"{'🟢 Bullish' if f.type=='bullish' else '🔴 Bearish'} FVG {f.low:,.2f} - {f.high:,.2f}\n"
    if liq:
        msg+=f"\n{chr(10).join(liq)}\n"
    msg+=f"\n--- ALL ZONES ---\n"
    for z in zones:
        emoji="🟢 DEMAND" if z.type=="demand" else "🔴 SUPPLY"
        dist=abs(current-(z.high+z.low)/2)/current*100
        fresh="🆕 FRESH" if z.is_fresh else f"Tested {z.tested}x"
        flip=" | FLIP RISK" if z.is_flip else ""
        tag=" ← PRICE HERE" if inside==z else ""
        msg+=f"{emoji} {z.low:,.2f}-{z.high:,.2f} | {z.confidence:.0f}% | {fresh}{flip} | {dist:.2f}% away{tag}\n"
    msg+="\n⚠️ Not financial advice. No trade 30min before NFP / CPI / FOMC."
    return msg

def get_confluence(symbol_key):
    # Check all TFs
    results={}
    for tf in ["15m","1h","4h","1d"]:
        ticker=SYMBOLS.get(symbol_key.upper())
        df, disp = fetch_df(ticker, tf)
        if df is None: continue
        zones=detect_zones(df, symbol=symbol_key.upper(), timeframe=disp)
        if not zones: continue
        current=float(df["close"].iloc[-1])
        trend,_,bias,_,_,_,_ = get_market_thinking(df, zones)
        best=sorted(zones, key=lambda z:(z.is_fresh,z.confidence), reverse=True)[0]
        results[tf]=(trend,bias,best,current)
    if not results: return "No data for confluence"
    # Count bullish vs bearish
    bull=sum(1 for v in results.values() if "UPTREND" in v[0] or "BUY" in v[1])
    bear=sum(1 for v in results.values() if "DOWNTREND" in v[0] or "SELL" in v[1])
    if bull>=3: verdict="🟢🟢🟢 STRONG CONFLUENCE: ALL TIMEFRAMES BULLISH - High probability buy"
    elif bear>=3: verdict="🔴🔴🔴 STRONG CONFLUENCE: ALL TIMEFRAMES BEARISH - High probability sell"
    elif bull==2 and bear==2: verdict="🟡 CONFLICT: 2 vs 2 - DO NOT TRADE, wait for alignment"
    else: verdict=f"🟡 MIXED: {bull} Bullish / {bear} Bearish - Trade with caution, smaller size"
    msg=f"🌐 {symbol_key.upper()} MULTI-TIMEFRAME CONFLUENCE\n{verdict}\n\n"
    for tf,(trend,bias,best,cur) in results.items():
        msg+=f"{tf.upper()}: {trend} | {bias}\nBest: {'🟢' if best.type=='demand' else '🔴'} {best.low:,.2f}-{best.high:,.2f} ({best.confidence:.0f}%)\n\n"
    # Overlap check: 1h + 4h zones close?
    if "1h" in results and "4h" in results:
        z1=results["1h"][2]; z4=results["4h"][2]
        if z1.type==z4.type and abs(z1.low-z4.low)/z1.low < 0.01:
            msg+=f"💎 KILLER OVERLAP: 1H + 4H {z1.type.upper()} overlap at {z1.low:,.2f}-{z1.high:,.2f} - STRONGEST ZONE!\n"
    return msg

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 PRO Pivot Zone Bot - 30yr Trader Brain\n\n"
        "/zones GOLD 1h - Single TF\n"
        "/zones GOLD all - All TFs Confluence\n"
        "/zones GOLD 15m / 4h / 1d\n"
        "/alert GOLD 3511 - Ping me when price hits\n"
        "/alerts - My alerts\n"
        "/score - My journal score\n\n"
        "Features: Fresh/Tested, Flip, FVG, Liquidity, R:R, Session, Round Numbers"
    )

async def zones_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /zones GOLD 1h  or  /zones GOLD all")
        return
    symbol=context.args[0].upper()
    tf=context.args[1].lower() if len(context.args)>1 else "1h"
    if tf=="all":
        await update.message.reply_text(f"🌐 Checking ALL timeframes for {symbol}... please wait (20s)")
        text=get_confluence(symbol)
    else:
        await update.message.reply_text(f"🧠 Pro thinking about {symbol} on {tf.upper()}...")
        text=build_analysis(symbol, tf)
    await update.message.reply_text(text)

async def alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args)<2:
        await update.message.reply_text("Usage: /alert GOLD 3511\nI will ping you when price hits that level.")
        return
    symbol=context.args[0].upper(); 
    try: price=float(context.args[1])
    except: await update.message.reply_text("Price must be a number. Example: /alert GOLD 3511"); return
    uid=update.effective_user.id
    ALERTS.setdefault(uid, []).append({"symbol":symbol,"price":price})
    await update.message.reply_text(f"🔔 Alert set! I will ping you when {symbol} hits {price:,.2f}")

async def alerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    lst=ALERTS.get(uid, [])
    if not lst: await update.message.reply_text("No alerts yet. Use /alert GOLD 3511"); return
    msg="🔔 Your Alerts:\n"
    for a in lst: msg+=f"{a['symbol']} at {a['price']:,.2f}\n"
    await update.message.reply_text(msg)

async def score_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not JOURNAL: await update.message.reply_text("No trades logged yet. Use /zones first."); return
    msg="📓 JOURNAL - Last Signals:\n\n"
    for j in JOURNAL[-10:]:
        msg+=f"{j['time']} UTC | {j['symbol']} {j['tf']} | {j['bias'][:30]} | Price {j['price']:,.2f} | Best {j['best']} | R:R 1:{j['rr']}\n"
    # Simple score: count fresh zones suggested
    fresh_count=sum(1 for j in JOURNAL if j['rr']>=2)
    msg+=f"\n✅ Good R:R setups: {fresh_count}/{len(JOURNAL)}"
    await update.message.reply_text(msg)

async def check_alerts(context: ContextTypes.DEFAULT_TYPE):
    # Runs every 5 mins
    for uid, lst in list(ALERTS.items()):
        remaining=[]
        for a in lst:
            ticker=SYMBOLS.get(a['symbol'])
            if not ticker: continue
            try:
                df=yf.download(ticker, period="1d", interval="15m", progress=False, auto_adjust=False)
                if df is None or len(df)==0: remaining.append(a); continue
                df=normalize_df(df)
                cur=float(df["close"].iloc[-1])
                # Hit if within 0.2%
                if abs(cur-a['price'])/a['price'] < 0.002:
                    await context.bot.send_message(chat_id=uid, text=f"🚨 ALERT! {a['symbol']} just hit {a['price']:,.2f} (Now {cur:,.2f})\nCheck your zone! Use /zones {a['symbol']} 1h")
                else:
                    remaining.append(a)
            except:
                remaining.append(a)
        ALERTS[uid]=remaining

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set!"); return
    print("Bot is running PRO...")
    app_bot=ApplicationBuilder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("zones", zones_cmd))
    app_bot.add_handler(CommandHandler("alert", alert_cmd))
    app_bot.add_handler(CommandHandler("alerts", alerts_cmd))
    app_bot.add_handler(CommandHandler("score", score_cmd))
    if app_bot.job_queue:
        app_bot.job_queue.run_repeating(check_alerts, interval=300, first=10)
    app_bot.run_polling()

if __name__=="__main__":
    main()
