# Memoria AI Workflow

This document describes how user data flows through the system from input, through preprocessing and LLM interaction, to safe structured output.

---

## Data Input

User data enters Memoria through the following capture points:

**New Chat (Home Page)**
A POST form in `app/memoria/views.py` accepts an initial `message` field, trims it, and creates a `Session` plus a first `Message` row via `Session.create_with_opening_exchange`. Session titles are automatically derived here and capped at 200 characters.

**Ongoing Conversation**
`ConversationMessagesView.post` in `app/chat/views.py` handles both AJAX and regular form POST requests. It reads the `message` field, trims whitespace, rejects empty submissions, and appends the user message plus a placeholder assistant reply through `create_user_message_with_agent_reply`.

**Session Management**
Rename and delete actions in `app/chat/views.py` accept small form POSTs to update session titles or remove sessions entirely. Titles are truncated to 200 characters on write.

**Analytics and Memory Filters**
Search and filter parameters on the Memory and Analytics pages are captured via GET query params and processed in `get_memory_list_data` in `app/chat/service.py`. These power filtered views over the user's stored memories and session analytics.

---

## Preprocessing

Before data is stored or (in future) sent to the LLM, Memoria applies the following preprocessing steps:

**Whitespace Trimming**
All user text inputs are trimmed with `.strip()` at view and service entry points. This prevents blank or whitespace-only messages from being stored or processed.

**Empty Input Short-Circuit**
Messages with no content after trimming are rejected early. `create_user_message_with_agent_reply` returns `False` for empty inputs, ensuring no empty records are written to the database.

**Title Length Guard**
Session titles are sliced to 200 characters in `Session.create_with_opening_exchange` to keep both the database and the UI consistent.

**Filter Sanitization**
Memory and analytics filter inputs are validated before reaching the database. Numeric fields are checked with `.isdigit()` and non-numeric values are discarded. Text search fields use `icontains` queries rather than raw string interpolation. This logic lives in `_apply_memory_bullet_filters` in `app/chat/service.py`.

**Context Assembly (Planned)**
The service layer currently saves the conversation turn and a static placeholder assistant reply. When the LLM integration is added, this is the hook where session history and the user's scoped memory bullets will be fetched and assembled into the prompt before being sent to the model.

---

## Safety Guardrails

Memoria enforces guardrails at the authentication, input, and output layers.

**Authentication and User Isolation**
All chat views and APIs are wrapped with `login_required`. Every queryset is filtered by the current user's Profile via `get_or_create_profile_for_user` and `_get_session_queryset_for_user` in `app/chat/service.py`. This ensures users can only read or modify their own sessions, messages, and memories — cross-user data access is not possible.

**CSRF Protection and HTTP Verb Enforcement**
Django CSRF tokens are included in all forms and AJAX request headers. Mutating endpoints use `require_http_methods(["POST"])` or class-based method decorators across `app/chat/api.py` and `app/chat/views.py`, preventing unintended GET-based state changes.

**Input Validation**
Numeric filters are validated with `.isdigit()` before use. Empty messages are rejected. Session titles are length-limited to 200 characters. These checks together mitigate spammy or malformed payloads reaching the database.

**Output Safety**
Assistant replies are currently a static placeholder (`"Agent Response"`), meaning no untrusted LLM-generated text reaches users yet. When the LLM is integrated, this existing hook is the designated place to add toxicity filtering, PII detection, and fallback behavior for malformed or empty model outputs.

**Data Export Guards**
CSV and JSON exports in `app/chat/views.py` are scoped strictly to the requesting user's own data. Only CSV and JSON formats are accepted, with bounded result limits, preventing unbounded data exposure or format injection.

**API Key Security**
All API keys and the Django secret key are stored in a `.env` file (templated as `.env.example` in the repo). The `.gitignore` explicitly excludes `.env` from version control, as well as model weight files (`*.bin`, `*.safetensors`, `*.pt`).
