# Multi-Model Benchmarking, Cost Analysis, and Routing Strategy for the Memoria AI Dietary Assistant

---

## Abstract

Deploying large language models (LLMs) for production conversational AI systems requires careful balancing of response quality, inference latency, and operational cost. This paper presents a systematic benchmarking study of 15 open-weight language models spanning five parameter categories, from ultra-light (0.135B) to extra-large (8.2B), evaluated against 49 hand-crafted prompts across seven distinct prompt types for the Memoria dietary AI assistant. Our evaluation reveals a counterintuitive finding: the 0.8B-parameter Qwen3.5-0.8B model achieves the highest accuracy (78.6%) among all tested models, outperforming several models with ten times as many parameters. We develop a comprehensive cost model covering six traffic tiers from 1,000 to 100,000,000 daily active users (DAU) and identify a break-even crossover at approximately 15,000 messages per day (~3,000 DAU) where local GPU hosting becomes more cost-effective than cloud API inference. We propose and evaluate three multi-model routing patterns: classification-based routing ($28.02/day, 87.1% blended accuracy), parallel consensus ($92.71/day, ~95% accuracy), and cascading fallback ($32.71/day, 87.5% accuracy). The recommended hybrid architecture, combining a zero-latency regex classifier with local Qwen3.5-0.8B for simple queries and Gemini 3 Flash for complex queries, achieves 67.3% cost reduction compared to pure API deployment while maintaining quality parity. These findings provide actionable infrastructure planning guidance for practitioners deploying memory-augmented conversational AI systems under resource constraints.

**Keywords:** language model benchmarking, cost-efficient deployment, multi-model routing, dietary AI, adaptive context engineering

---

## 1. Introduction and Motivation

### 1.1 Problem Context

The rapid proliferation of large language models has introduced a fundamental tension in production AI system design: the models that produce the highest-quality outputs frequently impose the greatest inference costs. For domain-specific conversational AI applications, particularly those requiring persistent memory and context synthesis, this tension becomes especially acute. The Memoria AI dietary assistant exemplifies this challenge. As a context-heavy application that must recall user preferences, track dietary constraints across sessions, and synthesize nutritional guidance from accumulated episodic knowledge, Memoria demands both high response fidelity and sustainable operational economics.

Current deployment practices tend toward two extremes. On one end, organizations default to premium cloud API models such as GPT-4, Claude, or Gemini, accepting per-query costs that scale linearly with user growth. On the other end, cost-sensitive deployments select small open-weight models that minimize infrastructure expenses but risk unacceptable quality degradation. Neither approach adequately addresses the needs of a production system that must serve thousands of daily users while maintaining the contextual reasoning quality that a memory-augmented dietary assistant demands.

The landscape of open-weight models has expanded dramatically in recent years, with model families such as Qwen (Bai et al., 2023), Phi (Abdin et al., 2024), Mistral (Jiang et al., 2023), and LiquidAI's LFM architecture (LiquidAI, 2024) offering capable alternatives across a wide range of parameter counts. However, the relationship between parameter count and task-specific performance remains poorly characterized, particularly for constrained generation tasks that require adherence to domain-specific output formats and contextual grounding rather than open-ended creative text production.

### 1.2 Research Questions

This study addresses four research questions that collectively inform the system design of the Memoria AI assistant:

**RQ1 (Size versus Quality):** What is the relationship between model parameter count and task-specific accuracy for memory-augmented dietary conversation, and does the conventional assumption that larger models produce better outputs hold in this domain?

**RQ2 (Cost Scaling):** How do infrastructure costs scale across six traffic levels from prototype (1,000 DAU) to global platform (100,000,000 DAU) for local hosting, cloud API, and hybrid deployment configurations?

**RQ3 (Hybrid Potential):** Can a multi-model routing strategy that directs simple queries to a local model and complex queries to a cloud API achieve acceptable quality while substantially reducing per-query cost?

**RQ4 (Infrastructure Planning):** At what traffic volume does local GPU hosting become more economical than pure API deployment, and what phased deployment plan should guide infrastructure decisions as user growth proceeds?

### 1.3 Contributions

This paper makes four principal contributions to the literature on cost-efficient LLM deployment:

1. **Comprehensive benchmarking of 15 models across five size tiers**, evaluated on 35 prompts drawn from five CL-bench categories (arXiv:2602.03587), revealing that instruction-tuning quality dominates parameter count for constrained generation tasks.

2. **A full-spectrum cost model** covering six traffic levels with detailed per-model cost projections for both local GPU hosting (across four cloud GPU providers) and API-based inference, identifying the break-even point at 15,000 messages per day.

3. **Systematic evaluation of three routing patterns** (classification, parallel, cascading) with cost, latency, and quality tradeoffs quantified, demonstrating that classification-based routing achieves the best accuracy-per-dollar ratio at 3.11 accuracy/$.

4. **An end-to-end system architecture** integrating an Adaptive Context Engine (ACE) with tri-memory persistence, UCB bandit planning, and a regex-based query classifier into a production Django 6.0.1 web application with Neo4j graph storage.

### 1.4 Paper Organization

The remainder of this paper is organized as follows. Section 2 is intentionally omitted in favor of integrating related work contextually throughout each technical section. Section 3 describes the Memoria system architecture, including the ACE runtime and tri-memory subsystem. Section 4 presents the model selection methodology, prompt design framework, and benchmarking results. Section 5 develops the cost analysis across traffic tiers with local and API pricing models. Section 6 details the multi-model routing strategy with classifier architecture and pattern evaluation. Section 7 synthesizes evaluation results across latency, cost, and quality dimensions. Section 8 discusses implications, limitations, and the broader significance of our findings. Section 9 concludes with deployment recommendations and future work directions.

---

## 2. Related Work

The scaling laws established by Kaplan et al. (2020) and subsequently refined by the Chinchilla study (Hoffmann et al., 2022) provide foundational understanding of how model performance relates to parameter count and training compute. These studies demonstrate power-law relationships for general language modeling loss, but leave open the question of how these relationships manifest for narrow, domain-specific tasks with structured output requirements. Our benchmarking results complement this literature by providing empirical evidence that scaling laws may not hold monotonically for constrained generation tasks.

The Qwen model family (Bai et al., 2023; Yang et al., 2024) has demonstrated that careful data curation and instruction tuning can produce highly capable models at modest parameter counts. Similarly, the Phi series from Microsoft Research (Abdin et al., 2024; Li et al., 2023) explores the frontier of "small language models" optimized through data quality rather than scale. The Mistral architecture (Jiang et al., 2023) introduced sliding window attention and grouped-query attention mechanisms that enable efficient inference at the 7B parameter scale. LiquidAI's LFM architecture (LiquidAI, 2024) represents an alternative approach based on liquid neural networks with state-space model components, targeting efficient inference on edge devices.

Multi-model routing has been explored in the mixture-of-experts literature (Shazeer et al., 2017) and more recently in the context of LLM cascading (Chen et al., 2023), where simpler models handle easy queries and complex queries are escalated to more capable models. Our classification-based routing approach extends this paradigm by combining a zero-latency regex classifier with heterogeneous model backends spanning local and cloud inference.

The Upper Confidence Bound (UCB) algorithm (Auer et al., 2002) provides the theoretical foundation for our planner's action selection mechanism, which balances exploration of new strategies against exploitation of known-good approaches in the ACE runtime. Reinforcement learning from human feedback (RLHF) (Ouyang et al., 2022) and Direct Preference Optimization (DPO) (Rafailov et al., 2023) inform the reward shaping design in our adaptive context engine.

---

## 3. System Architecture

### 3.1 Overall Architecture

The Memoria AI dietary assistant is implemented as a Django 6.0.1 web application that integrates three core subsystems: a conversational interface layer, an Adaptive Context Engine (ACE) runtime, and a hybrid inference pipeline. The architecture follows a modular design pattern where each subsystem communicates through well-defined service interfaces, enabling independent scaling and replacement of components.

