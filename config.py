from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    nodo_id: str = "nodo-local"
    nodo_nombre: str = "Nodo local"
    nodo_role: str = "slave"
    nodo_api_token: str = "dev-token-change-me"
    nodo_vpn_ip: str = "10.66.0.11"
    nodo_host: str = "0.0.0.0"
    nodo_port: int = 8443
    nodo_ssl_certfile: str = ""
    nodo_ssl_keyfile: str = ""
    nodo_allow_insecure: bool = True

    sync_db_path: str = "./data/sync.sqlite"
    sync_worker_enabled: bool = True
    sync_worker_poll_interval_seconds: float = 0.5

    hub_base_url: str = ""
    hub_api_key: str = ""

    # Contratos guía (multishop-hub): endpoints de nodo autenticados por Bearer apiToken
    hub_nodo_sync_categorias_path: str = "/api/nodo/sync/categorias"
    hub_nodo_categorias_path: str = "/api/nodo/categorias"
    hub_pull_enabled: bool = False
    hub_pull_interval_seconds: int = 10
    hub_pull_path: str = "/orchestration/sync/events"
    hub_pull_batch_size: int = 200

    hub_push_enabled: bool = False
    hub_push_interval_seconds: float = 1.0
    hub_push_path: str = "/orchestration/node-outbox"

    huey_enabled: bool = False
    huey_db_path: str = "./data/huey.sqlite"
    huey_outbox_enqueue_interval_seconds: float = 5.0
    huey_outbox_batch_size: int = 200
    huey_outbox_task_retries: int = 30
    huey_outbox_retry_delay_seconds: int = 10

    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = ""


settings = Settings()
