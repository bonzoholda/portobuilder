import time
from web3 import Web3
from decimal import Decimal
try:
    from web3.middleware import ExtraDataToPOAMiddleware as POAMiddleware
except ImportError:
    from web3.middleware import geth_poa_middleware as POAMiddleware

from config import (
    RPC_URL, PRIVATE_KEY, WALLET_ADDRESS,
    UNISWAP_V3_ROUTER, USDC, CHAIN_ID
)
from uniswap_abi import SWAP_ROUTER_ABI, ERC20_ABI

# ================= CONFIG & ABIs =================
UNISWAP_V3_QUOTER = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e"
SWAP_ROUTER_ADDRESS = "0xE592427A0AEce92De3Edee1F18E0157C05861564"

class UniswapV3Client:
    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        # Inject POA middleware for Polygon
        self.w3.middleware_onion.inject(POAMiddleware, layer=0)
        
        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        self.router_address = Web3.to_checksum_address(SWAP_ROUTER_ADDRESS)
        self.router = self.w3.eth.contract(address=self.router_address, abi=SWAP_ROUTER_ABI)

    def _get_gas_params(self):
        """
        Dynamically calculates EIP-1559 gas fees based on current network congestion.
        """
        try:
            latest_block = self.w3.eth.get_block("latest")
            base_fee = latest_block.get("baseFeePerGas", self.w3.to_wei(50, 'gwei'))
            
            # Suggest a priority fee (tip) from the network, fallback to 35 Gwei if it fails
            try:
                suggested_priority_fee = self.w3.eth.max_priority_fee_per_gas
            except:
                suggested_priority_fee = self.w3.to_wei(35, 'gwei')

            # We multiply base fee by 2.5 to ensure inclusion during spikes
            # Max Fee = (Base Fee * 2.5) + Priority Fee
            max_fee_per_gas = int(base_fee * 2.5) + suggested_priority_fee

            return {
                "maxFeePerGas": max_fee_per_gas,
                "maxPriorityFeePerGas": suggested_priority_fee,
                "type": 2 # EIP-1559
            }
        except Exception as e:
            print(f"⚠️ Gas estimation failed: {e}. Falling back to legacy gas price.")
            return {"gasPrice": int(self.w3.eth.gas_price * 1.5)}

    def _get_fresh_nonce(self):
        """Always get the most recent nonce from the blockchain."""
        return self.w3.eth.get_transaction_count(WALLET_ADDRESS, 'pending')

    def _force_approve(self, token, amount_wei):
        """Ensures the router is allowed to spend your tokens."""
        token_addr = Web3.to_checksum_address(token)
        erc20 = self.w3.eth.contract(address=token_addr, abi=ERC20_ABI)
        
        current_allowance = erc20.functions.allowance(WALLET_ADDRESS, self.router_address).call()
        
        if current_allowance < amount_wei:
            print(f"🔓 Approving {token_addr} for Router...")
            gas_params = self._get_gas_params()
            
            # Approve a very large amount to avoid frequent re-approvals
            approve_tx = erc20.functions.approve(self.router_address, 2**256 - 1).build_transaction({
                "from": WALLET_ADDRESS,
                "nonce": self._get_fresh_nonce(),
                "gas": 70000,
                "chainId": CHAIN_ID,
                **gas_params
            })
            
            signed = self.account.sign_transaction(approve_tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
            print(f"⏳ Approval sent: {tx_hash.hex()}. Waiting...")
            self.w3.eth.wait_for_transaction_receipt(tx_hash)
            time.sleep(5) # Cooldown for network state sync

    def swap_exact_input(self, token_in, token_out, amount_in):
        """Executes a swap on Uniswap V3 with dynamic gas and status verification."""
        token_in = Web3.to_checksum_address(token_in)
        token_out = Web3.to_checksum_address(token_out)
        
        # Calculate decimals for input amount
        erc20_in = self.w3.eth.contract(address=token_in, abi=ERC20_ABI)
        decimals = erc20_in.functions.decimals().call()
        amount_in_wei = int(Decimal(str(amount_in)) * (10 ** decimals))

        # 1. Handle Approval
        self._force_approve(token_in, amount_in_wei)

        # 2. Build Swap Parameters
        params = {
            "tokenIn": token_in,
            "tokenOut": token_out,
            "fee": 500, # 0.05% tier
            "recipient": WALLET_ADDRESS,
            "deadline": int(time.time()) + 600,
            "amountIn": amount_in_wei,
            "amountOutMinimum": 0, # Slippage handled by higher logic or set via quoter
            "sqrtPriceLimitX96": 0
        }

        print(f"🚀 Attempting Swap: {amount_in} {token_in} -> {token_out}")
        
        try:
            gas_params = self._get_gas_params()
            tx = self.router.functions.exactInputSingle(params).build_transaction({
                "from": WALLET_ADDRESS,
                "nonce": self._get_fresh_nonce(),
                "gas": 350000, # Sufficient for complex V3 swaps
                "chainId": CHAIN_ID,
                **gas_params
            })
            
            signed = self.account.sign_transaction(tx)
            tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
            
            # Return the hash immediately so bot.py can use wait_for_success helper
            return tx_hash.hex()
            
        except Exception as e:
            print(f"❌ Swap build/send failed: {e}")
            raise e

    def buy_with_usdc(self, token, usdc_amount):
        return self.swap_exact_input(USDC, token, usdc_amount)

    def sell_for_usdc(self, token, token_amount):
        return self.swap_exact_input(token, USDC, token_amount)
