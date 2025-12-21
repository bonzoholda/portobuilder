import pandas as pd

# =========================
# INDICATORS
# =========================

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds EMA50, EMA200, RSI to dataframe.
    Returns a COPY (never mutates original).
    """
    if df is None or len(df) < 210:
        raise ValueError("Not enough OHLCV data")

    df = df.copy()

    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["rsi"] = compute_rsi(df["close"], 14)

    return df


# =========================
# STRATEGY LOGIC
# =========================

def htf_ok(df_htf: pd.DataFrame) -> bool:
    """
    Higher timeframe trend filter.
    Only trade in bullish trend.
    """
    try:
        df = add_indicators(df_htf)
        return (
            df["ema50"].iloc[-1] > df["ema200"].iloc[-1]
            and df["close"].iloc[-1] > df["ema50"].iloc[-1]
        )
    except Exception:
        return False


def entry_ok(df_ltf: pd.DataFrame) -> bool:
    """
    Entry condition on lower timeframe.
    """
    try:
        df = add_indicators(df_ltf)

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # Conditions
        price_above_ema = last["close"] > last["ema50"]
        rsi_ok = 35 < last["rsi"] < 65
        momentum = last["close"] > prev["close"]

        return price_above_ema and rsi_ok and momentum

    except Exception:
        return False


# =========================
# EXIT LEVELS (future use)
# =========================

def exit_levels(entry_price: float):
    """
    Returns TP levels (for later sell logic).
    """
    return {
        "tp1": entry_price * 1.015,  # +1.5%
        "tp2": entry_price * 1.03,   # +3%
        "sl": entry_price * 0.985,   # -1.5%
    }
