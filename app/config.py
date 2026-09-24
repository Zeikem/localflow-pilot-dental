from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./localflow.db"
    auto_create_schema: bool = True

    whatsapp_verify_token: str = "dev-verify-token"
    whatsapp_app_secret: str = ""
    meta_graph_api_version: str = "v26.0"

    # Obligatorio para endpoints /admin en despliegues reales.
    admin_api_token: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
