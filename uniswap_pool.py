from web3 import Web3

POOL_ABI = [
    {
        "name": "slot0",
        "outputs": [
            {"name": "sqrtPriceX96", "type": "uint160"},
            {"name": "tick", "type": "int24"},
            {"name": "observationIndex", "type": "uint16"},
            {"name": "observationCardinality", "type": "uint16"},
            {"name": "observationCardinalityNext", "type": "uint16"},
            {"name": "feeProtocol", "type": "uint8"},
            {"name": "unlocked", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]

def get_sqrt_price_limit(w3, pool_address, max_bps=30, is_buy=True):
    """
    max_bps: max price movement allowed (30 = 0.30%)
    """
    pool = w3.eth.contract(
        address=Web3.to_checksum_address(pool_address),
        abi=POOL_ABI
    )

    sqrt_price, *_ = pool.functions.slot0().call()

    # sqrtPrice scales linearly with price sqrt
    # bps adjustment
    delta = sqrt_price * max_bps // 10_000

    if is_buy:
        return int(sqrt_price + delta)
    else:
        return int(sqrt_price - delta)
