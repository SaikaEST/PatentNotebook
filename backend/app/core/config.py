from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "patent-notebook"
    env: str = "dev"
    api_port: int = 8000
    frontend_port: int = 3000

    database_url: str = "postgresql+psycopg2://patent:patent@postgres:5432/patent_notebook"
    redis_url: str = "redis://redis:6379/0"

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minio"
    minio_secret_key: str = "minio123"
    minio_bucket: str = "patent-notebook"

    jwt_secret: str = "dev-secret"
    jwt_alg: str = "HS256"
    jwt_expires_min: int = 120

    enable_oidc: bool = False
    enable_saml: bool = False

    vector_dim: int = 1536

    # Enterprise fallback: import files from an internal DMS path by case number folder.
    dms_root: str = "/data/dms"
    dms_recursive: bool = False

    # CNIPR adapter configuration.
    cnipr_base_url: str = "https://open.cnipr.com"
    cnipr_client_id: str = ""
    cnipr_client_secret: str = ""
    cnipr_user_account: str = ""
    cnipr_user_password: str = ""
    cnipr_access_token: str = ""
    cnipr_openid: str = ""
    cnipr_token_expires_in: int = 3600
    cnipr_timeout_sec: int = 20
    cnipr_dbs: str = "FMZL,FMSQ,SYXX,WGZL"

    # EPO OPS adapter configuration.
    epo_ops_key: str = ""
    epo_ops_secret: str = ""
    epo_ops_timeout_sec: int = 30
    ep_ingest_out_dir: str = "/data"
    ep_register_delay_sec: float = 0.5
    ep_register_concurrency: int = 2
    ep_register_log_level: str = "INFO"
    ep_register_browser_fallback: bool = False
    ep_register_browser_headless: bool = True
    ep_register_browser_user_data_dir: str = ""
    ep_register_proxy: str = ""
    ep_register_only: bool = False

    # OCR fallback for image/scanned PDFs.
    enable_pdf_ocr: bool = True
    pdf_ocr_min_chars: int = 80
    pdf_ocr_page_min_chars: int = 20
    pdf_ocr_max_pages: int = 40
    pdf_ocr_scale: float = 2.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
