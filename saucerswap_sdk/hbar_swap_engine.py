"""
SaucerSwap V2 HBAR Swap Module
==============================

Standalone implementations for HBAR-related swaps.
Uses exactInputSingle (NOT exactInput) based on earlier successful test.

This module is SEPARATE from swap_engine.py which handles Token↔Token swaps.

Key findings:
1. exactInputSingle with struct params works for HBAR (proven in earlier test)
2. Path-based exactInput failed for WHBAR/USDC (no pool found at any fee tier)
3. Quote using quoteExactInputSingle with struct params
"""

import os
import time
import logging
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from web3 import Web3

# Import tokens from the working codebase
from tokens import TOKENS

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =============================================================================
# CONTRACT ADDRESSES (Hedera Mainnet)
# =============================================================================

QUOTER_ADDRESS = "0x00000000000000000000000000000000003c4380"  # 0.0.3949424
ROUTER_ADDRESS = "0x00000000000000000000000000000000003c437A"  # 0.0.3949434

# Token references
WHBAR = TOKENS["WHBAR"]
USDC = TOKENS["USDC"]
WBTC = TOKENS["WBTC"]

# Fee tier
FEE_1500 = 1500  # 0.15%

# =============================================================================
# ABIs - Including exactInputSingle (proven to work for HBAR swaps)
# =============================================================================

QUOTER_ABI = [
    # quoteExactInputSingle - for single-hop quotes (USED FOR HBAR)
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "quoteExactInputSingle",
        "outputs": [
            {"name": "amountOut", "type": "uint256"},
            {"name": "sqrtPriceX96After", "type": "uint160"},
            {"name": "initializedTicksCrossed", "type": "uint32"},
            {"name": "gasEstimate", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

ROUTER_ABI = [
    # exactInputSingle - for single-hop swaps (PROVEN TO WORK FOR HBAR)
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function"
    }
]

ERC20_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"}
        ],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]


@dataclass
class SwapResult:
    """Result of a swap operation."""
    success: bool
    tx_hash: str = ""
    amount_in: float = 0.0
    amount_out: float = 0.0
    gas_used: int = 0
    error: str = ""


# =============================================================================
# HBAR SWAP ENGINE - Using exactInputSingle
# =============================================================================

