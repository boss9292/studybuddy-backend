from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import List

class Settings(BaseSettings):
    # OpenAI
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    MOCK_MODE: bool = False

    # Performance knobs
    MAX_PAGES: int = 30
    CONCURRENCY: int = 4

    # Safety/abuse knobs
    MAX_UPLOAD_MB: int = 25
    RATE_LIMIT: str = "30/minute"

    # CORS
    ALLOW_ORIGINS: List[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # Optional extra frontend
    FRONTEND_ORIGIN: str | None = None

    # Supabase
    SUPABASE_URL: str | None = None
    SUPABASE_SERVICE_ROLE_KEY: str | None = None
    SUPABASE_JWT_SECRET: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
if settings.FRONTEND_ORIGIN:
    settings.ALLOW_ORIGINS.append(settings.FRONTEND_ORIGIN)
