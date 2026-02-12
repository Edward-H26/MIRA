from .service import get_sidebar_sessions_for_user


def user_sessions(request):
    if not request.user.is_authenticated:
        return {"sessions": []}
    return {"sessions": get_sidebar_sessions_for_user(request.user)}
