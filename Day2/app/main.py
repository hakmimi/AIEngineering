from pydantic import BaseModel,Field
from fastapi import FastAPI,HTTPException
from llm import get_answer
import logging

logging.basicConfig(level=logging.INFO,
                    format= "%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI()

class UserRequest(BaseModel):
    question : str = Field(min_length=2,max_length=500,description="This is the question")
    type : str = Field(default="General")

class LLMResponse(BaseModel):
    answer : str
    source : str
    confidence : float
    type : str
    temprature : float

@app.get("/health")
def get_root():
    return {"Status":"Ok"}

@app.post("/llm/regular",response_model=LLMResponse)
def ask_llm(response :UserRequest):
    try:
        logging.info(f"Recieved quesion {response.question}")
        result = get_answer(question=response.question)
        logging.info(f"return result {result["answer"]} ")
        return LLMResponse(answer=result["answer"],
                       source="llm",
                       confidence=result["confidence"],
                       type  = result["type"],
                       temprature=result["temprature"]
                       )
    except Exception as e:
        logging.error(f"Error occurred: {e}")
        raise HTTPException(status_code=500, detail="LLM request failed")
        
    
    