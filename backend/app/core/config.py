from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Guardian Gateway"
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://guardian:change-me-locally@localhost:5432/guardian_gateway"
    redis_url: str = "redis://localhost:6379/0"
    redis_socket_timeout_seconds: float = 1.0
    redis_connect_timeout_seconds: float = 1.0
    frontend_origin: str = "http://localhost:3000"
    admin_token: str = "change-me-admin-token"
    allowed_upstream_hosts: str = "mock-upstream,localhost,127.0.0.1"

    @property
    def upstream_host_allowlist(self) -> set[str]:
        return {
            hostname.strip().rstrip(".").lower()
            for hostname in self.allowed_upstream_hosts.split(",")
            if hostname.strip()
        }

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
