from functools import lru_cache

from pydantic import AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Stolosio"
    database_url: str = "postgresql+asyncpg://stolosio:stolosio@localhost:5433/stolosio"
    nats_url: AnyUrl = AnyUrl("nats://localhost:4223")
    nats_seed: str = ""
    nats_connect_timeout_seconds: float = 1
    jetstream_event_max_age_seconds: int = 86_400
    jetstream_event_max_bytes: int = 10 * 1024 * 1024 * 1024
    jetstream_event_max_message_bytes: int = 256 * 1024
    jetstream_event_duplicate_window_seconds: int = 600
    jetstream_event_replicas: int = 1
    jetstream_dead_letter_max_bytes: int = 256 * 1024 * 1024
    event_recorder_batch_size: int = 250
    event_recorder_fetch_timeout_seconds: float = 1
    event_recorder_ack_wait_seconds: int = 60
    event_recorder_max_deliver: int = 5
    debug_reference_wait_seconds: float = 30
    debug_stream_max_pending_events: int = 1_000
    debug_stream_max_pending_bytes: int = 4 * 1024 * 1024
    maintenance_metrics_port: int = 9000
    maintenance_retention_interval_seconds: int = 3600
    session_event_retention_days: int = 30
    terminal_session_retention_days: int = 90
    domain_history_retention_days: int = 365
    capture_method_cache_retention_days: int = 30
    capture_default_deadline_ms: int = 120_000
    retention_delete_batch_size: int = 10_000
    browserless_url: AnyUrl = AnyUrl("ws://localhost:3000")
    browserless_session_timeout_seconds: int = 600
    # Browserless cloud (paid): stealth browsers behind residential proxies. Credentials and
    # endpoint only; whether it's enabled and how many run at once is operator policy
    # (external_provider_limits).
    browserless_cloud_url: AnyUrl = AnyUrl("https://production-sfo.browserless.io")
    browserless_cloud_token: str = ""
    browserless_cloud_proxy_country: str = "jp"
    browserless_cloud_session_timeout_seconds: int = 300
    stolosio_max_active_sessions: int = 100
    session_lease_seconds: float = 30
    session_heartbeat_seconds: float = 10
    provider_queue_poll_ms: int = 1000
    provider_queue_timeout_seconds: float = 30
    provider_acquisition_timeout_seconds: int = 30
    session_cleanup_timeout_seconds: float = 2
    http_request_timeout_seconds: float = 20
    # Page acquisition must never inherit the API process's internal network access.
    http_fetch_proxy_url: str = "http://localhost:3128"
    http_max_response_bytes: int = 10 * 1024 * 1024
    fleet_reconcile_interval_seconds: float = 1
    fleet_observation_ttl_seconds: float = 5
    fleet_instance_startup_timeout_seconds: float = 30
    fleet_controller_backoff_seconds: float = 2
    fleet_controller_metrics_port: int = 9101
    fleet_compose_project_name: str = "stolosio"
    fleet_compose_workdir: str = "."
    browserless_fleet_compose_service: str = "browserless"
    kubernetes_namespace: str = "stolosio"
    kubernetes_browserless_statefulset: str = "stolosio-browserless"
    kubernetes_browserless_workload_config_map: str = "stolosio-browserless-workload"
    kubernetes_browserless_headless_service: str = "stolosio-browserless-headless"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
