from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Siempre .env en la raíz de Multishop-nodo-API (no depende del cwd al ejecutar scripts).
_PACKAGE_DIR = Path(__file__).resolve().parent
_ENV_FILE = _PACKAGE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if _ENV_FILE.is_file() else None,
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

    sync_db_path: str = "./data/sync.sqlite"
    sync_worker_enabled: bool = True
    sync_worker_poll_interval_seconds: float = 0.5

    hub_base_url: str = ""

    # Contratos hub↔nodo (Bearer NODO_API_TOKEN)
    hub_nodo_sync_categorias_path: str = "/api/nodo/sync/categorias"
    hub_nodo_sync_proveedores_path: str = "/api/nodo/sync/proveedores"
    hub_nodo_sync_productos_path: str = "/api/nodo/sync/productos"
    hub_nodo_catalog_pull_warnings_path: str = (
        "/api/nodo/catalog-pull-warnings/batch"
    )
    hub_nodo_catalog_push_categorias_path: str = (
        "/api/nodo/catalog-push/categorias/batch"
    )
    hub_nodo_catalog_push_proveedores_path: str = (
        "/api/nodo/catalog-push/proveedores/batch"
    )
    hub_nodo_catalog_push_inventario_path: str = (
        "/api/nodo/catalog-push/inventario/batch"
    )
    hub_nodo_sync_jobs_path: str = "/api/nodo/sync-jobs"
    hub_nodo_categorias_path: str = "/api/nodo/categorias"
    hub_nodo_proveedores_path: str = "/api/nodo/proveedores"

    hub_push_enabled: bool = False
    hub_push_interval_seconds: float = 1.0
    # Contrato actual: node -> hub (ingest) para transaccional vía outbox.
    hub_push_path: str = "/api/nodo/events/batch"

    huey_enabled: bool = False
    huey_db_path: str = "./data/huey.sqlite"
    huey_outbox_enqueue_interval_seconds: float = 5.0
    huey_outbox_batch_size: int = 200
    huey_outbox_task_retries: int = 30
    huey_outbox_retry_delay_seconds: int = 10

    nodo_sync_jobs_dir: str = "./data/sync-jobs"
    catalog_sync_progress_throttle_ms: int = 2000
    huey_catalog_sync_enabled: bool = True

    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = ""


settings = Settings()
