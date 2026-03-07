# Proactive Context Injection and Retrieval Systems for LLMs

*Research compiled 2026-01-09*

---

## 1. ChatGPT's Memory System

ChatGPT's memory is **not traditional RAG**. OpenAI uses a simpler, faster approach:

### Architecture
The context structure follows this hierarchy ([reverse engineering analysis](https://manthanguptaa.in/posts/chatgpt_memory/)):
1. System Instructions
2. Developer Instructions
3. Session Metadata (ephemeral)
4. **User Memory** (long-term facts)
5. **Recent Conversations Summary** (past chats, titles + snippets)
6. Current Session Messages
7. Latest message

### Key Design Decisions
- **No vector search**: "There's no vector database frantically searching millions of embeddings... ChatGPT's approach skips the search step entirely. It pre-computes summaries and injects them directly."
- **Two memory types** (as of [April 2025 update](https://openai.com/index/memory-and-new-controls-for-chatgpt/)):
  - **Saved Memories**: Explicit facts (name, job, preferences) stored and shown in settings
  - **Reference Chat History**: Implicit context drawn from past conversations, not visible in settings

### Triggers for Memory Creation
- Model detects a fact fitting OpenAI's criteria (name, job title, stated preferences)
- User implicitly agrees through conversation
- User explicitly says "Remember this..."

**Security concern**: The bio/memory tool can be invoked via [indirect prompt injection](https://embracethered.com/blog/posts/2025/chatgpt-how-does-chat-history-memory-preferences-work/) without user consent.

---

## 2. Proactive vs Reactive RAG

### Reactive RAG (Traditional)
User asks question -> Embed query -> Search -> Retrieve -> Generate

### Proactive/Active RAG Approaches

**FLARE (Forward-Looking Active Retrieval)** ([Paper](https://arxiv.org/abs/2305.06983), [GitHub](https://github.com/jzbjyb/FLARE)):
- Generates the next sentence *without* retrieval first
- Checks token probabilities during generation
- If any token probability < threshold, triggers retrieval using the generated sentence as query
- Regenerates with retrieved context
- Key insight: "Anticipate future content, use it as query"

**Self-RAG** ([Learn Prompting](https://learnprompting.org/docs/retrieval_augmented_generation/self-rag)):
- Uses special reflection tokens: `Retrieve`, `ISREL`, `ISSUP`, `ISUSE`
- Model first decides if retrieval is necessary
- Critically assesses its own outputs
- More selective: only retrieves when the model is uncertain

**CRAG (Corrective RAG)** ([LangChain blog](https://blog.langchain.com/agentic-rag-with-langgraph/)):
- Evaluates retrieved documents for relevance
- If all irrelevant, transforms query and re-retrieves
- Can fall back to web search as supplementary source

**Agentic RAG** ([Survey paper](https://arxiv.org/abs/2501.09136)):
- Embeds autonomous agents into RAG pipeline
- Uses reflection, planning, tool use, multi-agent collaboration
- Dynamically manages retrieval strategies
- Adapts based on task requirements

---

## 3. When to Retrieve

### The Core Question
"When to retrieve (based upon the question and composition of the index), when to re-write the question for better retrieval, or when to discard irrelevant retrieved documents and re-try retrieval"

### Uncertainty-Based Triggering
**DTR (Decide Then Retrieve)** ([ArXiv](https://arxiv.org/html/2601.03908)):
- Uses LLM's generation uncertainty to decide if retrieval helps
- Confident queries bypass retrieval entirely
- Adjustable threshold trades off coverage vs accuracy

**DRAGIN**:
- Token-level retrieval decisions using entropy signals
- Detects knowledge gaps during generation
- Higher inference cost, mitigated by adaptive frequency thresholds

### Practical Thresholds
From [SIGIR research](https://dl.acm.org/doi/10.1145/3626772.3657834):
- **Retrieve 3-5 documents max**: "Adding more increases the risk of including too many distracting, counterproductive documents"
- **Counter-intuitive finding**: "Adding random documents in the prompt improves LLM accuracy by up to 35%" - retriever's highest-scoring but non-relevant documents hurt performance

### Triage Approach
- Out-of-domain queries recognized and sent directly to LLM
- Retrieval only for queries where external knowledge demonstrably helps

---

## 4. Relevance Scoring

### Two-Stage Retrieval (Industry Standard)
From [Pinecone's guide](https://www.pinecone.io/learn/series/rag/rerankers/):

1. **Stage 1 - Fast Retrieval** (Bi-encoder):
   - Pre-computed embeddings, cosine similarity
   - ~1ms for 1,000 passages
   - Frontloads transformer computation

2. **Stage 2 - Reranking** (Cross-encoder):
   - Jointly embeds query + document
   - Outputs relevance score
   - Much slower but far more accurate
   - Popular model: `cross-encoder/ms-marco-MiniLM-L-6-v2`

### Why Reranking Matters
"High similarity scores don't always guarantee perfect relevance... the retriever may retrieve a text chunk that has a high similarity score, but is in fact not that useful"

### Threshold Guidelines
From [Confident AI](https://www.confident-ai.com/blog/rag-evaluation-metrics-answer-relevancy-faithfulness-and-more):
- Standard: Faithfulness guardrails at 0.7-0.8 minimum
- Critical systems (finance, healthcare): 0.9+
- Similarity "drastically decreases after the first chunk... average similarity approaches zero from the fifth chunk onwards"

### Conformal Prediction ([ArXiv](https://arxiv.org/html/2511.17908))
- Coverage-controlled filtering with statistical guarantees
- Reduced context size by up to 3x while maintaining quality

---

## 5. Injection Format

### Best Practices from [APXML](https://apxml.com/courses/getting-started-rag/chapter-4-rag-generation-augmentation/context-injection-methods) and [Milvus](https://milvus.io/ai-quick-reference/what-are-effective-ways-to-structure-the-prompt-for-an-llm-so-that-it-makes-the-best-use-of-the-retrieved-context-for-example-including-a-system-message-that-says-use-the-following-passages-to-answer):

**Structure:**
```
[System: "Use the following passages to answer the query"]
---
[Retrieved Context - visual markers, XML tags, or separators]
---
[User Query]
```

**Key Guidelines:**
- **Place critical information first** - LLMs assign higher weight to earlier content
- **Keep context under 500 tokens** when possible - more often degrades accuracy
- **Use visual markers** (`---`, `<context>`, numbered lists) to separate retrieved content
- **Never concatenate raw user input directly into system instructions** (security)
- **Summarize before injecting raw data**

### Claude's Approach
Anthropic uses a **file-based approach** with `CLAUDE.md` files ([Claude Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)):
- Memory stored in Markdown files
- Version-controllable alongside project code
- "Unparalleled transparency... a tangible, editable artifact"
- Client-side: you control where and how data is stored

---

## 6. Production Memory Systems

### MemGPT / Letta ([Paper](https://arxiv.org/abs/2310.08560), [Docs](https://docs.letta.com/concepts/memgpt/))
- Inspired by OS virtual memory management
- Two-tier architecture: main context (in-context) + external context (out-of-context)
- Self-editing memory through tool use
- "Heartbeats" for multi-step reasoning
- Functions to move data between tiers

### Mem0 ([GitHub](https://github.com/mem0ai/mem0))
- "Universal memory layer for AI Agents"
- Auto-identifies and stores important facts
- Vector databases for long-term retention
- Fast, lightweight approach

### LifeContext ([GitHub](https://github.com/lifecontext/lifecontext))
- "Proactive AI agent built with your life"
- "Proactively generates supplementary insights based on browsing activities, not just summaries"
- Life-scale long-term retrieval

### A-MEM ([GitHub](https://github.com/agiresearch/A-mem))
- Agentic Memory for LLM Agents
- Dynamic memory operations
- Flexible agent-memory interactions

### EM-LLM ([Project Page](https://em-llm.github.io/))
- Human-inspired episodic memory
- Bayesian surprise detection for event segmentation
- Two-stage retrieval mirroring human memory access
- No fine-tuning required

---

## 7. Latency Optimization

### Typical RAG Latency Breakdown ([HackerNoon](https://hackernoon.com/designing-production-ready-rag-pipelines-tackling-latency-hallucinations-and-cost-at-scale)):
- Query Processing: 50-200ms
- Vector Search: 100-500ms
- Document Retrieval: 200-1000ms
- Reranking: 300-800ms
- LLM Generation: 1000-5000ms
- **Total: 2-7 seconds per query**

### Caching Strategies ([RAG Latency Playbook](https://python.plainenglish.io/the-rag-latency-playbook-batching-caching-scope-reduction-reranking-and-graph-rag-b85dae5cdfb7)):

**What to cache:**
1. **Query embeddings** - bypass embedding generation
2. **Retrieved document sets** - for frequent queries
3. **KV tensors** - for repeated document references
4. **Generated responses** - for identical queries (if answers stable)

**Semantic caching** ([Medium](https://medium.com/@svosh2/semantic-cache-how-to-speed-up-llm-and-rag-applications-79e74ce34d1d)):
- Compare query meanings, not raw text
- Similar queries return cached results
- Transform queries to embeddings, search cache by similarity

**RAGCache** ([Paper](https://arxiv.org/pdf/2404.12457)):
- KV tensor caching for documents
- Reduced TTFT by up to 4x
- Improved throughput by 2.1x
- Uses knowledge tree with prefix-aware replacement

### Target Metrics
- Median latency: <500ms
- 95th percentile: <1.5s
- Cache hit rate: 35-45%
- Accuracy: 90-95% of full processing

---

## 8. What Actually Helps vs Hurts

### Helps:
- **Fewer, better documents** (3-5) over many mediocre ones
- **Two-stage retrieval** with reranking
- **Semantic caching** for repeated/similar queries
- **Uncertainty-based retrieval decisions** (skip when confident)
- **Clear injection formatting** with separators
- **Hybrid retrieval** (BM25 + semantic)

### Hurts:
- **Over-retrieval**: "highest-scoring documents that are not directly relevant negatively impact LLM effectiveness"
- **Context > 500 tokens**: often degrades accuracy
- **Static retrieval timing**: retrieve-once misses multi-hop needs
- **No reranking**: cosine similarity alone misses contextual relevance

### Surprising Findings:
- Random padding documents can help: "adding random documents improves accuracy by up to 35%"
- The issue isn't too little context, it's distracting context from mid-relevance documents

---

## Key GitHub Repositories

| Project | Focus | Link |
|---------|-------|------|
| **FLARE** | Active retrieval during generation | [jzbjyb/FLARE](https://github.com/jzbjyb/FLARE) |
| **LightRAG** | Fast, simple RAG | [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) |
| **Mem0** | Universal memory layer | [mem0ai/mem0](https://github.com/mem0ai/mem0) |
| **MemGPT/Letta** | OS-style memory management | [cpacker/MemGPT](https://github.com/cpacker/MemGPT) |
| **A-MEM** | Agentic memory | [agiresearch/A-mem](https://github.com/agiresearch/A-mem) |
| **LifeContext** | Proactive life-scale memory | [lifecontext/lifecontext](https://github.com/lifecontext/lifecontext) |
| **Memlayer** | 3-line memory integration | [divagr18/memlayer](https://github.com/divagr18/memlayer) |
| **LangGraph Memory** | Production memory for agents | [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) |
| **Agent Memory Papers** | Curated paper list | [Shichun-Liu/Agent-Memory-Paper-List](https://github.com/Shichun-Liu/Agent-Memory-Paper-List) |

---

## Sources

### ChatGPT Memory
- [Reverse Engineering ChatGPT Memory](https://manthanguptaa.in/posts/chatgpt_memory/)
- [OpenAI Memory Announcement](https://openai.com/index/memory-and-new-controls-for-chatgpt/)
- [Memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq)
- [Security Analysis](https://embracethered.com/blog/posts/2025/chatgpt-how-does-chat-history-memory-preferences-work/)

### Proactive RAG
- [FLARE Paper](https://arxiv.org/abs/2305.06983)
- [Agentic RAG Survey](https://arxiv.org/abs/2501.09136)
- [Self-RAG Guide](https://learnprompting.org/docs/retrieval_augmented_generation/self-rag)
- [Self-Reflective RAG with LangGraph](https://blog.langchain.com/agentic-rag-with-langgraph/)

### Relevance & Retrieval
- [Rerankers Guide - Pinecone](https://www.pinecone.io/learn/series/rag/rerankers/)
- [Power of Noise Paper](https://dl.acm.org/doi/10.1145/3626772.3657834)
- [RAG Evaluation Metrics](https://www.confident-ai.com/blog/rag-evaluation-metrics-answer-relevancy-faithfulness-and-more)

### Context Injection
- [Context Injection Methods](https://apxml.com/courses/getting-started-rag/chapter-4-rag-generation-augmentation/context-injection-methods)
- [Claude Memory Tool Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)

### Production Systems
- [LangGraph Long-Term Memory](https://blog.langchain.com/launching-long-term-memory-support-in-langgraph/)
- [MemGPT Paper](https://arxiv.org/abs/2310.08560)
- [RAG Latency Playbook](https://python.plainenglish.io/the-rag-latency-playbook-batching-caching-scope-reduction-reranking-and-graph-rag-b85dae5cdfb7)
- [RAGCache Paper](https://arxiv.org/pdf/2404.12457)
- [Gemini Memory Features](https://www.datastudios.org/post/google-gemini-context-window-token-limits-and-memory-in-2025)
