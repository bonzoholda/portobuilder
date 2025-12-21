import time
from web3 import Web3
from decimal import Decimal, getcontext
# Import the middleware
from web3.middleware import ExtraDataToPOAMiddleware 
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
        
        # --- FIX: Inject PoA Middleware for Polygon ---
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        
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
        
        # Local nonce tracking to prevent "replacement transaction underpriced"
        self.nonce = self.w3.eth.get_transaction_count(WALLET_ADDRESS)

    # -------------------------
    # Internal helpers
    # -------------------------

    def _get_next_nonce(self):
        current_nonce = self.nonce
        self.nonce += 1
        return current_nonce

    def _get_eip1559_params(self):
        """Dynamic gas fees for Polygon EIP-1559."""
        latest_block = self.w3.eth.get_block("latest")
        base_fee = latest_block["baseFeePerGas"]
        priority_fee = self.w3.to_wei(30, 'gwei') 
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

    # -------------------------
    # Core swap
    # -------------------------

    def swap_exact_input(self, token_in, token_out, amount_in, fee=500):
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)

        erc20 = self.w3.eth.contract(address=token_in, abi=ERC20_ABI)
        decimals = erc20.functions.decimals().call()
        amount_in_wei = int(Decimal(str(amount_in)) * (10 ** decimals))

        self._approve_if_needed(token_in, amount_in_wei)

        # Structure matches exactInputSingle(params)
        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": fee,
            "recipient": WALLET_ADDRESS,
            "deadline": int(time.time()) + 120,
            "amountIn": amount_in_wei,
            "amountOutMinimum": 0,
            "sqrtPriceLimitX96": 0
        }

        gas_params = self._get_eip1559_params()
        swap_fn = self.router.functions.exactInputSingle(params)

        try:
            # Note: value: 0 because we are swapping tokens, not native MATIC
            estimated_gas = swap_fn.estimate_gas({"from": WALLET_ADDRESS, "value": 0})
            gas_limit = int(estimated_gas * 1.2)
        except Exception:
            gas_limit = 350_000

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
