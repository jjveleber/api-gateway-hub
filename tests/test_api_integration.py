import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
import httpx
import respx

from app.main import app


client = TestClient(app)


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    with patch("app.dependencies.get_redis") as mock:
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        redis_mock.setex.return_value = None
        redis_mock.incr.return_value = 1
        redis_mock.expire.return_value = None
        mock.return_value = redis_mock
        yield redis_mock


@respx.mock
def test_weather_endpoint_success(mock_redis):
    """Test /api/weather endpoint returns weather data."""
    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "London",
                "sys": {"country": "GB"},
                "main": {"temp": 15.2, "feels_like": 14.1, "humidity": 72},
                "weather": [{"description": "cloudy"}],
                "wind": {"speed": 3.5},
            },
        )
    )

    response = client.get("/api/weather?city=London")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "openweather"
    assert data["data"]["city"] == "London"
    assert data["data"]["temperature"] == 15.2
    assert data["cached"] is False


@respx.mock
def test_weather_endpoint_cached(mock_redis):
    """Test /api/weather returns cached data on second request."""
    # First request: cache miss
    mock_redis.get.return_value = None
    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Paris",
                "sys": {"country": "FR"},
                "main": {"temp": 18.0, "feels_like": 17.0, "humidity": 65},
                "weather": [{"description": "sunny"}],
                "wind": {"speed": 2.0},
            },
        )
    )

    response1 = client.get("/api/weather?city=Paris")
    assert response1.json()["cached"] is False

    # Second request: cache hit
    mock_redis.get.return_value = '{"city": "Paris", "temperature": 18.0}'

    response2 = client.get("/api/weather?city=Paris")
    assert response2.json()["cached"] is True


@respx.mock
def test_crypto_endpoint_success(mock_redis):
    """Test /api/crypto endpoint returns crypto data."""
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

    response = client.get("/api/crypto?symbol=btc")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "coingecko"
    assert data["data"]["symbol"] == "BTC"
    assert data["data"]["price_usd"] == 45000.0
    assert data["cached"] is False


@respx.mock
def test_countries_endpoint_success(mock_redis):
    """Test /api/countries endpoint returns country data."""
    respx.get("https://restcountries.com/v3.1/name/Japan").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "name": {"common": "Japan", "official": "Japan"},
                    "capital": ["Tokyo"],
                    "region": "Asia",
                    "subregion": "Eastern Asia",
                    "population": 125000000,
                    "area": 377975,
                    "languages": {"jpn": "Japanese"},
                    "currencies": {"JPY": {"name": "Japanese yen"}},
                    "timezones": ["UTC+09:00"],
                    "flag": "🇯🇵",
                }
            ],
        )
    )

    response = client.get("/api/countries?country=Japan")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "restcountries"
    assert data["data"]["name"] == "Japan"
    assert data["data"]["capital"] == "Tokyo"
    assert data["cached"] is False


def test_status_endpoint(mock_redis):
    """Test /status endpoint returns rate limit info."""
    mock_redis.get.return_value = "42"

    response = client.get("/status")

    assert response.status_code == 200
    data = response.json()
    assert "openweather" in data
    assert "coingecko" in data
    assert "restcountries" in data
    assert data["openweather"]["usage"] == 42
    assert data["openweather"]["limit"] == 1000


def test_root_endpoint():
    """Test root endpoint returns API info."""
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "API Gateway Hub"
    assert "/api/weather" in data["endpoints"]
