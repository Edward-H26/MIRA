# Memoria AI System Design and Workflow

This document describes the design decisions and technical architecture of the Memoria AI pipeline, a Django-based AI assistant that combines local Hugging Face model inference with external API generation. Each section addresses a specific aspect of the system design, explains the implementation choices, and discusses the rationale behind those choices along with alternatives that were considered and rejected.

## Abstract

Memoria is a conversational AI assistant built on Django that employs a hybrid inference architecture combining a locally hosted Hugging Face model (Qwen3.5-0.8B, 0.8 billion parameters) with an external API (Google Gemini 3 Flash) for response generation. The system implements the ACE (Agentic Context Engineering) memory algorithm, which augments every response with learned experience from prior conversations through a tri-memory system (semantic, episodic, procedural) with differential decay rates. A regex-based complexity classifier routes approximately 80% of user messages directly to the API while directing the remaining 20% through local preprocessing first. This classification-based routing architecture achieves an estimated 87% blended accuracy while reducing costs by 67.3% compared to pure API deployment at 10,000 daily active users. Safety guardrails operate at five layers: authentication, input validation, processing constraints, output quality gating, and persistent memory deduplication.

---

## 1. Data Input

User data enters Memoria through four distinct capture points, each designed for a specific interaction pattern within the Django request lifecycle.

### 1.1 Capture Architecture

**New Chat (Home Page)**

The initial conversation begins with a POST form in `app/memoria/views.py`. When a user submits their first message, the view accepts a `message` field, trims whitespace, and delegates to `Session.create_with_opening_exchange`, which atomically creates a new `Session` row and a first `Message` row in a single database transaction. Session titles are automatically derived from the opening message content and capped at 200 characters to prevent database bloat and UI overflow.

**Ongoing Conversation**

Subsequent messages are handled by `ConversationMessagesView.post` in `app/chat/views.py`. This endpoint accepts both AJAX and regular form POST requests, reads the `message` field, trims whitespace, and rejects empty submissions with an immediate error response. For valid messages, the view calls `stream_user_message_with_agent_reply`, which returns a Django `StreamingHttpResponse` that delivers the AI-generated reply in real time as NDJSON delta events. This streaming approach means the user sees the first tokens of the response within milliseconds rather than waiting for the complete generation to finish.

**Session Management**

Rename and delete actions in `app/chat/views.py` accept small form POST requests to update session titles or remove sessions entirely. Titles are truncated to 200 characters on write. Delete operations cascade to remove all associated messages and memory bullets for the session.

**Analytics and Memory Filters**

Search and filter parameters on the Memory and Analytics pages are captured via GET query parameters and processed in `get_memory_list_data` in `app/chat/service.py`. These power filtered views over the user's stored memories and session analytics, enabling users to search their conversation history by content, tags, memory type, and date range.

### 1.2 Session Lifecycle

Each conversation follows a defined lifecycle: creation (opening exchange), active messaging (ongoing conversation with streaming responses), optional management (rename, review), and termination (delete). User isolation is enforced at every stage through the `Profile` model: `get_or_create_profile_for_user` binds each Django `User` to a `Profile`, and `_get_session_queryset_for_user` filters all session queries by the current user's profile. This ensures that users can only read or modify their own sessions, messages, and memories.

### 1.3 Design Rationale

The decision to use POST forms with Django's `StreamingHttpResponse` rather than WebSocket connections reflects a deliberate simplicity tradeoff. Django's built-in CSRF protection applies automatically to POST forms, eliminating the need for custom token handling that WebSocket implementations require. Server-Sent Events (SSE) via `StreamingHttpResponse` provide the real-time streaming behavior that users expect from a conversational AI interface without introducing the deployment complexity of Django Channels or an ASGI server. Since the communication pattern is unidirectional (server streams response to client), full-duplex WebSocket capabilities are unnecessary.

Session-based conversation organization maps directly to the natural structure of human conversations: each session represents a coherent dialogue thread with its own context window and memory scope. This design enables the ACE memory system to scope learned experience per conversation context, preventing cross-contamination between unrelated dialogue threads.

The 200-character title limit was chosen to balance informativeness with UI constraints. Auto-derived titles reduce friction for users who would otherwise need to name every conversation manually, while the length cap ensures consistent rendering across desktop and mobile layouts.

