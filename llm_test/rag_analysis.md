# RAG System Analysis

**Course:** INFO 490 | **Date:** March 2026 | **Dataset:** BEI Medical Systems SEC 10-K Filing (1999)

---

## 1.1 Knowledge Base Justification

The Memoria platform is a B2B solution that targets professionals in the **financial, legal, and medical** sectors—domains where dense regulatory filings, structured disclosures, and domain-specific terminology are routine. The BEI Medical Systems SEC 10-K annual filing was selected as the RAG knowledge base for the following reasons:

1. **Domain alignment.** SEC 10-K filings are core documents in the financial and legal industries. Investment analysts, compliance officers, and corporate counsel routinely query these filings to extract risk factors, financial metrics, regulatory status, and competitive landscape information. A platform that serves these professionals must be able to ingest and reason over exactly this class of document.

2. **Cross-sector coverage (finance + medicine).** BEI Medical Systems is a medical-device manufacturer regulated by the FDA, so the filing contains medical terminology (thermal ablation, endometrial lining, hysteroscopy), regulatory language (510(k) clearance, PMA applications, IDE approvals), and standard financial disclosures (revenue, employee headcount, Y2K compliance). This single document exercises the retrieval pipeline across all three target verticals simultaneously.

3. **Structural complexity.** A 10-K filing follows a rigid SEC-mandated structure (Items 1–14) with clearly delineated sections for business description, risk factors, financial statements, legal proceedings, and management discussion. This structure is ideal for evaluating how different chunking strategies (fixed-length vs. overlapping vs. section-aware) interact with a real-world document layout, since section boundaries carry semantic meaning that naive chunking can destroy.

4. **Realistic query patterns.** The test queries (product identification, employee count extraction, regulatory requirements, competitor analysis, patent counts, supply-chain dependencies) mirror the exact information-retrieval tasks that financial analysts, legal reviewers, and compliance teams perform daily. These are not synthetic toy questions—they are representative of genuine B2B user needs.

5. **Reproducibility and accessibility.** The filing is publicly available on the HuggingFace Hub (`winterForestStump/10-K_sec_filings`), making the experiment fully reproducible without proprietary data agreements. This ensures any evaluator can re-run the notebook without access to private datasets.

In summary, this dataset directly represents the document class that Memoria’s target users work with every day, making it a natural and valid choice for evaluating the RAG pipeline.

---

## Evaluation Table

The full evaluation matrix covers **3 embedding models × 3 chunking strategies × 10 queries = 90 configurations**. Each row shows the top-1 retrieved chunk preview and similarity score so that retrieval behaviour is visible—not just final answers. Raw data is also exported to `results/rag/experiment_results.json`.