class HbarSwapEngine:
    """
    Standalone engine for HBAR-related swaps.
    Uses exactInputSingle (proven to work in earlier test).
    """
    
    def __init__(self, rpc_url: str = None, private_key: str = None):
        """Initialize HBAR swap engine."""
        load_dotenv()
        
        self.rpc_url = rpc_url or os.getenv("RPC_URL", "https://mainnet.hashio.io/api")
        self.private_key = private_key or os.getenv("PRIVATE_KEY")
        
        if not self.private_key:
            raise ValueError("PRIVATE_KEY required")
        
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(f"Failed to connect to {self.rpc_url}")
        
        self.account = self.w3.eth.account.from_key(self.private_key)
        self.eoa = self.account.address
        self.chain_id = 295  # Hedera mainnet
        
        # Initialize contracts
        self.quoter = self.w3.eth.contract(
            address=Web3.to_checksum_address(QUOTER_ADDRESS),
            abi=QUOTER_ABI
        )
        self.router = self.w3.eth.contract(
            address=Web3.to_checksum_address(ROUTER_ADDRESS),
            abi=ROUTER_ABI
        )
        
        logger.info(f"HbarSwapEngine initialized")
        logger.info(f"  Account: {self.eoa}")
        logger.info(f"  Using exactInputSingle approach")
    
    def get_balance_hbar(self) -> float:
        """Get native HBAR balance."""
        wei = self.w3.eth.get_balance(self.eoa)
        return wei / 10**18
    
    def get_balance_token(self, token_addr: str, decimals: int) -> float:
        """Get token balance. Returns 0 if not associated."""
        try:
            contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(token_addr),
                abi=ERC20_ABI
            )
            raw = contract.functions.balanceOf(self.eoa).call()
            return raw / (10 ** decimals)
        except Exception:
            return 0.0
    
    def ensure_approval(self, token_addr: str, amount: int) -> bool:
        """Ensure token approved for router."""
        contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_addr),
            abi=ERC20_ABI
        )
        
        allowance = contract.functions.allowance(
            self.eoa,
            Web3.to_checksum_address(ROUTER_ADDRESS)
        ).call()
        
        if allowance >= amount:
            logger.info(f"  Token already approved")
            return False
        
        logger.info(f"  Approving token...")
        tx = contract.functions.approve(
            Web3.to_checksum_address(ROUTER_ADDRESS),
            2**256 - 1
        ).build_transaction({
            "from": self.eoa,
            "gas": 1000000,
            "gasPrice": self.w3.eth.gas_price,
            "nonce": self.w3.eth.get_transaction_count(self.eoa),
            "chainId": self.chain_id
        })
        signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        logger.info(f"  Approval confirmed: {tx_hash.hex()}")
        return True
    
    # =========================================================================
    # SWAP: Native HBAR → USDC (using exactInputSingle - PROVEN APPROACH)
    # =========================================================================
    
    def swap_hbar_for_usdc(self, amount_hbar: float, slippage_percent: float = 2.0) -> SwapResult:
        """
        Swap native HBAR for USDC using exactInputSingle.
        
        This approach was proven to work in earlier test:
        - Uses struct-based params (not path encoding)
        - Sends native HBAR as transaction value
        - Router auto-wraps HBAR to WHBAR
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🔥 SWAP: HBAR → USDC (exactInputSingle)")
        logger.info(f"{'='*60}")
        
        try:
            # Get EVM addresses
            whbar_addr = WHBAR.evm_address
            usdc_addr = USDC.evm_address
            
            # Amount conversions
            amount_in_8dec = int(amount_hbar * 10**8)   # WHBAR is 8 decimals
            amount_in_wei = int(amount_hbar * 10**18)  # Native value is 18 decimals
            
            # Get quote using quoteExactInputSingle
            quote_params = (whbar_addr, usdc_addr, amount_in_8dec, FEE_1500, 0)
            quote = self.quoter.functions.quoteExactInputSingle(quote_params).call()
            expected_out = quote[0]
            min_out = int(expected_out * (100 - slippage_percent) / 100)
            
            logger.info(f"  Quote: {amount_hbar:.4f} HBAR → ~{expected_out/10**6:.6f} USDC")
            
            # Build exactInputSingle params (struct format - proven to work)
            deadline = int(time.time()) + 120
            swap_params = (
                whbar_addr,      # tokenIn
                usdc_addr,       # tokenOut
                FEE_1500,        # fee
                self.eoa,        # recipient
                deadline,        # deadline
                amount_in_8dec,  # amountIn
                min_out,         # amountOutMinimum
                0                # sqrtPriceLimitX96
            )
            
            # Build transaction with native HBAR value
            tx = self.router.functions.exactInputSingle(swap_params).build_transaction({
                "from": self.eoa,
                "value": amount_in_wei,
                "gas": 500000,
                "gasPrice": self.w3.eth.gas_price,
                "nonce": self.w3.eth.get_transaction_count(self.eoa),
                "chainId": self.chain_id
            })
            
            signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            logger.info(f"  TX sent: {tx_hash.hex()}")
            
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt["status"] == 1:
                logger.info(f"  ✅ SUCCESS! Gas: {receipt['gasUsed']}")
                return SwapResult(
                    success=True,
                    tx_hash=tx_hash.hex(),
                    amount_in=amount_hbar,
                    amount_out=expected_out / 10**6,
                    gas_used=receipt["gasUsed"]
                )
            else:
                logger.error(f"  ❌ REVERTED")
                return SwapResult(success=False, tx_hash=tx_hash.hex(), error="Transaction reverted")
                
        except Exception as e:
            logger.error(f"  ❌ FAILED: {e}")
            return SwapResult(success=False, error=str(e))
    
    # =========================================================================
    # SWAP: USDC → WHBAR (using exactInputSingle)
    # =========================================================================
    
    def swap_usdc_for_whbar(self, amount_usdc: float, slippage_percent: float = 2.0) -> SwapResult:
        """
        Swap USDC for WHBAR using exactInputSingle.
        
        User receives WHBAR (not native HBAR).
        Uses same struct-based approach.
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🔥 SWAP: USDC → WHBAR (exactInputSingle)")
        logger.info(f"{'='*60}")
        
        try:
            # Get EVM addresses
            usdc_addr = USDC.evm_address
            whbar_addr = WHBAR.evm_address
            
            # Amount in USDC smallest units (6 decimals)
            amount_in = int(amount_usdc * 10**6)
            
            # Get quote
            quote_params = (usdc_addr, whbar_addr, amount_in, FEE_1500, 0)
            quote = self.quoter.functions.quoteExactInputSingle(quote_params).call()
            expected_out = quote[0]
            min_out = int(expected_out * (100 - slippage_percent) / 100)
            
            logger.info(f"  Quote: {amount_usdc:.6f} USDC → ~{expected_out/10**8:.4f} WHBAR")
            
            # Ensure approval
            self.ensure_approval(usdc_addr, amount_in)
            
            # Build exactInputSingle params
            deadline = int(time.time()) + 120
            swap_params = (
                usdc_addr,       # tokenIn
                whbar_addr,      # tokenOut
                FEE_1500,        # fee
                self.eoa,        # recipient
                deadline,        # deadline
                amount_in,       # amountIn
                min_out,         # amountOutMinimum
                0                # sqrtPriceLimitX96
            )
            
            # Build transaction - no value (token swap)
            tx = self.router.functions.exactInputSingle(swap_params).build_transaction({
                "from": self.eoa,
                "value": 0,
                "gas": 500000,
                "gasPrice": self.w3.eth.gas_price,
                "nonce": self.w3.eth.get_transaction_count(self.eoa),
                "chainId": self.chain_id
            })
            
            signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
            logger.info(f"  TX sent: {tx_hash.hex()}")
            
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            
            if receipt["status"] == 1:
                logger.info(f"  ✅ SUCCESS! Gas: {receipt['gasUsed']}")
                return SwapResult(
                    success=True,
                    tx_hash=tx_hash.hex(),
                    amount_in=amount_usdc,
                    amount_out=expected_out / 10**8,
                    gas_used=receipt["gasUsed"]
                )
            else:
                logger.error(f"  ❌ REVERTED")
                return SwapResult(success=False, tx_hash=tx_hash.hex(), error="Transaction reverted")
                
        except Exception as e:
            logger.error(f"  ❌ FAILED: {e}")
            return SwapResult(success=False, error=str(e))