**Alternative considered:** WebSocket via Django Channels for bidirectional streaming. This was rejected because the additional deployment complexity (Redis channel layer, ASGI server, WebSocket routing) does not justify the marginal benefit for a unidirectional streaming use case. If future features require client-to-server streaming (e.g., real-time collaborative editing), this decision would be revisited.

---

## 2. Preprocessing

Before data reaches the LLM pipeline, Memoria applies a multi-stage preprocessing pipeline where each stage serves a distinct purpose: sanitize, classify, compress, and contextualize.

### 2.1 Input Sanitization Pipeline

**Whitespace Trimming.** All user text inputs are trimmed with `.strip()` at view and service entry points. This prevents blank or whitespace-only messages from being stored or processed, ensuring that downstream components always receive non-empty text.

**Empty Input Short-Circuit.** Messages with no content after trimming are rejected early with a `ValueError`, ensuring no empty records are written to the database and no LLM inference is wasted on null input.

**Title Length Guard.** Session titles are sliced to 200 characters in `Session.create_with_opening_exchange` to keep both the database schema and the UI consistent across all rendering contexts.

**Filter Sanitization.** Memory and analytics filter inputs are validated before reaching the database. Numeric fields are checked with `.isdigit()` and non-numeric values are discarded. Text search fields use Django ORM `icontains` queries rather than raw string interpolation, preventing SQL injection through filter parameters. This logic lives in `_apply_memory_bullet_filters` in `app/chat/service.py`.

### 2.2 Prompt Complexity Classification

The classifier in `app/services/classifier.py` scores each user message across eight dimensions using regular expression pattern matching:

| Dimension | Max Points | Detection Method |
|---|---|---|
| Message Length | 20 | Word count thresholds: 30 words = 5pts, 80 = 10pts, 140 = 15pts, 220+ = 20pts |
| Multi-Step Signals | 25 | Patterns: "step 1", "first", "then", "finally", conditional logic |
| Analytical Depth | 20 | Patterns: "compare", "evaluate", "debug", "analyze", "walk me through" |
| Constraints | 15 | Patterns: "must", "cannot", "at least", "avoid", "without" |
| Question Density | 10 | Count of question marks: 2 = 5pts, 3+ = 10pts |
| Conjunctions | 10 | Patterns: "and also", "furthermore", "moreover", "in addition" |
| Enumeration | 5 | Patterns: "list 5 items", "give me 3 examples" |
| Context Depth | 5 | Session message count: 8+ with signals = 3pts, 15+ = 5pts |
| Synergy Bonus | 15 | 2 active dimensions = 10pts, 3+ active = 15pts |

The maximum possible score is 100 (capped). Messages scoring 40 or above are classified as "complex" and trigger local LLM preprocessing; all others are classified as "simple" and route directly to the Gemini API.

**Concrete example (simple query):** "What can I make with eggs?" contains 7 words (below the 30-word threshold for any length points), no multi-step signals, no analytical keywords, and no constraints. Score: approximately 0. Classification: simple.

**Concrete example (complex query):** "Compare three dairy-free approaches that must be ready in under 15 minutes and should avoid all tree nuts, then rank them by difficulty" scores approximately: length 5 (18 words) + multi-step 8 ("then") + analytical 8 ("compare") + constraints 10 ("must", "should avoid") + conjunctions 5 ("and should") + synergy 15 (4 active dimensions) = 51. Classification: complex.

### 2.3 Local LLM Preprocessing (Complex Path)

For complex prompts, the local Qwen3.5-0.8B model in `app/services/local_llm.py` acts as the Reflector component of the ACE system. The `ACE_PREPROCESS_TEMPLATE` prompt instructs the model to analyze learned experience from prior conversations and the current conversation context, then extract structured lessons in JSON format:

```
{
  "lessons": [
    {"content": "Specific lesson", "type": "success|failure|domain|tool", "tags": ["tag1"]}
  ],
  "reflection": "Brief overall reflection"
}
```

The preprocessing operates within strict token budgets: input is truncated to 2048 tokens, and output is limited to 384 tokens. The preprocessed analysis is only generated when three conditions are met simultaneously: the prompt is classified as "complex" (score >= 40), the local model is available (weights downloaded), and the model is already loaded in memory (controlled by `CHAT_LOCAL_PREPROCESS_WARM_ONLY`). This conditional execution ensures that simple queries, which constitute approximately 80% of traffic, incur zero additional latency from local model inference.

