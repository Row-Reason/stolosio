import pytest
from sqlalchemy import select

from backend.db.models import ExternalProviderLimitEvent
from backend.proxy.contracts import ProviderName
from backend.proxy.external_capacity import (
    ExternalCapacityEnablementError,
    ExternalCapacityRepository,
)


@pytest.mark.asyncio
async def test_bootstrap_preserves_database_external_capacity(
    database_sessions,
) -> None:
    repository = ExternalCapacityRepository(database_sessions)
    initial = await repository.ensure(
        ProviderName.BROWSERLESS_CLOUD,
        enabled=False,
        max_active_sessions=5,
        max_queued_attempts=100,
    )
    preserved = await repository.ensure(
        ProviderName.BROWSERLESS_CLOUD,
        enabled=True,
        max_active_sessions=9,
        max_queued_attempts=40,
    )

    assert initial.configuration_version == 1
    assert preserved.enabled is False
    assert preserved.max_active_sessions == 5
    assert preserved.max_queued_attempts == 100
    assert preserved.configuration_version == 1
    async with database_sessions() as database:
        event = await database.scalar(select(ExternalProviderLimitEvent))
    assert event is None


@pytest.mark.asyncio
async def test_browserless_cloud_cannot_be_enabled_without_a_token(
    database_sessions,
) -> None:
    repository = ExternalCapacityRepository(database_sessions)
    await repository.ensure(
        ProviderName.BROWSERLESS_CLOUD,
        enabled=False,
        max_active_sessions=5,
        max_queued_attempts=100,
    )

    with pytest.raises(
        ExternalCapacityEnablementError,
        match="token is not configured",
    ):
        await repository.update(
            ProviderName.BROWSERLESS_CLOUD,
            {"enabled": True},
            actor="test-operator",
        )

    capacity = await repository.get(ProviderName.BROWSERLESS_CLOUD)
    assert capacity is not None
    assert capacity.enabled is False
    assert capacity.configuration_version == 1


@pytest.mark.asyncio
async def test_browserless_cloud_can_be_enabled_when_a_token_is_configured(
    database_sessions,
) -> None:
    repository = ExternalCapacityRepository(
        database_sessions,
        browserless_cloud_token="configured-secret",
    )
    await repository.ensure(
        ProviderName.BROWSERLESS_CLOUD,
        enabled=False,
        max_active_sessions=5,
        max_queued_attempts=100,
    )

    capacity = await repository.update(
        ProviderName.BROWSERLESS_CLOUD,
        {"enabled": True},
        actor="test-operator",
    )

    assert capacity is not None
    assert capacity.enabled is True
