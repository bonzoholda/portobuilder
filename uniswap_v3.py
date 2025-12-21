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
UNISWAP_V3_QUOTER = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e" 

FACTORY_ABI = '[{"inputs":[{"internalType":"address","name":"","type":"address"},{"internalType":"address","name":"","type":"address"},{"internalType":"uint24","name":"","type":"uint24"}],"name":"getPool","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}]'
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

    def _get_eip1559_params(self):
        latest = self.w3.eth.get_block("latest")
        base_fee = latest["baseFeePerGas"]
        # Aggressive priority for Polygon (60 Gwei)
        priority = self.w3.to_wei(60, 'gwei') 
        return {"maxFeePerGas": (2 * base_fee) + priority, "maxPriorityFeePerGas": priority}

    def _approve_if_needed(self, token, amount):
        erc20 = self.w3.eth.contract(address=token, abi=ERC20_ABI)
        allowance = erc20.functions.allowance(WALLET_ADDRESS, UNISWAP_V3_ROUTER).call()
        
        if allowance < amount:
            print(f"🔓 Allowance insufficient. Sending approval...")
            # Using a large but standard number instead of max_uint256
            approval_amount = 10**30 
            tx = erc20.functions.approve(UNISWAP_V3_ROUTER, approval_amount).build_transaction({
                "from": WALLET_ADDRESS,
                "nonce": self.nonce,
                "gas": 70_000,
                "chainId": CHAIN_ID,
                **self._get_eip1559_params()
            })
            self.nonce += 1
            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
            print(f"⏳ Approval sent: {self.w3.to_hex(tx_hash)}. Waiting for indexing...")
            self.w3.eth.wait_for_transaction_receipt(tx_hash)
            time.sleep(15) # Extended wait for Polygon state propagation

    def swap_exact_input(self, token_in, token_out, amount_in):
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)

        # 1. SETUP
        erc20 = self.w3.eth.contract(address=token_in, abi=ERC20_ABI)
        decimals = erc20.functions.decimals().call()
        amount_in_wei = int(Decimal(str(amount_in)) * (10 ** decimals))

        # 2. QUOTE & FEE DISCOVERY
        best_fee = 0
        expected_out = 0
        for f in [500, 3000, 10000]:
            try:
                out = self.quoter.functions.quoteExactInputSingle({
                    "tokenIn": token_in, "tokenOut": token_out,
                    "amountIn": amount_in_wei, "fee": f, "sqrtPriceLimitX96": 0
                }).call()
                if out[0] > expected_out:
                    expected_out = out[0]
                    best_fee = f
            except: continue

        if expected_out == 0:
            raise RuntimeError("❌ No route/liquidity found.")

        # 3. APPROVAL
        self._approve_if_needed(token_in, amount_in_wei)

        # 4. SWAP PARAMS
        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": best_fee,
            "recipient": WALLET_ADDRESS,
            "deadline": int(time.time()) + 600,
            "amountIn": amount_in_wei,
            "amountOutMinimum": 0, # Set to 0 temporarily to force through simulation
            "sqrtPriceLimitX96": 0
        }

        # 5. RETRY SIMULATION (Crucial for Polygon)
        swap_fn = self.router.functions.exactInputSingle(params)
        print("🧪 Testing simulation...")
        
        simulated = False
        for i in range(5):
            try:
                swap_fn.estimate_gas({"from": WALLET_ADDRESS})
                simulated = True
                print("✅ Simulation passed!")
                break
            except Exception as e:
                print(f"🔄 Node state lag (Attempt {i+1}/5). Waiting...")
                time.sleep(5)
        
        if not simulated:
            raise RuntimeError("❌ Contract still reverts. Possible missing balance or allowance sync.")

        # 6. EXECUTE
        tx = swap_fn.build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.nonce,
            "gas": 400_000,
            "chainId": CHAIN_ID,
            **self._get_eip1559_params()
        })
        self.nonce += 1

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"🚀 SUCCESS! Hash: {self.w3.to_hex(tx_hash)}")
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def buy_with_usdc(self, token, usdc_amount):
        return self.swap_exact_input(USDC, token, usdc_amount)
