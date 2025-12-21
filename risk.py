import json
import os
import time

STATE_FILE = "state.json"

# ================= DEFAULT STATE =================

DEFAULT_STATE = {
    "daily_loss": 0.0,
    "last_reset": 0,
    "last_trade": {}
}

# ================= STATE IO =================

def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return DEFAULT_STATE.copy()

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
    except Exception:
        state = {}

    return normalize_state(state)


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def normalize_state(state: dict) -> dict:
    for k, v in DEFAULT_STATE.items():
        state.setdefault(k, v)
    return state

# ================= RISK LOGIC =================

def can_trade(state: dict) -> bool:
    state = normalize_state(state)

    # Hard stop example (can be expanded)
    if state["daily_loss"] <= -5:
        return False

    return True


def record_loss(state: dict, loss_amount: float) -> dict:
    state = normalize_state(state)
    state["daily_loss"] += loss_amount
    return state
