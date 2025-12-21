import os
import time
import random
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from pair_scanner import get_safe_pairs
from strategy import htf_ok, entry_ok
from risk import load_state, save_state, can_trade
from uniswap_v3 import UniswapClient
from state import (
    init_db,
    record_trade,
    set_meta
)

from ohlcv import load_ohlcv
from token_list import TOKEN_BY_SYMBOL

# ================= CONFIG =================

TRADE_USDC_AMOUNT = 2.4
LAST_TRADE_COOLDOWN = 1800       # 30 minutes
MAX_DAILY_LOSS = -1.5            # USDC
LOOP_SLEEP = 300                 # 5 minutes

# ================= INIT ===================

init_db()
client = UniswapClient()

print("✅ Bot started")

# ================= HELPERS =================

def today_timestamp():
    return int(datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp())


def get_daily_pnl():
    import sqlite3
    conn = sqlite3.connect("trader.db")
    c = conn.cursor()
    c.execute(
        "SELECT SUM(amount_out - amount_in) FROM trades WHERE timestamp >= ?",
        (today_timestamp(),)
    )
    pnl = c.fetchone()[0] or 0
    conn.close()
    return pnl


# ================= MAIN LOOP =================

while True:
    try:
        state = load_state()

        daily_pnl = get_daily_pnl()
        set_meta("daily_pnl", daily_pnl)

        # 🔴 KILL SWITCH
        if daily_pnl <= MAX_DAILY_LOSS:
            print(f"🛑 Kill switch triggered: {daily_pnl:.2f} USDC")
            time.sleep(86400)
            continue

        if not can_trade(state):
            print("⚠️ Trading disabled by risk module")
            time.sleep(600)
            continue

        pairs = get_safe_pairs()

        for p in pairs:
            symbol = (
                p["token0"]["symbol"]
                if p["token0"]["symbol"] != "USDC"
                else p["token1"]["symbol"]
            )

            if symbol not in TOKEN_BY_SYMBOL:
                continue

            last_trade = state.get("last_trade", {}).get(symbol, 0)
            if time.time() - last_trade < LAST_TRADE_COOLDOWN:
                continue

            df_htf = load_ohlcv(symbol, "4h")
            df_ltf = load_ohlcv(symbol, "15m")

            if not htf_ok(df_htf):
                continue

            if not entry_ok(df_ltf):
                continue

            token_addr = TOKEN_BY_SYMBOL[symbol]

            print(f"🟢 BUY {symbol}")

            tx = client.buy_with_usdc(
                token_addr=token_addr,
                usdc_amount=TRADE_USDC_AMOUNT
            )

            record_trade(
                pair=f"{symbol}/USDC",
                side="BUY",
                amount_in=TRADE_USDC_AMOUNT,
                amount_out=0,
                price=0,
                tx=tx
            )

            # Update cooldown state
            state.setdefault("last_trade", {})[symbol] = int(time.time())
            save_state(state)

            time.sleep(random.randint(5, 25))

        time.sleep(LOOP_SLEEP)

    except Exception as e:
        print("❌ Bot error:", str(e))
        time.sleep(30)
