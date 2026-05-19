from fastapi import FastAPI
from pydantic import BaseModel,Field
from llm import get_answer
import logging
import time

logging.basicConfig(level=logging.INFO,
                    format = "%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI()
@app.get("/")
def root():
    logging.info(f'Reached root!')
    return {'hello':'world'}

@app.get("/health")
def get_health_status():
    return {'Status':'ok'}

class AskRequest(BaseModel):
    question : str  

class AdvancedRequest(BaseModel):
    question : str  = Field(
        min_length=2,
        max_length=500,
        description= "The users question"
    )
    
@app.post("/ask")
def ask_static(request : AskRequest):
    return {
        "question": request.question,
        "answer" :  "This is static answer!"
    }
 
@app.post("/askllm")
def ask_llm(request : AdvancedRequest):
    
    logging.info(f"Received question: {request.question}")
    try:
        start_time = time.time()
        answer = get_answer(request.question)
        durartion = time.time()- start_time
        logging.info(f'Returned answer with duration of {round(durartion,3)} - {answer[:80]} ')
        return {'answer' : answer}
    
    except Exception as e:
        logging.error(f'Error during LLM call {e}')
        return({"error":"Something went wrong!"})
        
# Invoke-RestMethod `
#   -Uri "http://127.0.0.1:8000/ask" `
#   -Method Post `
#   -ContentType "application/json" `
#   -Body '{"question":"What is AI engineering?"}'    

#Experiments

class Item(BaseModel):
    item_name : str

item_list = []

@app.post("/items")
def add_items(item:Item):
    item_list.append(item.item_name)
    return(item_list)

@app.get("/items")
def get_items():
    return item_list

# Invoke-RestMethod `
#   -Uri "http://127.0.0.1:8000/items" `
#   -Method Post `
#   -ContentType "application/json" `
#   -Body '{"item_name":"apple"}'


