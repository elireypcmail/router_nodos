from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_DIR = Path(__file__).resolve().parent.parent
_ENV_TXT_FILE = _ROOT_DIR / "env.txt"
_DOTENV_FILE = _ROOT_DIR / ".env"


def _pick_env_file() -> Path | None:
    if _ENV_TXT_FILE.is_file():
        return _ENV_TXT_FILE
    if _DOTENV_FILE.is_file():
        return _DOTENV_FILE
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_pick_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    nodo_id: str = "nodo-local"
    nodo_nombre: str = "Nodo local"
    nodo_role: str = "slave"
    nodo_api_token: str = "dev-token-change-me"
    nodo_vpn_ip: str = "10.66.0.11"
    nodo_host: str = "0.0.0.0"
    nodo_port: int = 8443
    nodo_ssl_certfile: str = ""
    nodo_ssl_keyfile: str = ""
    nodo_ssl_client_ca_file: str = ""
    nodo_ssl_client_cert_required: bool = False
    nodo_allow_insecure: bool = True

    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = ""
    nodo_mysql_startup_attempts: int = 30
    nodo_mysql_startup_delay_seconds: float = 2.0


settings = Settings()
