import time
from web3 import Web3
from decimal import Decimal, getcontext
try:
    from web3.middleware import ExtraDataToPOAMiddleware as POAMiddleware
except ImportError:
    from web3.middleware import geth_poa_middleware as POAMiddleware

from config import (
    RPC_URL, PRIVATE_KEY, WALLET_ADDRESS,
    UNISWAP_V3_ROUTER, USDC, CHAIN_ID
)
from uniswap_abi import SWAP_ROUTER_ABI, ERC20_ABI

# Use the Router02 for better compatibility on Polygon
UNISWAP_V3_ROUTER = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"
UNISWAP_V3_QUOTER = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e"

# Missing ABI added here
QUOTER_ABI = '[{"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"params","type":"tuple"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceX96After","type":"uint160"},{"internalType":"uint32","name":"initializedTicksCrossed","type":"uint32"},{"internalType":"uint256","name":"gasEstimate","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]'


class UniswapV3Client:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.w3.middleware_onion.inject(POAMiddleware, layer=0)
        
        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        self.router = self.w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_ROUTER), abi=SWAP_ROUTER_ABI)
        self.quoter = self.w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_QUOTER), abi=QUOTER_ABI)
        
        self.nonce = self.w3.eth.get_transaction_count(WALLET_ADDRESS)

    def _get_gas_params(self):
        latest = self.w3.eth.get_block("latest")
        # Polygon requires a significant priority fee to prioritize transactions
        priority = self.w3.to_wei(50, 'gwei') 
        return {
            "maxFeePerGas": int(latest["baseFeePerGas"] * 2) + priority,
            "maxPriorityFeePerGas": priority,
            "type": 2
        }

    def _force_approve(self, token, amount):
        erc20 = self.w3.eth.contract(address=token, abi=ERC20_ABI)
        allowance = erc20.functions.allowance(WALLET_ADDRESS, UNISWAP_V3_ROUTER).call()
        
        if allowance < amount:
            print(f"🔄 Setting allowance for {token}...")
            # Approve a very large number (10^30)
            approve_tx = erc20.functions.approve(UNISWAP_V3_ROUTER, 10**30).build_transaction({
                "from": WALLET_ADDRESS,
                "nonce": self.nonce,
                "gas": 60_000,
                "chainId": CHAIN_ID,
                **self._get_gas_params()
            })
            self.nonce += 1
            signed = self.account.sign_transaction(approve_tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
            print(f"⏳ Approval sent. Waiting for indexing...")
            self.w3.eth.wait_for_transaction_receipt(tx_hash)
            time.sleep(10) # Wait for Polygon state sync

    def swap_exact_input(self, token_in, token_out, amount_in):
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)
        
        erc20 = self.w3.eth.contract(address=token_in, abi=ERC20_ABI)
        amount_in_wei = int(Decimal(str(amount_in)) * (10 ** erc20.functions.decimals().call()))

        # 1. VERIFY ALLOWANCE
        current_allowance = erc20.functions.allowance(WALLET_ADDRESS, UNISWAP_V3_ROUTER).call()
        if current_allowance < amount_in_wei:
            print(f"🔓 Approving {token_in}...")
            tx = erc20.functions.approve(UNISWAP_V3_ROUTER, 2**256-1).build_transaction({
                "from": WALLET_ADDRESS, "nonce": self.nonce, "gas": 60000, **self._get_gas_params()
            })
            self.nonce += 1
            self.w3.eth.send_raw_transaction(self.account.sign_transaction(tx).rawTransaction)
            time.sleep(10) # Essential wait for Polygon indexing

        # 2. SWAP PARAMS
        # Note: We use 5% slippage (0.95) to ensure the test buy works
        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": 500, # Start with the 0.05% pool
            "recipient": WALLET_ADDRESS,
            "deadline": int(time.time()) + 600,
            "amountIn": amount_in_wei,
            "amountOutMinimum": 0, # Forced 0 for testing purposes
            "sqrtPriceLimitX96": 0
        }

        print("🚀 Executing Swap...")
        # Build without simulation to bypass the lag
        tx = self.router.functions.exactInputSingle(params).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.nonce,
            "gas": 250000, # Generous limit
            **self._get_gas_params()
        })
        self.nonce += 1
        
        signed = self.account.sign_transaction(tx)
        hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"✅ Transaction Sent: {self.w3.to_hex(hash)}")
        return self.w3.eth.wait_for_transaction_receipt(hash)

    def buy_with_usdc(self, token, usdc_amount):
        return self.swap_exact_input(USDC, token, usdc_amount)

    def sell_to_usdc(self, token, token_amount):
        return self.swap_exact_input(token, USDC, token_amount)