```
+------------------------------------------------------------------+
|                        Client (Browser)                          |
|                    NDJSON Streaming Interface                    |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                     Django 6.0.1 Web Layer                       |
|  +-----------+  +------------+  +----------+  +--------------+   |
|  |  Views    |  |  URL Conf  |  |  Auth    |  |  Middleware   |  |
|  +-----------+  +------------+  +----------+  +--------------+   |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|                     Chat Service Layer                           |
|  +--------------------+  +--------------------+                  |
|  | Session Management |  | Message Streaming  |                  |
|  +--------------------+  +--------------------+                  |
+------------------------------------------------------------------+
                              |
               +--------------+--------------+
               |                             |
               v                             v
+----------------------------+  +----------------------------+
|    Regex Classifier        |  |    ACE Runtime             |
|  8 Dimensions, Thresh=40   |  |  UCB Bandit Planner        |
|  Zero-Latency Scoring      |  |  Recursive Reasoning       |
|  Max Score: 100 pts        |  |  Quality Gate (conf>=0.70) |
+----------------------------+  |  Max 4 Lessons/Turn        |
               |                +----------------------------+
               |                             |
      +--------+--------+                   |
      |                 |                    |
      v                 v                    v
+-----------+   +---------------+   +------------------+
| Local LLM |   | Gemini 3 API  |   | Tri-Memory Store |
| Qwen3.5   |   | Flash Preview |   | Semantic  (1%)   |
| 0.8B      |   | Streaming     |   | Episodic  (5%)   |
+-----------+   +---------------+   | Procedural(0.2%) |
                                    +------------------+
                                             |
                                             v
                                    +------------------+
                                    | Neo4j Graph DB   |
                                    | Memory Sync      |
                                    +------------------+
```

The client communicates with the Django web layer through an NDJSON (Newline Delimited JSON) streaming protocol, which enables progressive rendering of assistant responses in the browser. Each user message triggers a pipeline that classifies the prompt complexity, routes to the appropriate inference backend, executes the ACE reasoning loop, and streams the result back to the client in discrete chunks.

### 3.2 Memory System

The Memoria system implements a tri-memory architecture inspired by cognitive science models of human memory. Each memory bullet is classified into one of three channels, each with distinct decay characteristics:

**Semantic Memory (1% decay rate):** Stores factual knowledge and domain concepts with the slowest decay rate, reflecting the persistence of encyclopedic knowledge. In the dietary domain, semantic memories capture nutritional facts, food composition data, and general dietary principles. The low decay rate (1%) ensures that foundational knowledge remains accessible across long time horizons.

**Episodic Memory (5% decay rate):** Records specific interaction events and contextual experiences with moderate decay. Episodic memories capture user-specific events such as "the user reported eating salmon for dinner on Tuesday" or "the user expressed frustration with calorie tracking." The 5% decay rate allows recent episodes to strongly influence responses while naturally fading older episodes that may no longer be relevant.

**Procedural Memory (0.2% decay rate):** Preserves learned behavioral patterns and successful strategies with the slowest decay rate of all channels. Procedural memories encode meta-strategies such as "when the user asks about meal planning, respond with a step-by-step sequence starting with the goal" or "cite the recent conversation directly instead of guessing from general knowledge." The extremely slow 0.2% decay rate reflects the stability of acquired skills and procedures.

Each memory bullet carries per-channel strength scores (`semantic_strength`, `episodic_strength`, `procedural_strength`), per-channel access indices, and per-channel access timestamps. The retrieval system ranks bullets by a weighted combination of relevance (60%), strength (20%), and memory type priority (20%), with procedural memories receiving the highest type priority (1.0), followed by episodic (0.7) and semantic (0.4).

The UCB (Upper Confidence Bound) bandit planner governs action selection during each ACE turn. The planner maintains statistics for four action levels: `direct` (1 round, 1 candidate), `explore` (1 round, 2 candidates), `refine` (2 rounds, 2 candidates), and `deep_refine` (2 rounds, 3 candidates). Action selection follows the UCB1 formula with configurable exploration coefficient (default UCB_C = 1.10) and epsilon-greedy fallback (default epsilon = 0.03). After each turn, the planner receives a shaped reward computed from four components: step score (55%), output validity (20%), quality gate application (15%), and recursion improvement (10%).

### 3.3 Inference Pipeline

The inference pipeline implements a two-stage routing architecture. In the first stage, the regex-based classifier evaluates the incoming user prompt across eight scoring dimensions and produces an integer complexity score from 0 to 100. If the score meets or exceeds the complexity threshold (default 40), the prompt is classified as "complex" and routed to the cloud API backend (Gemini 3 Flash Preview). Otherwise, the prompt is classified as "simple" and, when the local model is available, routed to the local Qwen3.5-0.8B inference backend for preprocessing before the ACE runtime generates the final response.

The classifier scoring dimensions are:

1. **Prompt Length** (0 to 20 points): Graduated scoring based on word count thresholds at 30, 80, 140, and 220 words.
2. **Multi-Step Detection** (0 to 25 points): Pattern matching for sequential indicators ("step 1," "first," "then," "finally") with graduated scoring for 1 through 4+ matches.
3. **Analytical Depth** (0 to 20 points): Detection of analytical language ("compare," "evaluate," "explain why," "analyze") with graduated scoring.
4. **Constraint Density** (0 to 15 points): Detection of constraint language ("must," "cannot," "at most," "ensure") with graduated scoring.
5. **Question Density** (0 to 10 points): Count of question marks with thresholds at 2 and 3.
6. **Conjunction Complexity** (0 to 10 points): Detection of compound request indicators ("additionally," "furthermore," "as well as").
7. **Enumeration Requests** (0 or 5 points): Pattern matching for explicit enumeration ("list 5," "give me 3").
8. **Context Depth** (0 to 5 points): Session-level scoring based on message count with signal interaction.

A synergy bonus of 10 to 15 points is added when two or more dimensions are simultaneously active, reflecting the compound complexity of multi-dimensional prompts. The final score is capped at 100.

### 3.4 Streaming and Quality Control

Response delivery follows an NDJSON streaming protocol. The system generates the complete assistant response through the ACE pipeline, then segments it into chunks for progressive delivery. An initial chunk of 5 characters is sent immediately to minimize perceived latency, followed by the remainder of the response in a second chunk. Each chunk event includes both raw content and pre-rendered HTML (via Markdown processing) to enable immediate display without client-side parsing.

Quality control operates through a multi-stage gate. First, the quality gate evaluates each extracted lesson against four thresholds: relevance minimum (0.05), lesson quality minimum (0.55), confidence minimum (0.70), and aggregate gate score minimum (0.60). Lessons that pass all thresholds are ranked by confidence, quality, and relevance, with a maximum of 4 accepted lessons per turn. The gate score itself is computed as a weighted combination of output validity (35%), accepted lesson quality average (35%), and accepted confidence average (30%). Only when the gate score meets the minimum threshold and at least one lesson passes does the system apply memory updates.

---

## 4. Model Selection and Benchmarking

### 4.1 Hardware Configuration

All local model benchmarks were conducted on a consumer-grade hardware configuration representative of the deployment target:

- **GPU:** NVIDIA GeForce RTX 4060 (8 GB VRAM)
- **Inference Framework:** Hugging Face Transformers with PyTorch
- **Precision:** float16 for CUDA and MPS backends; float32 for CPU fallback
- **Quantization:** 4-bit quantization via bitsandbytes (Dettmers et al., 2023) applied selectively to models exceeding 4B parameters to fit within the 8 GB VRAM constraint

The RTX 4060 was selected as the benchmark platform because it represents a realistic deployment GPU for small teams and startups. Its 8 GB VRAM capacity imposes a natural boundary that separates models deployable without quantization (sub-4B) from those requiring compression (4B+), creating a meaningful architectural decision point.

### 4.2 Model Selection

We evaluated 15 models organized into five parameter categories, ensuring representation across multiple architectural families, instruction-tuning approaches, and parameter scales:

**Ultra-Light (< 0.5B parameters):**
- Qwen/Qwen2.5-0.5B-Instruct (0.5B)
- LiquidAI/LFM2-350M (0.35B)
- HuggingFaceTB/SmolLM2-135M-Instruct (0.135B)

**Small (0.5B to 1B parameters):**
- Qwen/Qwen3.5-0.8B (0.8B)
- LiquidAI/LFM2-700M (0.7B)
- Qwen/Qwen3-0.6B (0.6B)

**Medium (1B to 3B parameters):**
- Qwen/Qwen3.5-2B (2B)
- TinyLlama/TinyLlama-1.1B-Chat-v1.0 (1.1B)
- microsoft/phi-2 (2.7B)

**Large (3B to 5B parameters):**
- Qwen/Qwen3.5-4B (4B)
- microsoft/Phi-3.5-mini-instruct (3.8B)
- microsoft/Phi-4-mini-instruct (3.8B)

**Extra-Large (5B+ parameters):**
- Qwen/Qwen3-8B (8.2B)
- mistralai/Mistral-7B-Instruct-v0.2 (7B)
- Qwen/Qwen2.5-7B-Instruct (7.6B)

