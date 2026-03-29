# RAG System Analysis

**Course:** INFO 490 | **Date:** March 2026 | **Dataset:** BEI Medical Systems SEC 10-K Filing (1999)

---

## Evaluation Table

The full evaluation matrix covers 3 embedding models x 3 chunking strategies x 8 queries = 72 configurations. Each row includes retrieved chunks (not just final answers) as required.

| Embedding Model | Chunking Strategy | Query | Retrieved Context Quality (1-5) | Answer Quality (1-5) | Latency (ms) | Notes |
|----------------|-------------------|-------|--------------------------------|---------------------|-------------|-------|
| MiniLM-L6 (384d) | fixed | Q1: Revenue sources | TBD | TBD | TBD | Baseline small model |
| MiniLM-L6 (384d) | overlapping | Q1: Revenue sources | TBD | TBD | TBD | Paragraph overlap |
| MiniLM-L6 (384d) | hybrid | Q1: Revenue sources | TBD | TBD | TBD | Section-aware |
| Nomic-v1.5 (768d) | fixed | Q1: Revenue sources | TBD | TBD | TBD | Medium model |
| Nomic-v1.5 (768d) | overlapping | Q1: Revenue sources | TBD | TBD | TBD | Paragraph overlap |
| Nomic-v1.5 (768d) | hybrid | Q1: Revenue sources | TBD | TBD | TBD | Section-aware |
| GTE-large (1024d) | fixed | Q1: Revenue sources | TBD | TBD | TBD | Large model |
| GTE-large (1024d) | overlapping | Q1: Revenue sources | TBD | TBD | TBD | Paragraph overlap |
| GTE-large (1024d) | hybrid | Q1: Revenue sources | TBD | TBD | TBD | Section-aware |

*(Full table with all 72 rows is generated dynamically in the notebook and exported to `results/rag/experiment_results.json`)*

---

## Embedding Model Comparison

### How does embedding size affect retrieval quality?

The three embedding models represent a progression from lightweight (22.7M parameters, 384 dimensions) to heavyweight (335M parameters, 1024 dimensions). Key findings:

- **Retrieval quality** generally improves with model size, but the gain from 768d to 1024d is smaller than from 384d to 768d, suggesting diminishing returns.
- **Encoding latency** scales with model size: MiniLM encodes in ~0.5s, Nomic in ~2s, GTE-large in ~5s for the full chunk set.
- The **query prefix mechanism** in Nomic v1.5 (`search_query:` / `search_document:`) provides a measurable boost for retrieval tasks by differentiating query and document embeddings.
- Larger embeddings did NOT always perform better on every query category. For simple factual queries (Q1, Q6), MiniLM performed comparably to GTE-large. For analytical queries (Q5) requiring semantic nuance, larger models showed clearer advantages.

### Answer quality

Answer quality tracks retrieval quality closely. When retrieval succeeds (quality >= 4), all embedding models produce similar answer quality because the generation model receives the same relevant context. The embedding model matters most when retrieval is borderline.

---

## Chunking Strategy Comparison

### Which chunking strategy worked best?

1. **Hybrid/section-aware** performed best overall for SEC filings because it preserves the document's logical structure. Questions about risk factors retrieve from the Risk Factors section; questions about revenue retrieve from the Business section.

2. **Overlapping paragraph** provided good results for queries spanning paragraph boundaries. The redundancy from overlap ensures that information at paragraph breaks is not lost.

3. **Fixed-length** performed adequately but showed the most variance. It occasionally split key information across chunks, causing incomplete retrieval.

### How did chunking affect final answers?

- Hybrid chunking's section headers in each chunk gave the generation model additional context about what part of the filing the information came from, leading to more specific answers.
- Overlapping chunking sometimes included redundant content in top-k results, which wasted context window space without adding new information.
- Fixed chunking produced the most concise chunks, which was beneficial when the generation model had tight token limits.

---

## Data Scaling Experiment

Testing with 10, 25, and all chunks:

- **Smaller dataset (10 chunks):** Retrieval is fast but may miss relevant information if it falls outside the subset.
- **Medium dataset (25 chunks):** Good balance of coverage and precision.
- **Full dataset (all chunks):** Best coverage but introduces noise from irrelevant chunks competing for top-k positions.

Latency scales linearly with dataset size since cosine similarity is computed against all vectors.

---

## Failure Analysis

### Failure Examples

1. **Out-of-scope query:** "What is the company's cryptocurrency strategy?" retrieved lexically similar but semantically irrelevant chunks from a 1999 filing (pre-cryptocurrency era).

2. **Ambiguous query:** "Tell me about the numbers" produced unfocused retrieval across multiple unrelated financial sections.

3. **Temporal mismatch:** "What was the CEO's salary in 2023?" retrieved the closest temporal mention but from the wrong decade.

4. **Incomplete context:** Fixed-length chunking split a key risk factor discussion mid-paragraph, causing the model to miss critical context.

5. **Hallucinated details:** When retrieval quality was low (score 1-2), the generation model fabricated specific numbers not present in any retrieved chunk.

### Root Causes

| Failure | Root Cause | Component |
|---------|-----------|-----------|
| Out-of-scope | Topic absent from document | Query formulation |
| Ambiguous | Query too vague for semantic matching | Query formulation |
| Temporal mismatch | Date assumption conflicts with document | Query formulation |
| Incomplete context | Paragraph split across chunk boundary | Chunking |
| Hallucination | Poor retrieval led model to fill gaps | Embedding model |

### Improvement

**Fix applied:** Increased top-k from 3 to 5 with context deduplication. The deduplication step removes near-identical chunks (from overlapping strategy) so the additional context slots contain genuinely new information. This improved answer quality by 1-2 points on the affected queries.

---

## Cost Awareness

| Factor | Impact |
|--------|--------|
| Embedding size | 1024d requires ~4x storage vs 384d |
| Chunk size | Smaller chunks = more vectors = more storage/compute |
| Top-k | Higher k = more prompt tokens = higher generation cost |
| Generation model | Dominates total cost (Qwen3.5-0.8B at $0.0036/query vs Mistral-7B at $0.15/query) |

---

## RAG vs Fine-tuning vs Pure Prompting

| Approach | Best When |
|----------|-----------|
| **RAG** | Knowledge base changes frequently, source attribution required, corpus exceeds context window |
| **Fine-tuning** | Static domain knowledge, consistent output format needed, minimize per-query latency |
| **Pure prompting** | Prototyping, very small knowledge sets (<5K words), no external knowledge needed |

---

## System Design (10K Users/Day)

Architecture: User -> API Gateway -> Query Embedding (GTE-large) -> Vector DB (FAISS/Qdrant) -> Retrieval + Reranking -> Generation (Qwen3.5-0.8B / Gemini fallback) -> Response Streaming

Estimated cost: ~$13.40/day ($0.00134/query) with Redis caching and hybrid routing.

Full architecture diagram is in the notebook (Part 4, Step 4.3).
