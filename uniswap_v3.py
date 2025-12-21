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

# Constants
UNISWAP_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
UNISWAP_V3_QUOTER = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e" # Quoter V2 on Polygon

FACTORY_ABI = '[{"inputs":[{"internalType":"address","name":"","type":"address"},{"internalType":"address","name":"","type":"address"},{"internalType":"uint24","name":"","type":"uint24"}],"name":"getPool","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}]'
QUOTER_ABI = '[{"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"params","type":"tuple"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceX96After","type":"uint160"},{"internalType":"uint32","name":"initializedTicksCrossed","type":"uint32"},{"internalType":"uint256","name":"gasEstimate","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]'

getcontext().prec = 50

class UniswapV3Client:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.w3.middleware_onion.inject(POAMiddleware, layer=0)
        
        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        self.router = self.w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_ROUTER), abi=SWAP_ROUTER_ABI)
        self.factory = self.w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_FACTORY), abi=FACTORY_ABI)
        self.quoter = self.w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_QUOTER), abi=QUOTER_ABI)
        
        self.nonce = self.w3.eth.get_transaction_count(WALLET_ADDRESS)

    def _get_eip1559_params(self):
        latest = self.w3.eth.get_block("latest")
        base_fee = latest["baseFeePerGas"]
        # Polygon gas can spike; using a 50 Gwei priority to ensure inclusion
        priority = self.w3.to_wei(50, 'gwei') 
        return {
            "maxFeePerGas": (2 * base_fee) + priority, 
            "maxPriorityFeePerGas": priority
        }

    def get_quote(self, token_in, token_out, amount_in_wei, fee):
        """Asks the Quoter how much output we get for a specific fee tier."""
        try:
            # quoteExactInputSingle is technically a state-changing call on some chains, 
            # so we use .call() to simulate it without gas costs.
            quote = self.quoter.functions.quoteExactInputSingle({
                "tokenIn": token_in,
                "tokenOut": token_out,
                "amountIn": amount_in_wei,
                "fee": fee,
                "sqrtPriceLimitX96": 0
            }).call()
            return quote[0] # amountOut
        except Exception:
            return 0

    def _approve_if_needed(self, token, amount):
        erc20 = self.w3.eth.contract(address=token, abi=ERC20_ABI)
        allowance = erc20.functions.allowance(WALLET_ADDRESS, UNISWAP_V3_ROUTER).call()
        
        if allowance < amount:
            print(f"🔓 Approving {token}...")
            tx = erc20.functions.approve(UNISWAP_V3_ROUTER, 2**256 - 1).build_transaction({
                "from": WALLET_ADDRESS,
                "nonce": self.nonce,
                "gas": 60_000,
                "chainId": CHAIN_ID,
                **self._get_eip1559_params()
            })
            self.nonce += 1
            signed = self.account.sign_transaction(tx)
            self.w3.eth.send_raw_transaction(signed.rawTransaction)
            print("⏳ Waiting for approval confirmation...")
            time.sleep(10) # Crucial for Polygon state sync

    def swap_exact_input(self, token_in, token_out, amount_in):
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)

        # 1. SETUP AMOUNTS
        erc20 = self.w3.eth.contract(address=token_in, abi=ERC20_ABI)
        decimals = erc20.functions.decimals().call()
        amount_in_wei = int(Decimal(str(amount_in)) * (10 ** decimals))

        # 2. FIND BEST LIQUIDITY PATH
        print(f"🔍 Quoting {amount_in} units for best fee tier...")
        best_fee = 0
        expected_out = 0
        
        # Test 0.05%, 0.3%, and 1%
        for fee in [500, 3000, 10000]:
            out = self.get_quote(token_in, token_out, amount_in_wei, fee)
            if out > expected_out:
                expected_out = out
                best_fee = fee
        
        if expected_out == 0:
            raise RuntimeError("❌ No liquidity found for this pair in any fee tier.")
        
        print(f"✅ Best tier found: {best_fee} (Expected out: {expected_out / 10**18:.6f})")

        # 3. APPROVAL
        self._approve_if_needed(token_in, amount_in_wei)

        # 4. PREPARE SWAP
        # Use a 1% slippage tolerance
        min_out = int(expected_out * 0.99) 

        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": best_fee,
            "recipient": WALLET_ADDRESS,
            "deadline": int(time.time()) + 600,
            "amountIn": amount_in_wei,
            "amountOutMinimum": min_out,
            "sqrtPriceLimitX96": 0
        }

        swap_fn = self.router.functions.exactInputSingle(params)

        # 5. FINAL SIMULATION
        try:
            print("🧪 Simulating transaction...")
            swap_fn.estimate_gas({"from": WALLET_ADDRESS})
        except Exception as e:
            raise RuntimeError(f"❌ Reverted in simulation: {e}")

        # 6. SEND TRANSACTION
        tx = swap_fn.build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.nonce,
            "gas": 300_000,
            "chainId": CHAIN_ID,
            **self._get_eip1559_params()
        })
        self.nonce += 1

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"🚀 Sent: {self.w3.to_hex(tx_hash)}")
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def buy_with_usdc(self, token, usdc_amount):
        return self.swap_exact_input(USDC, token, usdc_amount)

    def sell_to_usdc(self, token, token_amount):
        return self.swap_exact_input(token, USDC, token_amount)
