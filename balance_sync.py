from web3 import Web3
from uniswap_abi import ERC20_ABI
from config import RPC_URL, WALLET_ADDRESS

w3 = Web3(Web3.HTTPProvider(RPC_URL))

def get_token_balance(token_address):
    token = w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI
    )

    decimals = token.functions.decimals().call()
    balance = token.functions.balanceOf(
        Web3.to_checksum_address(WALLET_ADDRESS)
    ).call()

    return balance / (10 ** decimals)
