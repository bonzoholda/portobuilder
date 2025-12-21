import ta

def apply_indicators(df):
    df["ema20"] = ta.trend.ema_indicator(df.close, 20)
    df["ema50"] = ta.trend.ema_indicator(df.close, 50)
    df["ema200"] = ta.trend.ema_indicator(df.close, 200)
    df["rsi"] = ta.momentum.rsi(df.close, 14)
    df["atr"] = ta.volatility.average_true_range(df.high, df.low, df.close)
    return df
