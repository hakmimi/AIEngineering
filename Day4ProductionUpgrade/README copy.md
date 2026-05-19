# Day 3 – AI Engineering Learning Plan

---

## 1. Objective

By the end of Day 3, the goal is to:

- Understand and implement embeddings
- Introduce a data layer (documents)
- Build the foundation for retrieval (before full RAG)
- Learn how AI systems connect data to reasoning

---

## 2. Layer-Based Learning Plan

| Layer | Task (Build) | Concepts (Learn) | Output | Sources | Time | Questions to Answer |
|---|---|---|---|---|---:|---|
| LLM (L2) | Generate embeddings from text | Vector representation, similarity | Embedding vectors | YouTube: “Embeddings explained simply” | 35 min | What does an embedding represent? |
| LLM (L2) | Compare embeddings (similarity) | Cosine similarity | Similarity score | Same | 25 min | How do we measure “similarity”? |
| Data (L1) | Load small dataset (5–10 docs) | Data ingestion | Local dataset | Self (text/json file) | 20 min | What makes data useful? |
| Data (L1) | Split documents into chunks | Chunking | Smaller text units | Basic script | 30 min | Why not use full documents? |
| Orchestration (L3) | Create retrieval function (`get_relevant_chunks`) | Retrieval logic | Top-k results | Self | 35 min | How do we choose relevant data? |
| Orchestration (L3) | Connect query → embedding → similarity search | Pipeline thinking | Retrieval pipeline | Self | 30 min | What are pipeline steps? |
| System (L4) | Add `/search` endpoint | API expansion | Working retrieval API | FastAPI docs | 20 min | How do we expose retrieval? |
| System (L4) | Log retrieved chunks | Observability | Visible retrieval results | Python logging | 15 min | What should we inspect? |

---

## 3. Execution Steps

**Total time: ~4 hours**

| Step | Task Description | Time |
|---:|---|---|
| 1 | Prepare small dataset (text file or JSON) | 15 min |
| 2 | Write script to generate embeddings | 30 min |
| 3 | Implement cosine similarity function | 20 min |
| 4 | Split documents into chunks | 25 min |
| 5 | Compute embeddings for all chunks | 20 min |
| 6 | Implement retrieval function (top-k matches) | 30 min |
| 7 | Connect query → retrieval pipeline | 30 min |
| 8 | Add `/search` endpoint | 20 min |
| 9 | Add logging for retrieved results | 10 min |
| 10 | Test + debug + refine | 40 min |

---

## 4. System Flow Understanding

The system now evolves into:

```text
Query → Embedding → Similarity Search → Retrieved Data
```

👉 (LLM is NOT yet used here — that comes tomorrow)

You should understand:

- how text becomes vectors
- how similarity is computed
- how data is retrieved

---

## 5. What to Avoid

| Avoid | Reason |
|---|---|
| Using vector DB (yet) | Learn mechanics first |
| Using LangChain | You must understand pipeline manually |
| Large datasets | Keep it small and understandable |
| Skipping chunking | Critical for real systems |

---

## 6. Success Criteria

| Criteria | Description |
|---|---|
| Embeddings work | You generate vectors |
| Similarity works | Relevant chunks retrieved |
| Data exists | Dataset is usable |
| Retrieval pipeline works | Query returns top-k chunks |
| API works | `/search` returns results |

---

## 7. Key Insight

This is one of the most important days:

LLMs don’t “know” your data

You must bring the right data to them

---

## ⚡ Final Tip

If you feel confused today, that’s normal.

👉 This is the first time you’re building:

- data → vector → similarity → retrieval

This is the foundation of:

- RAG
- semantic search
- AI agents

---

## 🔥 What Changes After Today

Before:

- LLM = answers everything

After:

- System = retrieves relevant data
- LLM = uses that data

Perfect — Day 4 is the turning point.

This is where everything connects:

Data (Day 3) + LLM (Day 1–2) → Real AI system (RAG)
