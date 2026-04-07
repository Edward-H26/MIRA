from django.apps import AppConfig


class ChatConfig(AppConfig):
    name = "app.chat"

    def ready(self):
        import app.chat.signals  # noqa: F401
