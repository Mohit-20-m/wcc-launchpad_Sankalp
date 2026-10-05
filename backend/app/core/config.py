"""
All configuration for the backend comes from environment variables,
which docker-compose.yml injects from your .env file. Nothing is
hardcoded here, and nothing here ever calls out to the internet.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "development"

    database_url: str = "postgresql+asyncpg://launchpad:launchpad_dev_password@postgres:5432/launchpad"
    redis_url: str = "redis://redis:6379/0"

    jwt_secret: str = "change_this_in_production"

    # Where uploaded submission files live (a Docker volume in compose).
    upload_dir: str = "/data/uploads"
    # Outbound webhooks. Private/loopback targets are refused by default so a
    # webhook can't be aimed at the platform's own internal network (SSRF);
    # set WEBHOOK_ALLOW_PRIVATE=true only to test against a local receiver.
    webhook_allow_private: bool = False
    webhook_timeout_seconds: float = 5.0
    webhook_retry_delays: str = "5,30,120,600,3600"  # seconds between attempts
    webhook_poll_seconds: float = 2.0
    # Used in certificate QR codes when the request's own host isn't right.
    public_base_url: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours

    # --- Email notifications ---
    # sendgrid: the SendGrid v3 HTTP API (needs SENDGRID_API_KEY and a
    #           MAIL_FROM address you verified in SendGrid)
    # smtp:     any SMTP server (Gmail with an app password, SendGrid SMTP,
    #           your host's mail server...)
    # disabled: emails are still recorded in the outbox (visible to the
    #           organizer) but never sent.
    # Until the chosen provider is configured, emails are recorded as
    # "skipped: not configured" instead of failing over and over.
    mail_provider: str = "sendgrid"
    mail_from: str = "Launchpad <noreply@example.com>"
    sendgrid_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    # Extra comma-separated domains never emailed. The reserved demo domains
    # used by the seed data (example.org/.com/.net, *.example, *.test...) are
    # ALWAYS skipped, so demo and fixture accounts never receive mail.
    mail_skip_domains: str = ""
    mail_retry_delays: str = "30,120,600,1800"
    # Where links inside emails point. Falls back to http://localhost:8080.
    platform_name: str = "Launchpad"

    # --- Code-level duplicate detection (GitHub) ---
    # Optional. Without a token GitHub allows ~60 API calls/hour (about 15
    # repositories); a token with no scopes at all raises that to 5,000.
    github_token: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
