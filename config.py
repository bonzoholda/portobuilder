# Polygon Mainnet
CHAIN_ID = 137
RPC_URL = "https://polygon-rpc.com"

WALLET_ADDRESS = "0xYOUR_WALLET"
PRIVATE_KEY = "YOUR_PRIVATE_KEY"

BASE_TOKEN = "USDC"

# Capital management (for $20)
POSITION_SIZE = 0.12       # 12% per trade
MAX_POSITIONS = 2

MAX_DAILY_LOSS = 0.01      # 1%
SLIPPAGE = 0.003           # 0.3%

# Pair safety
MIN_TVL = 5_000_000
MIN_VOLUME = 500_000

# Timeframes (using offchain OHLCV)
HTF = "4h"
LTF = "15m"
