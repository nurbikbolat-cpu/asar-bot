import os

BOT_TOKEN: str = os.environ["TELEGRAM_BOT_TOKEN"]

_raw_admin = os.environ.get("ADMIN_ID", "")
if not _raw_admin:
    raise EnvironmentError(
        "ADMIN_ID environment variable is not set. "
        "Please add your Telegram user ID as the ADMIN_ID secret."
    )
ADMIN_ID: int = int(_raw_admin)

# Каналы для каждого раздела
CHANNELS: dict[str, str] = {
    "chan_help":    "@asar_help",
    "chan_bazar":   "@asar_bazar",
    "chan_garage":  "@asar_garage",
    "chan_ostatki": "@asar_ostatki",
}
