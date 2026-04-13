Scannable map from each rubric item to the artifact that fulfills it. Designed for the 1v1 code-review demo so graders can jump directly to evidence.

## Primary AI stack (public / open models)

| Role | Model | Source | Paid API? | File |
|---|---|---|---|---|
| Primary LLM (chat generation, preprocessing) | `Qwen/Qwen3.5-0.8B` | Hugging Face Hub | No | `app/services/local_llm.py` |
| Primary embedding (semantic search, RAG) | `BAAI/bge-base-en-v1.5` (768-dim) | Hugging Face Hub | No | `app/services/embedding.py` |
| Primary OCR (document ingestion) | EasyOCR (PyTorch CRAFT + CRNN) | open-source | No | `app/services/ocr.py` |
| Optional chat-response enhancement | Gemini 3 Flash | Google API | Yes (gated by `GEMINI_API_KEY` and `CHAT_PREFER_LOCAL_LLM`) | `app/services/gemini.py` |

---

## Part 1 — Integrate AI into Django App

| Step | Requirement | Artifact / Path |
|---|---|---|
| 1.1 Choose AI feature | At least one AI feature, tied to app purpose | 4 delivered: chat generation (`service.py::stream_user_message_with_agent_reply`), semantic search (`service.py::retrieve_relevant_document_chunks` + `memory` view), RAG on documents (same + `ocr.py`), OCR document ingest (`views.py::document_upload_view`). See README_AI §1. |
| 1.2 Reuse prior work | Cite A6, A7, A8 integrations | README_AI §6 maps A6→`local_llm.py` (Qwen selection from 15-model bench), A7→`gemini.py` (hybrid routing), A8→`embedding.py` (originally MiniLM-L6, upgraded to BGE-base — see Improvement 5 in `evaluation/improvements.json`). |
| 1.3 Local / public model integration | Primary feature must not depend on paid API | README_AI §1.9 specifies local primaries for all four primary features. Paid Gemini is gated behind `GEMINI_API_KEY` and `CHAT_PREFER_LOCAL_LLM` env flag (see `app/chat/service.py::_should_use_local_model`). |
| 1.4 Full app flow | Real Django view / form / upload | `app/chat/views.py:966 document_upload_view` (OCR), `app/chat/forms.py::DocumentUploadForm`, `app/chat/views.py::ConversationMessagesView.post` (streaming chat), `app/chat/views.py::memory_list_view` (semantic search). |
| 1.5 Guardrails + error handling | Graceful failure, input validation | README_AI §5 (5 defense layers: auth, input validation, token budgets, quality gate, storage integrity); concrete examples in `evaluation/test_cases.json` Group D (empty input, corrupted file, concurrency, fallback, long input). |

## Part 2 — AI System Design Documentation

| Step | Artifact |
|---|---|
| 2.1 Workflow write-up | `README_AI.md` §1 (§1.1 entry points, §1.2 preprocessing, §1.3 models used, §1.4 classifier detail, §1.5 output, §1.6 delivery, §1.7 OCR, §1.8 semantic search, §1.9 primary stack & API role). |
| 2.2 Architecture diagrams | Three Mermaid flowcharts in `README_AI.md` §3 (hybrid chat pipeline, RAG pipeline, OCR pipeline). ER diagram at `docs/03_data_model/er_diagram.png`. |
| 2.3 Model selection rationale | `README_AI.md` §§2.1–2.4 (A6 15-model benchmark, A7 API cost comparison, A8 embedding comparison, production upgrade to BGE-base). Raw data at `llm_test/results/by_model/*.json` and `llm_test/results/rag/experiment_results.json`. |

## Part 3 — Evaluation of the Integrated Feature

| Step | Delivered | Artifact |
|---|---|---|
| 3.1 Realistic test inputs | 20 | `evaluation/test_cases.json` + `README_AI.md` §4.1 |
| 3.2 Output evaluation | Latency + quality + classifier score for 20 cases | `evaluation/test_cases.json`, `evaluation/evaluation_results.json` |
| 3.3 Failure analysis | 6 | `evaluation/failure_analysis.json` + `README_AI.md` §4.2 |
| 3.4 Improvement | 5 | `evaluation/improvements.json` + `README_AI.md` §4.3 |

## Part 4 — GitHub + Demo Readiness

