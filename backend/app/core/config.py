from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EXPORT_IMAGE_CACHE_MAX_MB = 500
EXPORT_IMAGE_CACHE_TARGET_MB = 450


class Settings(BaseSettings):
    """Настройки приложения, которые можно переопределить через .env или переменные контейнера."""

    database_url: str = "sqlite:///./vrcatalog.db"
    app_name: str = "VR Catalog"
    port: int = 8000
    upload_dir: str = "/app/uploads"
    secret_key: str = "change-me"
    previous_secret_key: str = ""
    internal_api_token: str = ""
    admin_password_hash: str = ""
    environment: str = "development"
    cors_origins: str = "http://localhost:8080,http://127.0.0.1:8080"
    enable_api_docs: bool = True
    admin_session_hours: int = 8
    max_xml_upload_mb: int = 200
    image_allowed_hosts: str = ""
    base_path: str = "/vr/catalog"
    export_image_cache_max_mb: int = EXPORT_IMAGE_CACHE_MAX_MB
    export_image_cache_target_mb: int = EXPORT_IMAGE_CACHE_TARGET_MB

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    @property
    def normalized_base_path(self) -> str:
        return "/" + self.base_path.strip("/") if self.base_path.strip("/") else ""

    @property
    def parsed_cors_origins(self) -> list[str]:
        return [item.strip().rstrip("/") for item in self.cors_origins.split(",") if item.strip()]

    @property
    def parsed_image_allowed_hosts(self) -> set[str]:
        return {item.strip().casefold() for item in self.image_allowed_hosts.split(",") if item.strip()}

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if self.environment.casefold() != "production":
            return self
        placeholders = {"", "change-me", "change-this-secret-key", "replace-me", "secret"}
        normalized_secret = self.secret_key.casefold().replace("_", "-")
        if normalized_secret in placeholders or normalized_secret.startswith(("change-", "replace-")) or len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY должен быть случайным значением длиной не менее 32 символов")
        normalized_token = self.internal_api_token.casefold().replace("_", "-")
        if len(self.internal_api_token) < 32 or normalized_token.startswith(("replace-", "change-")):
            raise ValueError("INTERNAL_API_TOKEN должен быть случайным значением длиной не менее 32 символов")
        if not self.admin_password_hash.startswith("$argon2id$"):
            raise ValueError("ADMIN_PASSWORD_HASH должен содержать Argon2id hash")
        if self.enable_api_docs:
            raise ValueError("ENABLE_API_DOCS должен быть false в production")
        if self.parsed_cors_origins != ["https://kvasmix.ru"]:
            raise ValueError("CORS_ORIGINS в production должен быть https://kvasmix.ru")
        return self


settings = Settings()
