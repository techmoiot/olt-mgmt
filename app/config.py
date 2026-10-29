from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ONU_", env_file=".env")

    # SQLite para desarrollo. En producción:
    # ONU_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost/onu_auth
    database_url: str = "sqlite:///./onu_auth.db"
    # Si es True, las OLTs de tipo "mock" se permiten (útil para pruebas)
    allow_mock: bool = True


settings = Settings()