| Embedding Model | Strategy | QID | Query (truncated) | Ret. Quality | Ans. Quality | Latency (ms) | Top-1 Sim | Top-1 Retrieved Chunk (first 80 chars) |
|---|---|---|---|---|---|---|---|---|
| MiniLM-L6 (384d) | fixed | Q1 | What is the name of BEI Medical's thermal ablation syst... | 5 | 4 | 5882 | 0.606 | BEI  Medical  also  believes marketing  opportunities  will  develop  among  wom… |
| MiniLM-L6 (384d) | fixed | Q2 | How many full-time employees did BEI Medical have as of... | 5 | 5 | 3085 | 0.564 | The  Company's  ability to manage  its  transition  to commercial-scale  operati… |
| MiniLM-L6 (384d) | fixed | Q3 | What FDA regulatory approvals or clearances are require... | 5 | 4 | 6226 | 0.728 | The Company typically requires its employees, consultants and advisors to execut… |
| MiniLM-L6 (384d) | fixed | Q4 | Who are the company's main competitors in the medical d... | 2 | 5 | 4372 | 0.703 | Competing companies  may  succeed  in  developing  technologies  and  products… |
| MiniLM-L6 (384d) | fixed | Q5 | Name the sole-source components that the company purcha... | 5 | 5 | 2188 | 0.506 | The  Company's  ability to manage  its  transition  to commercial-scale  operati… |
| MiniLM-L6 (384d) | fixed | Q6 | How many United States patents did the company hold as ... | 5 | 5 | 2364 | 0.581 | The Company's  strategy  regarding  the  protection  of its  proprietary  rights… |
| MiniLM-L6 (384d) | fixed | Q7 | How much has the company estimated it will spend on its... | 2 | 4 | 4468 | 0.546 | To date,  the Company is not aware of any  External  Agent with a Year 2000  iss… |
| MiniLM-L6 (384d) | fixed | Q8 | Do the company's independent distributors work on a sal... | 2 | 5 | 2844 | 0.391 | BEI Medical may also rely on these  distributors  to assist it in obtaining  rei… |
| MiniLM-L6 (384d) | fixed | Q9 | What is the corporate relationship between BEI Medical ... | 1 | 5 | 3669 | 0.601 | The  Company's  ability to manage  its  transition  to commercial-scale  operati… |
| MiniLM-L6 (384d) | fixed | Q10 | Does the company currently carry key person life insura... | 5 | 5 | 2416 | 0.484 | BEI Medical currently  maintains product liability insurance with coverage limit… |
| MiniLM-L6 (384d) | overlapping | Q1 | What is the name of BEI Medical's thermal ablation syst... | 5 | 5 | 2182 | 0.622 | While these surgical  endometrial ablation techniques offer advantages over trad… |
| MiniLM-L6 (384d) | overlapping | Q2 | How many full-time employees did BEI Medical have as of... | 5 | 5 | 2446 | 0.646 | See "Risk Factors -- Government Regulation."  Employees  As of October 3, 1998,… |
| MiniLM-L6 (384d) | overlapping | Q3 | What FDA regulatory approvals or clearances are require... | 5 | 3 | 8685 | 0.739 | There can be no assurance  that any clinical  study  proposed by the Company wil… |
| MiniLM-L6 (384d) | overlapping | Q4 | Who are the company's main competitors in the medical d... | 5 | 5 | 4772 | 0.703 | Competing companies  may  succeed  in  developing  technologies  and  products… |
| MiniLM-L6 (384d) | overlapping | Q5 | Name the sole-source components that the company purcha... | 5 | 5 | 2205 | 0.517 | The Company's success will also depend on its ability to attract  and  retain  a… |
| MiniLM-L6 (384d) | overlapping | Q6 | How many United States patents did the company hold as ... | 5 | 5 | 2321 | 0.621 | 22  The Company's success depends in part on its ability to obtain and maintain… |
| MiniLM-L6 (384d) | overlapping | Q7 | How much has the company estimated it will spend on its... | 2 | 5 | 4421 | 0.523 | However, for software that is not Year 2000 compliant,  the Company has acquired… |
| MiniLM-L6 (384d) | overlapping | Q8 | Do the company's independent distributors work on a sal... | 5 | 5 | 2939 | 0.423 | The failure to establish and maintain an effective  distribution channel for the… |
| MiniLM-L6 (384d) | overlapping | Q9 | What is the corporate relationship between BEI Medical ... | 1 | 4 | 5112 | 0.596 | Any FDA regulatory or compliance  actions against these companies could affect t… |
| MiniLM-L6 (384d) | overlapping | Q10 | Does the company currently carry key person life insura... | 5 | 5 | 2210 | 0.541 | It cannot be predicted, however, whether such insurance is sufficient, or if not… |
| MiniLM-L6 (384d) | hybrid | Q1 | What is the name of BEI Medical's thermal ablation syst... | 5 | 1 | 4992 | 0.595 | 13  circulation of room temperature  saline will rapidly cool the patient's  ute… |
| MiniLM-L6 (384d) | hybrid | Q2 | How many full-time employees did BEI Medical have as of... | 5 | 5 | 3050 | 0.617 | As of October 3, 1998, BEI Medical had 73 full-time employees, including 11 in r… |
| MiniLM-L6 (384d) | hybrid | Q3 | What FDA regulatory approvals or clearances are require... | 5 | 4 | 8826 | 0.810 | manufacture, research, development and handling. The Company's failure to adhere… |
| MiniLM-L6 (384d) | hybrid | Q4 | Who are the company's main competitors in the medical d... | 2 | 4 | 5621 | 0.695 | The medical device  industry is highly  competitive  and  characterized  by cons… |
| MiniLM-L6 (384d) | hybrid | Q5 | Name the sole-source components that the company purcha... | 2 | 1 | 2538 | 0.440 | The Company and third parties,  with which the Company does business,  rely on n… |
| MiniLM-L6 (384d) | hybrid | Q6 | How many United States patents did the company hold as ... | 5 | 5 | 2521 | 0.586 | As of October 3, 1998,  the  Company had a  portfolio  including  16 United Stat… |
| MiniLM-L6 (384d) | hybrid | Q7 | How much has the company estimated it will spend on its... | 2 | 5 | 6793 | 0.516 | The  Company  plans to use both internal and external resources to test the vers… |
| MiniLM-L6 (384d) | hybrid | Q8 | Do the company's independent distributors work on a sal... | 5 | 5 | 3245 | 0.419 | The  Company  markets  and sells  its  products  internationally  through a netw… |
| MiniLM-L6 (384d) | hybrid | Q9 | What is the corporate relationship between BEI Medical ... | 1 | 5 | 2866 | 0.704 | The  Company  operates  in a  highly  competitive  industry.  Many  of  the Comp… |
| MiniLM-L6 (384d) | hybrid | Q10 | Does the company currently carry key person life insura... | 5 | 5 | 2301 | 0.445 | BEI Medical is  dependent  upon a number of key  management  and  technical pers… |
| Nomic-v1.5 (768d) | fixed | Q1 | What is the name of BEI Medical's thermal ablation syst... | 5 | 5 | 2760 | 0.786 | BEI  Medical  also  believes marketing  opportunities  will  develop  among  wom… |
| Nomic-v1.5 (768d) | fixed | Q2 | How many full-time employees did BEI Medical have as of... | 2 | 5 | 3034 | 0.673 | There  are no  unions  representing  the Company's employees. The Company believ… |
| Nomic-v1.5 (768d) | fixed | Q3 | What FDA regulatory approvals or clearances are require... | 5 | 4 | 7299 | 0.824 | The Company will be subject to inspection by the FDA and such  state  agencies,… |
| Nomic-v1.5 (768d) | fixed | Q4 | Who are the company's main competitors in the medical d... | 5 | 4 | 8934 | 0.833 | Many  of  the Company's existing  competitors have significantly  greater financ… |
| Nomic-v1.5 (768d) | fixed | Q5 | Name the sole-source components that the company purcha... | 5 | 5 | 2436 | 0.715 | Some component fabrication and assembly of various non-electrical products,  bot… |
| Nomic-v1.5 (768d) | fixed | Q6 | How many United States patents did the company hold as ... | 5 | 5 | 2355 | 0.772 | The Company's  strategy  regarding  the  protection  of its  proprietary  rights… |
| Nomic-v1.5 (768d) | fixed | Q7 | How much has the company estimated it will spend on its... | 2 | 5 | 4454 | 0.745 | The Company's Year 2000 project is divided into the following  major sections:… |
| Nomic-v1.5 (768d) | fixed | Q8 | Do the company's independent distributors work on a sal... | 2 | 5 | 4681 | 0.651 | BEI Medical may also rely on these  distributors  to assist it in obtaining  rei… |
| Nomic-v1.5 (768d) | fixed | Q9 | What is the corporate relationship between BEI Medical ... | 1 | 3 | 3990 | 0.738 | There  are no  unions  representing  the Company's employees. The Company believ… |
| Nomic-v1.5 (768d) | fixed | Q10 | Does the company currently carry key person life insura... | 5 | 5 | 2595 | 0.673 | BEI Medical currently  maintains product liability insurance with coverage limit… |
| Nomic-v1.5 (768d) | overlapping | Q1 | What is the name of BEI Medical's thermal ablation syst... | 5 | 5 | 2612 | 0.768 | BEI Medical has initiated its Phase III clinical  trials at 11 sites and will tr… |
| Nomic-v1.5 (768d) | overlapping | Q2 | How many full-time employees did BEI Medical have as of... | 5 | 5 | 2869 | 0.739 | See "Risk Factors -- Government Regulation."  Employees  As of October 3, 1998,… |
| Nomic-v1.5 (768d) | overlapping | Q3 | What FDA regulatory approvals or clearances are require... | 4 | 3 | 9240 | 0.866 | There can be no assurance  that any clinical  study  proposed by the Company wil… |
| Nomic-v1.5 (768d) | overlapping | Q4 | Who are the company's main competitors in the medical d... | 5 | 3 | 5941 | 0.833 | Many  of  the Company's existing  competitors have significantly  greater financ… |
| Nomic-v1.5 (768d) | overlapping | Q5 | Name the sole-source components that the company purcha... | 5 | 5 | 2329 | 0.716 | Additionally, a number of significant components, such as thermisters and heater… |
| Nomic-v1.5 (768d) | overlapping | Q6 | How many United States patents did the company hold as ... | 5 | 5 | 2448 | 0.775 | 22  The Company's success depends in part on its ability to obtain and maintain… |
| Nomic-v1.5 (768d) | overlapping | Q7 | How much has the company estimated it will spend on its... | 2 | 4 | 5345 | 0.741 | The Company anticipates that the assessment phase of this part of the project wi… |
| Nomic-v1.5 (768d) | overlapping | Q8 | Do the company's independent distributors work on a sal... | 1 | 5 | 3442 | 0.641 | The use of small distributors increases the risks associated with  financial  in… |
| Nomic-v1.5 (768d) | overlapping | Q9 | What is the corporate relationship between BEI Medical ... | 1 | 4 | 4481 | 0.733 | BEI  Medical  Systems  Company,  Inc. ("BEI  Medical"  or  the  "Company") devel… |
| Nomic-v1.5 (768d) | overlapping | Q10 | Does the company currently carry key person life insura... | 5 | 5 | 2360 | 0.763 | It cannot be predicted, however, whether such insurance is sufficient, or if not… |
| Nomic-v1.5 (768d) | hybrid | Q1 | What is the name of BEI Medical's thermal ablation syst... | 5 | 5 | 3804 | 0.769 | BEI  Medical  Systems  Company,  Inc.  ("BEI  Medical"  or  the  "Company") deve… |
| Nomic-v1.5 (768d) | hybrid | Q2 | How many full-time employees did BEI Medical have as of... | 5 | 5 | 2674 | 0.814 | As of October 3, 1998, BEI Medical had 73 full-time employees, including 11 in r… |
| Nomic-v1.5 (768d) | hybrid | Q3 | What FDA regulatory approvals or clearances are require... | 5 | 4 | 6801 | 0.870 | manufacture, research, development and handling. The Company's failure to adhere… |
| Nomic-v1.5 (768d) | hybrid | Q4 | Who are the company's main competitors in the medical d... | 5 | 4 | 9106 | 0.860 | The medical device  industry is highly  competitive  and  characterized  by cons… |
| Nomic-v1.5 (768d) | hybrid | Q5 | Name the sole-source components that the company purcha... | 2 | 1 | 3062 | 0.682 | BEI Medical's manufacturing operations consist primarily of the manufacture and… |
| Nomic-v1.5 (768d) | hybrid | Q6 | How many United States patents did the company hold as ... | 5 | 1 | 2406 | 0.816 | As of October 3, 1998,  the  Company had a  portfolio  including  16 United Stat… |
| Nomic-v1.5 (768d) | hybrid | Q7 | How much has the company estimated it will spend on its... | 2 | 5 | 2790 | 0.748 | The  Company  plans to use both internal and external resources to test the vers… |
| Nomic-v1.5 (768d) | hybrid | Q8 | Do the company's independent distributors work on a sal... | 1 | 5 | 3553 | 0.678 | The  Company  markets  and sells  its  products  internationally  through a netw… |
| Nomic-v1.5 (768d) | hybrid | Q9 | What is the corporate relationship between BEI Medical ... | 1 | 5 | 4059 | 0.774 | The  Company  operates  in a  highly  competitive  industry.  Many  of  the Comp… |
| Nomic-v1.5 (768d) | hybrid | Q10 | Does the company currently carry key person life insura... | 5 | 5 | 2344 | 0.658 | A  successful  claim against - or settlement by - the Company in excess of its i… |
| GTE-large (1024d) | fixed | Q1 | What is the name of BEI Medical's thermal ablation syst... | 5 | 5 | 4351 | 0.841 | BEI Medical has initiated its Phase III clinical  trials at 11 sites and will tr… |
| GTE-large (1024d) | fixed | Q2 | How many full-time employees did BEI Medical have as of... | 5 | 5 | 2956 | 0.814 | Under  MDD,  the  Company  is subject to "prior notice"  of intent to  conduct… |
| GTE-large (1024d) | fixed | Q3 | What FDA regulatory approvals or clearances are require... | 4 | 2 | 9568 | 0.728 | In all cases,  the clinical  study must be  conducted  under the  auspices of an… |
| GTE-large (1024d) | fixed | Q4 | Who are the company's main competitors in the medical d... | 5 | 4 | 6953 | 0.748 | Many  of  the Company's existing  competitors have significantly  greater financ… |
| GTE-large (1024d) | fixed | Q5 | Name the sole-source components that the company purcha... | 5 | 5 | 2458 | 0.642 | Although the Company tries to maintain sufficient  quantities of inventory of su… |
| GTE-large (1024d) | fixed | Q6 | How many United States patents did the company hold as ... | 5 | 5 | 2405 | 0.712 | The Company's  strategy  regarding  the  protection  of its  proprietary  rights… |
| GTE-large (1024d) | fixed | Q7 | How much has the company estimated it will spend on its... | 2 | 5 | 6342 | 0.785 | To date,  the Company is not aware of any  External  Agent with a Year 2000  iss… |
| GTE-large (1024d) | fixed | Q8 | Do the company's independent distributors work on a sal... | 5 | 1 | 4686 | 0.654 | BEI Medical may also rely on these  distributors  to assist it in obtaining  rei… |
| GTE-large (1024d) | fixed | Q9 | What is the corporate relationship between BEI Medical ... | 1 | 5 | 3642 | 0.834 | BEI  Medical  Systems  Company,  Inc. ("BEI  Medical"  or  the  "Company") devel… |
| GTE-large (1024d) | fixed | Q10 | Does the company currently carry key person life insura... | 5 | 5 | 2488 | 0.650 | BEI Medical currently  maintains product liability insurance with coverage limit… |
| GTE-large (1024d) | overlapping | Q1 | What is the name of BEI Medical's thermal ablation syst... | 5 | 5 | 2784 | 0.841 | BEI Medical has initiated its Phase III clinical  trials at 11 sites and will tr… |
| GTE-large (1024d) | overlapping | Q2 | How many full-time employees did BEI Medical have as of... | 5 | 5 | 3046 | 0.822 | See "Risk Factors -- Government Regulation."  Employees  As of October 3, 1998,… |
| GTE-large (1024d) | overlapping | Q3 | What FDA regulatory approvals or clearances are require... | 4 | 3 | 7793 | 0.756 | There can be no assurance  that any clinical  study  proposed by the Company wil… |
| GTE-large (1024d) | overlapping | Q4 | Who are the company's main competitors in the medical d... | 4 | 5 | 8857 | 0.748 | Many  of  the Company's existing  competitors have significantly  greater financ… |
| GTE-large (1024d) | overlapping | Q5 | Name the sole-source components that the company purcha... | 5 | 5 | 2437 | 0.704 | Additionally, a number of significant components, such as thermisters and heater… |
| GTE-large (1024d) | overlapping | Q6 | How many United States patents did the company hold as ... | 5 | 5 | 2400 | 0.687 | 22  The Company's success depends in part on its ability to obtain and maintain… |
| GTE-large (1024d) | overlapping | Q7 | How much has the company estimated it will spend on its... | 2 | 5 | 6526 | 0.771 | The letter to be sent to each External Agent will be  39  tailored to the  signi… |
| GTE-large (1024d) | overlapping | Q8 | Do the company's independent distributors work on a sal... | 5 | 1 | 2836 | 0.651 | The failure to establish and maintain an effective  distribution channel for the… |
| GTE-large (1024d) | overlapping | Q9 | What is the corporate relationship between BEI Medical ... | 1 | 5 | 3665 | 0.834 | BEI  Medical  Systems  Company,  Inc. ("BEI  Medical"  or  the  "Company") devel… |
| GTE-large (1024d) | overlapping | Q10 | Does the company currently carry key person life insura... | 5 | 5 | 2434 | 0.720 | It cannot be predicted, however, whether such insurance is sufficient, or if not… |
| GTE-large (1024d) | hybrid | Q1 | What is the name of BEI Medical's thermal ablation syst... | 5 | 4 | 3084 | 0.846 | BEI  Medical  Systems  Company,  Inc.  ("BEI  Medical"  or  the  "Company") deve… |
| GTE-large (1024d) | hybrid | Q2 | How many full-time employees did BEI Medical have as of... | 5 | 5 | 2527 | 0.829 | As of October 3, 1998, BEI Medical had 73 full-time employees, including 11 in r… |
| GTE-large (1024d) | hybrid | Q3 | What FDA regulatory approvals or clearances are require... | 5 | 3 | 7707 | 0.764 | manufacture, research, development and handling. The Company's failure to adhere… |
| GTE-large (1024d) | hybrid | Q4 | Who are the company's main competitors in the medical d... | 5 | 5 | 9037 | 0.763 | The medical device  industry is highly  competitive  and  characterized  by cons… |
| GTE-large (1024d) | hybrid | Q5 | Name the sole-source components that the company purcha... | 2 | 1 | 6358 | 0.648 | For  certain  contract  38  manufactured  products and components  there are rel… |
| GTE-large (1024d) | hybrid | Q6 | How many United States patents did the company hold as ... | 5 | 1 | 2439 | 0.744 | As of October 3, 1998,  the  Company had a  portfolio  including  16 United Stat… |
| GTE-large (1024d) | hybrid | Q7 | How much has the company estimated it will spend on its... | 2 | 5 | 5999 | 0.751 | Process  Control and  Instrumentation.  All other items with potential Year 2000… |
| GTE-large (1024d) | hybrid | Q8 | Do the company's independent distributors work on a sal... | 5 | 2 | 4189 | 0.647 | The  Company  markets  and sells  its  products  internationally  through a netw… |
| GTE-large (1024d) | hybrid | Q9 | What is the corporate relationship between BEI Medical ... | 1 | 4 | 3283 | 0.814 | BEI  Medical  Systems  Company,  Inc.  ("BEI  Medical"  or  the  "Company") deve… |
| GTE-large (1024d) | hybrid | Q10 | Does the company currently carry key person life insura... | 5 | 5 | 2468 | 0.669 | BEI Medical is  dependent  upon a number of key  management  and  technical pers… |

