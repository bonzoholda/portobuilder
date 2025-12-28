import os
import time
import sqlite3
import requests
import logging
import json
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from pair_scanner import get_safe_pairs
from strategy import htf_ok, entry_ok, exit_levels
from risk import load_state, can_trade
from uniswap_v3 import UniswapV3Client
from state import (
    init_db,
    record_trade,
    set_meta,
    get_meta,
    set_balance,
    snapshot_portfolio
)
from ohlcv import load_ohlcv
from token_list import TOKEN_BY_SYMBOL

from baseline import (
    calculate_trade_size,
    check_and_update_baseline,
    get_or_init_baseline
)
from portfolio import get_portfolio_value, visualize_portfolio

from web3 import Web3
from uniswap_abi import ERC20_ABI
from config import WALLET_ADDRESS, USDC

# ================= LOGGING =================
log_file = 'bot_activity.log'
file_handler = RotatingFileHandler(log_file, maxBytes=100 * 1024, backupCount=0)
formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%H:%M:%S')
file_handler.setFormatter(formatter)

logger = logging.getLogger("BotLogger")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)

def log_activity(msg):
    logger.info(msg)
    print(f"DEBUG: {msg}")

# ================= INIT =================
init_db()

DECIMALS = {"USDC": 6, "WBTC": 8, "WBTC.e": 8}
TOKENS_TO_TRACK = [("MATIC", "MATIC", 18), ("USDC", USDC, 6)]

for symbol, addr in TOKEN_BY_SYMBOL.items():
    decimal = DECIMALS.get(symbol, 18)
    if (symbol, addr, decimal) not in TOKENS_TO_TRACK:
        TOKENS_TO_TRACK.append((symbol, addr, decimal))

LAST_TRADE_COOLDOWN = 600
MAX_DAILY_LOSS = -5.5
LOOP_SLEEP = 60
TRAILING_PERCENT = 0.005
PORTFOLIO_TRAILING_PCT = 0.05

SNAPSHOT_FILE = Path("portfolio_snapshots.json")
SNAPSHOT_INTERVAL = 300
MAX_POINTS = 288

client = UniswapV3Client()
log_activity("✅ Bot started with Tiered Exit Strategy & RSI Hook Logic")

baseline = get_or_init_baseline()
log_activity(f"📊 Portfolio baseline initialized at ${baseline:.2f}")

# ================= HELPERS =================

def get_price(symbol):
    if symbol == "USDC":
        return 1.0
    try:
        mapping = {"WMATIC": "POL", "MATIC": "POL", "WETH": "ETH", "WBTC": "BTC"}
        ticker_symbol = mapping.get(symbol.upper(), symbol.upper())
        url = f"https://www.okx.com/api/v5/market/ticker?instId={ticker_symbol}-USDT"
        res = requests.get(url, timeout=5)
        data = res.json()
        if data.get('code') == '0' and data.get('data'):
            return float(data['data'][0]['last'])
    except:
        pass
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
    pnl_dollars = c.fetchone()[0]
    conn.close()
    return pnl_dollars

def sync_balances(w3, wallet, tokens):
    log_activity("🔄 Syncing wallet balances...")
    for symbol, token_addr, decimals in tokens:
        try:
            if token_addr == "MATIC":
                bal = w3.eth.get_balance(wallet) / 1e18
            else:
                erc20 = w3.eth.contract(
                    address=Web3.to_checksum_address(token_addr),
                    abi=ERC20_ABI
                )
                bal = erc20.functions.balanceOf(wallet).call() / (10 ** decimals)

            price = get_price(symbol)
            set_balance(symbol, bal, price)
        except Exception as e:
            log_activity(f"⚠️ Sync error {symbol}: {e}")

