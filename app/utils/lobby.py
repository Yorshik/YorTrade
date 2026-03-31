from app.clients.common.mailbox import InlineKeyboardButton, InlineKeyboardMarkup
from app.market.settings import build_default_game_settings

SETTINGS_FIELDS = {
    "tick_seconds": {"label": "Тик", "step": 5, "min": 5, "max": 120},
    "game_duration_minutes": {"label": "Длительность", "step": 5, "min": 5, "max": 180},
    "global_volatility": {
        "label": "Волатильность",
        "step": 0.1,
        "min": 0.1,
        "max": 50.0,
    },
    "default_balance": {"label": "Баланс", "step": 100, "min": 100, "max": 1000000},
}


def normalize_game_settings(settings: dict | None) -> dict:
    normalized = build_default_game_settings()
    if settings:
        for key, value in settings.items():
            if key in normalized:
                normalized[key] = value
    return normalized


def adjust_setting(settings: dict, field_name: str, direction: int) -> dict:
    field = SETTINGS_FIELDS[field_name]
    value = settings[field_name] + (field["step"] * direction)
    value = max(field["min"], min(field["max"], value))
    value = int(value) if isinstance(field["step"], int) else round(float(value), 1)
    settings[field_name] = value
    return normalize_game_settings(settings)


def set_setting_value(settings: dict, field_name: str, raw_value: str) -> dict:
    field = SETTINGS_FIELDS[field_name]
    value_raw = str(raw_value or "").strip().replace(",", ".")
    if not value_raw:
        raise ValueError("empty input")
    if isinstance(field["step"], int):
        parsed = float(value_raw)
        if not parsed.is_integer():
            raise ValueError("expected integer")
        value = int(parsed)
    else:
        value = round(float(value_raw), 1)
    value = max(field["min"], min(field["max"], value))
    settings[field_name] = value
    return normalize_game_settings(settings)


def get_setting_label(field_name: str) -> str:
    return SETTINGS_FIELDS[field_name]["label"]


def render_setting_input_prompt(field_name: str, settings: dict) -> str:
    label = get_setting_label(field_name)
    return (
        f"Введите новое значение для параметра «{label}».\n"
        f"Текущее значение: {settings[field_name]}\n"
        f"Допустимый диапазон: {SETTINGS_FIELDS[field_name]['min']} - {SETTINGS_FIELDS[field_name]['max']}"
    )


def render_setting_input_keyboard(field_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назад к настройкам",
                    callback_data=f"cancel_setting_input:{field_name}",
                )
            ]
        ]
    )


def render_lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Присоединиться", callback_data="join_game"),
                InlineKeyboardButton(
                    text="Настройки", callback_data="open_game_settings"
                ),
                InlineKeyboardButton(text="Старт", callback_data="begin_game"),
            ],
            [
                InlineKeyboardButton(text="Покинуть игру", callback_data="leave_game"),
                InlineKeyboardButton(text="Стоп", callback_data="end_game"),
            ],
        ]
    )


def _display_user_name(user) -> str:
    if user is None:
        return "неизвестный"
    username = str(getattr(user, "username", "") or "").strip()
    if username:
        return username
    platform = str(getattr(user, "platform", "TG")).lower()
    external_id = int(getattr(user, "tg_user_id", 0) or 0)
    return f"пользователь_{platform}_{external_id}"


async def build_lobby_text(app, game, chat_title: str | None = None) -> str:
    players = await app.users.player.list_by_game(game.id)
    lines = []
    if chat_title:
        lines.append(f"Лобби: {chat_title}")
    lines.append("Набор в игру открыт.")
    lines.append(f"Участники ({len(players)}):")
    if players:
        for index, player in enumerate(players, start=1):
            user = await app.users.user.get_by_id(player.user_id)
            marker = " (хост)" if user is not None and user.id == game.host_id else ""
            lines.append(f"{index}. {_display_user_name(user)}{marker}")
    else:
        lines.append("— пока никого —")
    lines.append("")
    lines.append("Можно присоединяться и менять настройки.")
    return "\n".join(lines)


def render_settings_keyboard(
    settings: dict, use_client: str = "TG"
) -> InlineKeyboardMarkup:
    use_client = str(use_client or "TG").upper()
    rows = []
    if use_client == "VK":
        vk_buttons = [
            InlineKeyboardButton(
                text=f"{field['label']}: {settings[field_name]}",
                callback_data=f"game_settings_input:{field_name}",
            )
            for field_name, field in SETTINGS_FIELDS.items()
        ]
        rows.extend(
            vk_buttons[index : index + 2] for index in range(0, len(vk_buttons), 2)
        )
    else:
        for field_name, field in SETTINGS_FIELDS.items():
            rows.append(
                [
                    InlineKeyboardButton(
                        text="-", callback_data=f"game_settings:{field_name}:-1"
                    ),
                    InlineKeyboardButton(
                        text=f"{field['label']}: {settings[field_name]}",
                        callback_data=f"game_settings_input:{field_name}",
                    ),
                    InlineKeyboardButton(
                        text="+", callback_data=f"game_settings:{field_name}:1"
                    ),
                ]
            )

    rows.append(
        [InlineKeyboardButton(text="Назад", callback_data="close_game_settings")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def render_settings_text(settings: dict) -> str:
    return (
        "Настройки игры:\n"
        "Компаний: все доступные\n"
        f"Длительность тика: {settings['tick_seconds']} сек\n"
        f"Длительность игры: {settings['game_duration_minutes']} мин\n"
        f"Глобальная волатильность: {settings['global_volatility']}\n"
        f"Стартовый баланс: {settings['default_balance']}"
    )
