"""全局配置：一切配置走环境变量，见 deploy/control/.env.example。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TT2_", env_file=".env", extra="ignore")

    # 基础
    env: str = "dev"
    api_base_url: str = "https://cli.tt2.li"  # CLI 与回调使用的公网 API 根
    web_base_url: str = "https://free.hub.tt2.li"  # 控制台公网地址
    app_url: str = "https://free.hub.tt2.li"  # TokenDance 归因 X-App-URL

    # 存储
    database_url: str = "postgresql+asyncpg://tt2:tt2@127.0.0.1:5432/tt2"
    redis_url: str = "redis://127.0.0.1:6379/9"
    staging_dir: str = "/srv/tt2/staging"
    sites_dir: str = "/srv/tt2/sites"

    # 密钥（生产必须覆盖）
    session_secret: str = "dev-session-secret"  # noqa: S105
    fernet_key: str = ""  # Fernet.generate_key() 生成
    internal_secret: str = "dev-internal-secret"  # noqa: S105

    # 观猹 OAuth
    watcha_client_id: str = "1p9Mcr+CNLPAMFC0"  # 官方文档测试 client，上线前替换
    watcha_client_secret: str = "aqkUs+5ZGLSVG6A/L/I0ib9uownWxH+w"  # noqa: S105 官方公开测试凭据
    watcha_authorize_url: str = "https://watcha.cn/oauth/authorize"
    watcha_token_url: str = "https://watcha.cn/oauth/api/token"  # noqa: S105
    watcha_userinfo_url: str = "https://watcha.cn/oauth/api/userinfo"

    # TokenDance / TokenPay
    tokendance_base_url: str = "https://tokendance.space/gateway/v1"
    tokendance_auth_url: str = "https://tokendance.space/auth"
    tokendance_key_exchange_url: str = "https://tokendance.space/portal/api/v1/auth/keys"
    chaxunma_model: str = "glm-5.3-flash"
    platform_tokendance_key: str = ""  # 平台自有 Key（共享免费池熔断时使用）

    # 配额
    max_sites_per_user: int = 5
    max_tasks_per_day: int = 20
    max_upload_bytes: int = 50 * 1024 * 1024
    max_extracted_bytes: int = 100 * 1024 * 1024
    free_pool_daily: int = 50  # 全平台共享免费任务池（每日）
    session_max_rounds: int = 6
    task_timeout_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()
