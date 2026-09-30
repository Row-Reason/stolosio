from pydantic import ValidationError

from backend.proxy.contracts import (
    RequestedSessionSettings,
    ResolvedSessionSettings,
    SettingSource,
)
from backend.proxy.errors import InvalidStolosioSettings
from backend.proxy.settings.registry import StolosioSettingsRegistry, stolosio_settings_registry


class StolosioSettingsResolver:
    def __init__(self, registry: StolosioSettingsRegistry) -> None:
        self._registry = registry

    async def resolve(
        self,
        query_items: list[tuple[str, str]],
    ) -> tuple[RequestedSessionSettings, ResolvedSessionSettings]:
        requested = self._registry.parse(query_items)
        defaults = self._registry.defaults()
        values: dict[str, object] = {}
        sources: dict[str, SettingSource] = {}
        for field in self._registry.fields:
            query = field.query
            if query in requested.overrides:
                values[query] = requested.overrides[query]
                sources[query] = SettingSource.EXPLICIT
            else:
                values[query] = defaults[query]
                sources[query] = SettingSource.DEFAULT

        try:
            models = self._registry.build_models(values)
        except ValidationError as error:
            raise InvalidStolosioSettings from error
        return requested, ResolvedSessionSettings(
            provider=models["provider"],
            session=models["session"],
            sources=sources,
            browserless=models["browserless"],
        )


stolosio_settings_resolver = StolosioSettingsResolver(stolosio_settings_registry)