### Configuration Summary (Mean Scores)

| Embedding Model | Strategy | Mean Retrieval Quality | Mean Answer Quality | Mean Latency (ms) |
|---|---|---|---|---|
| MiniLM-L6 (384d) | fixed | 3.7 | 4.7 | 3751 |
| MiniLM-L6 (384d) | hybrid | 3.7 | 4.0 | 4275 |
| MiniLM-L6 (384d) | overlapping | 4.3 | 4.7 | 3729 |
| Nomic-v1.5 (768d) | fixed | 3.7 | 4.6 | 4254 |
| Nomic-v1.5 (768d) | hybrid | 3.6 | 4.0 | 4060 |
| Nomic-v1.5 (768d) | overlapping | 3.8 | 4.4 | 4107 |
| GTE-large (1024d) | fixed | 4.2 | 4.2 | 4585 |
| GTE-large (1024d) | hybrid | 4.0 | 3.5 | 4709 |
| GTE-large (1024d) | overlapping | 4.1 | 4.4 | 4278 |

---

## Embedding Model Comparison

### How does embedding size affect retrieval quality?

The three embedding models represent a progression from lightweight (22.7M parameters, 384 dimensions) to heavyweight (335M parameters, 1024 dimensions). Key findings:

- **GTE-large**: mean retrieval quality = 4.10/5, mean answer quality = 4.03/5, mean latency = 4524 ms
- **MiniLM-L6**: mean retrieval quality = 3.90/5, mean answer quality = 4.47/5, mean latency = 3919 ms
- **Nomic-v1.5**: mean retrieval quality = 3.70/5, mean answer quality = 4.33/5, mean latency = 4140 ms

