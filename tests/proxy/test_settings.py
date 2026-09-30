from uuid import UUID

import pytest

from backend.proxy.contracts import ProviderName, SettingSource
from backend.proxy.errors import InvalidStolosioSettings
from backend.proxy.settings import stolosio_settings_registry, stolosio_settings_resolver


@pytest.mark.asyncio
async def test_omitted_provider_defaults_to_the_local_fleet() -> None:
    requested, resolved = await stolosio_settings_resolver.resolve([])

    assert requested.overrides == {}
    assert resolved.provider.slug is ProviderName.BROWSERLESS
    assert resolved.sources["stolosio.provider.slug"] is SettingSource.DEFAULT


@pytest.mark.asyncio
async def test_resolves_explicit_provider_and_ignores_non_stolosio_keys() -> None:
    requested, resolved = await stolosio_settings_resolver.resolve(
        [("client.setting", "value"), ("stolosio.provider.slug", "browserless_cloud")]
    )

    assert requested.overrides == {"stolosio.provider.slug": ProviderName.BROWSERLESS_CLOUD}
    assert resolved.provider.slug is ProviderName.BROWSERLESS_CLOUD
    assert resolved.sources["stolosio.provider.slug"] is SettingSource.EXPLICIT


def test_registry_exposes_the_canonical_query_contract() -> None:
    assert stolosio_settings_registry.queries == frozenset(
        {
            "stolosio.provider.slug",
            "stolosio.session.reference",
            "stolosio.session.admission_timeout_ms",
            "stolosio.browserless.proxy_country",
        }
    )


@pytest.mark.asyncio
async def test_resolves_client_generated_session_reference() -> None:
    requested, resolved = await stolosio_settings_resolver.resolve(
        [("stolosio.session.reference", "3a10fc5f-1b31-45d4-b95f-3981ea833a91")]
    )

    assert requested.session_reference == UUID("3a10fc5f-1b31-45d4-b95f-3981ea833a91")
    assert resolved.session.reference == requested.session_reference
    assert resolved.sources["stolosio.session.reference"] is SettingSource.EXPLICIT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        [("stolosio.provider.slug", "")],
        [("stolosio.provider.slug", "BROWSERLESS")],
        [("stolosio.provider.slug", "unknown")],
        [("stolosio.provider.slug", "auto")],
        [("stolosio.provider.slug", "http")],
        [("stolosio.provider.slug", "browserbase")],
        [("stolosio.unknown", "value")],
        [("stolosio.provider", "browserless")],
        [("stolosio.provider.slug", "browserless"), ("stolosio.provider.slug", "browserless")],
        [("stolosio.provider.allow_paid_fallback", "true")],
        [("stolosio.session.browser_required", "true")],
        [("stolosio.session.reference", "not-a-uuid")],
        [("stolosio.session.reference", "auto")],
    ],
)
async def test_rejects_invalid_stolosio_settings(query: list[tuple[str, str]]) -> None:
    with pytest.raises(InvalidStolosioSettings):
        await stolosio_settings_resolver.resolve(query)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["0", "-1", "60001", "1.5", "auto", "invalid"])
async def test_admission_budget_is_bounded(value):
    with pytest.raises(InvalidStolosioSettings):
        await stolosio_settings_resolver.resolve([("stolosio.session.admission_timeout_ms", value)])
