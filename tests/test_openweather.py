import pytest
import httpx
import respx

from app.integrations.openweather import OpenWeatherClient


@pytest.mark.asyncio
@respx.mock
async def test_openweather_client_fetch():
    """Test OpenWeather client fetches and normalizes data."""
    # Mock the OpenWeather API response
    respx.get("https://api.openweathermap.org/data/2.5/weather").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "London",
                "sys": {"country": "GB"},
                "main": {
                    "temp": 20.5,
                    "feels_like": 19.2,
                    "humidity": 65,
                },
                "weather": [{"description": "cloudy"}],
                "wind": {"speed": 5.5},
            },
        )
    )

    client = OpenWeatherClient()
    data = await client.fetch(city="London")

    assert data["city"] == "London"
    assert data["country"] == "GB"
    assert data["temperature"] == 20.5
    assert data["feels_like"] == 19.2
    assert data["humidity"] == 65
    assert data["description"] == "cloudy"
    assert data["wind_speed"] == 5.5


@pytest.mark.asyncio
@respx.mock
async def test_openweather_client_retry_on_failure():
    """Test OpenWeather client retries on failure."""
    # First two calls fail, third succeeds
    route = respx.get("https://api.openweathermap.org/data/2.5/weather")
    route.mock(side_effect=[
        httpx.Response(500),
        httpx.Response(500),
        httpx.Response(
            200,
            json={
                "name": "Paris",
                "sys": {"country": "FR"},
                "main": {"temp": 18.0, "feels_like": 17.0, "humidity": 70},
                "weather": [{"description": "rainy"}],
                "wind": {"speed": 3.0},
            },
        ),
    ])

    client = OpenWeatherClient()
    data = await client.fetch(city="Paris")

    assert data["city"] == "Paris"
    assert route.call_count == 3  # Retried twice before success