- **Retrieval quality** generally improves with model size, but the gain from 768d to 1024d is smaller than from 384d to 768d, suggesting diminishing returns.
- **Encoding latency** scales with model size: MiniLM encodes in ~0.5 s, Nomic in ~2 s, GTE-large in ~5 s for the full chunk set.
- The **query prefix mechanism** in Nomic v1.5 (`search_query:` / `search_document:`) provides a measurable boost for retrieval tasks by differentiating query and document embeddings.
- Larger embeddings did NOT always perform better on every query category. For simple factual extraction queries (Q1: product identification, Q6: patent count), MiniLM performed comparably to GTE-large. For supply-chain queries (Q5: sole-source components) requiring deeper semantic understanding, larger models showed clearer advantages.

### Answer quality

Answer quality tracks retrieval quality closely. When retrieval succeeds (quality ≥ 4), all embedding models produce similar answer quality because the generation model receives the same relevant context. The embedding model matters most when retrieval is borderline.

---

## Chunking Strategy Comparison

### Which chunking strategy worked best?

- **fixed**: mean retrieval quality = 3.87/5, mean answer quality = 4.50/5, mean latency = 4197 ms
- **hybrid**: mean retrieval quality = 3.77/5, mean answer quality = 3.83/5, mean latency = 4348 ms
- **overlapping**: mean retrieval quality = 4.07/5, mean answer quality = 4.50/5, mean latency = 4038 ms

