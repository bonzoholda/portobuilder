import os
import time
import random
import sqlite3
import requests
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from pair_scanner import get_safe_pairs
from strategy import htf_ok, entry_ok, exit_levels  # Added exit_levels
from risk import load_state, save_state, can_trade
from uniswap_v3 import UniswapV3Client
from state import init_db, record_trade, set_meta, set_balance
from ohlcv import load_ohlcv
from token_list import TOKEN_BY_SYMBOL

from web3 import Web3
from uniswap_abi import ERC20_ABI
from config import WALLET_ADDRESS, USDC

# Ensure DB is ready
init_db()

# ================= CONFIG =================
DECIMALS = {
    "USDC": 6,
    "WBTC": 8,
    "WBTC.e": 8
}

TOKENS_TO_TRACK = [
    ("MATIC", "MATIC", 18),
    ("USDC", USDC, 6)
]

for symbol, addr in TOKEN_BY_SYMBOL.items():
    decimal = DECIMALS.get(symbol, 18)
    if (symbol, addr, decimal) not in TOKENS_TO_TRACK:
        TOKENS_TO_TRACK.append((symbol, addr, decimal))

TRADE_USDC_AMOUNT = 2.4
LAST_TRADE_COOLDOWN = 1800
MAX_DAILY_LOSS = -1.5
LOOP_SLEEP = 300

# ================= INIT ===================
client = UniswapV3Client()
print("✅ Bot started")

# ================= HELPERS =================

def get_price(symbol):
    if symbol == "USDC": return 1.0
    try:
        mapping = {"WMATIC": "POL", "MATIC": "POL", "WETH": "ETH", "WBTC": "BTC"}
        ticker_symbol = mapping.get(symbol.upper(), symbol.upper())
        url = f"https://www.okx.com/api/v5/market/ticker?instId={ticker_symbol}-USDT"
        res = requests.get(url, timeout=5)
        data = res.json()
        if data.get('code') == '0' and data.get('data'):
            return float(data['data'][0]['last'])
        return 0.0
    except Exception as e:
        print(f"⚠️ OKX API Error for {symbol}: {e}")
        return 0.0

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
    print("🔄 Syncing balances to dashboard...")
    for symbol, token_addr, decimals in tokens:
        try:
            if token_addr == "MATIC":
                bal = w3.eth.get_balance(wallet) / 1e18
            else:
                erc20 = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
                bal = erc20.functions.balanceOf(wallet).call() / (10 ** decimals)
            price = get_price(symbol)
            set_balance(symbol, bal, price)
        except Exception as e:
            print(f"⚠️ Error syncing {symbol}: {e}")

def get_active_positions():
    """Finds tokens we currently hold and their last buy price."""
    conn = sqlite3.connect("trader.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    # Find tokens where the last action was a BUY and we still have a balance
    c.execute("SELECT asset, amount, price FROM balances WHERE amount > 0.01 AND asset != 'USDC'")
    positions = c.fetchall()
    conn.close()
    return positions

# ================= MAIN LOOP =================

print("🔄 Performing initial balance sync...")
try:
    sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
    print("✅ Initial sync complete")
except Exception as e:
    print(f"❌ Initial sync failed: {e}")

while True:
    try:
        state = load_state()
        daily_pnl = get_daily_pnl()
        set_meta("daily_pnl", daily_pnl)

        if daily_pnl <= MAX_DAILY_LOSS:
            print(f"🛑 Kill switch triggered: {daily_pnl:.2f} USDC")
            time.sleep(86400)
            continue

        # --- PART 1: MONITOR FOR EXITS ---
        active_positions = get_active_positions()
        for pos in active_positions:
            symbol = pos['asset']
            current_price = get_price(symbol)
            entry_price = pos['price'] # We use the price saved in balances table
            
            if entry_price == 0: continue

            levels = exit_levels(entry_price)
            
            reason = ""
            if current_price >= levels['tp2']: reason = "TP2 (+3%)"
            elif current_price >= levels['tp1']: reason = "TP1 (+1.5%)"
            elif current_price <= levels['sl']: reason = "SL (-1.5%)"

            if reason:
                print(f"🔴 SELL {symbol} at {current_price} | Reason: {reason}")
                token_addr = TOKEN_BY_SYMBOL.get(symbol)
                if token_addr:
                    # Execute Sell logic
                    tx = client.sell_for_usdc(token_addr=token_addr, amount=pos['amount'])
                    
                    record_trade(
                        pair=f"{symbol}/USDC",
                        side="SELL",
                        amount_in=0,
                        amount_out=pos['amount'] * current_price,
                        price=current_price,
                        tx=tx
                    )
                    sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)

        # --- PART 2: SCAN FOR NEW ENTRIES ---
        if can_trade(state):
            pairs = get_safe_pairs()
            if isinstance(pairs, list):
                for p in pairs:
                    try:
                        if "token0" not in p or "token1" not in p: continue
                        symbols = [p["token0"].get("symbol"), p["token1"].get("symbol")]
                        if "USDC" not in symbols: continue

                        symbol = symbols[0] if symbols[1] == "USDC" else symbols[1]
                        if symbol not in TOKEN_BY_SYMBOL: continue
                        
                        # Don't buy if we already have a position
                        if any(pos['asset'] == symbol for pos in active_positions): continue

                        last_trade = state.get("last_trade", {}).get(symbol, 0)
                        if time.time() - last_trade < LAST_TRADE_COOLDOWN: continue

                        df_htf = load_ohlcv(symbol, "4h")
                        df_ltf = load_ohlcv(symbol, "15m")

                        if df_htf is None or df_ltf is None or df_htf.empty or df_ltf.empty: continue

                        if htf_ok(df_htf) and entry_ok(df_ltf):
                            token_addr = TOKEN_BY_SYMBOL[symbol]
                            print(f"🟢 BUY {symbol}")
                            tx = client.buy_with_usdc(token_addr=token_addr, usdc_amount=TRADE_USDC_AMOUNT)
                            
                            current_trade_price = get_price(symbol)
                            record_trade(
                                pair=f"{symbol}/USDC",
                                side="BUY",
                                amount_in=TRADE_USDC_AMOUNT,
                                amount_out=0,
                                price=current_trade_price,
                                tx=tx
                            )
                            state.setdefault("last_trade", {})[symbol] = int(time.time())
                            save_state(state)
                            sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
                            time.sleep(random.randint(5, 25))
                    except Exception as pair_error:
                        continue

        time.sleep(LOOP_SLEEP)

    except Exception as e:
        print("❌ Bot error:", str(e))
        time.sleep(30)
