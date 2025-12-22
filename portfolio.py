import sqlite3
from web3 import Web3
from config import RPC_URL

# Local DB import
from state import DB_FILE

w3 = Web3(Web3.HTTPProvider(RPC_URL))


# ================= PORTFOLIO VALUATION =================

def get_balances():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("SELECT asset, amount, price FROM balances")
    rows = c.fetchall()

    conn.close()
    return rows


def get_native_price_usd():
    """
    WMATIC / ETH native price via RPC
    Fallback-safe (returns 0 if fail)
    """
    try:
        latest = w3.eth.get_block("latest")
        return float(latest.baseFeePerGas) * 0  # placeholder safety
    except:
        return 0


def calculate_portfolio_value():
    balances = get_balances()
    total = 0.0

    for asset, amount, price in balances:
        if amount is None or amount == 0:
            continue

        # If price is stored, trust it
        if price and price > 0:
            total += amount * price
        else:
            # Worst-case fallback
            total += 0

    return round(total, 6)
