from abc import ABC, abstractmethod
from tenacity import retry, stop_after_attempt, wait_exponential
import httpx


class BaseAPIClient(ABC):
    """Abstract base for all external API clients."""

    base_url: str
    rate_limit: int  # requests per day
    cache_ttl: int  # seconds

    @abstractmethod
    async def fetch(self, **params) -> dict:
        """Fetch and normalize data from external API."""
        pass

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _request(self, endpoint: str, params: dict = None) -> dict:
        """Make HTTP request with retry logic."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/{endpoint}", params=params
            )
            response.raise_for_status()
            return response.json()


class RateLimitExceeded(Exception):
    """Raised when API rate limit is exceeded."""

    pass
