from backend.proxy.contracts import BrowserlessSettingSchema
from backend.proxy.settings.base import BaseStolosioSetting


class StolosioBrowserlessSetting(BaseStolosioSetting[BrowserlessSettingSchema]):
    slug = "browserless"
    query_prefix = "stolosio.browserless"
    schema = BrowserlessSettingSchema
    automatic = False
