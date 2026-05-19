# Day 2 – AI Engineering Learning Plan

---

## 1. Objective

By the end of Day 2, the goal is to:

- Improve API structure and clarity
- Gain control over LLM outputs (not random anymore)
- Introduce basic decision logic before calling the LLM
- Understand how to make responses consistent and reliable

---

## 2. Layer-Based Learning Plan

| Layer | Task (Build) | Concepts (Learn) | Output | Sources | Time | Questions to Answer |
|---|---|---|---|---|---:|---|
| System (L4) | Refactor `/ask` endpoint to structured request/response | Clean API design, separation | Improved API | FastAPI docs (Body, Response Models) | 35 min | What makes an API “clean”? |
| System (L4) | Add response format (answer, source, confidence) | Output contracts | Structured response | FastAPI + Pydantic | 25 min | Why structure responses? |
| LLM (L2) | Add system prompt + user prompt | Prompt roles (system vs user) | Controlled behavior | Building Systems with ChatGPT API | 45 min | How does system prompt influence output? |
| LLM (L2) | Tune temperature (0 vs 0.7) | Determinism vs creativity | Stable answers | Same | 25 min | When do we want deterministic output? |
| LLM (L2) | Create fixed prompt template | Prompt engineering basics | Reusable prompt | Self | 20 min | Why not build prompt dynamically each time? |
| Orchestration (L3) | Add rule-based routing before LLM | Decision logic | Conditional flow | Self | 30 min | When should we NOT call LLM? |
| Orchestration (L3) | Add simple classifier logic (keyword-based) | Pre-processing | Smarter pipeline | Self | 20 min | What can rules do better than LLM? |
| Data (L1) | Improve request structure (type, question) | Better input modeling | Rich input schema | Pydantic docs | 20 min | What defines good input? |
| System (L4) | Improve logging (input + output) | Observability basics | Clear logs | Python logging | 20 min | What should we log in production? |

---

## 3. Execution Steps

**Total time: ~4 hours**

| Step | Task Description | Time |
|---:|---|---|
| 1 | Refactor API request/response using Pydantic | 30 min |
| 2 | Add structured response fields | 20 min |
| 3 | Implement system + user prompt | 30 min |
| 4 | Test prompt variations | 20 min |
| 5 | Add temperature control | 15 min |
| 6 | Create reusable prompt template | 20 min |
| 7 | Add rule-based routing (if/else before LLM) | 30 min |
| 8 | Add simple classifier logic (keywords) | 20 min |
| 9 | Improve logging (input/output) | 15 min |
| 10 | Test + debug + refine | 40 min |

---

## 4. System Flow Understanding

The system now evolves into:

```text
Client → API → Decision Logic → (Optional LLM) → Response
```

You should understand:

- when LLM is used
- when it is skipped
- how prompt affects output

---

## 5. What to Avoid

| Avoid | Reason |
|---|---|
| Jumping to agents frameworks | You are building logic manually first |
| Over-complicated prompts | Simplicity first |
| Ignoring structure | Structure = production readiness |
| Treating LLM as magic | You must control it |

---

## 6. Success Criteria

| Criteria | Description |
|---|---|
| Controlled outputs | Responses are more consistent |
| Structured API | Input + output are clean |
| Logic exists | Not every request goes to LLM |
| Prompt reusable | Clear template exists |
| Logs improved | Inputs + outputs visible |

---

## 7. Key Insight

Day 1 was:

"Make it work"

Day 2 is:

"Make it controlled and predictable"

---

## ⚡ Final Tip

The biggest mindset shift today:

- LLM is NOT the system
- LLM is just a component inside the system