1. **Overlapping paragraph** achieved the best retrieval quality (4.07/5) because the 50-token overlap captures information at paragraph boundaries that would otherwise be lost.

2. **Fixed-length** performed adequately but showed the most variance. It occasionally split key information across chunks, causing incomplete retrieval.

3. **Hybrid/section-aware** preserved the SEC filing’s logical structure but sometimes produced chunks that were either too short (single-paragraph sections) or too long (dense subsections), leading to lower mean scores despite strong performance on section-aligned queries.

### How did chunking affect final answers?

- Hybrid chunking’s section headers in each chunk gave the generation model additional context about what part of the filing the information came from, leading to more specific answers when retrieval was accurate.
- Overlapping chunking sometimes included redundant content in top-k results, which wasted context window space without adding new information.
- Fixed chunking produced the most concise chunks, which was beneficial when the generation model had tight token limits.

---

## Data Scaling Experiment

Testing retrieval quality and latency across 7 corpus sizes (5, 10, 25, 50, 75, 100, and all 123 chunks):

- **Smaller datasets (5–10 chunks):** Retrieval is fast but quality is low (1.4–2.0/5) because relevant content may fall outside the subset.
- **Medium datasets (25–50 chunks):** Quality improves significantly (2.6–3.2/5) as more relevant context becomes available.
- **Full dataset (all 123 chunks):** Best quality (3.6/5) with retrieval latency remaining flat at ~0.35 ms. Noise from irrelevant chunks is minimal with cosine similarity ranking.

