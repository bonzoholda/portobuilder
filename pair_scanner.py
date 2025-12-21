import requests

GRAPH_URL = "https://api.thegraph.com/subgraphs/name/ianlapham/uniswap-v3-polygon"

QUERY = """
{
  pools(first: 10, orderBy: volumeUSD, orderDirection: desc) {
    token0 { symbol id }
    token1 { symbol id }
    feeTier
  }
}
"""

def get_safe_pairs():
    try:
        r = requests.post(GRAPH_URL, json={"query": QUERY}, timeout=10)
        j = r.json()

        # 🔒 HARD GUARD
        if "data" not in j or "pools" not in j["data"]:
            print("⚠️ Pair scanner: invalid response", j)
            return []

        return j["data"]["pools"]

    except Exception as e:
        print("⚠️ Pair scanner error:", str(e))
        return []
