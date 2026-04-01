# RAG System: Retrieval-Augmented Generation with SEC 10-K Filings

## Overview

This notebook implements a complete RAG pipeline that retrieves relevant context from a SEC 10-K annual filing and uses it to generate grounded answers via local language models. It evaluates 3 embedding models x 3 chunking strategies = 9 configurations across 10 test queries (90 total evaluations).

## Prerequisites

- Python 3.12+
- NVIDIA GPU with CUDA support (tested on RTX 4060, 8 GB VRAM)
- ~10 GB disk space for model caches

## Setup

```bash
pip install -r requirements_rag.txt
```

## How to Run

```bash
jupyter notebook rag_system.ipynb
```

Then click **Kernel > Restart & Run All**. The notebook runs end-to-end in approximately 15-25 minutes on an RTX 4060.

## Model Caching

Models are automatically downloaded and cached on first run:
- Generation models: `cache/huggingface-models/`
- Embedding models: `cache/embedding-models/`

Subsequent runs use the local cache (no internet required).

## Output Files

| File | Description |
|------|-------------|
| `rag_system.ipynb` | Full implementation with experiments and analysis |
| `rag_analysis.md` | Evaluation tables, comparisons, failure analysis |
| `results/rag/experiment_results.json` | Raw experiment data (90 evaluations) |

## Dataset

Uses `winterForestStump/10-K_sec_filings` from HuggingFace (BEI Medical Systems Co Inc, 1999 filing).

## Models Used

**Embedding models:**
- sentence-transformers/all-MiniLM-L6-v2 (384d, Small)
- nomic-ai/nomic-embed-text-v1.5 (768d, Medium)
- Alibaba-NLP/gte-large-en-v1.5 (1024d, Large)

**Generation models (top 3 from A7):**
- Qwen/Qwen3.5-0.8B (primary, 78.6% A7 accuracy, **4.80/5 RAG quality**, 3.7s latency)
- Qwen/Qwen3.5-2B (71.4% A7 accuracy, 4.70/5 RAG quality, 5.0s latency)
- mistralai/Mistral-7B-Instruct-v0.2 (71.4% A7 accuracy, 4.40/5 RAG quality, 271s latency)

**Best configuration:** MiniLM-L6 + overlapping chunking. **Best generation model:** Qwen3.5-0.8B — highest quality, lowest latency, and smallest model.