### 2.4 ACE Context Assembly

The ACE runtime in `app/chat/ace_runtime.py` assembles the final prompt through three steps. First, it retrieves the top 10 memory bullets relevant to the user's query using a hybrid ranking formula: 60% relevance weight (token-level Jaccard similarity between the query and bullet content), 20% strength weight (decay-adjusted memory strength across semantic, episodic, and procedural channels), and 20% type weight (procedural bullets receive highest priority at 1.0, episodic at 0.7, semantic at 0.4). Meta-strategy seed bullets receive a penalty of -0.25 to prevent generic advice from dominating retrieval, while learned bullets receive a bonus of +0.08 to prioritize experience-derived insights.

Second, the retrieved bullets are formatted into a guidance block using `guidance_from_bullets()`, which structures each bullet with its content, tags, and type for inclusion in the prompt.

Third, the final prompt is assembled by concatenating: the guidance block, recent conversation context (last 6 messages formatted as User/Assistant pairs), the preprocessed analysis from the local model (if available), and the user's current question.

### 2.5 Design Rationale

The multi-stage preprocessing pipeline was chosen over a single-pass approach because each stage serves a distinct, independently optimizable purpose. Input sanitization prevents invalid data from entering the system. Classification determines the appropriate processing depth without incurring inference cost. Local preprocessing compresses complex prompts into structured constraint representations. Context assembly enriches the prompt with relevant historical experience. This separation of concerns enables each stage to be modified, tested, and optimized independently.

The regex-based classifier was chosen over an ML-based routing model because it provides zero-latency, zero-cost classification with deterministic, auditable behavior. Using a language model to classify prompt complexity would add 1 to 2 seconds of latency to every message, defeating the purpose of fast-path routing for simple queries. The regex approach requires no training data, no model maintenance, and no additional inference infrastructure.

The conditional local preprocessing design avoids cold-loading the 0.8B model (which takes 2.6 seconds on the benchmark hardware) for simple queries that do not benefit from constraint extraction. The `CHAT_LOCAL_PREPROCESS_WARM_ONLY` flag ensures that only messages arriving after the model is already in memory trigger preprocessing, preventing the first complex query from experiencing a loading delay that would degrade user experience.

The ACE memory-augmented context assembly enables the system to improve over time by learning from prior successes and failures, a capability absent from stateless LLM calls. Each conversation turn potentially contributes new lessons to the memory system, which are then available to inform future responses.

**Alternative considered:** Retrieval-Augmented Generation (RAG) with a vector database (e.g., FAISS, Pinecone) for context retrieval. This was rejected in favor of the tri-memory bullet system because the bullet architecture provides richer metadata per memory unit (type classification, per-channel decay rates, helpful/harmful counts, content hashing for deduplication) and is more interpretable than opaque embedding similarity scores. The bullet system also enables explicit memory management operations (mark as helpful, mark as harmful, delete) that vector databases do not natively support.

---

## 3. Safety Guardrails

Memoria enforces safety guardrails at five layers: authentication (who can access), input validation (what enters the system), processing constraints (how data is transformed), output quality control (what the system learns), and storage integrity (how learned knowledge persists).

### 3.1 Authentication and User Isolation

All chat views and APIs are wrapped with Django's `login_required` decorator. Every queryset is filtered by the current user's Profile via `get_or_create_profile_for_user` and `_get_session_queryset_for_user` in `app/chat/service.py`. This ensures that users can only read or modify their own sessions, messages, and memories. Cross-user data access is prevented at the ORM query level, not merely at the view level, providing defense in depth against authorization bypass.

### 3.2 Input Validation

Django CSRF tokens are included in all forms and AJAX request headers, preventing cross-site request forgery attacks. Mutating endpoints use `require_http_methods(["POST"])` or class-based method decorators, preventing unintended GET-based state changes. Numeric filter parameters are validated with `.isdigit()` before use. Empty messages are rejected at the view layer. Session titles are length-limited to 200 characters. The complexity classifier adds an additional validation layer by scoring prompt characteristics before routing decisions, ensuring that only well-formed text reaches the inference pipeline.

### 3.3 Output Quality Control (ACE Quality Gate)

