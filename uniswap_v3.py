import time
from web3 import Web3
from config import (
    RPC_URL,
    PRIVATE_KEY,
    WALLET_ADDRESS,
    UNISWAP_V3_ROUTER,
    USDC,
    CHAIN_ID
)
from uniswap_abi import SWAP_ROUTER_ABI, ERC20_ABI
from decimal import Decimal, getcontext
getcontext().prec = 50

USDC_DECIMALS = 6  # Polygon canonical USDC


class UniswapV3Client:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        assert self.w3.is_connected(), "❌ RPC not connected"

        actual_chain = self.w3.eth.chain_id
        print(f"🔗 RPC chainId = {actual_chain}")

        if actual_chain != CHAIN_ID:
            raise RuntimeError(
                f"❌ CHAIN_ID mismatch: env={CHAIN_ID} rpc={actual_chain}"
            )

        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(UNISWAP_V3_ROUTER),
            abi=SWAP_ROUTER_ABI
        )

    # -------------------------
    # Internal helpers
    # -------------------------

    def _get_nonce(self):
        return self.w3.eth.get_transaction_count(WALLET_ADDRESS, "pending")

    def _approve_if_needed(self, token, amount):
        token = Web3.to_checksum_address(token)
        erc20 = self.w3.eth.contract(token, abi=ERC20_ABI)

        allowance = erc20.functions.allowance(
            WALLET_ADDRESS,
            UNISWAP_V3_ROUTER
        ).call()

        if allowance >= amount:
            return

        tx = erc20.functions.approve(
            UNISWAP_V3_ROUTER,
            amount
        ).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self._get_nonce(),
            "gas": 100_000,
            "gasPrice": int(self.w3.eth.gas_price * 1.1),
            "chainId": CHAIN_ID,
        })

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)

        print(f"[APPROVE] {self.w3.to_hex(tx_hash)}")

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            raise RuntimeError("❌ Approve reverted on-chain")

        print("✅ Approve confirmed in block", receipt.blockNumber)
        time.sleep(3)

    # -------------------------
    # Core swap
    # -------------------------

    def swap_exact_input(self, token_in, token_out, amount_in, fee=500):
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)

        # 1. Handle Decimals correctly
        erc20 = self.w3.eth.contract(address=token_in, abi=ERC20_ABI)
        decimals = erc20.functions.decimals().call()
        
        # Ensure we use integer for Wei calculation
        amount_in_wei = int(Decimal(str(amount_in)) * (10 ** decimals))

        # 2. Check and Approve
        self._approve_if_needed(token_in, amount_in_wei)

        # 3. Prepare ExactInputSingleParams struct
        # Structure: (tokenIn, tokenOut, fee, recipient, deadline, amountIn, amountOutMinimum, sqrtPriceLimitX96)
        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": fee,
            "recipient": WALLET_ADDRESS,
            "deadline": int(time.time()) + 60,
            "amountIn": amount_in_wei,
            "amountOutMinimum": 0, # Note: Set to 0 for testing; use Quoter for production
            "sqrtPriceLimitX96": 0
        }

        # 4. Build Transaction with Dynamic Gas
        base_tx_params = {
            "from": WALLET_ADDRESS,
            "nonce": self._get_nonce(),
            "value": 0,
            "chainId": CHAIN_ID,
        }

        # Use the dictionary/struct inside the function call
        swap_fn = self.router.functions.exactInputSingle(params)
        
        try:
            # Estimate gas instead of hardcoding
            estimated_gas = swap_fn.estimate_gas(base_tx_params)
            base_tx_params["gas"] = int(estimated_gas * 1.2) # Add 20% buffer
        except Exception as e:
            print(f"⚠️ Gas estimation failed: {e}. Falling back to manual limit.")
            base_tx_params["gas"] = 400_000

        # Add gas price (EIP-1559 is preferred on Polygon, but keeping your logic)
        base_tx_params["gasPrice"] = int(self.w3.eth.gas_price * 1.1)

        tx = swap_fn.build_transaction(base_tx_params)

        # 5. Sign and Send
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)

        print(f"[SWAP] Sent: {self.w3.to_hex(tx_hash)}")

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            raise RuntimeError(f"❌ Swap reverted: {self.w3.to_hex(tx_hash)}")

        print(f"✅ Swap confirmed in block {receipt.blockNumber}")
        return self.w3.to_hex(tx_hash)

    # -------------------------
    # Convenience wrappers
    # -------------------------

    def buy_with_usdc(self, token, usdc_amount):
        print(f"[BUY] USDC → {token} | ${usdc_amount}")
        return self.swap_exact_input(
            token_in=USDC,
            token_out=token,
            amount_in=usdc_amount,
            fee=500  # ✅ Polygon canonical pool
        )


    def sell_to_usdc(self, token, token_amount):
        print(f"[SELL] {token} → USDC | amount {token_amount}")
        return self.swap_exact_input(
            token_in=token,
            token_out=USDC,
            amount_in=token_amount,
            fee=500
        )

