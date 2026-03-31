from app.clients.common.worker import Worker as CommonWorker
from app.clients.tg.mailbox import Update


class Worker(CommonWorker):
    def __init__(self, app):
        super().__init__(
            app,
            updates_queue_name="telegram_updates",
            sender_queue_name="telegram_sender_queue",
            update_model=Update,
            source_platform="TG",
        )
