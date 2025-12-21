import time
from web3 import Web3
from config import (
    RPC_URL,
    PRIVATE_KEY,
    WALLET_ADDRESS,
    UNISWAP_V3_ROUTER,
    USDC,
    SLIPPAGE
)
from uniswap_abi import SWAP_ROUTER_ABI, ERC20_ABI


class UniswapV3Client:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        assert self.w3.is_connected(), "❌ RPC not connected"

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
        })

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        print(f"[APPROVE] {self.w3.to_hex(tx_hash)}")
        time.sleep(3)

    # -------------------------
    # Core swap
    # -------------------------

    def swap_exact_input(
        self,
        token_in,
        token_out,
        amount_in,
        fee=3000
    ):
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)

        erc20 = self.w3.eth.contract(token_in, abi=ERC20_ABI)
        decimals = erc20.functions.decimals().call()
        amount_in_wei = int(amount_in * (10 ** decimals))

        # ⚠ For testing: allow any output (Quoter comes later)
        min_out = 0

        self._approve_if_needed(token_in, amount_in_wei)

        params = (
            token_in,
            token_out,
            fee,
            WALLET_ADDRESS,
            int(time.time()) + 60,
            amount_in_wei,
            min_out,
            0
        )

        tx = self.router.functions.exactInputSingle(params).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": self._get_nonce(),
            "gas": 350_000,
            "gasPrice": int(self.w3.eth.gas_price * 1.1),
            "value": 0
        })

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)

        print(f"[SWAP] {self.w3.to_hex(tx_hash)}")
        return self.w3.to_hex(tx_hash)

    # -------------------------
    # Convenience wrappers
    # -------------------------

    def buy_with_usdc(self, token, usdc_amount):
        print(f"[BUY] USDC → {token} | ${usdc_amount}")
        return self.swap_exact_input(
            token_in=USDC,
            token_out=token,
            amount_in=usdc_amount
        )

    def sell_to_usdc(self, token, token_amount):
        print(f"[SELL] {token} → USDC | amount {token_amount}")
        return self.swap_exact_input(
            token_in=token,
            token_out=USDC,
            amount_in=token_amount
        )