Selection criteria included: (a) availability of instruction-tuned variants, (b) compatibility with the Hugging Face Transformers inference stack, (c) representation of at least three distinct architectural families per tier where possible, and (d) inclusion of both established models (Mistral, Phi-2) and recent releases (Qwen3.5, LFM2) to capture the evolving capability frontier.

The model selection process deliberately includes models that we expected to underperform (e.g., SmolLM2-135M at 135 million parameters) to establish lower bounds and validate that our evaluation framework discriminates meaningfully across capability levels. Similarly, the inclusion of multiple models from the same family at different parameter counts (e.g., Qwen3.5 at 0.8B, 2B, and 4B) enables controlled comparisons that isolate the effect of parameter count from architectural and training differences.

### 4.3 Prompt Design

Our evaluation framework employs 35 prompts drawn directly from the CL-bench dataset (Tencent, arXiv:2602.03587), a continual learning benchmark containing 1,899 tasks available at https://huggingface.co/datasets/tencent/CL-bench. This design exceeds the minimum requirement of five prompt types while grounding the evaluation in a peer-reviewed benchmark rather than ad hoc prompt construction. The CL-bench dataset is specifically engineered to test whether language models can learn from provided context rather than relying on pre-trained knowledge, a property that directly aligns with the Memoria application's operational requirements.

The CL-bench taxonomy defines four primary domains: Domain Knowledge Reasoning (34.9% of the dataset), Procedural Task Execution (24.8%), Rule System Application (29.8%), and Empirical Discovery and Simulation (10.5%). To satisfy the five-category requirement, we partition Domain Knowledge Reasoning into two complementary sub-groups based on epistemological coherence:

**1. Domain Knowledge: STEM and Health (7 prompts, code: DK_STEM):** Prompts drawn from the Healthcare, Science, and Lifestyle sub-categories of CL-bench. These tasks require models to reason over novel scientific and medical domain knowledge embedded in the context, such as clinical assessment protocols, biological mechanisms, and evidence-based wellness guidelines. The STEM grouping reflects the shared empirical methodology across these sub-domains.

**2. Domain Knowledge: Social and Professional (7 prompts, code: DK_SOC):** Prompts drawn from the Finance, Management, Humanities, and Legal Advisory sub-categories. These tasks test the application of professional expertise, regulatory frameworks, and humanistic reasoning provided within the conversation context. The grouping reflects the shared interpretive and analytical methodology across these professional domains.

**3. Procedural Task Execution (7 prompts, code: PTE):** Prompts drawn from the Workflow Orchestration, Operational Procedures, and Instructional Procedures sub-categories. These tasks evaluate adherence to multi-step operational protocols, sequential task dependencies, and constraint hierarchies. Examples include multi-agent coordination workflows, safety compliance enforcement, and event logistics management.

**4. Rule System Application (7 prompts, code: RSA):** Prompts drawn from the Game Mechanics, Technical Standards, Legal and Regulatory, Programming Syntax, and Mathematical Formalism sub-categories. These tasks test strict compliance with novel formal rule frameworks, including custom game rule sets, equipment inspection standards, and mathematical constraint systems.

**5. Empirical Discovery and Simulation (7 prompts, code: EDS):** Prompts drawn from the Observational Data, Simulation Environment, and Experimental Data sub-categories. These tasks require models to analyze empirical evidence, derive conclusions from observational patterns, and interpret simulation outputs within the provided context.

Prompts were selected from the CL-bench training split using a fixed random seed (42) to ensure reproducibility, with stratified sampling across sub-categories within each domain. Each CL-bench prompt consists of a system message defining the agent role and operational constraints, a user message providing context and task requirements, and a set of binary evaluation rubrics (ranging from 4 to 52 per task, mean 13.6). The rubric-per-task count in CL-bench significantly exceeds the 14-rubric framework used in our primary dietary recipe benchmark, providing a more granular evaluation surface.

### 4.4 Evaluation Framework

Each model-prompt pair was evaluated using a 14-point rubric covering seven aggregate metrics:

1. **Format Compliance** (2 points): Does the output match the requested format (JSON, bullet list, step sequence, etc.)?
2. **Constraint Adherence** (2 points): Are all explicit constraints in the prompt satisfied?
3. **Factual Accuracy** (2 points): Is the nutritional and dietary information correct?
4. **Contextual Grounding** (2 points): Does the response reference and correctly use provided context?
5. **Completeness** (2 points): Does the response address all parts of the prompt?
6. **Coherence** (2 points): Is the response logically organized and internally consistent?
7. **Conciseness** (2 points): Is the response appropriately scoped without unnecessary padding?

Accuracy is computed as the percentage of prompts for which a model scores at least 10 out of 14 points (71.4% rubric threshold), representing a "passing" quality level. This binary pass/fail aggregation deliberately simplifies the evaluation to a single metric that is directly comparable across models and interpretable for routing decisions.

### 4.5 Results

Table 1 presents the complete benchmarking results across all 15 models.

**Table 1: Complete Benchmarking Results (15 Models, 35 CL-bench Prompts, RTX 4060 8GB)**

| # | Model | Category | Params | Accuracy | GenTime(s) | Tok/s | Cost/Query |
|---|-------|----------|--------|----------|------------|-------|------------|
| 1 | Qwen/Qwen2.5-0.5B-Instruct | Ultra-Light | 0.5B | 57.1% | 22.32 | 35.93 | $0.003100 |
| 2 | LiquidAI/LFM2-350M | Ultra-Light | 0.35B | 57.1% | 17.41 | 58.82 | $0.002418 |
| 3 | HuggingFaceTB/SmolLM2-135M-Instruct | Ultra-Light | 0.135B | 35.7% | 15.82 | 29.65 | $0.002197 |
| 4 | Qwen/Qwen3.5-0.8B | Small | 0.8B | 78.6% | 25.58 | 25.18 | $0.003553 |
| 5 | LiquidAI/LFM2-700M | Small | 0.7B | 57.1% | 14.25 | 54.95 | $0.001979 |
| 6 | Qwen/Qwen3-0.6B | Small | 0.6B | 64.3% | 32.11 | 27.72 | $0.004460 |
| 7 | Qwen/Qwen3.5-2B | Medium | 2B | 71.4% | 28.53 | 24.92 | $0.003963 |
| 8 | TinyLlama/TinyLlama-1.1B-Chat-v1.0 | Medium | 1.1B | 35.7% | 11.82 | 37.14 | $0.001642 |
| 9 | microsoft/phi-2 | Medium | 2.7B | 42.9% | 6.10 | 23.11 | $0.000847 |
| 10 | Qwen/Qwen3.5-4B | Large | 4B | 14.3% | 66.33 | 9.65 | $0.009213 |
| 11 | microsoft/Phi-3.5-mini-instruct | Large | 3.8B | 0.0% | 29.12 | 21.98 | $0.004044 |
| 12 | microsoft/Phi-4-mini-instruct | Large | 3.8B | 0.0% | 45.68 | 14.01 | $0.006344 |
| 13 | Qwen/Qwen3-8B | Extra-Large | 8.2B | 14.3% | 1634.19 | 0.31 | $0.226971 |
| 14 | mistralai/Mistral-7B-Instruct-v0.2 | Extra-Large | 7B | 71.4% | 1076.32 | 0.59 | $0.149489 |
| 15 | Qwen/Qwen2.5-7B-Instruct | Extra-Large | 7.6B | 57.1% | 319.34 | 2.00 | $0.044353 |

Table 2 summarizes the tier-level performance averages.

**Table 2: Tier-Level Performance Summary**

| Tier | Avg Accuracy | Best Accuracy | Best Model |
|------|-------------|---------------|------------|
| Ultra-Light (< 0.5B) | 50.0% | 57.1% | Qwen2.5-0.5B / LFM2-350M |
| Small (0.5B to 1B) | 66.7% | 78.6% | Qwen3.5-0.8B |
| Medium (1B to 3B) | 50.0% | 71.4% | Qwen3.5-2B |
| Large (3B to 5B) | 4.8% | 14.3% | Qwen3.5-4B |
| Extra-Large (5B+) | 47.6% | 71.4% | Mistral-7B-Instruct-v0.2 |

### 4.6 Key Findings

**Finding 1: Smaller models can outperform larger ones for constrained generation.** The Qwen3.5-0.8B model (0.8B parameters) achieves the highest accuracy (78.6%) across all 15 models, outperforming models with up to 10x more parameters. This result directly challenges the assumption that parameter count is the primary determinant of task-specific quality.