The ACE quality gate in `app/chat/ace_runtime.py` filters low-confidence lessons before they are stored in memory. The gate implements a three-factor scoring system:

**Relevance scoring** combines three token-overlap metrics: Jaccard similarity (intersection/union of question and lesson tokens), F1 overlap (harmonic mean of precision and recall), and coverage (intersection divided by the smaller token set). These are weighted as 50% Jaccard + 30% F1 + 20% coverage.

**Lesson quality scoring** evaluates structural completeness: token count (minimum threshold to reject trivially short lessons), presence of tags (categorical labels for retrieval), and valid type classification (success, failure, domain, or tool).

**Confidence scoring** aggregates the above factors: 45% lesson quality + 40% relevance + 15% external verifier score (or a proxy computed from quality and relevance if no verifier is available).

Lessons must pass minimum thresholds for relevance (>= 0.05), lesson quality (>= 0.55), and confidence (>= 0.70). The composite gate score must exceed 0.60 before any memory update is applied. A maximum of 4 lessons are accepted per turn, sorted by confidence in descending order.

These thresholds were tuned empirically. Setting them too low allows irrelevant or low-quality lessons to accumulate in memory, gradually degrading response quality as noise overwhelms signal. Setting them too high prevents the system from learning at all, eliminating the adaptive capability that distinguishes ACE from stateless inference.

### 3.4 Memory Pollution Prevention

Beyond the quality gate, the system employs four mechanisms to prevent memory pollution:

**Content deduplication** uses SHA256 hashing of normalized text (whitespace-reduced, lowercased) to detect exact duplicates at creation time. A secondary fuzzy deduplication pass uses Jaccard similarity with a threshold of 0.9 to catch near-duplicate lessons that differ only in minor wording.

**Generic lesson filtering** rejects lessons with fewer than 8 tokens or those matching known generic patterns such as "provide a clear answer like:" or "when handling." These patterns indicate that the reflector produced a template response rather than a genuine insight.

**Fact recall pattern detection** identifies questions like "what is my name," "who am I," or "remind me what" and bypasses lesson extraction entirely. These queries request retrieval of previously stated facts rather than generating new knowledge, and extracting "lessons" from them would pollute the memory with trivial restatements.

**Memory type inference** uses keyword-based classification to route lessons into the appropriate memory channel (semantic, episodic, or procedural), preventing misclassification that could cause, for example, a transient user preference (episodic) from being stored with the low decay rate of procedural memory.

### 3.5 API Key and Data Export Security

All API keys and the Django secret key are stored in a `.env` file (templated as `.env.example` in the repository). The `.gitignore` explicitly excludes `.env` from version control, as well as model weight cache directories (`llm_test/cache/`). CSV and JSON exports in `app/chat/views.py` are scoped strictly to the requesting user's own data. Only CSV and JSON formats are accepted, with bounded result limits, preventing unbounded data exposure or format injection.

### 3.6 Design Rationale

The defense-in-depth architecture applies guardrails at every layer of the system rather than relying on any single checkpoint. Authentication prevents unauthorized access. Input validation prevents malformed data from entering the pipeline. Processing constraints (token limits, complexity thresholds) prevent resource abuse. Output quality gating prevents the system from learning from bad data. Storage integrity (deduplication, type inference) maintains long-term memory quality.

The multi-factor quality gate was chosen over simple heuristic filtering because it enables fine-grained control over the precision-recall tradeoff in lesson acceptance. A simple rule like "reject lessons shorter than 20 words" would miss many relevant short insights while still accepting long but irrelevant ones. The three-factor scoring enables the system to accept a concise, highly relevant lesson while rejecting a verbose but off-topic one.

SHA256 deduplication was chosen because exact duplicate detection is computationally trivial (O(1) hash lookup) and produces zero false positives. The secondary Jaccard similarity check at 0.9 threshold catches near-duplicates at an acceptable false-positive rate, since two lessons with 90% token overlap are unlikely to represent genuinely distinct insights.

**Alternative considered:** External content moderation API (OpenAI Moderation, Google Perspective API) for input filtering. This was rejected because Memoria handles scoped assistant data within a constrained domain, not open-ended generation. The domain constraint itself provides implicit content filtering: the system prompt directs the model to stay on-task, and off-topic requests are redirected by the system prompt's interaction guidelines. Adding an external moderation call would increase latency by 100 to 500 milliseconds per message without meaningfully improving safety for this specific domain.

