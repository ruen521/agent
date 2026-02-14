from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    qingyun_api_url: str = "https://api.qingyuntop.top/v1"
    qingyun_api_key: str = ""
    qingyun_model: str = "gpt-4o"
    daily_holding_cost_pct: float = 0.0007  # ~25% 年化

    spapi_refresh_token: str = Field(
        default="", validation_alias=AliasChoices("SPAPI_REFRESH_TOKEN", "AMAZON_SP_API_REFRESH_TOKEN")
    )
    lwa_client_id: str = Field(
        default="", validation_alias=AliasChoices("LWA_CLIENT_ID", "AMAZON_SP_API_CLIENT_ID")
    )
    lwa_client_secret: str = Field(
        default="", validation_alias=AliasChoices("LWA_CLIENT_SECRET", "AMAZON_SP_API_CLIENT_SECRET")
    )
    aws_seller_id: str = Field(
        default="", validation_alias=AliasChoices("AWS_SELLER_ID", "AMAZON_SP_API_SELLER_ID")
    )
    aws_role_arn: str = Field(
        default="", validation_alias=AliasChoices("AWS_ROLE_ARN", "AMAZON_SP_API_ROLE_ARN")
    )
    spapi_access_key: str = Field(
        default="", validation_alias=AliasChoices("SPAPI_ACCESS_KEY", "AMAZON_SP_API_ACCESS_KEY")
    )
    spapi_secret_key: str = Field(
        default="", validation_alias=AliasChoices("SPAPI_SECRET_KEY", "AMAZON_SP_API_SECRET_KEY")
    )
    spapi_region: str = Field(
        default="na", validation_alias=AliasChoices("SPAPI_REGION", "AMAZON_SP_API_REGION")
    )
    spapi_use_sandbox: bool = Field(
        default=True, validation_alias=AliasChoices("SPAPI_USE_SANDBOX", "AMAZON_SP_API_USE_SANDBOX")
    )
    spapi_marketplace_id: str = Field(
        default="us", validation_alias=AliasChoices("SPAPI_MARKETPLACE", "AMAZON_SP_API_MARKETPLACE")
    )

    api_key: str = ""
    allowed_origins: str = "http://localhost:5173"
    rate_limit_per_minute: int = 120
    database_url: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE_URL", "MYSQL_URL"),
    )
    db_strict: bool = True
    alert_error_rate: float = 0.2
    alert_min_requests: int = 50
    alert_llm_error_rate: float = 0.3
    alert_llm_min_requests: int = 20
    alert_webhook_url: str = ""
    alert_cooldown_seconds: int = 300

    session_store_path: str = "data/session_memory.json"
    session_max_messages: int = 20

    agent_lifecycle_path: str = "data/agent_lifecycle.json"
    agent_default_alias: str = "prod"
    planner_max_steps: int = 6
    planner_max_replans: int = 4
    strict_error_mode: bool = True
    report_dispatch_mode: str = "subprocess"
    report_worker_python: str = ""
    report_pdf_timeout_seconds: int = 120

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
