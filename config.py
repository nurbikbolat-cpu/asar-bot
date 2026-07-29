import os

BOT_TOKEN: str = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")

if not BOT_TOKEN:
    raise EnvironmentError("BOT_TOKEN environment variable is not set.")

_raw_admin = os.getenv("ADMIN_ID", "")
if not _raw_admin:
    raise EnvironmentError("ADMIN_ID environment variable is not set.")

ADMIN_ID: int = int(_raw_admin)

CHANNELS: dict[str, str] = {
    "chan_help":    "@asar_help",
    "chan_bazar":   "@asar_bazar",
    "chan_garage":  "@asar_garage",
    "chan_ostatki": "@asar_ostatki",
}
