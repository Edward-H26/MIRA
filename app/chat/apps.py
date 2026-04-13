from django.apps import AppConfig

_NEO4J_INITIALIZED = False


class ChatConfig(AppConfig):
    name = "app.chat"

    def ready(self):
        import app.chat.signals  # noqa: F401

        global _NEO4J_INITIALIZED
        if not _NEO4J_INITIALIZED:
            _NEO4J_INITIALIZED = True
            try:
                from app.services.neo4j_memory import init_neo4j_constraints
                init_neo4j_constraints()
            except Exception:
                pass
