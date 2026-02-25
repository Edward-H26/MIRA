from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = "app.users"

    def ready(self):
        import app.users.signals  # noqa: F401
