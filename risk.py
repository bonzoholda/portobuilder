import json
from pathlib import Path

STATE = Path("state.json")

def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"daily_loss": 0, "positions": {}}

def save_state(state):
    STATE.write_text(json.dumps(state, indent=2))

def can_trade(state):
    return state["daily_loss"] < 0.01
