from risk import load_state, save_state
from position_sync import sync_positions
from uniswap_v3 import UniswapV3Client
from pnl_tracker import record_realized_pnl


client = UniswapV3Client()

TP1 = 1.012
TP2 = 1.025

def handle_position(symbol, price, atr):
    sync_positions()
    state = load_state()

    pos = state["positions"].get(symbol)
    if not pos:
        return

    entry = pos["entry_price"]
    amount = pos["amount"]

    # --- TP1 ---
    if not pos["tp1_done"] and price >= entry * TP1:
        sell_amt = amount * 0.30
        client.sell_to_usdc(pos["token"], sell_amt)
        pos["tp1_done"] = True
        print(f"[TP1] {symbol} 30% sold")

        sell_price = price
        pnl = (sell_price - entry) * sell_amt
        record_realized_pnl(pnl)


    # --- TP2 ---
    if pos["tp1_done"] and not pos["tp2_done"] and price >= entry * TP2:
        sell_amt = amount * 0.40
        client.sell_to_usdc(pos["token"], sell_amt)
        pos["tp2_done"] = True
        pos["trail_stop"] = price - atr * 1.2
        print(f"[TP2] {symbol} 40% sold")

        sell_price = price
        pnl = (sell_price - entry) * sell_amt
        record_realized_pnl(pnl)

    # --- Trailing ---
    if pos["tp2_done"]:
        new_trail = price - atr * 1.2
        pos["trail_stop"] = max(pos["trail_stop"], new_trail)

        if price <= pos["trail_stop"]:
            client.sell_to_usdc(pos["token"], amount)
            print(f"[EXIT] {symbol} trailing stop")

            sell_price = price
            pnl = (sell_price - entry) * sell_amt
            record_realized_pnl(pnl)

    save_state(state)
