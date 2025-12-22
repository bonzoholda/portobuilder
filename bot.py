import os
import time
import random
import sqlite3
import requests
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from pair_scanner import get_safe_pairs
from strategy import htf_ok, entry_ok, exit_levels
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
DECIMALS = {"USDC": 6, "WBTC": 8, "WBTC.e": 8}
TOKENS_TO_TRACK = [("MATIC", "MATIC", 18), ("USDC", USDC, 6)]

for symbol, addr in TOKEN_BY_SYMBOL.items():
    decimal = DECIMALS.get(symbol, 18)
    if (symbol, addr, decimal) not in TOKENS_TO_TRACK:
        TOKENS_TO_TRACK.append((symbol, addr, decimal))

TRADE_USDC_AMOUNT = 2.4
LAST_TRADE_COOLDOWN = 1800
MAX_DAILY_LOSS = -1.5
LOOP_SLEEP = 300
TRAILING_PERCENT = 0.01 # 1% drop from ATH after TP2 hits

client = UniswapV3Client()
print("✅ Bot started with Tiered Exit Strategy (30/30/40)")

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
    except:
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
    print("🔄 Syncing balances...")
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
            print(f"⚠️ Sync error {symbol}: {e}")

def get_active_positions():
    conn = sqlite3.connect("trader.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM balances WHERE amount > 0.001 AND asset != 'USDC'")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def update_position_state(symbol, column, value):
    conn = sqlite3.connect("trader.db")
    c = conn.cursor()
    c.execute(f"UPDATE balances SET {column} = ? WHERE asset = ?", (value, symbol))
    conn.commit()
    conn.close()

# ================= MAIN LOOP =================

while True:
    try:
        state = load_state()
        daily_pnl = get_daily_pnl()
        set_meta("daily_pnl", daily_pnl)

        # 🛑 Kill switch
        if daily_pnl <= MAX_DAILY_LOSS:
            print(f"🛑 Daily Loss Limit Hit: {daily_pnl:.2f}")
            time.sleep(3600)
            continue

        # --- PART 1: MONITOR FOR EXITS (30/30/40) ---
        active_pos = get_active_positions()
        for pos in active_pos:
            symbol = pos['asset']
            cur_price = get_price(symbol)
            entry_price = pos['price']
            if entry_price <= 0: continue
            
            levels = exit_levels(entry_price)
            token_addr = TOKEN_BY_SYMBOL.get(symbol)
            if not token_addr: continue

            # Update ATH (All Time High) for trailing logic
            if cur_price > pos.get('ath', 0):
                update_position_state(symbol, "ath", cur_price)
                pos['ath'] = cur_price # Update local var too

            # 1. Stop Loss (Full Exit)
            if cur_price <= levels['sl']:
                print(f"🛑 SL Triggered for {symbol}")
                tx = client.sell_for_usdc(token_addr=token_addr, amount=pos['amount'])
                record_trade(f"{symbol}/USDC", "SELL", 0, pos['amount']*cur_price, cur_price, tx)
                sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
                continue

            # 2. TP1 (Sell 30%)
            if cur_price >= levels['tp1'] and not pos.get('tp1_hit'):
                sell_amt = pos['amount'] * 0.30
                print(f"💰 TP1 Hit! Selling 30% of {symbol}")
                tx = client.sell_for_usdc(token_addr=token_addr, amount=sell_amt)
                record_trade(f"{symbol}/USDC", "SELL", 0, sell_amt*cur_price, cur_price, tx)
                update_position_state(symbol, "tp1_hit", 1)
                sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)

            # 3. TP2 (Sell 30%)
            if cur_price >= levels['tp2'] and not pos.get('tp2_hit'):
                sell_amt = pos['amount'] * 0.30
                print(f"💰 TP2 Hit! Selling 30% of {symbol}")
                tx = client.sell_for_usdc(token_addr=token_addr, amount=sell_amt)
                record_trade(f"{symbol}/USDC", "SELL", 0, sell_amt*cur_price, cur_price, tx)
                update_position_state(symbol, "tp2_hit", 1)
                sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)

            # 4. Trailing TP (Final 40%) - Activates after TP2
            if pos.get('tp2_hit'):
                ath = pos.get('ath', cur_price)
                if cur_price <= (ath * (1 - TRAILING_PERCENT)):
                    print(f"📈 Trailing Stop Hit! Selling final {symbol}")
                    tx = client.sell_for_usdc(token_addr=token_addr, amount=pos['amount'])
                    record_trade(f"{symbol}/USDC", "SELL", 0, pos['amount']*cur_price, cur_price, tx)
                    sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)

        # --- PART 2: SCAN FOR NEW ENTRIES ---
        if can_trade(state):
            pairs = get_safe_pairs()
            if isinstance(pairs, list):
                for p in pairs:
                    # (Standard validation logic)
                    symbols = [p["token0"].get("symbol"), p["token1"].get("symbol")]
                    if "USDC" not in symbols: continue
                    symbol = symbols[0] if symbols[1] == "USDC" else symbols[1]
                    
                    # Don't buy if already holding
                    if any(ap['asset'] == symbol for ap in active_pos): continue

                    # Check strategy
                    df_htf = load_ohlcv(symbol, "4h")
                    df_ltf = load_ohlcv(symbol, "15m")
                    if df_htf is not None and htf_ok(df_htf) and entry_ok(df_ltf):
                        print(f"🟢 Buying {symbol}")
                        tx = client.buy_with_usdc(token_addr=TOKEN_BY_SYMBOL[symbol], usdc_amount=TRADE_USDC_AMOUNT)
                        record_trade(f"{symbol}/USDC", "BUY", TRADE_USDC_AMOUNT, 0, get_price(symbol), tx)
                        sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
                        time.sleep(10)

        time.sleep(LOOP_SLEEP)
    except Exception as e:
        print(f"❌ Bot Loop Error: {e}")
        time.sleep(30)
