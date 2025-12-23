import os
import time
import sqlite3
import requests
import logging
import json
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

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
    snapshot_portfolio   # 👈 ADD THIS
)
from ohlcv import load_ohlcv
from token_list import TOKEN_BY_SYMBOL

# ✅ BASELINE / PORTFOLIO (SINGLE SOURCE OF TRUTH)
from baseline import (
    calculate_trade_size,
    check_and_update_baseline,
    get_or_init_baseline
)
from portfolio import get_portfolio_value, visualize_portfolio

from web3 import Web3
from uniswap_abi import ERC20_ABI
from config import WALLET_ADDRESS, USDC
from pathlib import Path

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
MAX_DAILY_LOSS = -1.5
LOOP_SLEEP = 60
TRAILING_PERCENT = 0.005
PORTFOLIO_TRAILING_PCT = 0.03

SNAPSHOT_FILE = Path("portfolio_snapshots.json")
SNAPSHOT_INTERVAL = 300        # 5 minutes
MAX_POINTS = 288               # 24h * 12 points/hr

client = UniswapV3Client()
log_activity("✅ Bot started with Tiered Exit Strategy (30/30/40)")

# ================= BASELINE INIT =================
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
    pnl = c.fetchone()[0]
    conn.close()
    return pnl

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
        data = json.loads(SNAPSHOT_FILE.read_text())

    # 1️⃣ Create initial snapshot if not exists
    if not any(d.get("type") == "initial" for d in data):
        data.insert(0, {
            "type": "initial",
            "ts": now.isoformat(),
            "value": round(value, 4)
        })
        SNAPSHOT_FILE.write_text(json.dumps(data))
        return

    # 2️⃣ Enforce interval (5 min)
    last = next((d for d in reversed(data) if d["type"] == "point"), None)
    if last:
        last_ts = datetime.fromisoformat(last["ts"])
        if (now - last_ts).total_seconds() < SNAPSHOT_INTERVAL:
            return

    # 3️⃣ Append new point
    data.append({
        "type": "point",
        "ts": now.isoformat(),
        "value": round(value, 4)
    })

    # 4️⃣ Keep initial + last 24h points
    points = [d for d in data if d["type"] == "point"][-MAX_POINTS:]
    initial = [d for d in data if d["type"] == "initial"][:1]

    SNAPSHOT_FILE.write_text(json.dumps(initial + points))


# ================= START =================
log_activity("🔄 Performing initial balance sync...")
sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
log_activity("✅ Initial sync complete")

