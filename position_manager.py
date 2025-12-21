from risk import load_state, save_state
from indicators import apply_indicators
from uniswap_v3 import UniswapV3Client

client = UniswapV3Client()

TP1_RATIO = 0.30
TP2_RATIO = 0.40

def handle_position(symbol, price, atr):
    state = load_state()
    pos = state["positions"].get(symbol)
    if not pos:
        return

    entry = pos["entry_price"]

    # --- TP1 ---
    if not pos["tp1_done"] and price >= entry * 1.012:
        sell_amount = pos["amount"] * TP1_RATIO
        client.sell_to_usdc(pos["token"], sell_amount)

        pos["amount"] -= sell_amount
        pos["tp1_done"] = True
        print(f"[TP1] {symbol} sold 30%")

    # --- TP2 ---
    if pos["tp1_done"] and not pos["tp2_done"] and price >= entry * 1.025:
        sell_amount = pos["amount"] * (TP2_RATIO / (1 - TP1_RATIO))
        client.sell_to_usdc(pos["token"], sell_amount)

        pos["amount"] -= sell_amount
        pos["tp2_done"] = True
        pos["trail_stop"] = price - atr * 1.2
        print(f"[TP2] {symbol} sold 40%")

    # --- Trailing Stop ---
    if pos["tp2_done"]:
        new_trail = price - atr * 1.2
        pos["trail_stop"] = max(pos["trail_stop"], new_trail)

        if price <= pos["trail_stop"]:
            client.sell_to_usdc(pos["token"], pos["amount"])
            print(f"[EXIT] {symbol} trailing stop hit")
            del state["positions"][symbol]

    save_state(state)