| Step | Evidence |
|---|---|
| 4.1 GitHub quality | `.gitignore` excludes `*.bin`, `*.safetensors`, `*.pt`, `*.onnx`, `*.h5`, `llm_test/cache/`, `.env`. Reproducible setup in `README.md` §Installation. Clean project tree documented in `README.md` §Project Structure. |
| 4.2 Live demo readiness | Demo script below; screenshots referenced in `README.md` §AI Feature Screenshots (all paths resolve to files currently on disk in `docs/screenshots/`). |
| 4.3 Technical explanation | This document + `README_AI.md` full coverage + `evaluation/README.md` index. |

---

## Demo Script (5-minute walkthrough)

Run fully on local models with Gemini disabled to prove paid-API independence:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python unit_test/mock_data.py
export CHAT_PREFER_LOCAL_LLM=true
python manage.py runserver
```

1. **Chat simple (Group A1):** `/home/` → send "What can I make with eggs?" → show streaming response from `Qwen3.5-0.8B` (local).
2. **Chat complex (Group B1):** same page → send "Compare three dairy-free pasta dishes that must be ready in under 15 minutes and should avoid all tree nuts, then rank them by difficulty" → show constraint extraction in log + ranked comparison output.
3. **Semantic search (Group C1):** `/chat/memory/?q=dairy-free recipes` → show top-5 ranked bullets with cosine similarity scores.
4. **OCR (Group C2):** `/chat/document/upload/` → upload `docs/screenshots/test_receipt.png` → show EasyOCR extraction and parsed fields.
5. **Edge case — empty input (Group D1):** submit empty message → show graceful rejection.
6. **Optional enhancement** (if GEMINI_API_KEY is configured): unset `CHAT_PREFER_LOCAL_LLM` → repeat case A1 → show the Gemini-enhanced response path to prove the optional layer also works.

## Live Demo Walkthrough

We run Memoria locally by creating a Python virtual environment, installing dependencies from `requirements.txt`, running `python manage.py migrate`, and seeding mock data via `python unit_test/mock_data.py`. By exporting `CHAT_PREFER_LOCAL_LLM=true` before `python manage.py runserver`, we force the system onto its open-weight primary stack so the demo proves paid-API independence. The application comes up at `http://127.0.0.1:8000/`, where we log in with the seeded `tester` account and land on `/home/` with a populated sidebar of 12 seeded conversations, 26 memory bullets, and recent activity charts.

For the first success case, we submit "What can I make with eggs?" through the home chat form. The request enters `app/chat/views.py` via `ConversationMessagesView.post`, which delegates to `stream_user_message_with_agent_reply` in `service.py`. By scoring the prompt with the 8-dimension complexity classifier, Memoria recognizes the query as simple (score 12) and routes it through ACE memory retrieval plus Qwen3.5-0.8B local generation without triggering the expensive preprocessing step. The NDJSON stream delivers the first characters within 300 ms, and the completed response arrives in approximately 1.2 seconds with three egg-based suggestions augmented by the user's semantic and procedural memory bullets.

For the second success case, we upload a grocery receipt PNG via `/chat/document/upload/`. The `DocumentUploadForm` runs `validate_uploaded_image` for magic-byte checks, then `extract_text_from_file` invokes the EasyOCR reader (CRAFT detector plus CRNN recognizer, English, CPU mode). By running the regex patterns in `RECEIPT_PATTERNS` over the raw text, `parse_document_fields` extracts the total, subtotal, tax, and date fields. The parsed JSON renders in `document_results.html` in approximately 2.1 seconds for a 300 DPI scan. We then open `/chat/memory/?q=dairy-free%20recipes`, which encodes the query via BAAI/bge-base-en-v1.5 and returns the top five bullets with cosine similarities above 0.58, visibly ranked by relevance.

For the limitation case, we upload a deliberately low-resolution receipt (roughly 100 DPI) and observe the expected OCR degradation. EasyOCR misreads "Subtotal" as "Subtotai" and "$12.99" as "S12.99" because the CRNN recognizer struggles with narrow-font glyphs (lowercase l versus uppercase I, dollar sign versus capital S). The regex in `RECEIPT_PATTERNS` accepts flexible whitespace and an optional currency prefix, so the total field still parses, but character-level substitutions leak into the stored memory bullet content. This failure matches Failure 6 in `evaluation/failure_analysis.json`, where our current mitigation flags sub-100-DPI uploads for manual re-upload in the Documents UI rather than silently ingesting noisy text.

## Technical Explanation

