"""
Local SaucerSwap V2 client
==========================

This is a vendored copy of the proven SaucerSwap V2 implementation
from the parent repo, trimmed to the pieces we need:

- hedera_id_to_evm
- encode_path
- SaucerSwapV2 with:
  - mainnet contracts 0.0.3949424 (quoter) and 0.0.3949434 (router)
  - get_quote_single / get_quote
  - approve_token / get_token_balance

It makes btc_rebalancer self-contained for deployment.
"""

from typing import List
from web3 import Web3

# Contract IDs (Mainnet/Testnet)
CONTRACTS = {
    "mainnet": {
        "quoter": "0.0.3949424",
        "router": "0.0.3949434",
        "whbar": "0.0.1456986",
    },
    "testnet": {
        "quoter": "0.0.1390002",
        "router": "0.0.1414040",
        "whbar": "0.0.15058",
    },
}

QUOTER_ABI = [
    {
        "inputs": [
            {"internalType": "bytes", "name": "path", "type": "bytes"},
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
        ],
        "name": "quoteExactInput",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
            {"internalType": "uint160[]", "name": "sqrtPriceX96AfterList", "type": "uint160[]"},
            {"internalType": "uint32[]", "name": "initializedTicksCrossedList", "type": "uint32[]"},
            {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"},
        ],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "bytes", "name": "path", "type": "bytes"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
                ],
                "internalType": "struct ISwapRouter.ExactInputParams",
                "name": "params",
                "type": "tuple",
            }
        ],
        "name": "exactInput",
        "outputs": [
            {"internalType": "uint256", "name": "amountOut", "type": "uint256"}
        ],
        "stateMutability": "payable",
        "type": "function",
    }
]

ERC20_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "spender", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "address", "name": "account", "type": "address"}
        ],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def hedera_id_to_evm(hedera_id: str) -> str:
    """Convert Hedera ID (0.0.123) to EVM address (0x000...007B)."""
    if hedera_id.startswith("0x"):
        return Web3.to_checksum_address(hedera_id)
    parts = hedera_id.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid Hedera ID format: {hedera_id}")
    num = int(parts[2])
    return Web3.to_checksum_address(f"0x{num:040x}")


def encode_path(tokens: List[str], fees: List[int]) -> bytes:
    """Encode [token0, token1, ...] and [fee0, fee1, ...] into SaucerSwap path bytes."""
    if len(fees) != len(tokens) - 1:
        raise ValueError(f"Expected {len(tokens) - 1} fees, got {len(fees)}")

    path = b""
    for i, token in enumerate(tokens):
        token_bytes = bytes.fromhex(hedera_id_to_evm(token)[2:])
        path += token_bytes
        if i < len(fees):
            fee_bytes = fees[i].to_bytes(3, "big")
            path += fee_bytes
    return path


class SaucerSwapV2:
    """Minimal SaucerSwap V2 client for quoting and token swaps."""

    def __init__(self, w3: Web3, network: str = "mainnet", private_key: str | None = None):
        self.w3 = w3
        self.network = network
        self.private_key = private_key

        if private_key:
            self.account = w3.eth.account.from_key(private_key)
            self.eoa = self.account.address
        else:
            self.account = None
            self.eoa = None

        contracts = CONTRACTS[network]
        self.quoter_address = hedera_id_to_evm(contracts["quoter"])
        self.router_address = hedera_id_to_evm(contracts["router"])
        self._whbar_for_path = hedera_id_to_evm(contracts["whbar"])  # kept for completeness

        self.quoter = w3.eth.contract(address=self.quoter_address, abi=QUOTER_ABI)
        self.router = w3.eth.contract(address=self.router_address, abi=ROUTER_ABI)

        self.chain_id = 295 if network == "mainnet" else 296

    def get_quote_single(self, token_in: str, token_out: str, amount_in: int, fee: int = 1500) -> dict:
        """Get a quote for a single-hop swap using quoteExactInput(path)."""
        path = encode_path([token_in, token_out], [fee])
        try:
            result = self.quoter.functions.quoteExactInput(path, amount_in).call()
            return {
                "amountOut": result[0],
                "sqrtPriceX96AfterList": result[1],
                "initializedTicksCrossedList": result[2],
                "gasEstimate": result[3],
            }
        except Exception as e:
            raise RuntimeError(f"Quote failed: {e}")

    def approve_token(self, token_id: str, amount: int | None = None) -> str:
        """Approve router to spend token_id for amount (or max uint256)."""
        if not self.private_key:
            raise ValueError("Private key required")

        token_address = hedera_id_to_evm(token_id)
        token = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
        if amount is None:
            amount = 2**256 - 1

        tx = token.functions.approve(self.router_address, amount).build_transaction({
            "from": self.eoa,
            "gas": 1_000_000,
            "gasPrice": self.w3.eth.gas_price,
            "nonce": self.w3.eth.get_transaction_count(self.eoa),
            "chainId": self.chain_id,
        })

        signed = self.w3.eth.account.sign_transaction(tx, self.private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()

    def get_token_balance(self, token_id: str, account: str | None = None) -> int:
        """Get token balance for account (defaults to EOA)."""
        token_address = hedera_id_to_evm(token_id)
        acct = account or self.eoa
        if acct and not acct.startswith("0x"):
            acct = hedera_id_to_evm(acct)
        token = self.w3.eth.contract(address=token_address, abi=ERC20_ABI)
        return token.functions.balanceOf(acct).call()
