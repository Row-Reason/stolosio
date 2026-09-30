from pydantic import ValidationError

from backend.proxy.contracts import (
    ProviderName,
    RequestedSessionSettings,
    ResolvedSessionSettings,
    SettingSource,
    SettingsResolutionContext,
)
from backend.proxy.errors import InvalidStolosioSettings
from backend.proxy.planner import StolosioPlanner, static_stolosio_planner
from backend.proxy.settings.registry import StolosioSettingsRegistry, stolosio_settings_registry


class StolosioSettingsResolver:
    def __init__(
        self,
        registry: StolosioSettingsRegistry,
        planner: StolosioPlanner,
    ) -> None:
        self._registry = registry
        self._planner = planner

    async def resolve(
        self,
        query_items: list[tuple[str, str]],
        context: SettingsResolutionContext | None = None,
    ) -> tuple[RequestedSessionSettings, ResolvedSessionSettings]:
        requested = self._registry.parse(query_items)
        defaults = self._registry.defaults()
        automatic = await self._planner.plan(
            context or SettingsResolutionContext(),
            requested,
            defaults,
        )
        values: dict[str, object] = {}
        sources: dict[str, SettingSource] = {}
        for field in self._registry.fields:
            query = field.query
            if query in requested.overrides:
                values[query] = requested.overrides[query]
                sources[query] = SettingSource.EXPLICIT
            elif field.automatic and query in automatic:
                values[query] = automatic[query]
                sources[query] = SettingSource.AUTO
            else:
                values[query] = defaults[query]
                sources[query] = SettingSource.DEFAULT

        try:
            models = self._registry.build_models(values)
        except ValidationError as error:
            raise InvalidStolosioSettings from error
        if models["session"].browser_required and models["provider"].slug is ProviderName.HTTP:
            raise InvalidStolosioSettings
        return requested, ResolvedSessionSettings(
            provider=models["provider"],
            session=models["session"],
            sources=sources,
            browserless=models["browserless"],
        )


stolosio_settings_resolver = StolosioSettingsResolver(
    stolosio_settings_registry,
    static_stolosio_planner,
)
