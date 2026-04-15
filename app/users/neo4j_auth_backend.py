from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User

from app.services import neo4j_memory as neo4j
from app.users.models import UserProfile


class Neo4jAuthenticationBackend:

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        userData = neo4j.get_user_by_username(username)
        if userData is None:
            return None
        storedHash = userData.get("passwordHash", "")
        if not storedHash or not check_password(password, storedHash):
            return None
        neo4j.update_user_last_login(userData["id"])
        return self._build_user_object(userData)

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    @staticmethod
    def _build_user_object(data):
        neoId = data.get("id", "")
        username = data.get("username", "")
        try:
            profile = UserProfile.objects.select_related("user").get(pk=int(neoId))
            return profile.user
        except (UserProfile.DoesNotExist, ValueError, TypeError):
            pass
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist:
                return None
        return None
