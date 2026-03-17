# Memoria AI Workflow

This document describes how user data flows through the system from input, through preprocessing and LLM interaction, to safe structured output. Memoria uses a hybrid AI pipeline combining a local Hugging Face model (Qwen3.5-0.8B) for preprocessing with an external API (Google Gemini 3 Flash) for final generation. The ACE (Autonomous Continuous Exploration) memory algorithm augments every response with learned experience from prior conversations.

---

## Data Input

User data enters Memoria through the following capture points:

**New Chat (Home Page)**
A POST form in `app/memoria/views.py` accepts an initial `message` field, trims it, and creates a `Session` plus a first `Message` row via `Session.create_with_opening_exchange`. Session titles are automatically derived and capped at 200 characters.

**Ongoing Conversation**
`ConversationMessagesView.post` in `app/chat/views.py` handles both AJAX and regular form POST requests. It reads the `message` field, trims whitespace, rejects empty submissions, and streams the agent reply in real time using `stream_user_message_with_agent_reply`.

**Session Management**
Rename and delete actions in `app/chat/views.py` accept small form POSTs to update session titles or remove sessions entirely. Titles are truncated to 200 characters on write.

**Analytics and Memory Filters**
Search and filter parameters on the Memory and Analytics pages are captured via GET query params and processed in `get_memory_list_data` in `app/chat/service.py`. These power filtered views over the user's stored memories and session analytics.

---

## Preprocessing

Before data is sent to the LLM pipeline, Memoria applies the following preprocessing steps:

**Whitespace Trimming**
All user text inputs are trimmed with `.strip()` at view and service entry points. This prevents blank or whitespace-only messages from being stored or processed.

**Empty Input Short-Circuit**
Messages with no content after trimming are rejected early with a ValueError, ensuring no empty records are written to the database.

**Title Length Guard**
Session titles are sliced to 200 characters in `Session.create_with_opening_exchange` to keep both the database and the UI consistent.

**Filter Sanitization**
Memory and analytics filter inputs are validated before reaching the database. Numeric fields are checked with `.isdigit()` and non-numeric values are discarded. Text search fields use `icontains` queries rather than raw string interpolation. This logic lives in `_apply_memory_bullet_filters` in `app/chat/service.py`.

**Prompt Classification**
The classifier in `app/services/classifier.py` scores each user message based on token count, structural complexity signals (multi-step instructions, conditional logic, multiple questions), and conversation depth. Messages scoring below the threshold are classified as "simple" and route directly to Gemini. Messages scoring at or above the threshold are classified as "complex" and trigger local LLM preprocessing before Gemini generation.

**Local LLM Preprocessing (Complex Prompts Only)**
For complex prompts, the local Qwen3.5-0.8B model in `app/services/local_llm.py` compresses the user message into a structured summary containing user intent, key constraints, relevant context, and a response plan. This compact representation reduces token usage and improves response quality when passed to Gemini.

**Context Assembly**
The ACE runtime in `app/chat/ace_runtime.py` retrieves ranked memory bullets relevant to the user's query, builds recent conversation context from the last 12 messages, and assembles the final prompt with guidance, preprocessed analysis (if available), and the user's question.

---

## Hybrid AI Pipeline

Memoria implements a classification-based hybrid routing architecture:

**Simple Path (approximately 80% of messages)**
User Input -> Classifier ("simple") -> ACE Memory Retrieval -> Gemini 3 Flash -> Streaming Response

**Complex Path (approximately 20% of messages)**
User Input -> Classifier ("complex") -> Qwen3.5-0.8B Preprocessing -> ACE Memory Retrieval -> Gemini 3 Flash -> Streaming Response

The classifier uses a conservative scoring threshold so that the vast majority of messages incur zero additional latency. Only genuinely long or multi-step prompts activate the local preprocessing step. If the local model is unavailable (weights not downloaded) or preprocessing fails, the system falls back to the simple path automatically.

---

## Local LLM Integration

**Model:** Qwen/Qwen3.5-0.8B (0.8 billion parameters)

**Purpose:** Preprocessing only. The local model extracts structured constraint ledgers from complex user prompts. It does not generate final responses.

**Selection Rationale:** Qwen3.5-0.8B was selected based on the 15-model benchmark in `llm_test/ai_prototype.ipynb`. It achieved the highest rubric pass rate (78.6%, 11/14) across all size categories, outperforming every tested 7B+ model while requiring only 2.60 seconds to load and 25.58 seconds to generate on an RTX 4060.

**Cache Path:** `llm_test/cache/huggingface-models/Qwen__Qwen3_5-0_8B/`

**Loading:** Lazy initialization on first complex prompt arrival, not at Django server startup. The model and tokenizer are cached as module-level singletons after first load.

**Device Detection:** Automatically selects CUDA (preferred), MPS (Apple Silicon), or CPU (fallback) based on available hardware.

---

## External API Integration

**Provider:** Google Gemini 3 Flash (`gemini-3-flash-preview`)

**Used For:** Final response generation for all prompts, both simple and complex.

**Streaming:** Responses are streamed via the `generate_content_stream` API. Chunks are delivered to the frontend as NDJSON delta events (48-character increments) with progressive HTML rendering of markdown content.

**Fallback Chain:**
1. ACE runtime with memory-augmented Gemini generation
2. Direct Gemini stream (if ACE fails)
3. Static fallback message: "Sorry, I couldn't reach the AI service just now."

---

## Safety Guardrails

Memoria enforces guardrails at the authentication, input, and output layers.

**Authentication and User Isolation**
All chat views and APIs are wrapped with `login_required`. Every queryset is filtered by the current user's Profile via `get_or_create_profile_for_user` and `_get_session_queryset_for_user` in `app/chat/service.py`. This ensures users can only read or modify their own sessions, messages, and memories.

**CSRF Protection and HTTP Verb Enforcement**
Django CSRF tokens are included in all forms and AJAX request headers. Mutating endpoints use `require_http_methods(["POST"])` or class-based method decorators, preventing unintended GET-based state changes.

**Input Validation**
Numeric filters are validated with `.isdigit()` before use. Empty messages are rejected. Session titles are length-limited to 200 characters. The classifier adds an additional layer by scoring prompt complexity before routing decisions.

**Output Safety**
The ACE quality gate filters low-confidence lessons before they are stored in memory. Lessons must pass minimum thresholds for relevance (0.05), lesson quality (0.55), and confidence (0.70). The gate score must exceed 0.60 before any memory update is applied. This prevents noisy or irrelevant learned behaviors from accumulating.

**Data Export Guards**
CSV and JSON exports in `app/chat/views.py` are scoped strictly to the requesting user's own data. Only CSV and JSON formats are accepted, with bounded result limits, preventing unbounded data exposure or format injection.

**API Key Security**
All API keys and the Django secret key are stored in a `.env` file (templated as `.env.example` in the repo). The `.gitignore` explicitly excludes `.env` from version control, as well as model weight cache directories (`llm_test/cache/`).
