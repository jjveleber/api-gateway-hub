from app.integrations.base import BaseAPIClient


class RESTCountriesClient(BaseAPIClient):
    """REST Countries API client for country data."""

    base_url = "https://restcountries.com/v3.1"
    rate_limit = 100000  # No official limit, set conservative
    cache_ttl = 86400  # 24 hours (data rarely changes)

    async def fetch(self, country: str) -> dict:
        """Fetch country data by name or code."""
        data = await self._request(f"name/{country}", params={"fullText": "false"})

        if not data:
            raise ValueError(f"Country not found: {country}")

        # Get first match
        country_data = data[0]

        # Normalize response
        return {
            "name": country_data["name"]["common"],
            "official_name": country_data["name"]["official"],
            "capital": country_data.get("capital", ["N/A"])[0],
            "region": country_data["region"],
            "subregion": country_data.get("subregion", "N/A"),
            "population": country_data["population"],
            "area_km2": country_data.get("area"),
            "languages": list(country_data.get("languages", {}).values()),
            "currencies": list(country_data.get("currencies", {}).keys()),
            "timezones": country_data.get("timezones", []),
            "flag_emoji": country_data.get("flag", ""),
        }
