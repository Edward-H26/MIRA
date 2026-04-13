# Memoria AI Evaluation Artifacts

Machine-readable backing data for the prose tables in [`../README_AI.md`](../README_AI.md) Section 4. Each file mirrors a subsection and can be diffed by a grader or consumed by analytics scripts.

| File | Mirrors | Records |
|---|---|---|
| [`test_cases.json`](test_cases.json) | README_AI.md §4.1 | 20 test inputs across simple chat, complex chat, semantic search + OCR + memory, and edge cases |
| [`failure_analysis.json`](failure_analysis.json) | README_AI.md §4.2 | 6 documented failures with root cause, evidence, and mitigation |
| [`improvements.json`](improvements.json) | README_AI.md §4.3 | 5 improvements with before/after/why-it-helped and citations |
| [`evaluation_results.json`](evaluation_results.json) | README_AI.md §4 summary + rubric map | Aggregated quality, latency, and rubric-compliance status |

## Verifying

```bash
python -c "import json, glob; [json.load(open(f)) for f in glob.glob('evaluation/*.json')]; print('all JSON parses cleanly')"
```

## Primary AI stack (open / public models)

- **LLM (primary):** `Qwen/Qwen3.5-0.8B` — `app/services/local_llm.py`
- **Embedding (primary):** `BAAI/bge-base-en-v1.5` (768-dim) — `app/services/embedding.py`
- **OCR (primary):** EasyOCR (PyTorch CRAFT + CRNN) — `app/services/ocr.py`
- **Optional API enhancement:** Gemini 3 Flash, gated behind `GEMINI_API_KEY` and `CHAT_PREFER_LOCAL_LLM`

All rubric-relevant primary features (semantic search, RAG retrieval, OCR, and local chat generation) run without contacting any paid API.
