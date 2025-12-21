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

# Uniswap V3 Factory is required to find valid pools
UNISWAP_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
FACTORY_ABI = '[{"inputs":[{"internalType":"address","name":"","type":"address"},{"internalType":"address","name":"","type":"address"},{"internalType":"uint24","name":"","type":"uint24"}],"name":"getPool","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}]'

getcontext().prec = 50

class UniswapV3Client:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.w3.middleware_onion.inject(POAMiddleware, layer=0)
        
        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        self.router = self.w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_ROUTER), abi=SWAP_ROUTER_ABI)
        self.factory = self.w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_V3_FACTORY), abi=FACTORY_ABI)
        
        self.nonce = self.w3.eth.get_transaction_count(WALLET_ADDRESS)

    def _get_eip1559_params(self):
        latest = self.w3.eth.get_block("latest")
        base_fee = latest["baseFeePerGas"]
        priority = self.w3.to_wei(35, 'gwei')
        return {"maxFeePerGas": (2 * base_fee) + priority, "maxPriorityFeePerGas": priority}

    def _find_best_fee(self, token_in, token_out):
        """Checks the 3 most common fee tiers to find a valid pool."""
        for fee in [500, 3000, 10000]:
            pool = self.factory.functions.getPool(token_in, token_out, fee).call()
            if pool != "0x0000000000000000000000000000000000000000":
                return fee
        return None

    def swap_exact_input(self, token_in, token_out, amount_in):
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)

        # 1. Automatic Fee Discovery
        fee = self._find_best_fee(token_in, token_out)
        if not fee:
            raise RuntimeError(f"❌ No pool found for {token_in} -> {token_out}")
        print(f"🔍 Found pool with fee tier: {fee}")

        # 2. Balance & Decimals
        erc20 = self.w3.eth.contract(address=token_in, abi=ERC20_ABI)
        decimals = erc20.functions.decimals().call()
        amount_in_wei = int(Decimal(str(amount_in)) * (10 ** decimals))
        
        balance = erc20.functions.balanceOf(WALLET_ADDRESS).call()
        if balance < amount_in_wei:
            raise RuntimeError(f"❌ Balance too low. Have {balance}, Need {amount_in_wei}")

        # 3. Approval
        self._approve_if_needed(token_in, amount_in_wei)

        # 4. Params
        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": fee,
            "recipient": WALLET_ADDRESS,
            "deadline": int(time.time()) + 600,
            "amountIn": amount_in_wei,
            "amountOutMinimum": 0,
            "sqrtPriceLimitX96": 0
        }

        # 5. Simulation with Retry (Handles RPC lag)
        swap_fn = self.router.functions.exactInputSingle(params)
        for attempt in range(3):
            try:
                swap_fn.call({"from": WALLET_ADDRESS})
                break
            except Exception as e:
                if attempt == 2: raise RuntimeError(f"❌ Simulation still failing: {e}")
                print(f"🔄 Syncing state... (Attempt {attempt+1}/3)")
                time.sleep(3)

        # 6. Build & Send
        gas_params = self._get_eip1559_params()
        tx = swap_fn.build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.nonce,
            "gas": 400_000,
            "chainId": CHAIN_ID,
            **gas_params
        })
        self.nonce += 1

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"🚀 Swap Sent: {self.w3.to_hex(tx_hash)}")
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def _approve_if_needed(self, token, amount):
        erc20 = self.w3.eth.contract(address=token, abi=ERC20_ABI)
        if erc20.functions.allowance(WALLET_ADDRESS, UNISWAP_V3_ROUTER).call() < amount:
            print("🔓 Approving...")
            tx = erc20.functions.approve(UNISWAP_V3_ROUTER, amount * 10).build_transaction({
                "from": WALLET_ADDRESS, "nonce": self.nonce, "gas": 60_000, 
                "chainId": CHAIN_ID, **self._get_eip1559_params()
            })
            self.nonce += 1
            signed = self.account.sign_transaction(tx)
            h = self.w3.eth.send_raw_transaction(signed.rawTransaction)
            self.w3.eth.wait_for_transaction_receipt(h)

    # -------------------------
    # Convenience wrappers
    # -------------------------

    def buy_with_usdc(self, token, usdc_amount):
        """Wrapper to buy a token using USDC."""
        print(f"💰 [BUY] USDC → {token} | Amount: ${usdc_amount}")
        return self.swap_exact_input(
            token_in=USDC,
            token_out=token,
            amount_in=usdc_amount
        )

    def sell_to_usdc(self, token, token_amount):
        """Wrapper to sell a token back to USDC."""
        print(f"k [SELL] {token} → USDC | Amount: {token_amount}")
        return self.swap_exact_input(
            token_in=token,
            token_out=USDC,
            amount_in=token_amount
        )
