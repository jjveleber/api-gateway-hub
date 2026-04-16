from fastapi import FastAPI, Depends
import logging

from app.api import weather, crypto, countries
from app.dependencies import get_rate_limiter
from app.services.rate_limiter import RateLimiter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(
    title="API Gateway Hub",
    description="Integration service aggregating multiple external APIs",
    version="1.0.0",
)

# Include routers
app.include_router(weather.router, prefix="/api", tags=["Weather"])
app.include_router(crypto.router, prefix="/api", tags=["Crypto"])
app.include_router(countries.router, prefix="/api", tags=["Countries"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "API Gateway Hub",
        "version": "1.0.0",
        "endpoints": ["/api/weather", "/api/crypto", "/api/countries", "/status"],
    }


@app.get("/status")
async def get_status(rate_limiter: RateLimiter = Depends(get_rate_limiter)):
    """Get rate limit status for all APIs."""
    return {
        "openweather": {
            "usage": await rate_limiter.get_usage("openweather"),
            "limit": 1000,
            "remaining": 1000 - await rate_limiter.get_usage("openweather"),
        },
        "coingecko": {
            "usage": await rate_limiter.get_usage("coingecko"),
            "limit": 10000,
            "remaining": 10000 - await rate_limiter.get_usage("coingecko"),
        },
        "restcountries": {
            "usage": await rate_limiter.get_usage("restcountries"),
            "limit": 100000,
            "remaining": 100000 - await rate_limiter.get_usage("restcountries"),
        },
    }
