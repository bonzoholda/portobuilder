import requests

SUBGRAPH = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3"

SAFE_TOKENS = {"WETH", "WMATIC", "WBTC", "LINK", "AAVE"}

def get_safe_pairs():
    query = """
    {
      pools(first: 30, orderBy: volumeUSD, orderDirection: desc) {
        id
        token0 { symbol }
        token1 { symbol }
        totalValueLockedUSD
        volumeUSD
      }
    }
    """
    r = requests.post(SUBGRAPH, json={"query": query}).json()
    pools = r["data"]["pools"]

    safe = []
    for p in pools:
        symbols = {p["token0"]["symbol"], p["token1"]["symbol"]}
        if "USDC" in symbols and symbols & SAFE_TOKENS:
            if float(p["totalValueLockedUSD"]) >= 5_000_000:
                safe.append(p)
    return safe
