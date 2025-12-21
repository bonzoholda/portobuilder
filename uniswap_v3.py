from web3 import Web3
from config import RPC_URL, PRIVATE_KEY, WALLET_ADDRESS

class UniswapClient:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)

    def buy(self, token, usdc_amount):
        print(f"[BUY] {token} for ${usdc_amount:.2f}")

    def sell(self, token, amount):
        print(f"[SELL] {token} amount {amount}")
