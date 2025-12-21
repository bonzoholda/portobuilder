import requests
import pandas as pd

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"

TF_MAP = {
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d"
}

def load_ohlcv(symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    if timeframe not in TF_MAP:
        raise ValueError("Unsupported timeframe")

    pair = f"{symbol}USDT"  # CEX proxy
    params = {
        "symbol": pair,
        "interval": TF_MAP[timeframe],
        "limit": limit
    }

    r = requests.get(BINANCE_KLINES, params=params, timeout=10)
    r.raise_for_status()

    data = r.json()
    if not data:
        raise ValueError("Empty OHLCV")

    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
    ])

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("open_time", inplace=True)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    return df