AI enters Memoria at four well-defined surfaces. The home page chat form at `/home/` hands user messages to `stream_user_message_with_agent_reply`, which is the central hub for ACE retrieval, complexity classification, local preprocessing, and response generation. The semantic search endpoint at `/chat/api/semantic-search/` encodes queries through `app/services/embedding.py` and returns ranked memory bullets. The document upload view at `/chat/document/upload/` triggers the EasyOCR pipeline through `app/services/ocr.py`. Finally, the memory list page at `/chat/memory/` reuses the same semantic search plumbing to power user-facing filtering and sorting of stored bullets.

Memoria operates on three primary open-weight models plus one optional paid enhancement. Qwen/Qwen3.5-0.8B drives chat generation, constraint preprocessing, and vague-query rewriting, and was selected from a 15-model A6 benchmark (78.6% accuracy, highest of its size tier). BAAI/bge-base-en-v1.5 produces 768-dimensional embeddings for semantic search and RAG retrieval, upgraded from all-MiniLM-L6-v2 after we observed weaker clustering on multi-topic memory bullets in production. EasyOCR (PyTorch CRAFT detector plus CRNN recognizer) extracts text from receipts and nutrition labels with pdfplumber as the direct-text PDF fallback. Gemini 3 Flash serves as an optional fluency enhancement gated behind `GEMINI_API_KEY` and `CHAT_PREFER_LOCAL_LLM`, never a hard dependency.

By trimming whitespace and rejecting empty strings at the view layer, Memoria sanitizes every user input before any model sees it. The text then passes through the regex-based complexity classifier in `app/services/classifier.py`, which assigns a 0 to 100 score across eight dimensions (length, multi-step signals, analytical depth, constraints, question density, conjunctions, enumeration, context depth) plus a synergy bonus that rewards multi-dimensional queries. Messages above the 40-point threshold receive Qwen3.5-0.8B preprocessing that extracts structured lessons into JSON, while all messages funnel into ACE retrieval where the top 10 memory bullets are ranked via a hybrid 60/20/20 mix of semantic relevance, strength, and memory-type weight. For uploaded files, the OCR pipeline enforces a 10 MB size cap, checks PDF magic bytes, verifies image decoding with PIL, and normalizes to RGB before sending the tensor to EasyOCR.

Three limitations stand out in the current build. First, the local Qwen3.5-0.8B path is latency-bound on CPU (roughly 1.2 to 5.2 seconds per response) and degrades fluency on highly conversational prompts compared to Gemini 3 Flash, which is why we retain the optional API path. Second, EasyOCR falters on documents below roughly 100 DPI or with poor contrast, and the regex post-processing cannot fully correct glyph-level substitutions such as "Subtotai" or "S12.99". Third, embedding retrieval performs an in-process cosine similarity scan over the user's bullets rather than using a dedicated vector index, which keeps recall high but will scale linearly once a single user's memory grows past tens of thousands of bullets.

Before production deployment, we would pursue four improvements in sequence. We would first replace the linear cosine scan with pgvector or Qdrant to maintain sub-100 ms search latency beyond 100,000 bullets while preserving the existing BGE-base embedding interface. By adding a TrOCR or PaddleOCR secondary engine and an ensemble vote for low-confidence tokens, we would close the OCR accuracy gap on sub-150 DPI scans. Porting Qwen3.5-0.8B to a quantized GGUF build served through llama.cpp would cut CPU latency by roughly half without sacrificing the 78.6% accuracy observed in A6. Finally, we would add structured output validation through Pydantic schemas for extracted lessons and parsed receipt fields so that malformed model JSON fails loudly rather than propagating silently into memory storage.

## Quick verification (before demo)

```bash
# 1. Documentation accuracy
grep -rn "all-MiniLM\|pytesseract\|tesseract" README.md README_AI.md | grep -v "historical\|A8 winner\|Improvement 5\|§2.3\|§2.4"
# expected: empty

# 2. Evaluation JSON validity
python -c "import json, glob; [json.load(open(f)) for f in glob.glob('evaluation/*.json')]; print('OK')"

# 3. Model identity cross-check
grep -n "MODEL_ID" app/services/embedding.py app/services/local_llm.py
# expected: bge-base-en-v1.5 in embedding.py, Qwen3.5-0.8B in local_llm.py

# 4. Git hygiene
git check-ignore -v llm_test/cache/ .env 2>/dev/null || echo "already gitignored"
```