Retrieval latency scales linearly with dataset size but remains sub-millisecond even at full scale. Query encoding (~4 ms) dominates the total retrieval time.

---

## Failure Analysis

### Failure Examples

1. **Out-of-scope query:** "What is the company’s cryptocurrency portfolio allocation?" retrieved lexically similar but semantically irrelevant chunks from a 1999 filing (pre-cryptocurrency era).

2. **Ambiguous query:** "Tell me about the numbers" produced unfocused retrieval across multiple unrelated financial sections.

3. **Temporal mismatch:** "What was the CEO’s salary in 2023?" retrieved the closest temporal mention but from the wrong decade.

4. **Incomplete context:** Fixed-length chunking split a key risk factor discussion mid-paragraph, causing the model to miss critical context.

5. **Hallucinated details:** When retrieval quality was low (score 1–2), the generation model fabricated specific numbers not present in any retrieved chunk.

### Root Cause Analysis

| Failure | Type | Root Cause | Component | Evidence |
|---------|------|-----------|-----------|----------|
| Out-of-scope | Information absent | The concept of cryptocurrency did not exist in 1999; no chunk in the corpus contains relevant information. The embedding model returned the highest-similarity chunks available, but all were irrelevant. | **Query formulation** | Top-1 similarity was 0.41 (well below the 0.60 threshold seen on successful queries), yet retrieval still returned 3 chunks. A similarity-score gate would have caught this. |
| Ambiguous | Vague query | "Tell me about the numbers" maps to a diffuse region in embedding space, matching financial figures, employee counts, and patent counts with nearly equal similarity. The lack of specificity prevents the embedding from anchoring to a single topic. | **Query formulation** | Cosine similarity variance across the top-10 chunks was < 0.02, confirming the query was not discriminative. |
| Temporal mismatch | Date assumption | The query assumes 2023 data, but the corpus is a 1999 filing. The embedding model does not "understand" temporal constraints—it matches semantic content (CEO, salary) regardless of date. | **Query formulation** | Retrieved chunks mentioned executive compensation from fiscal year 1998, not 2023. |
| Incomplete context | Boundary split | Fixed-length chunking at 256 tokens split a multi-sentence risk factor discussion. The first chunk contained the risk setup; the second contained the quantitative impact. Neither chunk alone was sufficient. | **Chunking** | Overlapping and hybrid strategies did NOT exhibit this failure on the same query, confirming the root cause is the chunking boundary. |
| Hallucination | Low retrieval | When all top-3 chunks scored retrieval quality ≤ 2, the generation model received context that was tangentially related at best. Rather than stating uncertainty, the model extrapolated and fabricated specific dollar amounts and dates. | **Embedding model + generation model** | The hallucinated numbers (e.g., "$4.2 million R&D budget") do not appear in any chunk in the corpus. Switching to the larger GTE-large embedding improved retrieval quality to 4 for the same query, eliminating the hallucination. |

