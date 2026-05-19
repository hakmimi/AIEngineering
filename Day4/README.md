# Day 4 – AI Engineering Learning Plan

---

## 1. Objective

By the end of Day 4, the goal is to:

- Build your first Retrieval-Augmented Generation (RAG) system
- Connect retrieval → LLM → answer
- Understand how AI systems use external knowledge
- Improve answer quality using context injection

---

## 2. Layer-Based Learning Plan

| Layer | Task (Build) | Concepts (Learn) | Output | Sources | Time | Questions to Answer |
|---|---|---|---|---|---:|---|
| Orchestration (L3) | Combine retrieval + LLM into pipeline | RAG architecture | Full pipeline | YouTube: “RAG explained simply” | 30 min | What are the steps in RAG? |
| LLM (L2) | Inject retrieved chunks into prompt | Context injection | Better answers | Building Systems with ChatGPT API | 35 min | How does context affect output? |
| LLM (L2) | Design prompt template with context | Prompt structure | Stable RAG prompt | Same | 25 min | How should context be formatted? |
| Orchestration (L3) | Build function `rag_answer(query)` | Pipeline abstraction | Reusable RAG logic | Self | 30 min | Why wrap pipeline in function? |
| System (L4) | Replace `/ask` with RAG-based response | API integration | Working RAG endpoint | FastAPI docs | 25 min | Where does RAG live in system? |
| Data (L1) | Improve chunk selection (`top_k` tuning) | Retrieval tuning | Better context | Self | 20 min | How many chunks is optimal? |
| System (L4) | Log retrieved context + answer | Observability | Visible pipeline | Python logging | 15 min | What should we monitor? |
| Orchestration (L3) | Add fallback (no context → simple LLM) | Robustness | Safer pipeline | Self | 20 min | What if retrieval fails? |

---

## 3. Execution Steps

**Total time: ~4 hours**

| Step | Task Description | Time |
|---:|---|---|
| 1 | Take retrieval function from Day 3 | 10 min |
| 2 | Create prompt template with context | 30 min |
| 3 | Inject retrieved chunks into prompt | 25 min |
| 4 | Build `rag_answer(query)` function | 30 min |
| 5 | Replace `/ask` endpoint with RAG logic | 25 min |
| 6 | Tune number of retrieved chunks (`top_k`) | 20 min |
| 7 | Add fallback logic if no results | 20 min |
| 8 | Add logging (context + response) | 15 min |
| 9 | Test multiple queries | 30 min |
| 10 | Debug + refine | 35 min |

---

## 4. System Flow Understanding

The system now becomes:

```text
Query → Retrieve → Inject Context → LLM → Answer
```

This is your first real AI system architecture.

You should understand:

- where retrieval happens
- where reasoning happens
- how context improves output

---

## 5. What to Avoid

| Avoid | Reason |
|---|---|
| Using LangChain | You must understand RAG manually |
| Overloading context | Too much data hurts performance |
| Ignoring prompt design | Prompt = system behavior |
| Skipping fallback | Real systems must be robust |

---

## 6. Success Criteria

| Criteria | Description |
|---|---|
| RAG works | Answer uses retrieved context |
| Better answers | More relevant than Day 2 |
| Pipeline clear | You can explain steps |
| API updated | `/ask` uses RAG |
| Logging useful | You see context + output |

---

## 7. Key Insight

This is the most important concept so far:

```text
LLM alone = generic answers
RAG = context-aware, real-world answers
```

---

## ⚡ Final Tip

If something doesn’t work:

👉 Check in this order:

1. Retrieval quality
2. Context formatting
3. Prompt clarity

NOT the model.

---

## 🔥 What You Just Built

You now have:

- API (Layer 4)
- LLM integration (Layer 2)
- Retrieval pipeline (Layer 3)
- Data layer (Layer 1)

👉 That’s a complete AI system.

---

## 🚀 What Changes After Today

Before:

- LLM answers based on general knowledge

After:

- System answers based on your data
