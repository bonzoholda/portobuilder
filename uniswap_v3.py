import time
from web3 import Web3
from eth_account import Account

from config import (
    RPC_URL,
    PRIVATE_KEY,
    WALLET_ADDRESS,
    UNISWAP_V3_ROUTER,
    USDC,
    SLIPPAGE
)

from uniswap_pool import get_sqrt_price_limit

# ================== ERC20 ABI ==================

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]

# ================== ROUTER ABI ==================

ROUTER_ABI = [
    {
        "inputs": [{
            "components": [
                {"internalType": "address", "name": "tokenIn", "type": "address"},
                {"internalType": "address", "name": "tokenOut", "type": "address"},
                {"internalType": "uint24", "name": "fee", "type": "uint24"},
                {"internalType": "address", "name": "recipient", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
            ],
            "internalType": "struct ISwapRouter.ExactInputSingleParams",
            "name": "params",
            "type": "tuple"
        }],
        "name": "exactInputSingle",
        "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function"
    }
]

# ================== CLIENT ==================

class UniswapClient:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        if not self.w3.is_connected():
            raise RuntimeError("Web3 not connected")

        self.account = Account.from_key(PRIVATE_KEY)
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(UNISWAP_V3_ROUTER),
            abi=ROUTER_ABI
        )

    # ---------- INTERNAL ----------

    def _approve(self, token, amount):
        token = Web3.to_checksum_address(token)
        erc20 = self.w3.eth.contract(token, abi=ERC20_ABI)

        tx = erc20.functions.approve(
            UNISWAP_V3_ROUTER,
            amount
        ).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.w3.eth.get_transaction_count(WALLET_ADDRESS),
            "gas": 120000,
            "gasPrice": self.w3.eth.gas_price,
        })

        signed = self.account.sign_transaction(tx)
        self.w3.eth.send_raw_transaction(signed.rawTransaction)
        time.sleep(3)

    # ---------- PUBLIC ----------

    def buy_with_usdc(self, token_addr, usdc_amount, pool_address=None):
        token_addr = Web3.to_checksum_address(token_addr)

        usdc = self.w3.eth.contract(USDC, abi=ERC20_ABI)
        usdc_decimals = usdc.functions.decimals().call()

        amount_in = int(usdc_amount * (10 ** usdc_decimals))
        min_out = int(amount_in * (1 - SLIPPAGE))

        self._approve(USDC, amount_in)

        sqrt_limit = 0
        if pool_address:
            sqrt_limit = get_sqrt_price_limit(
                self.w3,
                pool_address,
                max_bps=30,
                is_buy=True
            )

        params = (
            USDC,
            token_addr,
            3000,                     # 0.3% fee tier
            WALLET_ADDRESS,
            int(time.time()) + 45,    # short deadline
            amount_in,
            min_out,
            sqrt_limit
        )

        tx = self.router.functions.exactInputSingle(params).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.w3.eth.get_transaction_count(WALLET_ADDRESS),
            "gas": 320000,
            "gasPrice": self.w3.eth.gas_price,
            "value": 0
        })

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)

        return self.w3.to_hex(tx_hash)
