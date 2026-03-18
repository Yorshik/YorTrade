from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import (
    MessagePayload,
    MessageType,
    PayloadAction,
    Update,
)
from app.utils.lobby import (
    adjust_setting,
    build_lobby_text,
    get_setting_label,
    normalize_game_settings,
    render_lobby_keyboard,
    render_setting_input_keyboard,
    render_setting_input_prompt,
    render_settings_keyboard,
    render_settings_text,
    set_setting_value,
)


class GameSettingsHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if not update.from_user:
            return False
        if update.type == MessageType.CALLBACK_QUERY:
            data = update.callback_query.data or ""
            return (
                data == "open_game_settings"
                or data == "close_game_settings"
                or data.startswith("game_settings:")
                or data.startswith("game_settings_input:")
                or data.startswith("cancel_setting_input:")
            )
        if update.type == MessageType.TEXT and update.message:
            text = (update.text or "").strip()
            if text.startswith(self.app.config.PREFIX):
                return False
            source_platform = (update.source_platform or "TG").upper()
            state = await self.app.fsm.get_state(
                update.from_user.id, platform=source_platform
            )
            return bool(
                state
                and state[0] == self.app.fsm.FSM.GAME_SETTINGS
                and state[1].get("pending_setting")
            )
        return False

    async def handle(self, update: Update) -> MessagePayload | None:
        game = await self.app.market.game.get_by_chat_id(
            update.chat_id,
            platform=(update.source_platform or "TG"),
        )
        if not game:
            if update.type == MessageType.CALLBACK_QUERY:
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text="Игра не найдена.",
                    show_alert=True,
                )
            return None

        source_platform = (update.source_platform or "TG").upper()
        actor_user = await self.app.users.user.get_by_external(
            source_platform, update.from_user.id
        )
        is_host = bool(actor_user and game.host_id == actor_user.id)

        if not is_host:
            if update.type == MessageType.CALLBACK_QUERY:
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text="Только хост меняет настройки.",
                    show_alert=True,
                )
            return None

        if update.type == MessageType.TEXT:
            return await self._handle_text_input(update, game)

        data = update.callback_query.data or ""
        settings = normalize_game_settings(game.settings)
        source_platform = (update.source_platform or "TG").upper()

        if data.startswith("game_settings:"):
            _, field_name, direction = data.split(":")
            settings = adjust_setting(settings, field_name, int(direction))
            game.settings = settings
            await self.app.market.game.save(game)
            await self.app.fsm.set_state(
                update.from_user.id,
                self.app.fsm.FSM.GAME_SETTINGS,
                {
                    "game_id": game.id,
                    "settings_message_id": update.callback_query.message.message_id,
                },
                platform=source_platform,
            )
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="Настройки обновлены.",
            )
        elif data.startswith("game_settings_input:"):
            field_name = data.split(":")[1]
            await self.app.fsm.set_state(
                update.from_user.id,
                self.app.fsm.FSM.GAME_SETTINGS,
                {
                    "game_id": game.id,
                    "settings_message_id": update.callback_query.message.message_id,
                    "pending_setting": field_name,
                },
                platform=source_platform,
            )
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text=f"Введите значение для «{get_setting_label(field_name)}».",
            )
            return MessagePayload(
                chat_id=update.chat_id,
                action=PayloadAction.EDIT,
                message_id=update.callback_query.message.message_id,
                text=render_setting_input_prompt(field_name, settings),
                keyboard=render_setting_input_keyboard(field_name),
            )
        elif data.startswith("cancel_setting_input:"):
            await self.app.fsm.set_state(
                update.from_user.id,
                self.app.fsm.FSM.GAME_SETTINGS,
                {
                    "game_id": game.id,
                    "settings_message_id": update.callback_query.message.message_id,
                },
                platform=source_platform,
            )
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="Возвращаю настройки.",
            )
        elif data == "open_game_settings":
            await self.app.fsm.set_state(
                update.from_user.id,
                self.app.fsm.FSM.GAME_SETTINGS,
                {
                    "game_id": game.id,
                    "settings_message_id": update.callback_query.message.message_id,
                },
                platform=source_platform,
            )
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="Открываю настройки.",
            )
            return MessagePayload(
                chat_id=update.chat_id,
                action=PayloadAction.EDIT,
                message_id=update.callback_query.message.message_id,
                text=render_settings_text(settings),
                keyboard=render_settings_keyboard(
                    settings, use_client=(update.source_platform or "TG")
                ),
            )
        else:
            await self.app.fsm.set_state(
                update.from_user.id,
                self.app.fsm.FSM.IN_LOBBY,
                {"game_id": game.id},
                platform=source_platform,
            )
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="Возвращаю в лобби.",
            )
            chat_title = None
            if (
                update.callback_query
                and update.callback_query.message
                and update.callback_query.message.chat.title
            ):
                chat_title = str(update.callback_query.message.chat.title)
            return MessagePayload(
                chat_id=update.chat_id,
                action=PayloadAction.EDIT,
                message_id=update.callback_query.message.message_id,
                text=await build_lobby_text(
                    self.app,
                    game,
                    chat_title=chat_title,
                ),
                keyboard=render_lobby_keyboard(),
            )

        return MessagePayload(
            chat_id=update.chat_id,
            action=PayloadAction.EDIT,
            message_id=update.callback_query.message.message_id,
            text=render_settings_text(settings),
            keyboard=render_settings_keyboard(
                settings, use_client=(update.source_platform or "TG")
            ),
        )

    async def _handle_text_input(self, update: Update, game) -> MessagePayload | None:
        source_platform = (update.source_platform or "TG").upper()
        state = await self.app.fsm.get_state(
            update.from_user.id, platform=source_platform
        )
        if not state:
            return None

        data = state[1]
        field_name = data.get("pending_setting")
        settings_message_id = data.get("settings_message_id")
        if not field_name:
            return None

        settings = normalize_game_settings(game.settings)
        try:
            settings = set_setting_value(settings, field_name, update.text or "")
        except ValueError:
            await self.app.sender.delete_message(
                update.chat_id, update.message.message_id
            )
            error_text = (
                f"Неверное значение для параметра «{get_setting_label(field_name)}».\n"
                f"Введите число.\n\n"
                f"{render_setting_input_prompt(field_name, settings)}"
            )
            if settings_message_id:
                return MessagePayload(
                    chat_id=update.chat_id,
                    action=PayloadAction.EDIT,
                    message_id=settings_message_id,
                    text=error_text,
                    keyboard=render_setting_input_keyboard(field_name),
                )
            return MessagePayload(
                chat_id=update.chat_id,
                text=error_text,
                keyboard=render_setting_input_keyboard(field_name),
            )

        game.settings = settings
        await self.app.market.game.save(game)
        await self.app.sender.delete_message(update.chat_id, update.message.message_id)
        state_payload = {
            "game_id": game.id,
        }
        if settings_message_id:
            state_payload["settings_message_id"] = settings_message_id
        await self.app.fsm.set_state(
            update.from_user.id,
            self.app.fsm.FSM.GAME_SETTINGS,
            state_payload,
            platform=source_platform,
        )
        settings_text = render_settings_text(settings)
        settings_keyboard = render_settings_keyboard(
            settings, use_client=(update.source_platform or "TG")
        )
        if settings_message_id:
            return MessagePayload(
                chat_id=update.chat_id,
                action=PayloadAction.EDIT,
                message_id=settings_message_id,
                text=settings_text,
                keyboard=settings_keyboard,
            )
        return MessagePayload(
            chat_id=update.chat_id,
            text=settings_text,
            keyboard=settings_keyboard,
        )
