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
        # Increase priority to 70 Gwei to beat Polygon's internal state lag
        priority = self.w3.to_wei(70, 'gwei') 
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

        # 1. THE "CLEAN" APPROVAL
        # We check the allowance, if it's not effectively infinite, we reset it.
        allowance = erc20.functions.allowance(WALLET_ADDRESS, UNISWAP_V3_ROUTER).call()
        if allowance < amount_in_wei:
            print(f"🔓 Updating Allowance for Native USDC...")
            # Using a specific large hex value that Native USDC prefers
            max_val = 0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
            tx = erc20.functions.approve(UNISWAP_V3_ROUTER, max_val).build_transaction({
                "from": WALLET_ADDRESS, "nonce": self.nonce, "gas": 60000, **self._get_gas_params()
            })
            self.nonce += 1
            self.w3.eth.send_raw_transaction(self.account.sign_transaction(tx).rawTransaction)
            print("⏳ Approval sent. Waiting 20 seconds for Polygon state sync...")
            time.sleep(20) # Native USDC on Polygon is slow to register approvals

        # 2. ENCODING THE SWAP
        # We will use the exactInputSingle parameters
        deadline = int(time.time()) + 600
        
        # Try the 3000 fee (0.3%) for Native USDC, as 500 (0.05%) often lacks depth for Native
        # Let's try 3000 this time to rule out liquidity gaps
        fee_tier = 3000 

        params = (
            token_in,
            token_out,
            fee_tier,
            WALLET_ADDRESS,
            deadline,
            amount_in_wei,
            0, # amountOutMinimum
            0  # sqrtPriceLimitX96
        )

        print(f"🚀 Swapping {amount_in} USDC via Tier {fee_tier}...")
        
        # 3. EXECUTION WITH HIGH GAS
        # We use 500,000 gas to ensure it never runs out during the complex V3 internal logic
        tx = self.router.functions.exactInputSingle(params).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.nonce,
            "gas": 500000,
            **self._get_gas_params()
        })
        self.nonce += 1
        
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"✅ Sent! Hash: {self.w3.to_hex(tx_hash)}")
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def buy_with_usdc(self, token, usdc_amount):
        return self.swap_exact_input(USDC, token, usdc_amount)

    def sell_to_usdc(self, token, token_amount):
        return self.swap_exact_input(token, USDC, token_amount)
