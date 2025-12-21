import time
from web3 import Web3
from decimal import Decimal, getcontext
# Try both names for compatibility across web3.py versions
try:
    from web3.middleware import ExtraDataToPOAMiddleware as POAMiddleware
except ImportError:
    from web3.middleware import geth_poa_middleware as POAMiddleware

from config import (
    RPC_URL,
    PRIVATE_KEY,
    WALLET_ADDRESS,
    UNISWAP_V3_ROUTER,
    USDC,
    CHAIN_ID
)
from uniswap_abi import SWAP_ROUTER_ABI, ERC20_ABI

getcontext().prec = 50

class UniswapV3Client:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        
        # Inject the middleware using the alias we created above
        self.w3.middleware_onion.inject(POAMiddleware, layer=0)
        
        if not self.w3.is_connected():
            raise RuntimeError("❌ RPC not connected")

        actual_chain = self.w3.eth.chain_id
        print(f"🔗 RPC chainId = {actual_chain}")

        if actual_chain != CHAIN_ID:
            raise RuntimeError(f"❌ CHAIN_ID mismatch: env={CHAIN_ID} rpc={actual_chain}")

        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(UNISWAP_V3_ROUTER),
            abi=SWAP_ROUTER_ABI
        )
        
        self.nonce = self.w3.eth.get_transaction_count(WALLET_ADDRESS)

    def _get_next_nonce(self):
        current_nonce = self.nonce
        self.nonce += 1
        return current_nonce

    def _get_eip1559_params(self):
        latest_block = self.w3.eth.get_block("latest")
        base_fee = latest_block["baseFeePerGas"]
        priority_fee = self.w3.to_wei(35, 'gwei') # Bumped slightly for Polygon speed
        max_fee = (2 * base_fee) + priority_fee
        
        return {
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee
        }

    def _approve_if_needed(self, token_address, amount):
        token_address = Web3.to_checksum_address(token_address)
        erc20 = self.w3.eth.contract(token_address, abi=ERC20_ABI)
        allowance = erc20.functions.allowance(WALLET_ADDRESS, UNISWAP_V3_ROUTER).call()

        if allowance >= amount:
            return

        print(f"🔓 Approving token: {token_address}...")
        gas_params = self._get_eip1559_params()
        tx = erc20.functions.approve(UNISWAP_V3_ROUTER, amount).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self._get_next_nonce(),
            "gas": 65_000,
            "chainId": CHAIN_ID,
            **gas_params
        })

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"[APPROVE] {self.w3.to_hex(tx_hash)}")
        self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    def swap_exact_input(self, token_in, token_out, amount_in, fee=500):
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)

        # 1. Check if the pool even exists
        # Uniswap V3 Factory Address on Polygon: 0x1F98431c8aD98523631AE4a59f267346ea31F984
        factory_abi = '[{"inputs":[{"internalType":"address","name":"","type":"address"},{"internalType":"address","name":"","type":"address"},{"internalType":"uint24","name":"","type":"uint24"}],"name":"getPool","outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}]'
        factory = self.w3.eth.contract(address="0x1F98431c8aD98523631AE4a59f267346ea31F984", abi=factory_abi)
        pool_address = factory.functions.getPool(token_in, token_out, fee).call()
        
        if pool_address == "0x0000000000000000000000000000000000000000":
            raise RuntimeError(f"❌ No pool found for {token_in} / {token_out} at fee {fee}")
        
        erc20 = self.w3.eth.contract(address=token_in, abi=ERC20_ABI)
        decimals = erc20.functions.decimals().call()
        amount_in_wei = int(Decimal(str(amount_in)) * (10 ** decimals))

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

        gas_params = self._get_eip1559_params()
        swap_fn = self.router.functions.exactInputSingle(params)

        try:
            estimated_gas = swap_fn.estimate_gas({"from": WALLET_ADDRESS, "value": 0})
            gas_limit = int(estimated_gas * 1.3) # 30% buffer for swaps
            print("🔍 Simulating swap to check for errors...")
            swap_fn.call({"from": WALLET_ADDRESS})
            print("✅ Simulation successful!")
        except Exception as e:
                    # This will capture the actual revert reason (e.g., "STF" or "TF")
                    print(f"❌ Simulation failed! Reason: {e}")
                    raise RuntimeError(f"Contract would revert: {e}")

        tx = swap_fn.build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self._get_next_nonce(),
            "gas": gas_limit,
            "value": 0,
            "chainId": CHAIN_ID,
            **gas_params
        })

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"[SWAP] Sent: {self.w3.to_hex(tx_hash)}")
        
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            raise RuntimeError(f"❌ Swap reverted: {self.w3.to_hex(tx_hash)}")

        print(f"✅ Swap confirmed in block {receipt.blockNumber}")
        return self.w3.to_hex(tx_hash)

    def buy_with_usdc(self, token, usdc_amount):
        return self.swap_exact_input(USDC, token, usdc_amount, fee=500)

    def sell_to_usdc(self, token, token_amount):
        return self.swap_exact_input(token, USDC, token_amount, fee=500)
