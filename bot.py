import os
import time
import random
import sqlite3
import requests
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from pair_scanner import get_safe_pairs
from strategy import htf_ok, entry_ok
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

# Build the TOKENS_TO_TRACK list dynamically
TOKENS_TO_TRACK = [
    ("MATIC", "MATIC", 18),
    ("USDC", USDC, 6)
]

for symbol, addr in TOKEN_BY_SYMBOL.items():
    decimal = DECIMALS.get(symbol, 18)
    if (symbol, addr, decimal) not in TOKENS_TO_TRACK:
        TOKENS_TO_TRACK.append((symbol, addr, decimal))

TRADE_USDC_AMOUNT = 2.4
LAST_TRADE_COOLDOWN = 1800       # 30 minutes
MAX_DAILY_LOSS = -1.5            # USDC
LOOP_SLEEP = 300                 # 5 minutes

# ================= INIT ===================
client = UniswapV3Client()
print("✅ Bot started")

# ================= HELPERS =================

def get_price(symbol):
    if symbol == "USDC": return 1.0
    try:
        # Improved mapping to CoinGecko IDs
        mapping = {
            "MATIC": "pol", 
            "WMATIC": "pol",
            "WETH": "eth", 
            "ETH": "ethereum",
            "WBTC": "btc",
            "LINK": "link",
            "UNI": "uni"
        }
        coin_id = mapping.get(symbol.upper(), symbol.lower())
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        
        res = requests.get(url, timeout=10)
        data = res.json()
        
        # Safely extract the price
        if coin_id in data and 'usd' in data[coin_id]:
            return float(data[coin_id]['usd'])
        else:
            print(f"⚠️ Price data missing for {coin_id}: {data}")
            return 0.0
    except Exception as e:
        print(f"⚠️ Price fetch error for {symbol}: {e}")
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
            # 1. Get Balance
            if token_addr == "MATIC":
                bal = w3.eth.get_balance(wallet) / 1e18
            else:
                erc20 = w3.eth.contract(address=Web3.to_checksum_address(token_addr), abi=ERC20_ABI)
                bal = erc20.functions.balanceOf(wallet).call() / (10 ** decimals)
            
            # 2. Get Price
            price = get_price(symbol)

            # 3. Save to DB with price
            set_balance(symbol, bal, price)
            
        except Exception as e:
            print(f"⚠️ Error syncing {symbol}: {e}")

# ================= MAIN LOOP =================

# FORCE AN IMMEDIATE SYNC ON STARTUP
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
                if "token0" not in p or "token1" not in p:
                    continue

                symbols = [p["token0"].get("symbol"), p["token1"].get("symbol")]
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

                if df_htf is None or df_ltf is None or df_htf.empty or df_ltf.empty:
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

                # Get price at moment of trade for recording
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
                
                # Update balances immediately after trade
                sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
                time.sleep(random.randint(5, 25))

            except Exception as pair_error:
                print(f"⚠️ Pair skipped due to error: {pair_error}")
                continue

        time.sleep(LOOP_SLEEP)

    except Exception as e:
        print("❌ Bot error:", str(e))
        time.sleep(30)
