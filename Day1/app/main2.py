from fastapi import FastAPI
from pydantic import BaseModel,Field
import logging
from llm2 import get_answer,get_answer_classify,get_answer_explain,get_answer_summary

logging.basicConfig(level=logging.INFO,
                    format = "%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI()

@app.get("/health")
def get_root():
    return({'Status':'Ok'})
    

class UserRequest(BaseModel):
    question : str = Field(min_length=3,
                          max_length=800,
                          description="The user's question"
    )

user_requests = []

@app.post("/llm/static")
def ask_llm_static(request : UserRequest):
    response = {"Answer" : "This is static answer"}
    user_requests.append(request.question)
    return {"answer": response}

@app.post("/llm/regular")
def ask_llm_raw(request : UserRequest):
    logging.info(f"Received question: {request.question}")
    try:
        response = get_answer(question=request.question)
        logging.info(f'Finished answering, the response is {response[0:60]} ')
        user_requests.append(request.question)
        return {"answer": response}
    except Exception as e:
        logging.error(f"Unable to continue. Error: {e}")
        return ({"message": f'Error {e}'})
        

@app.post("/llm/summary")
def ask_llm_summary(request : UserRequest):
    logging.info(f"Received question: {request.question}")
    try:
        response = get_answer_summary(question=request.question)
        logging.info(f'Finished answering, the response is {response[0:60]} ')
        user_requests.append(request.question)
        return {"answer": response}
    except Exception as e:
        logging.error(f"Unable to continue. Error: {e}")
        return ({"message": f'Error {e}'})

@app.post("/llm/explain")
def ask_llm_explain(request : UserRequest):
    logging.info(f"Received question: {request.question}")
    try:
        response = get_answer_explain(question=request.question)
        logging.info(f'Finished answering, the response is {response[0:60]} ')
        user_requests.append(request.question)
        return {"answer": response}
    except Exception as e:
        logging.error(f"Unable to continue. Error: {e}")
        return ({"message": f'Error {e}'})

@app.post("/llm/classify")
def ask_llm_classify(request : UserRequest):
    logging.info(f"Received question: {request.question}")
    try:
        response = get_answer_classify(question=request.question)
        logging.info(f'Finished answering, the response is {response[0:60]} ')
        user_requests.append(request.question)
        return {"answer": response}
    except Exception as e:
        logging.error(f"Unable to continue. Error: {e}")
        return ({"message": f'Error {e}'})

@app.get("/llm/history")
def get_history():
    return({"question list": user_requests})