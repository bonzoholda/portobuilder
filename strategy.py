def htf_ok(df):
    return (
        df.ema50.iloc[-1] > df.ema200.iloc[-1] and
        df.rsi.iloc[-1] > 45
    )

def entry_ok(df):
    price = df.close.iloc[-1]
    return (
        df.ema20.iloc[-1] <= price <= df.ema50.iloc[-1] and
        38 <= df.rsi.iloc[-1] <= 48
    )

def exit_levels(entry, atr):
    return {
        "tp1": entry * 1.012,
        "tp2": entry * 1.025,
        "trail": atr * 1.2
    }