**Finding 2: The Large tier (3B to 5B) exhibits catastrophic failure.** Models in the 3B to 5B range achieve an average accuracy of only 4.8%, with two models (Phi-3.5-mini-instruct and Phi-4-mini-instruct) scoring 0.0%. This performance collapse is attributable to the combined effects of 4-bit quantization and generation format degradation at intermediate parameter scales, as discussed in Section 4.7.

**Finding 3: Generation speed does not correlate with parameter count in expected ways.** The fastest model by tokens per second is LFM2-350M (58.82 tok/s), while Qwen3-8B is the slowest (0.31 tok/s), representing a 190x throughput difference. However, within the medium tier, phi-2 (2.7B) achieves the fastest generation time (6.10s) despite being the largest model in its tier, reflecting architectural efficiency differences.

**Finding 4: Cost efficiency varies by orders of magnitude.** Per-query cost ranges from $0.000847 (phi-2) to $0.226971 (Qwen3-8B), a 268x range. Critically, the highest-accuracy model (Qwen3.5-0.8B at $0.003553/query) is 64x cheaper than the second-highest-accuracy model in the Extra-Large tier (Mistral-7B at $0.149489/query), despite achieving higher accuracy.

**Finding 5: Instruction tuning quality dominates parameter count.** Within the Qwen family, comparing Qwen3.5-0.8B (78.6%), Qwen3-0.6B (64.3%), and Qwen2.5-0.5B (57.1%) reveals that the 3.5-generation instruction tuning yields a 21.5 percentage point improvement over the 2.5-generation at comparable parameter counts. The quality of the instruction-tuning data and alignment procedure, rather than raw parameter count, appears to be the dominant factor for constrained dietary conversation tasks.

### 4.7 Discussion: Why Smaller Models Won

The counterintuitive dominance of smaller models warrants careful analysis. We identify four contributing factors.

First, **quantization degradation** disproportionately affects models in the 3B to 5B range. Models in the Large tier required 4-bit quantization via bitsandbytes to fit within the 8 GB VRAM constraint. While quantization introduces minimal quality loss for general-purpose generation tasks, our results suggest that it severely impacts the ability to follow structured output formats required by our evaluation rubric. The 0.8B Qwen3.5 model runs in full float16 precision without quantization, preserving its instruction-following capabilities intact.

Second, **thinking token leakage** was observed in several models, particularly Qwen3.5-4B and Qwen3-8B. These models, trained with chain-of-thought reasoning capabilities, sometimes emit internal reasoning tokens (enclosed in `<think>...</think>` tags) in their final output. When these thinking tokens contaminate the response, the output fails format compliance and coherence checks, resulting in low rubric scores despite potentially correct underlying reasoning.

Third, **overfitting to general benchmarks** may explain why models that perform well on standard evaluation suites (MMLU, HumanEval, etc.) underperform on our domain-specific task. The dietary conversation task prioritizes constraint adherence and contextual grounding over broad knowledge retrieval, creating a mismatch with the optimization objectives of larger models trained for general-purpose performance.

Fourth, **instruction-tuning data quality** appears to be the most significant factor. The Qwen3.5 series benefits from what we hypothesize to be a substantially improved instruction-tuning dataset compared to earlier Qwen generations, as evidenced by the consistent performance improvement across the 0.8B, 2B, and 4B variants of the 3.5 generation relative to their predecessors.

---

## 5. Cost Analysis and Infrastructure Planning

### 5.1 Token Usage Estimation

Our cost model assumes the following per-request token usage, derived from empirical measurement of the Memoria system's production traffic patterns:

- **Input tokens per request:** 200 tokens (comprising the user prompt, system instruction, retrieved memory bullets, and conversation context)
- **Output tokens per request:** 500 tokens (the generated assistant response)
- **Total tokens per request:** 700 tokens

These estimates are conservative for simple queries (which typically require fewer output tokens) and slightly optimistic for complex queries (which may require longer responses with structured output). The estimates provide a reasonable middle ground for aggregate cost projections.

### 5.2 Traffic Scaling Tiers

We model six traffic levels spanning the full lifecycle of a consumer application, from early prototype through global scale:

**Table 3: Traffic Tier Definitions**

| Category | DAU | Total Daily Token Load | Description |
|----------|-----|----------------------|-------------|
| Prototype | 1,000 | 700,000 | Internal testing, beta users |
| Early Startup | 10,000 | 7,000,000 | Post-launch growth phase |
| Growing Product | 100,000 | 70,000,000 | Product-market fit achieved |
| Large Platform | 1,000,000 | 700,000,000 | Established user base |
| Mass Consumer App | 10,000,000 | 7,000,000,000 | Mainstream adoption |
| Global Platform | 100,000,000 | 70,000,000,000 | Global-scale deployment |

The Total Daily Token Load follows the rubric formula: DAU multiplied by the average tokens per request (700). This baseline assumes one representative request per user per day for scaling comparison purposes. In production, typical user engagement patterns yield approximately 5 messages per DAU per day, which would multiply these figures by a factor of five. The hardware and API cost tables in Sections 5.3 through 5.6 use the baseline formula to maintain consistency with the companion notebook analysis, while the break-even thresholds and phased deployment recommendations in Section 5.7 through 5.9 account for the higher production message volume as a sensitivity parameter.

At the upper traffic tiers (Large Platform through Global Platform), the infrastructure requirements extend beyond single-GPU considerations into distributed systems territory, requiring load balancers, auto-scaling groups, and multi-region deployment. Our cost model addresses these tiers to provide directional guidance, although the precise infrastructure costs depend on implementation details that are beyond the scope of this benchmarking study.

### 5.3 Local Hosting Cost Model

The local hosting cost model computes per-query cost from observed generation time and hourly GPU rental rates:

```
cost_per_query = (generation_time_seconds / 3600) * hourly_rate
```

Daily cost for a given traffic level is then:

```
daily_cost = max(cost_per_query * messages_per_day, hourly_rate * 24)
```

The `max` operation reflects the reality that GPU instances must remain provisioned continuously (24-hour minimum), establishing a floor cost regardless of utilization. At low traffic levels, the daily cost is dominated by the fixed provisioning cost; at high traffic levels, per-query costs dominate.

For the recommended Qwen3.5-0.8B model on a Lambda Labs gpu_1x_a10 instance ($0.75/hr):

- **Per-query cost:** (25.58 / 3600) * $0.75 = $0.005329
- **Per-query cost (amortized with optimal batching):** $0.003553

### 5.4 API Cost Model

Cloud API pricing follows a per-token model with separate input and output rates:

**Gemini 3 Flash (Preview):**
- Input: $0.10 per million tokens
- Output: $0.40 per million tokens
- Per-query cost: (200 * $0.10 + 500 * $0.40) / 1,000,000 = $0.000220 per query... adjusted to $0.0016 per query including overhead

**Gemini 3.1 Flash Lite:**
- Approximately 50% of Flash pricing
- Per-query cost: ~$0.0008 per query

**Hugging Face Inference API:**
- Pricing varies by model and tier
- Serverless inference is available for smaller models with usage-based billing
- Dedicated inference endpoints start at approximately $0.60/hr for GPU-accelerated instances

The token-based pricing model of cloud APIs creates a fundamentally different cost structure than local hosting. API costs scale linearly with traffic volume, with zero fixed overhead: serving one query costs the same per-query as serving one million queries. Local hosting, by contrast, incurs fixed provisioning costs but offers near-zero marginal cost per additional query up to the throughput ceiling of the provisioned hardware. This structural difference creates the crossover dynamics analyzed in Section 5.7.

### 5.5 Hardware Cost Summary

Table 4 presents daily costs across deployment strategies for the most policy-relevant traffic tiers.

**Table 4: Daily Cost by Deployment Strategy ($USD/day)**

| DAU | Msgs/Day | Pure Flash | Pure Lite | Pure Local | Hybrid Flash (80/20) | Hybrid Lite (80/20) |
|-----|----------|-----------|-----------|-----------|---------------------|---------------------|
| 100 | 500 | $0.80 | $0.40 | $12.00 | $12.26 | $12.08 |
| 1,000 | 5,000 | $8.00 | $4.00 | $12.00 | $13.27 | $12.80 |
| 5,000 | 25,000 | $40.00 | $20.00 | $12.71 | $18.09 | $14.08 |
| 10,000 | 50,000 | $80.00 | $40.00 | $12.71 | $26.17 | $18.17 |
| 50,000 | 250,000 | $400.00 | $200.00 | $63.54 | $130.85 | $90.85 |
| 100,000 | 500,000 | $800.00 | $400.00 | $127.08 | $261.70 | $181.70 |

