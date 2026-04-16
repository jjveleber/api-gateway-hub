import pytest
import httpx
import respx

from app.integrations.coingecko import CoinGeckoClient


@pytest.mark.asyncio
@respx.mock
async def test_coingecko_client_fetch():
    """Test CoinGecko client fetches and normalizes data."""
    respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
        return_value=httpx.Response(
            200,
            json={
                "bitcoin": {
                    "usd": 45000.0,
                    "usd_market_cap": 850000000000,
                    "usd_24h_change": 2.5,
                }
            },
        )
    )

    client = CoinGeckoClient()
    data = await client.fetch(symbol="btc")

    assert data["symbol"] == "BTC"
    assert data["coin_id"] == "bitcoin"
    assert data["price_usd"] == 45000.0
    assert data["market_cap_usd"] == 850000000000
    assert data["change_24h_percent"] == 2.5


@pytest.mark.asyncio
@respx.mock
async def test_coingecko_client_unknown_symbol():
    """Test CoinGecko client handles unknown symbol."""
    respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
        return_value=httpx.Response(200, json={})
    )

    client = CoinGeckoClient()

    with pytest.raises(ValueError, match="Unknown symbol"):
        await client.fetch(symbol="UNKNOWN")


@pytest.mark.asyncio
@respx.mock
async def test_coingecko_client_symbol_mapping():
    """Test symbol to coin_id mapping works."""
    respx.get("https://api.coingecko.com/api/v3/simple/price").mock(
        return_value=httpx.Response(
            200,
            json={
                "ethereum": {
                    "usd": 3000.0,
                    "usd_market_cap": 360000000000,
                    "usd_24h_change": -1.2,
                }
            },
        )
    )

    client = CoinGeckoClient()
    data = await client.fetch(symbol="eth")

    assert data["symbol"] == "ETH"
    assert data["coin_id"] == "ethereum"
    assert data["price_usd"] == 3000.0
