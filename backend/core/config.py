from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME:    str = "Rwanda Commodity Price API"
    APP_VERSION: str = "1.0.0"
    DEBUG:       bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    DB_HOST:     str = "postgres"
    DB_PORT:     int = 5432
    DB_NAME:     str = "commodities"
    DB_USER:     str = "admin"
    DB_PASSWORD: str = "strongpassword"

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://"
            f"{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ── Ollama ────────────────────────────────────────────────────────────────
    OLLAMA_HOST:  str = "http://host.docker.internal:11434"
    OLLAMA_MODEL: str = "mistral:7b-instruct-q4"

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Comma-separated string in .env: CORS_ORIGINS=https://a.com,https://b.com
    # Use * for development to allow all origins.
    CORS_ORIGINS: str = "*"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str) -> str:
        """Ensure CORS_ORIGINS is a valid string"""
        if isinstance(v, str):
            return v
        return "*"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    # ── Pagination ────────────────────────────────────────────────────────────
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE:     int = 500

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()