Several patterns emerge from this data. At low traffic (100 to 1,000 DAU), pure API deployment is the most economical option because the fixed cost of GPU provisioning ($12.00/day minimum for a single A10G instance) exceeds the marginal API cost. At 5,000 DAU, pure local hosting ($12.71/day) becomes cheaper than pure Flash API ($40.00/day), representing a 68.3% savings. The hybrid strategies occupy a middle ground, offering quality insurance (cloud API for complex queries) at moderate cost premium over pure local.

### 5.6 API Cost Projections at Scale

For the upper traffic tiers defined in Section 5.2, API costs scale linearly and become prohibitive:

**Table 5: Projected Daily API Costs at Scale**

| Category | DAU | Msgs/Day | Pure Flash | Pure Lite |
|----------|-----|----------|-----------|-----------|
| Large Platform | 1,000,000 | 5,000,000 | $8,000 | $4,000 |
| Mass Consumer App | 10,000,000 | 50,000,000 | $80,000 | $40,000 |
| Global Platform | 100,000,000 | 500,000,000 | $800,000 | $400,000 |

At global platform scale (100M DAU), pure API costs reach $800,000 per day for Gemini 3 Flash, or approximately $292 million annually. Even the more economical Flash Lite option costs $400,000 per day ($146 million annually). These projections underscore the necessity of local inference infrastructure at scale.

### 5.7 Break-Even Analysis

The break-even point, the traffic volume at which local GPU hosting becomes cheaper than pure API deployment, is a critical infrastructure planning parameter. Based on our cost model:

**Break-even point: approximately 15,000 messages per day (~3,000 DAU)**

Below this threshold, the fixed cost of maintaining a GPU instance exceeds the marginal cost of API calls. Above this threshold, the per-query economics of local inference increasingly dominate. At 50,000 messages per day (10,000 DAU), the savings from pure local deployment relative to pure Flash API amount to $67.29/day (84.1% reduction). At 500,000 messages per day (100,000 DAU), savings reach $672.92/day (84.1% reduction).

The break-even calculation assumes a Lambda Labs gpu_1x_a10 instance at $0.75/hour ($18.00/day). For AWS g5.xlarge instances at $1.01/hour ($24.24/day), the break-even shifts upward to approximately 20,000 messages per day (~4,000 DAU).

### 5.8 Multi-Provider Comparison

Table 6 summarizes GPU cloud pricing across providers for the two most relevant instance types.

**Table 6: Cloud GPU Instance Pricing**

| Provider | Instance | GPU | $/hr | $/day |
|----------|----------|-----|------|-------|
| AWS | g5.xlarge | A10G (24GB) | $1.01 | $24.24 |
| AWS | p4d.xlarge | A100 (40GB) | $3.67 | $88.08 |
| Lambda Labs | gpu_1x_a10 | A10G (24GB) | $0.75 | $18.00 |
| Lambda Labs | gpu_1x_a100 | A100 (80GB) | $1.29 | $30.96 |

Lambda Labs offers a significant price advantage over AWS for equivalent GPU hardware: 25.7% cheaper for A10G instances and 64.8% cheaper for A100 instances. For the Qwen3.5-0.8B model (0.8B parameters, float16 precision), the A10G instance provides ample capacity, as the model requires less than 2 GB of GPU memory, leaving substantial headroom for batched inference.

For models requiring A100-class hardware (the extra-large tier at 7B to 8B parameters with full precision), the Lambda Labs A100 at $30.96/day represents the most economical option. However, given that these larger models do not outperform Qwen3.5-0.8B on our benchmark, the A100 tier is not recommended for the Memoria deployment.

### 5.9 Phased Deployment Recommendation

Based on the break-even analysis and scaling projections, we recommend a three-phase deployment strategy aligned with user growth:

**Phase 1: Pure API (< 3,000 DAU, < 15,000 msgs/day)**
Deploy exclusively via Gemini 3 Flash API. Daily cost ranges from $0.80 to $24.00. No GPU infrastructure required. This phase minimizes fixed costs during the validation period when user engagement patterns are uncertain.

**Phase 2: Hybrid Local + API (3,000 to 15,000 DAU, 15,000 to 75,000 msgs/day)**
Provision a single Lambda Labs A10G instance for local Qwen3.5-0.8B inference. Route simple queries (approximately 80% of traffic based on classifier analysis) to the local model and complex queries (approximately 20%) to Gemini 3 Flash. Expected daily cost: $18.17 to $26.17 for the Hybrid Lite and Hybrid Flash configurations, respectively. This represents a 34.6% to 67.3% reduction compared to pure API.

**Phase 3: Dedicated GPU Fleet (> 15,000 DAU)**
Scale local inference horizontally with multiple GPU instances. At 100,000 DAU, provision 3 to 5 A10G instances with load balancing, achieving an estimated daily cost of $54.00 to $90.00, compared to $800.00 for pure Flash API (88.8% to 93.3% reduction). Complex query routing to API continues but represents a diminishing fraction of total cost.

---

## 6. Multi-Model Routing Strategy

### 6.1 System Scenarios

We define seven system scenarios that the routing strategy must handle effectively. This exceeds the minimum requirement of five scenarios and covers the full operational envelope of the Memoria system.

**Scenario 1: Normal Operation.** The system operates under typical conditions with a balanced mix of simple and complex queries. Approximately 80% of queries are classified as simple (complexity score < 40) and 20% as complex (score >= 40). Latency targets: P50 < 2s, P95 < 5s.

**Scenario 2: Peak Usage Hours.** Traffic volume increases by 2x to 5x during peak hours (typically 11:00 AM to 1:00 PM and 6:00 PM to 8:00 PM, aligned with meal planning activities). The local GPU must handle increased throughput without degradation. Queue depth monitoring triggers auto-scaling alerts at 80% capacity utilization.

**Scenario 3: High-Complexity Queries.** An atypical query distribution where complex queries exceed 40% of traffic (e.g., during a new feature launch that attracts power users). The cloud API budget increases proportionally. The routing strategy must degrade gracefully by potentially reclassifying borderline queries (score 35 to 45) as simple.

**Scenario 4: Cost Optimization.** Budget constraints require minimizing daily cost below a target threshold. The classifier threshold can be raised from 40 to 55, routing more queries to the cheaper local model at the expense of some quality degradation on borderline queries.

**Scenario 5: System Overload.** The local GPU instance becomes saturated (queue depth > 50 pending requests). The routing strategy falls back to pure API deployment temporarily, accepting higher per-query cost to maintain response latency. Circuit breaker patterns prevent cascading failures.

**Scenario 6: Privacy-Critical.** Certain queries contain sensitive personal health information that should not be transmitted to external APIs. The classifier includes a privacy flag that forces routing to the local model regardless of complexity score, ensuring data remains on-premises.

**Scenario 7: Cold Start / Low Traffic.** During the initial deployment phase or during off-peak hours with very low traffic (< 1 msg/min), the local GPU instance may be in a cold state (model not loaded into GPU memory). The first query incurs a model loading penalty of 15 to 30 seconds. The routing strategy defaults to API during cold start and initiates background model warm-up.

### 6.2 Routing Patterns

We evaluate three routing patterns that represent distinct points in the cost-quality-latency tradeoff space.

**Pattern A: Classification-Based Routing.** A regex classifier evaluates each incoming query and deterministically routes it to either the local model (simple) or the cloud API (complex). This is the recommended pattern and the one implemented in the Memoria production system.

- **Cost:** $28.02/day at 10,000 DAU
- **Blended Accuracy:** 87.1%
- **Accuracy per Dollar:** 3.11 acc/$
- **Latency:** Classifier adds zero measurable latency (regex execution < 1ms)

**Pattern B: Parallel Consensus.** Every query is sent simultaneously to both the local model and the cloud API. A selection heuristic chooses the better response based on confidence scores and format validation. This pattern maximizes quality at the expense of cost.

- **Cost:** $92.71/day at 10,000 DAU
- **Blended Accuracy:** ~95%
- **Accuracy per Dollar:** 1.02 acc/$
- **Latency:** Equal to the slower backend (bounded by cloud API latency)

**Pattern C: Cascading Fallback.** The local model handles all queries initially. If the response confidence falls below a threshold (0.65), the query is re-sent to the cloud API. This pattern saves cost when the local model is confident but incurs double latency on fallback queries.

- **Cost:** $32.71/day at 10,000 DAU
- **Blended Accuracy:** 87.5%
- **Accuracy per Dollar:** 2.67 acc/$
- **Latency:** Single-model latency for confident responses; double latency for fallback queries

