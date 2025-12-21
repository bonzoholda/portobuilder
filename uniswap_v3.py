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

# The Universal Router is often more successful with Native USDC on Polygon
UNIVERSAL_ROUTER = "0xec7BE89e9d109e7e3F35945244C187c72F02aB5e"
# We use the standard SwapRouter02 ABI for compatibility
SWAP_ROUTER_ABI = '[{"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"address","name":"recipient","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMinimum","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"exactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]'
UNISWAP_V3_QUOTER = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e"

# Missing ABI added here
QUOTER_ABI = '[{"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"params","type":"tuple"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceX96After","type":"uint160"},{"internalType":"uint32","name":"initializedTicksCrossed","type":"uint32"},{"internalType":"uint256","name":"gasEstimate","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]'


class UniswapV3Client:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        from web3.middleware import geth_poa_middleware
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        
        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        # Using the standard V3 Router address which is most reliable for exactInputSingle
        self.router_address = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
        self.router = self.w3.eth.contract(address=self.router_address, abi=SWAP_ROUTER_ABI)
        self.nonce = self.w3.eth.get_transaction_count(WALLET_ADDRESS)

    def _get_gas_params(self):
        latest = self.w3.eth.get_block("latest")
        priority = self.w3.to_wei(80, 'gwei') # Very high priority to ensure state sync
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

        # 1. THE "CLEAN SLATE" APPROVAL
        # Native USDC sometimes fails if an allowance already exists. 
        # We will check if it's already approved to the Router.
        allowance = erc20.functions.allowance(WALLET_ADDRESS, self.router_address).call()
        if allowance < amount_in_wei:
            print("🔓 Approving Router for Native USDC...")
            approve_tx = erc20.functions.approve(self.router_address, 10**30).build_transaction({
                "from": WALLET_ADDRESS, "nonce": self.nonce, "gas": 70000, **self._get_gas_params()
            })
            self.nonce += 1
            h = self.w3.eth.send_raw_transaction(self.account.sign_transaction(approve_tx).rawTransaction)
            self.w3.eth.wait_for_transaction_receipt(h)
            time.sleep(15)

        # 2. THE SWAP
        # Using 500 fee tier but with the original V3 Router address
        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": 500,
            "recipient": WALLET_ADDRESS,
            "deadline": int(time.time()) + 600,
            "amountIn": amount_in_wei,
            "amountOutMinimum": 0,
            "sqrtPriceLimitX96": 0
        }

        print(f"🚀 Attempting Swap via Router {self.router_address}...")
        tx = self.router.functions.exactInputSingle(params).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.nonce,
            "gas": 300000,
            **self._get_gas_params()
        })
        self.nonce += 1
        
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"✅ Transaction Sent: {self.w3.to_hex(tx_hash)}")
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def buy_with_usdc(self, token, usdc_amount):
        return self.swap_exact_input(USDC, token, usdc_amount)

    def sell_to_usdc(self, token, token_amount):
        return self.swap_exact_input(token, USDC, token_amount)