def get_active_positions():
    conn = sqlite3.connect("trader.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT * FROM balances
        WHERE amount > 0.00001
        AND asset NOT IN ('USDC','MATIC')
    """)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def update_position_state(symbol, column, value):
    conn = sqlite3.connect("trader.db")
    c = conn.cursor()
    c.execute(f"UPDATE balances SET {column} = ? WHERE asset = ?", (value, symbol))
    conn.commit()
    conn.close()

def snapshot_portfolioGrowth(value: float):
    now = datetime.now(timezone.utc)
    data = []
    if SNAPSHOT_FILE.exists():
        try:
            data = json.loads(SNAPSHOT_FILE.read_text())
        except: data = []

    if not any(d.get("type") == "initial" for d in data):
        data.insert(0, {"type": "initial", "ts": now.isoformat(), "value": round(value, 4)})
        SNAPSHOT_FILE.write_text(json.dumps(data))
        return

    last = next((d for d in reversed(data) if d["type"] == "point"), None)
    if last:
        last_ts = datetime.fromisoformat(last["ts"])
        if (now - last_ts).total_seconds() < SNAPSHOT_INTERVAL:
            return

    data.append({"type": "point", "ts": now.isoformat(), "value": round(value, 4)})
    points = [d for d in data if d["type"] == "point"][-MAX_POINTS:]
    initial = [d for d in data if d["type"] == "initial"][:1]
    SNAPSHOT_FILE.write_text(json.dumps(initial + points))

def wait_for_success(w3, tx_hash, timeout=120):
    hash_str = tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash)
    if not tx_hash: return False
    try:
        log_activity(f"⏳ Waiting for receipt: {hash_str}")
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
        if receipt.status == 1:
            log_activity(f"✅ Transaction confirmed successful: {hash_str}")
            return True
        else:
            log_activity(f"❌ Transaction REVERTED on-chain: {hash_str}")
            return False
    except Exception as e:
        log_activity(f"⚠️ Error verifying transaction {hash_str}: {e}")
        return False

# ================= START =================
log_activity("🔄 Performing initial balance sync...")
sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
log_activity("✅ Initial sync complete")

# ================= MAIN LOOP =================
while True:
    try:
        log_activity("🔍 --- Starting New Scan Cycle ---")
        portfolio_value = get_portfolio_value()
        
        snapshot_portfolio(realized_pnl=get_meta("realized_pnl", 0))
        snapshot_portfolioGrowth(portfolio_value)
        
        baseline = get_meta("portfolio_baseline", 0)
        
        # Self-heal baseline if zero
        if baseline <= 0 and portfolio_value > 0:
            baseline = portfolio_value
            set_meta("portfolio_baseline", baseline)
            log_activity(f"🌱 Baseline initialized to ${baseline:.2f}")

        visualize_portfolio(baseline, portfolio_value)
        state = load_state()

        # ================= RISK MANAGEMENT =================
        daily_pnl_dollars = get_daily_pnl()
        set_meta("daily_pnl", daily_pnl_dollars)
        
        pnl_percentage = (daily_pnl_dollars / baseline * 100) if baseline > 0 else 0
        log_activity(f"📈 Daily PnL: ${daily_pnl_dollars:.2f} ({pnl_percentage:.2f}%)")

        # Trading Halt logic (Soft lock)
        trading_halted = (pnl_percentage <= MAX_DAILY_LOSS) and (daily_pnl_dollars < 0)

        if trading_halted:
            log_activity(f"⚠️ RISK HALT: Entry logic paused. Monitoring exits only.")

        # ================= PORTFOLIO TRAILING =================
        ath = get_meta("portfolio_ath", 0)
        if portfolio_value > ath:
            set_meta("portfolio_ath", portfolio_value)
            ath = portfolio_value 

        if ath > 0 and portfolio_value <= ath * (1 - PORTFOLIO_TRAILING_PCT):
            log_activity(f"🚨 PORTFOLIO TRAILING STOP HIT")
            for pos in get_active_positions():
                symbol = pos['asset']
                try:
                    tx = client.sell_for_usdc(TOKEN_BY_SYMBOL[symbol], pos['amount'])
                    if wait_for_success(client.w3, tx):
                        record_trade(f"{symbol}/USDC", "SELL", 0, pos['amount'] * get_price(symbol), get_price(symbol), tx)
                except Exception as e:
                    log_activity(f"⚠️ Emergency sell failed {symbol}: {e}")
            
            sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
            set_meta("portfolio_ath", get_portfolio_value())
            time.sleep(600)
            continue

        # ================= EXITS & BREAK-EVEN SHIELD =================
        for pos in get_active_positions():
            symbol = pos['asset']
            cur_price = get_price(symbol)
            entry_price = pos['price']
            levels = exit_levels(entry_price)
            
            # Genius Shield: Move SL to Break-even if up 0.5%
            price_change = (cur_price - entry_price) / entry_price
            current_sl = levels['sl']
            
            if price_change > 0.009:
                # Shield active: cannot lose on this trade anymore
                current_sl = max(current_sl, entry_price * 1.001) 
            
            if cur_price <= current_sl:
                try:
                    tx = client.sell_for_usdc(TOKEN_BY_SYMBOL[symbol], pos['amount'])
                    if wait_for_success(client.w3, tx):
                        record_trade(f"{symbol}/USDC", "SELL", 0, pos['amount'] * cur_price, cur_price, tx)
                        sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
                except Exception as e:
                    log_activity(f"⚠️ Exit failed {symbol}: {e}")
                    
        # ================= ENTRIES (RSI HOOK LOGIC) =================
        if can_trade(state) and not trading_halted:
            active_assets = {ap['asset'] for ap in get_active_positions()}
            for p in get_safe_pairs() or []:
                symbols = [p["token0"]["symbol"], p["token1"]["symbol"]]
                if "USDC" not in symbols: continue
                symbol = symbols[0] if symbols[1] == "USDC" else symbols[1]
                
                if symbol in active_assets: continue
                
                df = load_ohlcv(symbol, "15m")
                if df is None or len(df) < 20: continue
                
                # RSI Calculation
                delta = df["close"].diff()
                gain = delta.clip(lower=0).rolling(14).mean()
                loss = (-delta.clip(upper=0)).rolling(14).mean()
                rsi = 100 - (100 / (1 + (gain / loss)))
                
                rsi_val = rsi.iloc[-1]
                rsi_prev = rsi.iloc[-2]
                
                # GENIUS ENTRY FILTER: RSI Hook + Price Confirmation
                is_oversold = rsi_val < 40
                is_hooking_up = rsi_val > rsi_prev
                price_recovering = df["close"].iloc[-1] > df["close"].iloc[-2]

                if is_oversold and is_hooking_up and price_recovering:
                    log_activity(f"🎯 RSI Hook Detected for {symbol} at {rsi_val:.2f}")
                    usdc_amount = calculate_trade_size()
                    if usdc_amount >= 1:
                        try:
                            tx = client.buy_with_usdc(TOKEN_BY_SYMBOL[symbol], usdc_amount)
                            if wait_for_success(client.w3, tx):
                                record_trade(f"{symbol}/USDC", "BUY", usdc_amount, 0, get_price(symbol), tx, strategy_tag="rsi_hook_scalp")
                                sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
                        except Exception as e:
                            log_activity(f"⚠️ Buy failed {symbol}: {e}")
                else:
                    # Log scanning but not entry
                    if time.time() % 300 < 60: # Log only once every 5 mins to keep logs clean
                         log_activity(f"🔍 {symbol} | RSI: {rsi_val:.1f} (No Hook)")

        elif trading_halted:
            log_activity("🚫 Skipping scan: Daily loss limit active.")

        log_activity(f"😴 Cycle complete. Sleeping {LOOP_SLEEP}s.")
        time.sleep(LOOP_SLEEP)

    except Exception as e:
        log_activity(f"❌ Bot Loop Error: {e}")
        time.sleep(30)