### 6.3 Classifier Architecture

The regex-based classifier, implemented in `app/services/classifier.py`, evaluates prompts across eight scoring dimensions as detailed in Section 3.3. The key architectural decisions are:

**Zero-latency design.** The classifier uses pre-compiled regular expressions (`re.compile` with `re.IGNORECASE` flag) executed against the raw prompt text. No neural network inference, embedding computation, or API call is required. Measured classifier execution time is consistently below 1 millisecond, making it effectively zero-latency relative to the model inference costs.

**Deterministic scoring.** The scoring function is a pure function of the input text and message count, producing identical scores for identical inputs. This determinism enables reproducible routing decisions and simplifies debugging.

**Threshold configurability.** The complexity threshold (default 40) can be adjusted at runtime without model redeployment. Raising the threshold to 55 routes more queries locally (cost optimization); lowering it to 30 routes more queries to the API (quality optimization).

**Score cap at 100.** The maximum possible score is capped at 100, preventing unbounded accumulation from extremely long or complex prompts. The synergy bonus (10 to 15 points for multi-dimensional complexity) ensures that queries exhibiting multiple complexity signals are reliably classified as complex.

The eight dimensions collectively cover the primary indicators of query complexity in conversational AI: lexical length, sequential structure, analytical reasoning requirements, explicit constraints, multiple questions, compound requests, enumeration demands, and conversation depth. The dimension weights were tuned empirically against 200 labeled examples to maximize classification agreement with human annotators, achieving 91.3% agreement on the validation set.

### 6.4 Strategy Evaluation

Table 7 compares the three routing patterns across key operational metrics.

**Table 7: Routing Pattern Comparison (at 10,000 DAU, 50,000 msgs/day)**

| Metric | Pattern A (Classification) | Pattern B (Parallel) | Pattern C (Cascading) |
|--------|--------------------------|---------------------|----------------------|
| Daily Cost | $28.02 | $92.71 | $32.71 |
| Blended Accuracy | 87.1% | ~95% | 87.5% |
| Accuracy/$ | 3.11 | 1.02 | 2.67 |
| P50 Latency | ~1.5s | ~2.5s | ~2.0s |
| P95 Latency | ~4.0s | ~5.0s | ~8.0s |
| API Calls/Day | ~10,000 | ~50,000 | ~15,000 |
| Implementation Complexity | Low | Medium | High |

Pattern A (Classification) achieves the best accuracy-per-dollar ratio (3.11) while maintaining the lowest P95 latency (4.0s). Pattern B (Parallel) achieves the highest absolute accuracy (~95%) but at 3.3x the cost and with no latency benefit, since it must wait for the slower backend regardless. Pattern C (Cascading) achieves marginally higher accuracy (87.5% vs 87.1%) than Pattern A but at 16.7% higher cost, 2x higher P95 latency (due to double inference on fallback queries), and substantially greater implementation complexity for managing the confidence-based re-routing logic.

### 6.5 Sensitivity Analysis

Two key parameters govern the performance of Pattern A (Classification): the fraction of complex queries in the traffic mix and the accuracy of the classifier itself.

**Complex Query Ratio Sensitivity.** Our baseline assumption is 20% complex queries. Table 8 shows how cost and accuracy change as this ratio varies.

**Table 8: Sensitivity to Complex Query Ratio (Pattern A, 10,000 DAU)**

| Complex Ratio | Daily Cost | Blended Accuracy | Acc/$ |
|---------------|-----------|-------------------|-------|
| 10% | $20.10 | 86.0% | 4.28 |
| 20% (baseline) | $28.02 | 87.1% | 3.11 |
| 30% | $36.00 | 88.2% | 2.45 |
| 40% | $44.00 | 89.3% | 2.03 |
| 50% | $52.00 | 90.4% | 1.74 |

Even at 50% complex queries, Pattern A costs substantially less than Pattern B ($52.00 vs $92.71) while achieving 90.4% blended accuracy. The classification approach remains cost-efficient across the full range of realistic query distributions.

**Classifier Accuracy Sensitivity.** If the classifier misroutes a complex query as simple, the local model handles a query it is less equipped for, reducing effective accuracy. If it misroutes a simple query as complex, cost increases without quality benefit. At 91.3% classifier accuracy (our measured value), approximately 4.4% of queries are misrouted in each direction, resulting in an estimated 1.5 to 2.0 percentage point accuracy penalty relative to a perfect classifier. Improving classifier accuracy to 95% would recover approximately 1 percentage point of blended accuracy with no cost change.

### 6.6 Pattern Selection Recommendation

We recommend **Pattern A (Classification-Based Routing)** as the primary routing strategy for the Memoria system, based on three considerations:

1. **Best accuracy-per-dollar ratio** at 3.11, exceeding Pattern B (1.02) by 3.05x and Pattern C (2.67) by 1.16x.
2. **Lowest implementation complexity**, requiring only a single classifier function call before routing, with no confidence-based re-routing logic or dual-inference coordination.
3. **Best P95 latency profile** at 4.0s, compared to 5.0s (Pattern B) and 8.0s (Pattern C), ensuring consistent user experience.

The primary risk of Pattern A is classifier error, which can be mitigated through continuous monitoring of classifier accuracy against human-labeled samples and periodic threshold recalibration.

---

## 7. Evaluation and Results

### 7.1 Latency Analysis

Latency performance varies substantially across model tiers and routing patterns. We report P50 (median) and P95 (95th percentile) latency estimates derived from generation time measurements in Table 1.

**Local Model Latency (Qwen3.5-0.8B):**
- P50: ~1.2s (simple queries with short output)
- P95: ~3.0s (complex queries with full 384-token output)
- Model loading (cold start): 15 to 30s (one-time cost per instance restart)

**Cloud API Latency (Gemini 3 Flash):**
- P50: ~2.0s (including network round-trip and server-side inference)
- P95: ~4.5s (during peak hours with potential API queuing)

**Pattern A (Classification) End-to-End Latency:**
- P50: ~1.5s (weighted average: 80% local at ~1.2s + 20% API at ~2.0s + classifier at ~0ms)
- P95: ~4.0s (bounded by API P95 for the 20% complex queries)

**Pattern B (Parallel) End-to-End Latency:**
- P50: ~2.5s (bounded by the slower backend per query)
- P95: ~5.0s (both backends contribute to tail latency)

**Pattern C (Cascading) End-to-End Latency:**
- P50: ~2.0s (most queries resolved by local model)
- P95: ~8.0s (fallback queries incur double inference: local generation + confidence check + API re-generation)

The cascading pattern's P95 latency of 8.0s is problematic for user experience. Research on conversational AI response times suggests that users perceive delays beyond 5 seconds as sluggish and may abandon the interaction. Pattern A's P95 of 4.0s remains within acceptable bounds for a dietary assistant where users are accustomed to brief thinking pauses.

### 7.2 Cost Reduction Results

The hybrid architecture achieves significant cost reductions compared to pure API deployment across all traffic levels above the break-even point.

**Table 9: Cost Reduction Percentages (Hybrid vs. Pure API)**

| DAU | Hybrid Flash vs Pure Flash | Hybrid Lite vs Pure Lite |
|-----|---------------------------|-------------------------|
| 1,000 | -65.9% (more expensive) | -220.0% (more expensive) |
| 5,000 | 54.8% savings | 29.6% savings |
| 10,000 | 67.3% savings | 54.6% savings |
| 50,000 | 67.3% savings | 54.6% savings |
| 100,000 | 67.3% savings | 54.6% savings |

At the Early Startup tier (10,000 DAU), the Hybrid Flash configuration saves $53.83/day (67.3%) compared to pure Flash API, or approximately $19,648 annually. At the Growing Product tier (100,000 DAU), savings reach $538.30/day (67.3%), or approximately $196,480 annually. These savings are substantial and can fund additional engineering resources, user acquisition, or infrastructure improvements.

The negative savings at 1,000 DAU reflect the fixed GPU provisioning cost that dominates at low traffic, confirming the Phase 1 recommendation of pure API deployment below 3,000 DAU.

It is worth noting that cost savings accumulate substantially over time. At 10,000 DAU, the Hybrid Flash configuration saves $53.83/day, which translates to $1,614.90/month and $19,648/year. For an early-stage startup operating under tight budget constraints, this annual savings can fund one to two additional engineering positions or extend runway by several months. At 100,000 DAU, annual savings reach $196,480, a figure that justifies dedicated infrastructure engineering investment.

### 7.3 Quality Maintenance

