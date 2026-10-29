from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ONU_", env_file=".env")

    # SQLite para desarrollo. En producción:
    # ONU_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost/onu_auth
    database_url: str = "sqlite:///./onu_auth.db"
    # Si es True, las OLTs de tipo "mock" se permiten (útil para pruebas)
    allow_mock: bool = True
    # Clave con la que se cifran contraseñas, comunidades SNMP y claves privadas de VPN.
    # Si no se define, se crea una en `secret_key_file` la primera vez (permisos 600).
    # IMPORTANTE: respáldala aparte; sin ella no se pueden descifrar los datos guardados.
    secret_key: str = ""
    secret_key_file: str = "./secret.key"
    # Sesiones de usuario: duración máxima y tiempo sin actividad antes de pedir login otra vez.
    session_hours: int = 12
    session_idle_minutes: int = 120
    # Marca la cookie de sesión como "Secure" (solo HTTPS). Actívalo si pones Ritsuko detrás de HTTPS;
    # con HTTPS directo (esquema https) se marca sola. Con HTTP plano debe quedar en False o el
    # navegador no la guardará.
    cookie_secure: bool = False


settings = Settings()
