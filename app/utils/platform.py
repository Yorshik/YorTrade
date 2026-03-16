from typing import Literal


Platform = Literal["TG", "VK"]
DEFAULT_PLATFORM: Platform = "TG"
SUPPORTED_PLATFORMS: tuple[Platform, Platform] = ("TG", "VK")


def normalize_platform(value: str | None, default: Platform = DEFAULT_PLATFORM) -> Platform:
    if value is None:
        return default
    normalized = str(value).strip().upper()
    if normalized in SUPPORTED_PLATFORMS:
        return normalized  # type: ignore[return-value]
    return default


def build_actor_key(platform: str | None, external_user_id: int | None) -> str | None:
    if external_user_id is None:
        return None
    normalized = normalize_platform(platform)
    return f"{normalized}:{external_user_id}"


def parse_actor_key(actor_key: str | None) -> tuple[Platform, int] | None:
    if not actor_key:
        return None
    platform_raw, sep, user_raw = actor_key.partition(":")
    if not sep:
        return None
    try:
        external_user_id = int(user_raw)
    except ValueError:
        return None
    return normalize_platform(platform_raw), external_user_id