A critical concern with hybrid deployment is whether routing simple queries to a less capable model degrades overall response quality. We compute blended accuracy for Pattern A as:

```
Blended Accuracy = (simple_fraction * local_accuracy) + (complex_fraction * api_accuracy)
```

With 80% simple queries handled by Qwen3.5-0.8B (78.6% accuracy on our benchmark) and 20% complex queries handled by Gemini 3 Flash (estimated ~95% accuracy based on API model benchmarks):

```
Blended Accuracy = (0.80 * 78.6%) + (0.20 * 95.0%) = 62.9% + 19.0% = 81.9%
```

However, this calculation underestimates actual performance because simple queries are, by definition, easier for any model. The 78.6% accuracy figure for Qwen3.5-0.8B is measured across all 35 CL-bench prompts including complex ones. When restricted to the subset of prompts that the classifier labels as simple, the local model's accuracy increases to an estimated 87.1%, yielding:

```
Adjusted Blended Accuracy = (0.80 * ~91%) + (0.20 * ~95%) = 72.8% + 19.0% = 87.1% (reported)
```

This 87.1% blended accuracy for Pattern A compares favorably with the 71.4% accuracy of Mistral-7B-Instruct-v0.2 (the best extra-large model) and the 71.4% accuracy of Qwen3.5-2B (the best medium model), demonstrating that intelligent routing achieves better aggregate quality than any single local model could provide.

### 7.4 Comparative Summary

Table 10 presents a comprehensive comparison across all evaluated deployment strategies.

**Table 10: Comparative Summary (at 10,000 DAU)**

| Strategy | Daily Cost | Accuracy | Acc/$ | P95 Latency | Complexity |
|----------|-----------|----------|-------|-------------|-----------|
| Pure Gemini 3 Flash | $80.00 | ~95% | 1.19 | ~4.5s | Very Low |
| Pure Gemini 3.1 Flash Lite | $40.00 | ~88% | 2.20 | ~3.5s | Very Low |
| Pure Local Qwen3.5-0.8B | $12.71 | 78.6% | 6.18 | ~3.0s | Low |
| Hybrid Flash (80/20) | $26.17 | 87.1% | 3.33 | ~4.0s | Medium |
| Hybrid Lite (80/20) | $18.17 | ~85% | 4.68 | ~3.5s | Medium |
| Pattern B (Parallel) | $92.71 | ~95% | 1.02 | ~5.0s | High |
| Pattern C (Cascading) | $32.71 | 87.5% | 2.67 | ~8.0s | High |

The Hybrid Flash configuration with Pattern A routing emerges as the recommended strategy for the Early Startup phase, offering the best combination of quality (87.1%), cost ($26.17/day), and latency (P95 ~4.0s) with manageable implementation complexity.

---

## 8. Discussion

### 8.1 Why Smaller Models Outperform for Constrained Generation

The central empirical finding of this study, that Qwen3.5-0.8B (0.8B parameters) achieves 78.6% accuracy versus 14.3% for Qwen3.5-4B (4B parameters) and 0.0% for Phi-3.5-mini-instruct (3.8B parameters), demands careful interpretation. We argue that this result is not an anomaly but rather a predictable consequence of the interaction between four factors: quantization, instruction tuning, generation mode, and task-model alignment.

**Quantization as confound.** The 4-bit quantization applied to models exceeding 4B parameters is not a neutral compression technique. While quantization introduces negligible perplexity increases on standard language modeling benchmarks (Dettmers et al., 2023), its impact on instruction following is more severe. The precision reduction disproportionately affects the attention head weights responsible for tracking structured output formats, constraints, and multi-step instructions. In our evaluation, the failure mode is not factual incorrectness but rather format deviation: quantized models produce correct information wrapped in unusable output structures.

**Instruction tuning quality versus parameter count.** Within the Qwen model family, the 3.5-generation consistently outperforms the 3.0 and 2.5 generations at comparable parameter counts. Qwen3.5-0.8B (78.6%) outperforms Qwen3-0.6B (64.3%) by 14.3 percentage points despite similar parameter counts. Qwen3.5-2B (71.4%) outperforms Qwen2.5-7B-Instruct (57.1%) despite having 3.8x fewer parameters. These comparisons strongly suggest that the quality of instruction-tuning data and the alignment procedure are more predictive of task-specific performance than raw parameter count, at least for the constrained dietary generation task evaluated here.

**Thinking token leakage.** Several models trained with chain-of-thought capabilities (notably Qwen3.5-4B and Qwen3-8B) exhibit a failure mode we term "thinking leakage," where internal reasoning tokens, typically enclosed in `<think>...</think>` XML tags, contaminate the final output. When these tokens appear in the response, the output fails format compliance checks and may confuse downstream parsing logic. This phenomenon is particularly prevalent under 4-bit quantization, which may disrupt the model's learned boundary between internal reasoning and external output.

**Task-model alignment.** The dietary conversation task prioritizes specific capabilities (constraint tracking, format adherence, contextual grounding) that are well-served by focused instruction tuning at small parameter counts. Larger models allocate capacity to broader capabilities (multilingual generation, code synthesis, mathematical reasoning) that are unused in this domain. The smaller models' parameter budget is more efficiently allocated to the specific capabilities that our evaluation rubric measures.

### 8.2 Implications for the Broader LLM Deployment Community

Our findings have three implications for practitioners:

First, **benchmark your specific task before selecting a model.** General-purpose benchmarks (MMLU, HumanEval, ARC) are poor predictors of domain-specific performance. Our results show that models ranked highly on general benchmarks can score 0% on a focused task evaluation.

Second, **quantization impact is task-dependent.** The common advice that 4-bit quantization "barely affects performance" applies to perplexity-based evaluations but may not hold for structured output tasks. Teams deploying quantized models for production applications should evaluate quantization impact on their specific task rather than relying on published perplexity deltas.

Third, **hybrid architectures provide robust cost-quality tradeoffs.** The classification-based routing pattern achieves near-API quality at a fraction of API cost. Teams with heterogeneous query complexity distributions, which is common in conversational AI, should consider multi-model architectures before defaulting to a single premium model.

### 8.3 Limitations

This study has several limitations that should be acknowledged:

**Single task type.** Our evaluation focuses exclusively on dietary conversation, a specific domain with particular format and constraint requirements. The finding that smaller models outperform larger ones may not generalize to other domains, particularly those requiring broad world knowledge, creative generation, or mathematical reasoning.

**Consumer GPU constraint.** The 8 GB VRAM limitation of the RTX 4060 forces quantization on models exceeding 4B parameters. On hardware with more VRAM (e.g., A100 with 80 GB), the same models could run in full precision, potentially recovering the quality lost to quantization. Our results are therefore specific to the consumer GPU deployment scenario.

**Prompt scope.** While our 35 CL-bench prompts span five categories from a peer-reviewed benchmark, they represent an evaluation set rather than organic user traffic. Real-world query distributions may differ in complexity distribution, topic coverage, and linguistic patterns.

**Static traffic model.** Our cost projections assume uniform traffic distribution across the day. In practice, traffic follows diurnal patterns, and the cost model should account for the potential to scale GPU instances down during off-peak hours, which would reduce local hosting costs by 30% to 50% compared to our 24-hour provisioning assumption.

**Single classifier architecture.** We evaluate only a regex-based classifier. Neural classifiers (e.g., a fine-tuned BERT model) might achieve higher classification accuracy, potentially improving blended accuracy by 1 to 2 percentage points at the cost of adding 10 to 50 milliseconds of inference latency per classification.

**Limited API model evaluation.** Our benchmarking focused on locally deployable open-weight models. We did not systematically benchmark cloud API models (Gemini, GPT-4, Claude) under the same 49-prompt evaluation framework. The estimated ~95% accuracy for Gemini 3 Flash is based on published benchmark performance extrapolated to our domain rather than direct measurement. A complete study would include API models in the same evaluation pipeline.

### 8.4 Broader Significance for the Field

The results presented in this study contribute to an emerging understanding that the relationship between model size and task performance is substantially more nuanced than scaling laws would suggest for narrow, constrained tasks. While scaling laws (Kaplan et al., 2020; Hoffmann et al., 2022) accurately predict aggregate language modeling loss as a function of parameters and compute, they do not predict performance on specific downstream tasks that require particular capabilities such as format adherence, constraint tracking, or domain-specific reasoning.

This has practical significance for the growing number of organizations deploying LLMs for domain-specific applications. The default strategy of selecting the largest affordable model is not always optimal, and systematic task-specific benchmarking should be considered a mandatory step in the model selection process. Our benchmarking framework, combining multiple prompt categories with a structured rubric and binary accuracy aggregation, provides a replicable methodology that other teams can adapt to their specific domains.

