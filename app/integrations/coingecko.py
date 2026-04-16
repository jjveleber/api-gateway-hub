from app.integrations.base import BaseAPIClient


class CoinGeckoClient(BaseAPIClient):
    """CoinGecko API client for cryptocurrency prices."""

    base_url = "https://api.coingecko.com/api/v3"
    rate_limit = 10000  # free tier: 10-50 calls/min
    cache_ttl = 300  # 5 minutes

    async def fetch(self, symbol: str) -> dict:
        """Fetch crypto price data for a symbol."""
        # CoinGecko uses coin IDs, not symbols
        # Common mappings: btc -> bitcoin, eth -> ethereum
        coin_id_map = {
            "btc": "bitcoin",
            "eth": "ethereum",
            "usdt": "tether",
            "bnb": "binancecoin",
            "sol": "solana",
            "usdc": "usd-coin",
            "xrp": "ripple",
            "ada": "cardano",
            "doge": "dogecoin",
            "trx": "tron",
        }

        coin_id = coin_id_map.get(symbol.lower(), symbol.lower())

        data = await self._request(
            f"simple/price",
            {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
            },
        )

        if coin_id not in data:
            raise ValueError(f"Unknown symbol: {symbol}")

        coin_data = data[coin_id]

        # Normalize response
        return {
            "symbol": symbol.upper(),
            "coin_id": coin_id,
            "price_usd": coin_data["usd"],
            "market_cap_usd": coin_data.get("usd_market_cap"),
            "change_24h_percent": coin_data.get("usd_24h_change"),
        }
