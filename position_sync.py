from risk import load_state, save_state
from balance_sync import get_token_balance

def sync_positions():
    state = load_state()
    positions = state.get("positions", {})

    to_delete = []

    for symbol, pos in positions.items():
        token = pos["token"]
        onchain_balance = get_token_balance(token)

        # Dust or fully sold
        if onchain_balance < 1e-8:
            to_delete.append(symbol)
            continue

        pos["amount"] = onchain_balance

    for s in to_delete:
        print(f"[SYNC] Removing closed position {s}")
        del positions[s]

    state["positions"] = positions
    save_state(state)
