# README_AI

## Data Input (capture points)
- **New chat from home**: POST form in `app/memoria/views.py:8-28` accepts `message`, trims it, and creates a Session plus first Message rows via `Session.create_with_opening_exchange`.
- **Ongoing conversation**: `ConversationMessagesView.post` (`app/chat/views.py:38-77`) handles AJAX + regular form posts. It reads `message`, trims, rejects empty, and appends user + placeholder assistant messages through `create_user_message_with_agent_reply`.
- **Session management**: Rename/delete actions in `app/chat/views.py:99-123` take small form posts to update titles or delete sessions (title truncated to 200 chars in `Session.create_with_opening_exchange`).
- **Analytics/Memory filters**: Query params for search/filter on memory and analytics pages are read via GET in views/services (e.g., `get_memory_list_data` in `app/chat/service.py:149-188`).

## Preprocessing before the (future) LLM
- Whitespace trimming on all user text inputs (`.strip()` in view/service entry points) to avoid blank/whitespace messages.
- Title length guard: session titles are sliced to 200 chars in `Session.create_with_opening_exchange` to keep UI/db sane.
- Empty-input short‑circuit: messages with no content are ignored (returns False in `create_user_message_with_agent_reply`).
- Filter sanitization: memory/analytics filters only accept digits where expected and apply `icontains` searches; non-numeric input is discarded (`_apply_memory_bullet_filters` in `app/chat/service.py:56-75`).
- Context assembly (planned): the service currently saves the turn and a stub assistant reply; when the LLM hook is added it will fetch session history + memory bullets from the user-scoped querysets before sending.

## Safety Guardrails
- **Authentication + isolation**: `login_required` wraps all chat views/APIs; querysets are always filtered by the current user's Profile (`get_or_create_profile_for_user` and `_get_session_queryset_for_user` in `app/chat/service.py:12-42`), preventing cross-user access.
- **CSRF & HTTP verb checks**: Django CSRF tokens are included in forms and AJAX headers; mutating endpoints use `require_http_methods(["POST"])` or class-based method decorators (`app/chat/api.py`, `app/chat/views.py`).
- **Input validation**: numeric filters validated via `.isdigit()`, empty messages rejected, and titles length-limited to mitigate spammy payloads.
- **Output handling**: assistant replies are currently static "Agent Response", so no untrusted LLM text reaches users yet. When the LLM is integrated, this is the hook to add toxicity/PII checks and fallback behavior for malformed model outputs.
- **Data export guards**: exports are constrained to the requesting user's data and support only CSV/JSON formats with bounded limits (`app/chat/views.py:146-197`).
