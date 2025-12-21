import time
import random
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from pair_scanner import get_safe_pairs
from strategy import htf_ok, entry_ok
from uniswap_v3 import UniswapV3Client
from state import init_db, record_trade, load_state, update_pnl, set_meta
from ohlcv import load_ohlcv
from token_list import TOKEN_BY_SYMBOL

# ================= CONFIG =================

TRADE_USDC_AMOUNT = 2.4
LAST_TRADE_COOLDOWN = 1800       # 30 minutes
MAX_DAILY_LOSS = -1.5            # USDC
LOOP_SLEEP = 300                 # 5 minutes

# ================= INIT ===================

init_db()
client = UniswapV3Client()

last_trade_ts = {}  # in-memory cooldown tracking

print("✅ Bot started")

# ================= HELPERS =================

def utc_day():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ================= MAIN LOOP =================

while True:
    try:
        state = load_state()
        daily_pnl = state["daily_pnl"]

        set_meta(
            network="polygon",
            base="USDC",
            date=utc_day(),
            daily_pnl=daily_pnl
        )

        # 🔴 KILL SWITCH
        if daily_pnl <= MAX_DAILY_LOSS:
            print(f"🛑 Kill switch triggered: {daily_pnl:.2f} USDC")
            time.sleep(86400)
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

            last_ts = last_trade_ts.get(symbol, 0)
            if time.time() - last_ts < LAST_TRADE_COOLDOWN:
                continue

            df_htf = load_ohlcv(symbol, "4h")
            df_ltf = load_ohlcv(symbol, "15m")

            if not htf_ok(df_htf):
                continue

            if not entry_ok(df_ltf):
                continue

            token_addr = TOKEN_BY_SYMBOL[symbol]

            print(f"🟢 BUY {symbol}")

            tx_hash = client.buy_with_usdc(
                token_addr,
                TRADE_USDC_AMOUNT
            )

            record_trade(
                side="BUY",
                symbol=symbol,
                amount=TRADE_USDC_AMOUNT,
                tx_hash=tx_hash
            )

            # No realized PnL yet (BUY only)
            last_trade_ts[symbol] = int(time.time())

            time.sleep(random.randint(5, 25))

        time.sleep(LOOP_SLEEP)

    except Exception as e:
        print("❌ Bot error:", str(e))
        time.sleep(30)