# ================= MAIN LOOP =================
while True:
    try:
        log_activity("🔍 --- Starting New Scan Cycle ---")

        # ✅ PROBE 1 — PORTFOLIO VALUE VISIBILITY
        portfolio_value = get_portfolio_value()
        log_activity(f"📊 Portfolio value = ${portfolio_value:.4f}")
        
        snapshot_portfolio(
            realized_pnl=get_meta("realized_pnl", 0)
        )

        snapshot_portfolioGrowth(portfolio_value)
        
        log_activity(
            f"📊 Baseline ${get_meta('portfolio_baseline', 0):.4f} | "
            f"Current ${portfolio_value:.4f}"
        )


        baseline = get_meta("portfolio_baseline", 0)
        current_value = portfolio_value
        
        visualize_portfolio(baseline, current_value)

        state = load_state()
        daily_pnl = get_daily_pnl()
        set_meta("daily_pnl", daily_pnl)

        # 🔒 BASELINE CHECK
        locked, old_base, new_base = check_and_update_baseline()
        if locked:
            log_activity(f"🔒 Baseline locked: ${old_base:.2f} → ${new_base:.2f}")

        # 🛑 DAILY LOSS KILL
        if daily_pnl <= MAX_DAILY_LOSS:
            log_activity(f"🛑 Daily Loss Limit Hit: {daily_pnl:.2f}. Sleeping 1h.")
            time.sleep(3600)
            continue

        # ================= PORTFOLIO TRAILING =================
        ath = get_meta("portfolio_ath", 0)
        if portfolio_value > ath:
            set_meta("portfolio_ath", portfolio_value)
            log_activity(f"📈 New Portfolio ATH: ${portfolio_value:.2f}")
        else:
            if ath > 0:
                drawdown = (ath - portfolio_value) / ath
                if drawdown >= PORTFOLIO_TRAILING_PCT:
                    log_activity(
                        f"🚨 PORTFOLIO TRAILING STOP HIT ({drawdown*100:.2f}%)"
                    )

                    for pos in get_active_positions():
                        symbol = pos['asset']
                        try:
                            tx = client.sell_for_usdc(
                                TOKEN_BY_SYMBOL[symbol],
                                pos['amount']
                            )
                            record_trade(
                                f"{symbol}/USDC",
                                "SELL",
                                0,
                                pos['amount'] * get_price(symbol),
                                get_price(symbol),
                                tx
                            )
                        except Exception as e:
                            log_activity(f"⚠️ Emergency sell failed {symbol}: {e}")

                    sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
                    set_meta("portfolio_ath", get_portfolio_value())
                    time.sleep(600)
                    continue

        # ================= EXITS =================
        for pos in get_active_positions():
            symbol = pos['asset']
            cur_price = get_price(symbol)
            entry_price = pos['price']
            if entry_price <= 0:
                continue
        
            levels = exit_levels(entry_price)
            token_addr = TOKEN_BY_SYMBOL[symbol]
        
            if cur_price > pos.get('ath', 0):
                update_position_state(symbol, "ath", cur_price)
        
            if cur_price <= levels['sl']:
                tx = client.sell_for_usdc(token_addr, pos['amount'])
                record_trade(
                    f"{symbol}/USDC",
                    "SELL",
                    0,
                    pos['amount'] * cur_price,
                    cur_price,
                    tx
                )
                sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)


        # ================= ENTRIES (MICRO-SCALP MODE) =================
        if can_trade(state):
            active_assets = {ap['asset'] for ap in get_active_positions()}
        
            for p in get_safe_pairs() or []:
                symbols = [p["token0"]["symbol"], p["token1"]["symbol"]]
                log_activity(f">>>>>> Scanning {symbol}")
                time.sleep(5)
                if "USDC" not in symbols:
                    continue
        
                symbol = symbols[0] if symbols[1] == "USDC" else symbols[1]
        
                # One position per asset
                if symbol in active_assets:
                    continue
        
                # ---- Micro-scalp timeframe (SAFE) ----
                df = load_ohlcv(symbol, "15m")
                if df is None or len(df) < 20:
                    continue
        
                # ---- RSI CALC (LOCAL, SAFE) ----
                delta = df["close"].diff()
                gain = delta.clip(lower=0).rolling(14).mean()
                loss = (-delta.clip(upper=0)).rolling(14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                rsi_val = rsi.iloc[-1]
        
                last_close = df["close"].iloc[-1]
                prev_close = df["close"].iloc[-2]

                log_activity(f"{symbol}: rsi {rsi_val:.1f}, last {last_close:.6f}, prev {prev_close:.6f}")
                
                # ---- MICRO-SCALP ENTRY CONDITIONS ----
                if rsi_val > 40:
                    continue
        
                if last_close <= prev_close:
                    continue
        
                usdc_amount = calculate_trade_size()
                if usdc_amount < 1:
                    continue
        
                log_activity(
                    f"⚡ MICRO-SCALP BUY {symbol} | "
                    f"RSI={rsi_val:.1f} | ${usdc_amount:.2f}"
                )
        
                try:
                    tx = client.buy_with_usdc(
                        TOKEN_BY_SYMBOL[symbol],
                        usdc_amount
                    )
        
                    record_trade(
                        f"{symbol}/USDC",
                        "BUY",
                        usdc_amount,
                        0,
                        get_price(symbol),
                        tx,
                        strategy_tag="micro_scalp"
                    )
        
                    sync_balances(client.w3, WALLET_ADDRESS, TOKENS_TO_TRACK)
                    time.sleep(5)
        
                except Exception as e:
                    log_activity(f"⚠️ Buy failed {symbol}: {e}")




        log_activity(f"😴 Cycle complete. Sleeping {LOOP_SLEEP}s.")
        time.sleep(LOOP_SLEEP)

    except Exception as e:
        log_activity(f"❌ Bot Loop Error: {e}")
        time.sleep(30)
