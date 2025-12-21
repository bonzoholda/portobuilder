import time
from web3 import Web3
from config import RPC_URL, PRIVATE_KEY, WALLET_ADDRESS, SLIPPAGE
from uniswap_abi import SWAP_ROUTER_ABI, ERC20_ABI
from config import UNISWAP_V3_ROUTER, USDC
from uniswap_pool import get_sqrt_price_limit


class UniswapV3Client:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(UNISWAP_V3_ROUTER),
            abi=SWAP_ROUTER_ABI
        )

    def _approve(self, token, amount):
        token = Web3.to_checksum_address(token)
        erc20 = self.w3.eth.contract(token, abi=ERC20_ABI)
    
        allowance = erc20.functions.allowance(
            WALLET_ADDRESS,
            UNISWAP_V3_ROUTER
        ).call()
    
        nonce = self.w3.eth.get_transaction_count(WALLET_ADDRESS)
    
        # USDT safety: reset to 0 first if needed
        if allowance > 0:
            tx0 = erc20.functions.approve(
                UNISWAP_V3_ROUTER,
                0
            ).build_transaction({
                "from": WALLET_ADDRESS,
                "nonce": nonce,
                "gas": 80000,
                "gasPrice": self.w3.eth.gas_price,
            })
    
            signed0 = self.account.sign_transaction(tx0)
            self.w3.eth.send_raw_transaction(signed0.rawTransaction)
            time.sleep(2)
            nonce += 1
    
        tx = erc20.functions.approve(
            UNISWAP_V3_ROUTER,
            amount
        ).build_transaction({
            "from": WALLET_ADDRESS,
            "nonce": nonce,
            "gas": 100000,
            "gasPrice": self.w3.eth.gas_price,
        })
    
        signed = self.account.sign_transaction(tx)
        self.w3.eth.send_raw_transaction(signed.rawTransaction)
        time.sleep(2)


def swap_exact_input(
    self,
    token_in,
    token_out,
    pool_address,
    amount_in,
    fee=3000,
    is_buy=True
):
    token_in = Web3.to_checksum_address(token_in)
    token_out = Web3.to_checksum_address(token_out)

    erc20 = self.w3.eth.contract(token_in, abi=ERC20_ABI)
    decimals = erc20.functions.decimals().call()
    amount_in_wei = int(amount_in * (10 ** decimals))

    min_out = int(amount_in_wei * (1 - SLIPPAGE))

    self._approve(token_in, amount_in_wei)

    sqrt_price_limit = get_sqrt_price_limit(
        self.w3,
        pool_address,
        max_bps=30,   # 0.30%
        is_buy=is_buy
    )

    params = (
        token_in,
        token_out,
        fee,
        WALLET_ADDRESS,
        int(time.time()) + 45,  # SHORT DEADLINE
        amount_in_wei,
        min_out,
        sqrt_price_limit
    )

    tx = self.router.functions.exactInputSingle(params).build_transaction({
        "from": WALLET_ADDRESS,
        "nonce": self.w3.eth.get_transaction_count(WALLET_ADDRESS),
        "gas": 320000,
        "gasPrice": self.w3.eth.gas_price
    })

    signed = self.account.sign_transaction(tx)
    return self.w3.to_hex(
        self.w3.eth.send_raw_transaction(signed.rawTransaction)
    )


    # === Convenience Wrappers ===

    def buy_with_usdc(self, token, usdc_amount):
        print(f"[SWAP] USDC → {token} | ${usdc_amount}")
        return self.swap_exact_input(
            token_in=USDC,
            token_out=token,
            amount_in=usdc_amount
        )

    def sell_to_usdc(self, token, token_amount):
        print(f"[SWAP] {token} → USDC | amount {token_amount}")
        return self.swap_exact_input(
            token_in=token,
            token_out=USDC,
            amount_in=token_amount
        )
