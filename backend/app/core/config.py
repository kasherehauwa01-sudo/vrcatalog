from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения, которые можно переопределить через .env или переменные контейнера."""

    database_url: str = "sqlite:///./vrcatalog.db"
    app_name: str = "VR Catalog"
    port: int = 8000
    upload_dir: str = "/app/uploads"
    image_dir: str = "/app/images"
    secret_key: str = "change-me"
    base_path: str = "/vr/catalog"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    @property
    def normalized_base_path(self) -> str:
        return "/" + self.base_path.strip("/") if self.base_path.strip("/") else ""


settings = Settings()
