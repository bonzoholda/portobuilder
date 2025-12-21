from datetime import datetime
from risk import load_state, save_state
from balance_sync import get_token_balance
from price_feed import get_price_usdc  # your existing price source

MAX_DAILY_LOSS = -0.01     # -1%
DAILY_PROFIT_LOCK = 0.015  # +1.5%

def _today():
    return datetime.utcnow().strftime("%Y-%m-%d")

def reset_if_new_day(state):
    if state.get("day") != _today():
        state["day"] = _today()
        state["daily_realized_pnl"] = 0.0
        state["daily_unrealized_pnl"] = 0.0
        state["trading_enabled"] = True

def update_unrealized_pnl():
    state = load_state()
    reset_if_new_day(state)

    unrealized = 0.0
    for symbol, pos in state["positions"].items():
        price = get_price_usdc(symbol)
        value_now = pos["amount"] * price
        value_entry = pos["amount"] * pos["entry_price"]
        unrealized += (value_now - value_entry)

    state["daily_unrealized_pnl"] = unrealized
    save_state(state)

def record_realized_pnl(pnl_usdc):
    state = load_state()
    reset_if_new_day(state)

    state["daily_realized_pnl"] += pnl_usdc
    save_state(state)

def check_kill_switch():
    state = load_state()
    reset_if_new_day(state)

    total_pnl = state["daily_realized_pnl"] + state["daily_unrealized_pnl"]

    if total_pnl <= MAX_DAILY_LOSS * 20:
        state["trading_enabled"] = False
        save_state(state)
        return False

    if total_pnl >= DAILY_PROFIT_LOCK * 20:
        state["trading_enabled"] = False
        save_state(state)
        return False

    return True
