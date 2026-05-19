| Check                    | Question                                                           | Status |
| ------------------------ | ------------------------------------------------------------------ | ------ |
| FastAPI installed        | Did I install `fastapi` and `uvicorn`?                             | ☐      |
| Project created          | Do I have `main.py` and `llm.py`?                                  | ☐      |
| Health endpoint works    | Does `/health` return a simple success response?                   | ☐      |
| Dummy ask endpoint works | Does `/ask` return a static answer before using the LLM?           | ☐      |
| LLM call works           | Can I call the LLM from Python and get a response in the terminal? | ☐      |
| LLM logic separated      | Is the LLM call inside a separate function like `get_answer()`?    | ☐      |
| Schema defined           | Do I use a structured input like `question` with Pydantic?         | ☐      |
| API connected to LLM     | Does `/ask` call `get_answer()` and return the real LLM response?  | ☐      |
| API tested               | Did I test the endpoint using `/docs`?                             | ☐      |
| Logging added            | Can I see request/response logs in the terminal?                   | ☐      |
