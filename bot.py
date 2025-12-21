import time
from pair_scanner import get_safe_pairs
from strategy import htf_ok, entry_ok, exit_levels
from risk import load_state, save_state, can_trade
from uniswap_v3 import UniswapClient

client = UniswapClient()

while True:
    state = load_state()
    if not can_trade(state):
        print("Daily loss limit hit. Bot paused.")
        break

    pairs = get_safe_pairs()

    for p in pairs:
        symbol = p["token0"]["symbol"] if p["token0"]["symbol"] != "USDC" else p["token1"]["symbol"]

        # You plug OHLCV fetcher here (Binance/OKX proxy)
        df_htf = load_ohlcv(symbol, "4h")
        df_ltf = load_ohlcv(symbol, "15m")

        if not htf_ok(df_htf):
            continue

        if entry_ok(df_ltf):
            tx = client.buy_with_usdc(TOKEN_ADDRESS, 2.4)
            print("TX:", tx)

            time.sleep(30)

    time.sleep(300)