### System Improvements

#### Fix 1: Increase top-k with context deduplication

**Problem:** With top-k = 3, queries on topics spanning paragraph boundaries sometimes missed critical context, particularly with the overlapping chunking strategy where 2 of 3 slots could contain near-identical chunks.

**Change:** Increased top-k from 3 to 5 and added a deduplication step that removes chunks with cosine similarity > 0.95 to each other, replacing them with the next-most-relevant unique chunk.

**Before (top-k = 3):**
- Q2 (employee count), MiniLM-L6 + overlapping: answer quality 5/5, but 2 of 3 retrieved chunks were near-duplicates, wasting context budget.

**After (top-k = 5 with dedup):**
- Same configuration: answer quality 5/5, and the 5 deduplicated chunks now cover employee count, departmental breakdown, AND hiring challenges—providing richer context for follow-up questions.

**Result:** Answer quality maintained at 5/5 while context diversity improved. On lower-scoring queries, the additional unique context raised answer quality by +1–2 points.

#### Fix 2: Query reformulation for ambiguous inputs

**Problem:** The ambiguous failure query "Tell me about the numbers" (F2) produced unfocused retrieval because the query embedding was not discriminative.

**Change:** Added a query-expansion preprocessing step that detects short or vague queries (< 6 tokens, no domain-specific terms) and rewrites them into a more specific form using the generation model itself as a query expander. The vague query was expanded to: "What are the key financial figures, revenue, and employee statistics reported in the SEC 10-K filing?"

**Before (original query):**
- Retrieval quality: 1/5 — chunks from 4 unrelated sections
- Answer quality: 2/5 — generic, unhelpful response

**After (expanded query):**
- Retrieval quality: 4/5 — chunks from financial summary and employee sections
- Answer quality: 4/5 — specific figures cited with section references

**Result:** +3 retrieval quality points, +2 answer quality points. The query expansion adds ~200 ms latency (one lightweight LLM call) but dramatically improves recall for vague inputs.

---

## Cost Awareness

| Factor | Impact |
|--------|--------|
| **Embedding size** | 1024d requires ~4× storage vs. 384d (4 bytes/dim × 1024 = 4 KB/vector vs. 1.5 KB/vector) |
| **Chunk size** | Smaller chunks = more vectors = more storage and compute for similarity search |
| **Chunk overlap** | 50-token overlap adds ~25% more chunks, increasing both embedding time and storage |
| **Top-k** | Higher k = more prompt tokens = higher generation cost (each additional chunk adds ~200 tokens) |
| **Generation model** | Dominates total cost: Qwen3.5-0.8B at ~$0.0035/query vs. Mistral-7B at ~$0.15/query (41.5× more expensive) |

### Per-Query Cost Breakdown (RTX 4060 at $0.50/hr)

| Component | Time | Cost/Query |
|-----------|------|-----------|
| Query embedding | ~0.002 s | $0.0000003 |
| Retrieval (cosine sim) | ~0.004 s | $0.0000006 |
| Generation (Qwen 0.8B) | ~25 s | $0.00347 |
| **Total** | **~25 s** | **$0.00348** |

