import json
import time
import os

STATE_FILE = "bot_state.json"
MAX_DAILY_LOSS = -1.5  # USDC


def init_db():
    """
    Placeholder init for future DB.
    Ensures state file exists.
    """
    if not os.path.exists(STATE_FILE):
        save_state(_default_state())


def _default_state():
    return {
        "date": time.strftime("%Y-%m-%d"),
        "daily_pnl": 0.0,
        "last_trade_ts": 0
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        return _default_state()

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    today = time.strftime("%Y-%m-%d")
    if state.get("date") != today:
        state = _default_state()

    return state


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def can_trade(state):
    return state["daily_pnl"] > MAX_DAILY_LOSS


def update_pnl(state, pnl_delta):
    state["daily_pnl"] += pnl_delta
    save_state(state)
