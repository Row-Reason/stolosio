from typing import ClassVar

from pydantic import BaseModel


class BaseStolosioSetting[SettingSchema: BaseModel]:
    slug: ClassVar[str]
    query_prefix: ClassVar[str]
    schema: ClassVar[type[SettingSchema]]

    @classmethod
    def defaults(cls) -> SettingSchema:
        return cls.schema()
