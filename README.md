# SaucerSwap V2 Python SDK

> A lightweight Python toolkit for programmatic token swaps on SaucerSwap V2 (Hedera Network)

## Who Is This For?

This SDK is designed for **developers and builders** who want to:

- 🤖 **Build Trading Bots**: Automate swap execution on Hedera's leading DEX
- 📊 **Create DeFi Dashboards**: Fetch real-time swap quotes and token prices
- 🔧 **Integrate Swaps into dApps**: Add token exchange functionality to your applications
- 📚 **Learn Hedera DeFi**: Understand how SaucerSwap V2 works at the code level

If you're looking to interact with SaucerSwap programmatically without building everything from scratch, this toolkit gives you a clean starting point.

---

## What Can You Do With It?

### ✅ Swap Any HTS Token
Execute swaps between any Hedera Token Service (HTS) tokens that have liquidity pools on SaucerSwap V2.

### ✅ Native HBAR Swaps
Swap to and from **native HBAR** (not just WHBAR). The SDK handles wrapping and unwrapping automatically using atomic multicall transactions.

### ✅ Get Accurate Quotes
Fetch on-chain quotes before executing swaps to calculate expected output and price impact.

### ✅ Configurable Tokens
Easily add your own token IDs to trade any assets available on SaucerSwap V2.

---

## Quick Start

### 1. Install Dependencies

```bash
pip install web3 python-dotenv eth-abi requests
```

### 2. Configure Environment

Create a `.env` file:

```env
RPC_URL=https://mainnet.hashio.io/api
PRIVATE_KEY=your_hedera_private_key
```

### 3. Run Your First Swap

```python
from saucerswap_v2_engine import SaucerSwapV2Engine
from v2_tokens import USDC_ID

# Initialize the engine
engine = SaucerSwapV2Engine()

# Get a quote: 10 USDC → HBAR
quote = engine.get_quote(
    token_in_id=USDC_ID,
    token_out_id="HBAR",
    amount=10.0,
    decimals_in=6
)
print(f"Expected output: {quote} tinybar")

# Execute the swap
result = engine.swap(
    token_in_id=USDC_ID,
    token_out_id="HBAR",
    amount=1.0,
    decimals_in=6,
    decimals_out=8,
    slippage=0.02  # 2% slippage tolerance
)

if result.success:
    print(f"✅ Swap successful! TX: {result.tx_hash}")
else:
    print(f"❌ Swap failed: {result.error}")
```

---

## File Overview

| File | Purpose |
| :--- | :--- |
| `saucerswap_v2_client.py` | Low-level client for interacting with V2 Router & Quoter contracts |
| `saucerswap_v2_engine.py` | High-level swap engine with automatic HBAR handling and multicall |
| `hbar_swap_engine.py` | Standalone module for HBAR-specific swaps |
| `v2_tokens.py` | Token ID configuration (add your own tokens here) |
| `.env.example` | Environment variable template |

---

## Adding Your Own Tokens

Edit `v2_tokens.py` to add any HTS token:

```python
# v2_tokens.py
WHBAR_ID = "0.0.1456986"
USDC_ID = "0.0.456858"
WBTC_ID = "0.0.10082597"

# Add your token here
MY_TOKEN_ID = "0.0.XXXXXX"
```

---

## Requirements

- Python 3.9+
- A Hedera account with:
  - Sufficient HBAR for gas fees
  - Token associations for any HTS tokens you want to trade
  - Token balances to swap

---

## Technical Notes

- **Deadline Format**: SaucerSwap V2 on Hedera requires **millisecond** Unix timestamps (not seconds)
- **Atomic HBAR Swaps**: When swapping to native HBAR, the SDK uses `multicall(exactInput, unwrapWHBAR)` to ensure you receive HBAR directly
- **Fee Tiers**: Default is 1500 (0.15%), but can be configured for different pools

---

## Disclaimer

This code is provided as-is for educational and development purposes. Always test with small amounts first and understand the risks of interacting with smart contracts. The authors are not responsible for any financial losses.

---

## License

MIT
