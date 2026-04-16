from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost/api_gateway"
    redis_url: str = "redis://localhost:6379/0"
    openweather_api_key: str = ""
    coingecko_api_key: str = ""
    log_level: str = "INFO"


settings = Settings()
