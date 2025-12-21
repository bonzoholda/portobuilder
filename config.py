import os
from dotenv import load_dotenv

load_dotenv()

CHAIN_ID = int(os.getenv("CHAIN_ID", 137))

RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")

if not RPC_URL or not PRIVATE_KEY or not WALLET_ADDRESS:
    raise RuntimeError("Missing environment variables")

# ================= TOKENS =================

USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# ================= UNISWAP V3 =================

UNISWAP_V3_ROUTER = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"

SLIPPAGE = 0.003          # 0.3%
MAX_PRICE_IMPACT_BPS = 30


# Capital management (for $20)
POSITION_SIZE = 0.12       # 12% per trade
MAX_POSITIONS = 2

MAX_DAILY_LOSS = 0.01      # 1%


# Pair safety
MIN_TVL = 5_000_000
MIN_VOLUME = 500_000

# Timeframes (using offchain OHLCV)
HTF = "4h"
LTF = "15m"