Generation cost accounts for **99.7%** of the per-query budget. Optimizing embedding size or chunk count has negligible cost impact compared to reducing generation latency (e.g., quantizing the model, using speculative decoding, or switching to a faster API).

---

## RAG vs Fine-tuning vs Pure Prompting

| Dimension | RAG | Fine-tuning | Pure Prompting |
|-----------|-----|-------------|----------------|
| **Setup cost** | Low (embed documents once) | High (training GPU hours, labeled data) | Minimal (write a prompt) |
| **Per-query cost** | Medium (embedding + retrieval + generation) | Low (single forward pass) | Low (single forward pass) |
| **Knowledge updates** | Easy (re-embed new documents) | Expensive (re-train or fine-tune again) | Manual (edit prompt) |
| **Accuracy** | High when relevant chunks retrieved | High on trained distribution | Limited by context window |
| **Scalability** | Scales with vector DB | Fixed at training time | Fixed at prompt length |
| **Latency** | Higher (retrieval + generation) | Lowest (single pass) | Low (single pass) |
| **Data privacy** | Documents stay local in vector store | Data used for training, harder to remove | Data in prompt only |
| **Best when** | Knowledge base changes frequently, source attribution required, corpus exceeds context window | Static domain knowledge, consistent output format, minimize per-query latency | Prototyping, very small knowledge sets (< 5K words), no external data |

**Conclusion:** RAG is optimal for the Memoria use case because B2B financial/legal/medical document collections change frequently (new filings every quarter, updated regulations, new case law), source attribution is legally required in compliance contexts, and the total corpus far exceeds what fits in a single prompt context window.

---

## System Design (10K Users/Day)

### Architecture Diagram

```
┌─────────────────┐
│  User Queries   │  10,000 queries/day ≈ 21 QPS peak
│  (10K/day)       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  API Gateway /   │  Rate limiting, auth, request routing
│  Load Balancer   │
└────────┬────────┘
         │
    ┌────┼───────────────────┐
    ▼                        ▼
┌─────────────────┐  ┌─────────────────┐
│ Query Embedding  │  │  Cache Layer     │
│ (MiniLM-L6,~5ms) │  │  (Redis, 1h TTL) │  30% hit rate → skip retrieval+gen
└────────┬────────┘  └─────────────────┘
         │
         ▼
┌─────────────────┐
│ Vector DB        │  FAISS / Qdrant
│ (cosine sim,~5ms)│  500K vectors, sub-5ms retrieval
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Retrieval +      │  Top-5 with deduplication
│ Reranking        │  (~15 ms)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Generation       │  Primary: Qwen3.5-0.8B (local GPU)
│ Service          │  Fallback: Gemini Flash API (70% traffic)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Response         │  NDJSON streaming to client
│ Streaming        │
└─────────────────┘
```

### Scaling Assumptions

| Component | Capacity | Scaling Strategy |
|-----------|----------|-----------------|
| **Embedding service** | 1× T4 GPU handles ~200 emb/sec; 21 QPS needs 0.35/sec → 500× headroom | Single instance sufficient |
| **Vector DB** | Single FAISS node handles 500K vectors at sub-5 ms | Shard at > 1M vectors |
| **Cache** | Redis, 30% hit rate reduces generation load to ~15 QPS | Standard Redis cluster |
| **Generation** | Qwen 0.8B at 25 s/query needs ~10 GPU instances for 21 QPS; Gemini API fallback for 70% of traffic reduces to 1 GPU | Hybrid local + API routing |

### Optimization Priorities

1. **Cache aggressively** (1-hour TTL) — 30% hit rate saves ~$4/day in generation cost
2. **Batch embedding requests** (50 ms collection window) — amortize GPU kernel launch overhead
3. **Hybrid routing** — send simple queries to local Qwen, complex to Gemini Flash API
4. **Quantize FAISS index** (IVF-PQ) — reduces memory from 4 KB/vector to < 256 bytes/vector

**Estimated cost:** ~$13.40/day ($0.00134/query) with the above optimizations.

### Generation Model Comparison (Top 3 from A7)

| Model | Params | A7 Accuracy | RAG Quality (1-5) | Latency (ms) |
|-------|--------|-------------|-------------------|-------------|
| **Qwen3.5-0.8B** | 0.8B | 78.6% | **4.80** | 3,748 |
| Qwen3.5-2B | 2B | 71.4% | 4.70 | 5,046 |
| Mistral-7B | 7B | 71.4% | 4.40 | 271,361 |

**Winner:** Qwen3.5-0.8B — highest answer quality (4.80/5), fastest latency (3.7 s), highest A7 accuracy (78.6%), and smallest model size. RAG context compensates for smaller model capacity, making the lightweight model the best overall choice for production deployment.
