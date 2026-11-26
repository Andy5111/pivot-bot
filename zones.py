# zones.py - Pivot Supply/Demand Zone Detector
import pandas as pd

def find_pivots(df, left=3, right=3):
    highs = []
    lows = []
    for i in range(left, len(df)-right):
        high = df['high'].iloc[i]
        low = df['low'].iloc[i]
        if high == df['high'].iloc[i-left:i+right+1].max():
            highs.append((df.index[i], high))
        if low == df['low'].iloc[i-left:i+right+1].min():
            lows.append((df.index[i], low))
    return highs, lows

def build_zones(df):
    highs, lows = find_pivots(df)
    zones = []
    for idx, low in lows[-10:]:
        zones.append({'type': 'DEMAND','top': float(low * 1.002),'bottom': float(low),'time': str(idx)})
    for idx, high in highs[-10:]:
        zones.append({'type': 'SUPPLY','top': float(high),'bottom': float(high * 0.998),'time': str(idx)})
    return zones

def get_latest_zones(df):
    zones = build_zones(df)
    supply = [z for z in zones if z['type']=='SUPPLY'][-3:]
    demand = [z for z in zones if z['type']=='DEMAND'][-3:]
    return supply, demand
