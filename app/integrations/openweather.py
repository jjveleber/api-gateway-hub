from app.integrations.base import BaseAPIClient
from app.config import settings


class OpenWeatherClient(BaseAPIClient):
    """OpenWeather API client for weather data."""

    base_url = "https://api.openweathermap.org/data/2.5"
    rate_limit = 1000  # free tier: 1000 calls/day
    cache_ttl = 900  # 15 minutes

    async def fetch(self, city: str) -> dict:
        """Fetch weather data for a city."""
        data = await self._request(
            "weather",
            {
                "q": city,
                "appid": settings.openweather_api_key,
                "units": "metric",
            },
        )

        # Normalize response
        return {
            "city": data["name"],
            "country": data["sys"]["country"],
            "temperature": data["main"]["temp"],
            "feels_like": data["main"]["feels_like"],
            "humidity": data["main"]["humidity"],
            "description": data["weather"][0]["description"],
            "wind_speed": data["wind"]["speed"],
        }