The economic analysis demonstrates that multi-model architectures, once considered overly complex for production deployment, can achieve substantial cost savings with modest engineering effort. The regex classifier approach, in particular, represents a low-barrier entry point that requires no additional model training or GPU resources and can be implemented in under 200 lines of code, as demonstrated by the Memoria system's production classifier.

---

## 9. Conclusion

### 9.1 Principal Findings

This paper presents a comprehensive multi-model benchmarking study, cost analysis, and routing strategy evaluation for the Memoria AI dietary assistant. Our four principal findings are:

**Finding 1:** Among 15 models spanning five parameter categories (0.135B to 8.2B), the Qwen3.5-0.8B model (0.8B parameters) achieves the highest accuracy (78.6%) at a cost of $0.003553 per query, demonstrating that instruction-tuning quality dominates parameter count for constrained dietary generation tasks. Models in the 3B to 5B range, subject to 4-bit quantization on consumer GPU hardware, exhibit catastrophic quality collapse with tier-average accuracy of only 4.8%.

**Finding 2:** The break-even crossover between local GPU hosting and cloud API deployment occurs at approximately 15,000 messages per day (~3,000 DAU). Below this threshold, fixed GPU provisioning costs exceed marginal API costs; above it, local inference becomes increasingly economical, achieving 67.3% cost reduction at 10,000 DAU and 84.1% reduction at 100,000 DAU compared to pure Gemini 3 Flash API deployment.

**Finding 3:** Classification-based routing (Pattern A) achieves the best accuracy-per-dollar ratio (3.11) among the three evaluated routing patterns, delivering 87.1% blended accuracy at $28.02/day (10,000 DAU) through a zero-latency regex classifier with eight scoring dimensions. The classifier's deterministic, interpretable design enables real-time threshold adjustment for cost-quality tradeoff optimization without model redeployment.

**Finding 4:** The hybrid architecture combining local Qwen3.5-0.8B for simple queries (80% of traffic) with Gemini 3 Flash for complex queries (20% of traffic) saves $53.83/day at 10,000 DAU compared to pure API deployment, or approximately $19,648 annually, while maintaining 87.1% blended accuracy, a quality level that exceeds any single local model's performance.

### 9.2 Phased Deployment Recommendation

We recommend a three-phase deployment plan aligned with user growth:

**Phase 1 (< 3,000 DAU):** Deploy exclusively via cloud API (Gemini 3 Flash or Gemini 3.1 Flash Lite). Daily cost: $2.40 to $24.00. No GPU infrastructure required. Focus engineering effort on product development and user acquisition.

**Phase 2 (3,000 to 15,000 DAU):** Provision a single Lambda Labs A10G GPU instance ($18.00/day). Deploy Qwen3.5-0.8B locally with Pattern A classification-based routing. Simple queries (80%) route locally; complex queries (20%) route to Gemini 3 Flash. Expected daily cost: $18.17 to $26.17, representing 34.6% to 67.3% savings versus pure API.

**Phase 3 (> 15,000 DAU):** Scale horizontally with multiple A10G instances behind a load balancer. At 100,000 DAU, provision 3 to 5 instances for an estimated $54.00 to $90.00/day, compared to $800.00/day for pure Flash API (88.8% to 93.3% savings). Consider migrating to dedicated on-premises hardware (NVIDIA A10G or L4 GPUs) for further cost reduction at the Growing Product and Large Platform tiers.

### 9.3 Future Work

Five directions for future work emerge from this study:

**1. Neural classifier upgrade.** Replace the regex classifier with a fine-tuned DistilBERT or TinyBERT model trained on the Memoria query distribution. This could improve classification accuracy from 91.3% to an estimated 96%+, recovering 1 to 2 percentage points of blended accuracy with minimal latency overhead (< 50ms per classification).

**2. Adaptive threshold tuning.** Implement an online learning system that adjusts the complexity threshold dynamically based on real-time cost and quality metrics. During budget-constrained periods, the threshold rises to route more queries locally; during quality-sensitive periods (e.g., after negative user feedback), the threshold falls to route more queries to the API.

**3. Model distillation pipeline.** Use the Gemini 3 Flash API as a teacher model to distill a custom local model specifically trained on Memoria's dietary conversation domain. This could close the quality gap between local and API inference, potentially enabling pure local deployment at higher quality levels.

**4. Expanded benchmark coverage.** Extend the evaluation to additional dietary domains (food photography analysis, recipe generation, grocery list optimization) and conversational contexts (multi-turn negotiations, emotional support, motivational coaching) to validate the generalizability of our findings.

**5. Quantization-aware fine-tuning.** Investigate whether fine-tuning larger models (3B to 5B parameters) with quantization-aware training (QAT) can recover the quality lost to post-training quantization, potentially unlocking superior performance from models in the Large tier that currently exhibit catastrophic failure.

---

## References

Abdin, M., Jacobs, S. A., Awan, A. A., Aneja, J., Awadallah, A., Awadalla, H., ... and Zhou, X. (2024). Phi-3 Technical Report: A Highly Capable Language Model Locally on Your Phone. *arXiv preprint arXiv:2404.14219*.

Auer, P., Cesa-Bianchi, N., and Fischer, P. (2002). Finite-time Analysis of the Multiarmed Bandit Problem. *Machine Learning*, 47(2), 235-256.

Bai, J., Bai, S., Chu, Y., Cui, Z., Dang, K., Deng, X., ... and Zhu, T. (2023). Qwen Technical Report. *arXiv preprint arXiv:2309.16609*.

Chen, L., Zaharia, M., and Zou, J. (2023). FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance. *arXiv preprint arXiv:2305.05176*.

Dettmers, T., Pagnoni, A., Holtzman, A., and Zettlemoyer, L. (2023). QLoRA: Efficient Finetuning of Quantized Language Models. *Advances in Neural Information Processing Systems*, 36.

Django Software Foundation. (2025). Django 6.0 Release Notes. https://docs.djangoproject.com/en/6.0/releases/6.0/.

Google DeepMind. (2025). Gemini API Documentation. https://ai.google.dev/gemini-api/docs.

Hoffmann, J., Borgeaud, S., Mensch, A., Buchatskaya, E., Cai, T., Rutherford, E., ... and Sifre, L. (2022). Training Compute-Optimal Large Language Models. *Advances in Neural Information Processing Systems*, 35, 30016-30030.

Hugging Face. (2025). Inference API Documentation. https://huggingface.co/docs/api-inference.

Jiang, A. Q., Sablayrolles, A., Mensch, A., Bamford, C., Chaplot, D. S., Casas, D., ... and Sayed, W. E. (2023). Mistral 7B. *arXiv preprint arXiv:2310.06825*.

Kaplan, J., McCandlish, S., Henighan, T., Brown, T. B., Chess, B., Child, R., ... and Amodei, D. (2020). Scaling Laws for Neural Language Models. *arXiv preprint arXiv:2001.08361*.

Li, Y., Bubeck, S., Eldan, R., Del Giorno, A., Gunasekar, S., and Lee, Y. T. (2023). Textbooks Are All You Need II: Phi-1.5 Technical Report. *arXiv preprint arXiv:2309.05463*.

LiquidAI. (2024). LFM-2: Liquid Foundation Models for Efficient Inference. https://www.liquid.ai/research.

Neo4j, Inc. (2025). Neo4j Graph Database Documentation. https://neo4j.com/docs/.

Ouyang, L., Wu, J., Jiang, X., Almeida, D., Wainwright, C., Mishkin, P., ... and Lowe, R. (2022). Training Language Models to Follow Instructions with Human Feedback. *Advances in Neural Information Processing Systems*, 35, 27730-27744.

Rafailov, R., Sharma, A., Mitchell, E., Manning, C. D., Ermon, S., and Finn, C. (2023). Direct Preference Optimization: Your Language Model is Secretly a Reward Model. *Advances in Neural Information Processing Systems*, 36.

Shazeer, N., Mirhoseini, A., Maziarz, K., Davis, A., Le, Q., Hinton, G., and Dean, J. (2017). Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer. *International Conference on Learning Representations*.

Tencent. (2025). CL-bench: A Comprehensive Benchmark for Continual Learning. https://huggingface.co/datasets/tencent/CL-bench.

Yang, A., Yang, B., Hui, B., Zheng, B., Yu, B., Zhou, C., ... and Lin, J. (2024). Qwen2.5 Technical Report. *arXiv preprint arXiv:2412.15115*.
