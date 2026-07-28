import os

# Ищем токен в любой из возможных переменных окружения
BOT_TOKEN: str = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")

if not BOT_TOKEN:
    raise EnvironmentError(
        "BOT_TOKEN environment variable is not set. "
        "Please add your Telegram Bot token as the BOT_TOKEN secret."
    )

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
