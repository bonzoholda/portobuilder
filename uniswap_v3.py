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
        
        # Start with a fresh nonce
        self.nonce = self.w3.eth.get_transaction_count(WALLET_ADDRESS)

    def _get_eip1559_params(self):
        latest = self.w3.eth.get_block("latest")
        base_fee = latest["baseFeePerGas"]
        priority = self.w3.to_wei(40, 'gwei') # High priority for Polygon
        return {"maxFeePerGas": (2 * base_fee) + priority, "maxPriorityFeePerGas": priority}

    def _find_best_fee(self, token_in, token_out):
        for fee in [500, 3000, 10000]:
            pool = self.factory.functions.getPool(token_in, token_out, fee).call()
            if pool != "0x0000000000000000000000000000000000000000":
                return fee
        return None

    def _approve_if_needed(self, token, amount):
        erc20 = self.w3.eth.contract(address=token, abi=ERC20_ABI)
        current_allowance = erc20.functions.allowance(WALLET_ADDRESS, UNISWAP_V3_ROUTER).call()
        
        if current_allowance < amount:
            print(f"🔓 Approving {token} for Swap Router...")
            gas_params = self._get_eip1559_params()
            tx = erc20.functions.approve(UNISWAP_V3_ROUTER, amount * 100).build_transaction({
                "from": WALLET_ADDRESS,
                "nonce": self.nonce,
                "gas": 60_000,
                "chainId": CHAIN_ID,
                **gas_params
            })
            self.nonce += 1
            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
            self.w3.eth.wait_for_transaction_receipt(tx_hash)
            time.sleep(2) # Buffer for state sync

    def swap_exact_input(self, token_in, token_out, amount_in):
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)

        fee = self._find_best_fee(token_in, token_out)
        if not fee: raise RuntimeError("❌ No valid Uniswap V3 pool found.")

        erc20 = self.w3.eth.contract(address=token_in, abi=ERC20_ABI)
        decimals = erc20.functions.decimals().call()
        amount_in_wei = int(Decimal(str(amount_in)) * (10 ** decimals))
        
        # Balance check
        bal = erc20.functions.balanceOf(WALLET_ADDRESS).call()
        if bal < amount_in_wei:
            raise RuntimeError(f"❌ Balance too low: {bal / 10**decimals} < {amount_in}")

        self._approve_if_needed(token_in, amount_in_wei)

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

        swap_fn = self.router.functions.exactInputSingle(params)
        
        # Final Simulation
        try:
            swap_fn.call({"from": WALLET_ADDRESS})
        except Exception as e:
            raise RuntimeError(f"❌ Contract Revert during simulation: {e}")

        gas_params = self._get_eip1559_params()
        tx = swap_fn.build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self.nonce,
            "gas": 350_000,
            "chainId": CHAIN_ID,
            **gas_params
        })
        self.nonce += 1

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"🚀 Swap Transaction Sent: {self.w3.to_hex(tx_hash)}")
        return self.w3.eth.wait_for_transaction_receipt(tx_hash)

    def buy_with_usdc(self, token, usdc_amount):
        return self.swap_exact_input(USDC, token, usdc_amount)

    def sell_to_usdc(self, token, token_amount):
        return self.swap_exact_input(token, USDC, token_amount)