---

## 4. Local LLM Integration

### 4.1 Model Selection (Benchmark-Driven)

Qwen3.5-0.8B was selected through a systematic 15-model benchmark documented in `llm_test/ai_prototype.ipynb` and analyzed in `llm_test/notes.txt`. The evaluation tested models ranging from 135 million to 8.2 billion parameters on a deliberately adversarial constrained-generation task using 14 binary rubrics graded by GPT-5.4-Pro.

Qwen3.5-0.8B achieved the highest rubric pass rate of any tested model: 78.6% (11 of 14 rubrics), while requiring only 2.60 seconds to load and 25.58 seconds to generate across 14 test queries on an NVIDIA RTX 4060 Laptop GPU. Its per-query cost of $0.003553 (at $0.50/hr GPU rental) makes it the most cost-effective option among all models scoring above 60% accuracy.

Larger models failed for specific, documented reasons. Qwen3-8B (8.2 billion parameters) scored only 14.3% because its entire 512-token output consisted of internal reasoning tokens enclosed in `<think>` tags, a phenomenon termed "thinking leakage," despite thinking mode being explicitly disabled. Both Microsoft Phi-3.5-mini and Phi-4-mini (3.8 billion parameters each) scored 0% due to output degeneration: Phi-3.5 produced Unicode garbage and invented non-existent product names, while Phi-4 devolved into a philosophical stream-of-consciousness passage. These failures demonstrate that parameter count alone does not predict task accuracy for constrained generation; instruction tuning quality and architecture stability matter more.

### 4.2 Integration Architecture

The local model integration in `app/services/local_llm.py` implements a thread-safe singleton pattern. The model and tokenizer are stored as module-level variables (`_model`, `_tokenizer`) protected by a `threading.Lock` (`_load_lock`). This ensures that concurrent Django request threads cannot trigger simultaneous model loads, which would exhaust GPU memory.

Initialization is lazy: the model loads only when the first complex prompt arrives, not at Django server startup. This design choice prevents a 2.6-second startup delay for the Django development server and avoids allocating GPU memory for the local model in deployments where all queries happen to be simple. After the first load, the model and tokenizer persist in memory for the lifetime of the Django process, eliminating per-request loading overhead.

A `_load_failed` boolean flag prevents repeated load attempts after a failure (e.g., missing model weights). Once the flag is set, all subsequent calls to `preprocess_prompt` return `None` immediately, and the system falls back to the simple processing path without additional error logging.

### 4.3 Device Detection and Fallback

The `_candidate_devices()` function probes available hardware in priority order: CUDA (NVIDIA GPU, preferred for throughput), MPS (Apple Silicon Metal Performance Shaders, for macOS development), and CPU (universal fallback). The model is loaded with `torch.float16` precision on GPU devices and `torch.float32` on CPU. If the preferred device fails (e.g., insufficient VRAM), the loader automatically attempts the next device in the priority list before raising an error.

### 4.4 ACE Memory System

The ACE (Agentic Context Engineering) memory system, implemented across `app/chat/ace_runtime.py`, `app/chat/models/memory.py`, and `app/chat/models/memory_bullet.py`, provides a self-improving context mechanism that enables the system to learn from every conversation turn.

**Tri-Memory Architecture.** Inspired by models of human memory consolidation, the system maintains three independent memory channels per bullet:

| Channel | Decay Rate | Priority Weight | Purpose |
|---|---|---|---|
| Semantic | 1% per tick | 0.4 | General knowledge and domain facts |
| Episodic | 5% per tick | 0.7 | User preferences and conversation history |
| Procedural | 0.2% per tick | 1.0 (highest) | Workflows, step sequences, and strategies |

Each channel tracks its own strength value, access index, and last-access timestamp. The aggregate strength of a bullet is computed by summing the exponential decay contributions from all three channels: `strength * (1 - decay_rate) ^ (access_clock - last_access_index)`. This differential decay model encodes the observation that procedural knowledge (how to do something) remains useful for much longer than episodic knowledge (what a specific user said in a specific conversation).

