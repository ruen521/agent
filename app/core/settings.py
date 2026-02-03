from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    qingyun_api_url: str = "https://api.qingyuntop.top"
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
