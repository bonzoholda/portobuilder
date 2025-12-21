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

# Modern Quoter V2 address for Polygon
UNISWAP_V3_QUOTER = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e" 

class UniswapV3Client:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.w3.middleware_onion.inject(POAMiddleware, layer=0)
        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        self.router = self.w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_ROUTER), abi=SWAP_ROUTER_ABI)
        self.quoter = self.w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_QUOTER), abi=QUOTER_ABI)
        self.nonce = self.w3.eth.get_transaction_count(WALLET_ADDRESS)

    def _get_gas_params(self):
        # Using higher priority to cut through Polygon congestion
        latest = self.w3.eth.get_block("latest")
        base_fee = latest["baseFeePerGas"]
        priority = self.w3.to_wei(55, 'gwei') 
        return {"maxFeePerGas": (2 * base_fee) + priority, "maxPriorityFeePerGas": priority}

    def _force_approve(self, token, amount):
        erc20 = self.w3.eth.contract(address=token, abi=ERC20_ABI)
        allowance = erc20.functions.allowance(WALLET_ADDRESS, UNISWAP_V3_ROUTER).call()
        
        if allowance < amount:
            print(f"🔄 Resetting and updating allowance for {token}...")
            # Step 1: Reset to 0 (Fixes some non-standard ERC20 issues)
            if allowance > 0:
                reset_tx = erc20.functions.approve(UNISWAP_V3_ROUTER, 0).build_transaction({
                    "from": WALLET_ADDRESS, "nonce": self.nonce, "gas": 50_000, 
                    "chainId": CHAIN_ID, **self._get_gas_params()
                })
                self.w3.eth.send_raw_transaction(self.account.sign_transaction(reset_tx).rawTransaction)
                self.nonce += 1
                time.sleep(5)

            # Step 2: Approve high amount
            approve_tx = erc20.functions.approve(UNISWAP_V3_ROUTER, 10**30).build_transaction({
                "from": WALLET_ADDRESS, "nonce": self.nonce, "gas": 60_000, 
                "chainId": CHAIN_ID, **self._get_gas_params()
            })
            self.nonce += 1
            tx_hash = self.w3.eth.send_raw_transaction(self.account.sign_transaction(approve_tx).rawTransaction)
            print(f"⏳ Waiting for approval: {self.w3.to_hex(tx_hash)}")
            self.w3.eth.wait_for_transaction_receipt(tx_hash)
            time.sleep(12) # State propagation wait

    def swap_exact_input(self, token_in, token_out, amount_in):
        token_in, token_out = Web3.to_checksum_address(token_in), Web3.to_checksum_address(token_out)
        
        # 1. Decimal Handling
        erc20 = self.w3.eth.contract(address=token_in, abi=ERC20_ABI)
        amount_in_wei = int(Decimal(str(amount_in)) * (10 ** erc20.functions.decimals().call()))

        # 2. Get Quote & Verify Path
        print(f"🔍 Finding best path for {amount_in} USDC...")
        best_fee, expected_out = 0, 0
        for fee in [500, 3000, 10000]:
            try:
                # Quoter V2 returns a tuple, [0] is amountOut
                quote = self.quoter.functions.quoteExactInputSingle({
                    "tokenIn": token_in, "tokenOut": token_out,
                    "amountIn": amount_in_wei, "fee": fee, "sqrtPriceLimitX96": 0
                }).call()
                if quote[0] > expected_out:
                    expected_out, best_fee = quote[0], fee
            except: continue

        if expected_out == 0: raise RuntimeError("❌ No liquidity path found.")
        print(f"✅ Route found: Fee {best_fee} | Est. Out: {expected_out/10**18:.6f} WETH")

        # 3. Approval
        self._force_approve(token_in, amount_in_wei)

        # 4. Build Transaction
        # Using 2% slippage for safety
        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": best_fee,
            "recipient": WALLET_ADDRESS,
            "deadline": int(time.time()) + 600,
            "amountIn": amount_in_wei,
            "amountOutMinimum": int(expected_out * 0.98),
            "sqrtPriceLimitX96": 0
        }

        # Use a high manual gas limit to bypass the 'estimate_gas' revert trap
        # Uniswap V3 swaps on Polygon typically cost 140k - 220k gas.
        print("🚀 Sending Swap...")
        tx = self.router.functions.exactInputSingle(params).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.nonce,
            "gas": 300_000,
            "chainId": CHAIN_ID,
            **self._get_gas_params()
        })
        self.nonce += 1

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"✅ Transaction Sent! Hash: {self.w3.to_hex(tx_hash)}")
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)
