from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Environment
    ENV: str = "development"
    SERVICE_NAME: str = "erp-v-backend"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/erp_v"

    # JWT / authentication
    SECRET_KEY: str = "dev-only-insecure-secret-change-in-production-32+"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # Password policy / brute-force lockout
    PASSWORD_MIN_LENGTH: int = 12
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15

    # Observability (env-driven; features are no-ops when unset)
    SENTRY_DSN: str | None = None
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    OTEL_ENABLED: bool = False

    # Fiscal — provedor de transmissão DF-e (assinatura ICP-Brasil + SEFAZ
    # delegados a um provedor, ex.: Focus NFe). Sem isto, a emissão é recusada
    # com erro claro (nunca saída fictícia).
    FISCAL_PROVIDER_URL: str | None = None
    FISCAL_PROVIDER_TOKEN: str | None = None

    # CORS (comma-separated origins)
    CORS_ORIGINS: str = "http://localhost:3000"

    # Paths that bypass JWT authentication (comma-separated prefixes).
    # Bank webhooks authenticate via HMAC signature, not user tokens.
    PUBLIC_PATH_PREFIXES: str = (
        "/health,/readiness,/api/v1/auth/login,/api/v1/auth/refresh,"
        "/api/v1/integrations/banking"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def public_path_prefixes(self) -> tuple[str, ...]:
        return tuple(
            p.strip() for p in self.PUBLIC_PATH_PREFIXES.split(",") if p.strip()
        )

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
