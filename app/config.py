from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Premium B2B Mailer"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5.6-luna"
    assistant_daily_limit: int = 30
    app_env: str = "development"
    free_plan_test_mode: bool = False
    app_secret_key: str = "development-only-secret-key-change-me"
    database_url: str = "postgresql+asyncpg://mailer_app:mailer_app_local@localhost:5432/mailer"
    migration_database_url: str | None = None
    database_null_pool: bool = False
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    default_sender_domain: str = "localhost"
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "mailer"
    s3_region: str = "us-east-1"
    public_base_url: str = "http://localhost:8000"
    email_provider: str = "smtp"
    aws_region: str = "eu-central-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    ses_configuration_set: str = ""
    ses_sns_topic_arn: str = ""
    bitrix24_webhook_url: str = ""
    hunter_api_key: str = ""
    neverbounce_api_key: str = ""
    neverbounce_api_url: str = "https://api.neverbounce.com/v4"
    linkedin_access_token: str = ""
    linkedin_api_base_url: str = "https://api.linkedin.com/rest"
    linkedin_api_version: str = "202601"
    tenchat_access_token: str = ""
    tenchat_api_base_url: str = "https://api.tenchat.ru/v1"
    tenchat_account_tier: str = "free"
    integration_max_retries: int = 3
    integration_circuit_failure_threshold: int = 5
    integration_circuit_recovery_seconds: float = 60.0
    notification_from_email: str = "notifications@localhost"
    webpush_vapid_private_key: str = ""
    webpush_vapid_public_key: str = ""
    webpush_vapid_subject: str = "mailto:admin@localhost"
    telegram_bot_token: str = ""
    webhook_allow_private_urls: bool = False
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_webhook_tolerance_seconds: int = 300
    tinkoff_terminal_key: str = ""
    tinkoff_password: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, value: object) -> object:
        if isinstance(value, str) and not value.startswith("["):
            return [part.strip() for part in value.split(",")]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
