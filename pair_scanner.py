from token_list import TOKEN_BY_SYMBOL

def get_safe_pairs():
    pairs = []

    for symbol, addr in TOKEN_BY_SYMBOL.items():
        pairs.append({
            "token0": {"symbol": symbol, "id": addr},
            "token1": {"symbol": "USDC", "id": "USDC"},
        })

    return pairs