**UCB Bandit Planner.** The planner selects one of four reasoning depth levels (direct, explore, refine, deep_refine) using an epsilon-greedy Upper Confidence Bound algorithm. Each level specifies a different number of reasoning rounds and candidate generations. The UCB formula balances exploration (trying underused strategies) with exploitation (repeating successful ones), enabling the system to automatically invest more compute on challenging queries while keeping simple responses fast. The shaped reward signal that updates the planner combines four factors: step quality score (55% weight), output validity (20%), quality gate acceptance (15%), and recursion improvement flag (10%).

**Neo4j Persistence.** An optional Neo4j graph database (`app/services/neo4j_memory.py`) provides persistent storage for the memory state. The graph schema stores `User` nodes connected to `AceMemoryState` nodes via `HAS_ACE_MEMORY` relationships. The state node contains a serialized JSON payload of all bullets, access clock, and version metadata. Sync operations use exponential backoff retry logic (default 2 retries, 1-second base delay) to handle transient network failures.

### 4.5 Design Rationale

Lazy loading was chosen over eager loading because the 2.6-second model load time is acceptable as a one-time cost amortized over many subsequent requests, but unacceptable as a blocking operation during Django server startup. In development, this means the server starts instantly; in production, the first complex query experiences a slight delay that all subsequent queries avoid.

The singleton pattern was chosen because Qwen3.5-0.8B requires approximately 1.6 GB of VRAM in FP16 precision. Loading the model once and sharing it across all request threads is both memory-efficient and latency-optimal. Per-request loading would require 2.6 seconds per complex query, rendering the local preprocessing useless.

The tri-memory architecture was chosen over flat memory storage because differential decay rates encode domain knowledge about memory utility that a uniform decay model cannot capture. A user's mention of a contextual preference (episodic, 5% decay) should fade faster than a learned workflow for handling recurring tasks (procedural, 0.2% decay). Without this differentiation, all memories would degrade at the same rate, causing the system to forget important procedures at the same speed as transient conversational details.

The UCB bandit planner was chosen over a fixed reasoning depth because query complexity varies enormously. A simple greeting requires only direct generation (1 round, 1 candidate), while a multi-constraint planning request may benefit from deep refinement (2 rounds, 3 candidates). The bandit formulation discovers this allocation automatically through accumulated reward signals, without requiring manual threshold tuning.

**Alternative considered:** LoRA adapter fine-tuned on Memoria-specific training data (allergen constraints, product catalog, formatting rules). This was deferred to future work because the base Qwen3.5-0.8B already achieves 78.6% accuracy on the benchmark task, and fine-tuning requires curated training data that has not yet been collected in sufficient volume. The ACE memory system provides a lightweight alternative to fine-tuning by adapting behavior through runtime experience rather than weight modification.

---

## 5. External API Integration

### 5.1 Provider and Model Selection

Google Gemini 3 Flash (`gemini-3-flash-preview`) was selected as the external API provider based on three criteria: free tier availability for development and low-volume production, native streaming support for real-time response delivery, and competitive response quality for constrained generation tasks.

At the time of selection, the pricing comparison across providers was:

| Provider | Model | Input (per 1M tokens) | Output (per 1M tokens) |
|---|---|---|---|
| Google | Gemini 3 Flash | $0.50 | $3.00 |
| Google | Gemini 3.1 Flash Lite | $0.25 | $1.50 |
| OpenAI | GPT-4o-mini | $3.00 | $6.00 |
| Groq | Llama-3 | Free (rate-limited) | Free (rate-limited) |

Gemini 3 Flash provides a 6x input cost advantage over GPT-4o-mini and a 2x output cost advantage, while Groq's free tier imposes rate limits that are incompatible with production traffic volumes. The Gemini SDK (`google-genai`) also provides a clean streaming interface that integrates directly with Django's `StreamingHttpResponse`.

The thinking configuration is set to "low" for streaming generation (minimizing latency) and is configurable for structured output (reflector and preprocessing), where deeper reasoning improves the quality of extracted lessons.

### 5.2 Streaming Architecture

The Gemini service in `app/services/gemini.py` exposes two generation modes. `generate_reply_stream()` uses `generate_content_stream` to yield text chunks as they arrive from the Gemini API. `generate_structured_text()` uses non-streaming `generate_content` with optional system instructions and configurable token budgets for structured output tasks like reflection and lesson extraction.

