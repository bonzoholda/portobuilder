import time

# ================= DEFAULT STATE =================

DEFAULT_STATE = {
    "daily_loss": 0.0,
    "last_reset": 0
}


# ================= STATE HELPERS =================

def normalize_state(state: dict) -> dict:
    """
    Ensure required keys always exist
    """
    for k, v in DEFAULT_STATE.items():
        state.setdefault(k, v)
    return state


# ================= RISK LOGIC =================

def can_trade(state: dict) -> bool:
    state = normalize_state(state)

    # Example future rule hooks
    if state["daily_loss"] <= -5:
        return False

    return True


def record_loss(state: dict, loss_amount: float):
    state = normalize_state(state)
    state["daily_loss"] += loss_amount
    return state
