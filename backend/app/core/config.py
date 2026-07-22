from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./vrcatalog.db"
    app_name: str = "VR Catalog"


settings = Settings()