On the Django side, `stream_user_message_with_agent_reply` in `app/chat/service.py` wraps the streamed chunks as NDJSON delta events. Each event contains the chunk text and a progressively rendered HTML version (using markdown-to-HTML conversion). An initial chunk strategy sends the first 5 characters immediately to establish perceived responsiveness, then delivers the remainder in standard-sized increments. This ensures that users see output beginning within milliseconds of the generation start, creating a conversational feel that batch generation cannot achieve.

### 5.3 Hybrid Pipeline Orchestration

The hybrid pipeline implements classification-based routing (Pattern A from the production cost analysis):

**Simple Path (approximately 80% of messages):**

```
User Input -> Classifier ("simple", score < 40)
  -> ACE Memory Retrieval (top-10 ranked bullets)
  -> Gemini 3 Flash Streaming
  -> NDJSON Delta Events -> Client
```

**Complex Path (approximately 20% of messages):**

```
User Input -> Classifier ("complex", score >= 40)
  -> Qwen3.5-0.8B Local Preprocessing (extract structured lessons)
  -> ACE Memory Retrieval (top-10 ranked bullets)
  -> Gemini 3 Flash Streaming (with preprocessed context)
  -> NDJSON Delta Events -> Client
```

The conservative classification threshold (40 out of 100) ensures that the majority of messages take the fast simple path with zero additional latency. Only genuinely long, multi-step, or analytically demanding prompts activate local preprocessing. If the local model is unavailable (weights not downloaded), not yet loaded (warm-only mode), or preprocessing fails for any reason, the system automatically falls back to the simple path.

### 5.4 Fallback Chain

The system implements a three-level fallback chain to ensure users always receive a response:

1. **Primary:** ACE runtime with memory-augmented Gemini generation, recursive reasoning, quality gate, and lesson extraction. This is the full pipeline that provides the highest quality responses.

2. **Secondary:** Direct Gemini stream without ACE augmentation. If the ACE pipeline throws an exception (e.g., memory retrieval failure, planner error), the system logs the error and falls back to a direct Gemini API call with the user's message only.

3. **Tertiary:** Static fallback message: "Sorry, I couldn't reach the AI service just now." If the Gemini API itself is unavailable (network error, rate limit, authentication failure), the system returns a safe static response rather than leaving the user with an error page.

Each fallback level is instrumented with event logging (`log_event` calls with error type and pipeline stage), enabling operators to monitor degradation patterns and identify recurring failure modes.

### 5.5 Design Rationale

Streaming was chosen over batch generation because perceived latency is a critical factor in conversational AI user experience. In batch mode, users wait 3 to 5 seconds seeing no output before the complete response appears. In streaming mode, the first tokens appear within hundreds of milliseconds, and the response builds progressively. Research on conversational interface design consistently shows that progressive disclosure of content reduces perceived wait time and increases user engagement.

Server-Sent Events via Django's `StreamingHttpResponse` were chosen over WebSocket because the communication pattern is unidirectional: the server streams a response to the client, and the client does not need to send data back during generation. Django provides `StreamingHttpResponse` natively with no additional dependencies, while WebSocket would require Django Channels (additional package), a channel layer backend (Redis), and an ASGI server (Daphne or Uvicorn). The deployment complexity of WebSocket is not justified for a unidirectional streaming use case.

Gemini was chosen over self-hosted larger models because the economic analysis (detailed in `llm_test/notes.txt`) demonstrates that the hybrid approach costs $26.17 per day at 10,000 daily active users, compared to $176.16 per day for self-hosting Mistral-7B on two A100 GPUs. The API provides better quality (Gemini's reasoning capability exceeds the local 0.8B model) at lower total cost, while the local model handles the high-volume simple queries that would otherwise dominate API spending.

The three-level fallback chain was designed to maximize availability. The full ACE pipeline represents the ideal operating mode. The direct Gemini fallback preserves response quality when memory or planner components fail. The static message preserves user experience when the API itself is unreachable. This progressive degradation ensures that system failures manifest as reduced quality rather than complete unavailability.

**Alternative considered:** OpenAI API with function calling for structured output (lesson extraction, reflection). This was rejected because Gemini's free tier and lower per-token pricing align better with the project's cost optimization goals. Function calling can be replicated through Gemini's system instruction mechanism and structured output prompting, achieving comparable structured extraction without the 6x input cost premium.
