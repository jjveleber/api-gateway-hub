from pydantic import BaseModel
from datetime import datetime


class APIResponse(BaseModel):
    """Unified response format for all APIs."""

    source: str  # "openweather", "coingecko", etc.
    data: dict  # Original API response (normalized)
    cached: bool  # True if from cache
    cached_at: datetime | None  # When cached
    request_id: str  # UUID for logging/debugging
