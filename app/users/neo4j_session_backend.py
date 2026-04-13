import logging

from django.contrib.sessions.backends.base import SessionBase, CreateError

from app.services import neo4j_memory as neo4j

logger = logging.getLogger(__name__)


class SessionStore(SessionBase):

    def load(self):
        record = neo4j.load_django_session(self.session_key)
        if record and record.get("data"):
            try:
                return self.decode(record["data"])
            except Exception:
                self._session_key = None
                return {}
        self._session_key = None
        return {}

    def exists(self, session_key):
        return neo4j.django_session_exists(session_key)

    def create(self):
        for _ in range(10):
            self._session_key = self._get_new_session_key()
            try:
                self.save(must_create=True)
            except CreateError:
                continue
            self.modified = True
            return
        logger.error("Could not allocate unique session key after 10 retries")
        raise CreateError()

    def save(self, must_create=False):
        if self.session_key is None:
            return self.create()
        if must_create and self.exists(self.session_key):
            raise CreateError()
        data = self.encode(self._get_session(no_load=must_create))
        expire = self.get_expiry_date().isoformat()
        neo4j.save_django_session(self.session_key, data, expire)

    def delete(self, session_key=None):
        key = session_key or self.session_key
        if key:
            neo4j.delete_django_session(key)

    @classmethod
    def clear_expired(cls):
        neo4j.cleanup_expired_sessions()
