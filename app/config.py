from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./impulvera.db"
    auto_create_schema: bool = True

    whatsapp_verify_token: str = "dev-verify-token"
    whatsapp_app_secret: str = ""
    meta_graph_api_version: str = "v26.0"

    # Optional automation relay. When unset, Impulvera remains fully functional
    # without n8n. Configure only an HTTPS endpoint controlled by the operator.
    n8n_ingress_url: str = ""
    n8n_shared_secret: str = ""

    # Obligatorio para endpoints /admin en despliegues reales.
    admin_api_token: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
