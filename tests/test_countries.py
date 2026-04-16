import pytest
import httpx
import respx

from app.integrations.countries import RESTCountriesClient


@pytest.mark.asyncio
@respx.mock
async def test_countries_client_fetch():
    """Test REST Countries client fetches and normalizes data."""
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

    client = RESTCountriesClient()
    data = await client.fetch(country="Japan")

    assert data["name"] == "Japan"
    assert data["official_name"] == "Japan"
    assert data["capital"] == "Tokyo"
    assert data["region"] == "Asia"
    assert data["subregion"] == "Eastern Asia"
    assert data["population"] == 125000000
    assert data["area_km2"] == 377975
    assert data["languages"] == ["Japanese"]
    assert data["currencies"] == ["JPY"]
    assert data["timezones"] == ["UTC+09:00"]
    assert data["flag_emoji"] == "🇯🇵"


@pytest.mark.asyncio
@respx.mock
async def test_countries_client_not_found():
    """Test REST Countries client handles country not found."""
    respx.get("https://restcountries.com/v3.1/name/NotACountry").mock(
        return_value=httpx.Response(200, json=[])
    )

    client = RESTCountriesClient()

    with pytest.raises(ValueError, match="Country not found"):
        await client.fetch(country="NotACountry")
