import os
import time
import random
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from pair_scanner import get_safe_pairs
from strategy import htf_ok, entry_ok
from risk import load_state, save_state, can_trade
from uniswap_v3 import UniswapV3Client
from state import init_db, record_trade, set_meta
from ohlcv import load_ohlcv
from token_list import TOKEN_BY_SYMBOL

from state import set_balance
from web3 import Web3

import sqlite3

# ================= CONFIG =================

TRADE_USDC_AMOUNT = 2.4
LAST_TRADE_COOLDOWN = 1800       # 30 minutes
MAX_DAILY_LOSS = -1.5            # USDC
LOOP_SLEEP = 300                 # 5 minutes

# ================= INIT ===================

init_db()
client = UniswapV3Client()

print("✅ Bot started")

# ================= HELPERS =================

def today_timestamp():
    return int(datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).timestamp())


def get_daily_pnl():
    conn = sqlite3.connect("trader.db")
    c = conn.cursor()
    c.execute("""
        SELECT COALESCE(SUM(amount_out - amount_in), 0)
        FROM trades
        WHERE timestamp >= ?
    """, (today_timestamp(),))
    pnl = c.fetchone()[0]
    conn.close()
    return pnl

def sync_balances(w3, wallet, tokens):
    for symbol, token_addr, decimals in tokens:
        if token_addr == "MATIC":
            bal = w3.eth.get_balance(wallet) / 1e18
        else:
            erc20 = w3.eth.contract(token_addr, abi=ERC20_ABI)
            bal = erc20.functions.balanceOf(wallet).call() / (10 ** decimals)

        set_balance(symbol, bal)
        
# ================= MAIN LOOP =================

while True:
    try:
        state = load_state()

        daily_pnl = get_daily_pnl()
        set_meta("daily_pnl", daily_pnl)

        # 🛑 Kill switch
        if daily_pnl <= MAX_DAILY_LOSS:
            print(f"🛑 Kill switch triggered: {daily_pnl:.2f} USDC")
            time.sleep(86400)
            continue

        if not can_trade(state):
            print("⚠️ Trading disabled by risk module")
            time.sleep(600)
            continue

        pairs = get_safe_pairs()

        if not isinstance(pairs, list):
            print("⚠️ Pair scanner returned invalid data, skipping cycle")
            time.sleep(LOOP_SLEEP)
            continue

        for p in pairs:
            try:
                # ---- Validate pair structure ----
                if "token0" not in p or "token1" not in p:
                    continue

                symbols = [
                    p["token0"].get("symbol"),
                    p["token1"].get("symbol")
                ]

            
                if "USDC" not in symbols:
                    continue

                symbol = symbols[0] if symbols[1] == "USDC" else symbols[1]

                if symbol not in TOKEN_BY_SYMBOL:
                    continue
               
                
                last_trade = state.get("last_trade", {}).get(symbol, 0)
                if time.time() - last_trade < LAST_TRADE_COOLDOWN:
                    continue

                # ---- Load OHLCV safely ----
                df_htf = load_ohlcv(symbol, "4h")
                df_ltf = load_ohlcv(symbol, "15m")

                if df_htf is None or df_ltf is None:
                    continue

                if df_htf.empty or df_ltf.empty:
                    continue

                print(f"Checking {symbol}")
                
                if not htf_ok(df_htf):
                    print(f"❌ HTF fail {symbol}")
                    continue

                if not entry_ok(df_ltf):
                    print(f"❌ Entry fail {symbol}")
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

                state.setdefault("last_trade", {})[symbol] = int(time.time())
                save_state(state)

                sync_balances()

                time.sleep(random.randint(5, 25))

            except Exception as pair_error:
                print(f"⚠️ Pair skipped due to error: {pair_error}")
                continue

        time.sleep(LOOP_SLEEP)

    except Exception as e:
        print("❌ Bot error:", str(e))
        time.sleep(30)