# =============================================================================
# TEST RUNNER
# =============================================================================

def test_hbar_swaps():
    """Test HBAR swap with exactInputSingle approach."""
    print("\n" + "="*60)
    print("HBAR SWAP ENGINE TESTS (exactInputSingle)")
    print("="*60)
    
    engine = HbarSwapEngine()
    
    # Print initial balances
    print("\n--- INITIAL BALANCES ---")
    hbar_bal = engine.get_balance_hbar()
    usdc_bal = engine.get_balance_token(USDC.evm_address, 6)
    whbar_bal = engine.get_balance_token(WHBAR.evm_address, 8)
    print(f"  HBAR:  {hbar_bal:.4f}")
    print(f"  USDC:  {usdc_bal:.6f}")
    print(f"  WHBAR: {whbar_bal:.8f}")
    
    results = []
    
    # Test 1: HBAR → USDC
    print("\n--- TEST 1: HBAR → USDC ---")
    result1 = engine.swap_hbar_for_usdc(amount_hbar=0.5, slippage_percent=2.0)
    results.append(("HBAR → USDC", result1))
    
    time.sleep(3)
    
    # Test 2: USDC → WHBAR
    print("\n--- TEST 2: USDC → WHBAR ---")
    result2 = engine.swap_usdc_for_whbar(amount_usdc=0.10, slippage_percent=2.0)
    results.append(("USDC → WHBAR", result2))
    
    # Print final balances
    print("\n--- FINAL BALANCES ---")
    hbar_bal = engine.get_balance_hbar()
    usdc_bal = engine.get_balance_token(USDC.evm_address, 6)
    whbar_bal = engine.get_balance_token(WHBAR.evm_address, 8)
    print(f"  HBAR:  {hbar_bal:.4f}")
    print(f"  USDC:  {usdc_bal:.6f}")
    print(f"  WHBAR: {whbar_bal:.8f}")
    
    # Summary
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    for name, result in results:
        status = "✅ PASS" if result.success else "❌ FAIL"
        print(f"  {name}: {status}")
        if result.success:
            print(f"    TX: {result.tx_hash}")
            print(f"    Gas: {result.gas_used}")
        else:
            print(f"    Error: {result.error}")


if __name__ == "__main__":
    test_hbar_swaps()
