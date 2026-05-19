# Day 1 – AI Engineering Learning Plan

---

## 1. Objective

By the end of Day 1, the goal is to:

- Build a working FastAPI service
- Integrate a Large Language Model (LLM) call
- Connect both into a simple end-to-end system
- Understand the basic architecture of an AI system

---

## 2. Layer-Based Learning Plan

| Layer | Task (Build) | Concepts (Learn) | Output | Sources | Time | Questions to Answer |
|---|---|---|---|---|---:|---|
| System (L4) | Create FastAPI app + `/health` endpoint | API basics, request/response | Working endpoint | FastAPI official docs (Quickstart) / YouTube: “FastAPI in 10 minutes” | 40 min | What happens when request hits API? |
| System (L4) | Create `/ask` endpoint (dummy) | Routing, JSON input/output | Static response | FastAPI docs (Request Body) | 30 min | Why separate endpoints? |
| LLM (L2) | Call LLM API from Python | Tokens, prompts, temperature | LLM response in terminal | Building Systems with ChatGPT API (Lessons 1–2) | 45 min | What controls output? |
| LLM (L2) | Test 3 prompt variations | Prompt sensitivity | Different outputs | Same course / OpenAI Playground | 30 min | Why wording matters? |
| Orchestration (L3) | Wrap LLM in function `get_answer()` | Separation of concerns | Reusable logic | Self implementation | 20 min | Why separate logic from API? |
| Data (L1) | Define schema `question` | Validation, structured input | Clean request object | FastAPI + Pydantic docs | 20 min | Why schema? |
| System (L4) | Connect API → LLM | End-to-end flow | Working endpoint | Combine all above | 35 min | Can I explain full flow? |
| System (L4) | Add logging | Debugging basics | Execution logs | Python logging basic tutorial | 20 min | Where do I debug? |

---

## 3. Execution Steps

**Total time: ~4 hours**

| Step | Task Description | Time | Status |
|---:|---|---|---:|
| 1 | Install libraries: `fastapi`, `uvicorn`, `openai` | 10 min | Done |
| 2 | Create project structure: `main.py`, `llm.py` | 10 min | Done |
| 3 | Implement `/health` endpoint | 20 min | Done |
| 4 | Implement `/ask` endpoint with static response | 20 min | Done |
| 5 | Build LLM call in separate file | 30 min | Done |
| 6 | Connect API to LLM function | 30 min | Done |
| 7 | Add input validation with Pydantic | 20 min | Done |
| 8 | Test API using `/docs` | 20 min | Done |
| 9 | Add logging | 20 min | Done |
| 10 | Debug and iterate | 40 min | Done |

---

## 4. System Flow Understanding

The system built today should follow this flow:

```text
Client → API → Python Function → LLM → Response
```
## 5. What to Avoid
| Avoid | Reason |
|---|---|
| LangChain or frameworks | Focus on fundamentals first |
| Over-engineering | Goal is clarity, not complexity |
| Building UI | Not relevant at this stage |
| Watching too many tutorials | Learning happens through building |

## 6. Success Criteria
| Criteria | Description |
|---|---|
| API works | `/ask` returns real LLM response |
| LLM understanding | You can control output via prompt |
| System clarity | You can explain full flow |
| Debugging ability | Logs show execution |
| Clean structure | API and logic separated |
## 7. Key Insight
At this stage, the focus is not on advanced tools or optimization.
The goal is to understand:

- How a real AI system is structured
- How components interact across layers
- Where logic, intelligence, and data flow exist

## ⚡ Final Tip
If you run out of time, use this priority order:
- API works
- LLM call works  
- Connect them
- Everything else

## 9. Questions
### What is the role of the API?
The API is the interface between the user/client and the backend system. In our case, it receives requests, validates them, routes them to the right function, and returns a structured response.

### What is the role of the LLM service?
The LLM service is responsible only for communicating with the model: sending the user’s question to the LLM API and returning the model’s answer to the main app.

### What exactly is sent to the model?
The user sends a JSON body that is validated by a Pydantic model. From that object, we extract request.question, and that string is sent to the LLM.

### What exactly is returned to the user?
The API returns a JSON response, for example:
`{
  "answer": "..."
}`

The answer itself is a string, but the full response is JSON.

### Where would I add validation?
Input validation should be done with Pydantic, for example min_length, max_length, and required fields. Error handling around the LLM call should be done with try/except.

### Where would I add logging?
The most important logs are before the LLM call, after the LLM response, and inside the error block if the model call fails.

### What would break if the LLM API failed?
Without try/except, the /askllm request would fail and return a server error. With try/except, the app stays alive and returns a controlled error response.

### Why should API logic and LLM logic be separated?
Because they have different responsibilities. The API handles requests and responses. The LLM service handles model communication. This makes the code easier to test, debug, replace, and extend.