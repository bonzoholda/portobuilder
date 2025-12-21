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
UNISWAP_V3_QUOTER = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e" 

# Missing ABI added here
QUOTER_ABI = '[{"inputs":[{"components":[{"internalType":"address","name":"tokenIn","type":"address"},{"internalType":"address","name":"tokenOut","type":"address"},{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint24","name":"fee","type":"uint24"},{"internalType":"uint160","name":"sqrtPriceLimitX96","type":"uint160"}],"name":"params","type":"tuple"}],"name":"quoteExactInputSingle","outputs":[{"internalType":"uint256","name":"amountOut","type":"uint256"},{"internalType":"uint160","name":"sqrtPriceX96After","type":"uint160"},{"internalType":"uint32","name":"initializedTicksCrossed","type":"uint32"},{"internalType":"uint256","name":"gasEstimate","type":"uint256"}],"stateMutability":"nonpayable","type":"function"}]'

getcontext().prec = 50

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
        base_fee = latest["baseFeePerGas"]
        # High priority for Polygon to ensure it beats the simulation lag
        priority = self.w3.to_wei(60, 'gwei') 
        return {
            "maxFeePerGas": int(base_fee * 1.5) + priority, 
            "maxPriorityFeePerGas": priority,
            "type": 2 # Explicitly EIP-1559
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

        # 1. FIND BEST PATH
        print(f"🔍 Finding best path for {amount_in} units...")
        best_fee, expected_out = 0, 0
        for fee in [500, 3000, 10000]:
            try:
                # Quoter V2 call
                quote = self.quoter.functions.quoteExactInputSingle({
                    "tokenIn": token_in, "tokenOut": token_out,
                    "amountIn": amount_in_wei, "fee": fee, "sqrtPriceLimitX96": 0
                }).call()
                if quote[0] > expected_out:
                    expected_out, best_fee = quote[0], fee
            except: continue

        if expected_out == 0:
            raise RuntimeError("❌ No liquidity found in any pool.")
        
        print(f"✅ Route: {best_fee} fee | Est. Out: {expected_out/10**18:.6f}")

        # 2. APPROVAL
        self._force_approve(token_in, amount_in_wei)

        # 3. BUILD TRANSACTION
        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": best_fee,
            "recipient": WALLET_ADDRESS,
            "deadline": int(time.time()) + 600,
            "amountIn": amount_in_wei,
            "amountOutMinimum": int(expected_out * 0.98), # 2% slippage
            "sqrtPriceLimitX96": 0
        }

        # Use high manual gas to bypass the 'estimate_gas' revert trap on laggy nodes
        print("🚀 Sending Swap...")
        tx = self.router.functions.exactInputSingle(params).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.nonce,
            "gas": 350_000,
            "chainId": CHAIN_ID,
            **self._get_gas_params()
        })
        self.nonce += 1

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"✅ Sent: {self.w3.to_hex(tx_hash)}")
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def buy_with_usdc(self, token, usdc_amount):
        return self.swap_exact_input(USDC, token, usdc_amount)

    def sell_to_usdc(self, token, token_amount):
        return self.swap_exact_input(token, USDC, token_amount)
