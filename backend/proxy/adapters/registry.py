from backend.proxy.adapters.browserless_cloud import BrowserlessCloudAdapter
from backend.proxy.adapters.cdp import DirectCdpAdapter
from backend.proxy.contracts import ProviderAdapter, ProviderName
from backend.settings import settings


def get_provider_adapter(provider: ProviderName, *, endpoint: str | None = None) -> ProviderAdapter:
    match provider:
        case ProviderName.BROWSERLESS:
            return DirectCdpAdapter(
                provider,
                endpoint or str(settings.browserless_url),
                session_timeout_seconds=settings.browserless_session_timeout_seconds,
            )
        case ProviderName.BROWSERLESS_CLOUD:
            return BrowserlessCloudAdapter(
                base_url=str(settings.browserless_cloud_url),
                token=settings.browserless_cloud_token,
                proxy_country=settings.browserless_cloud_proxy_country,
                session_timeout_seconds=settings.browserless_cloud_session_timeout_seconds,
            )
        case _:
            raise ValueError(f"Unsupported provider: {provider}")
