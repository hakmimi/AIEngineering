from fastapi import FastAPI,HTTPException
from pydantic import BaseModel,Field
from llm import get_answer
import logging

logging.basicConfig(level=logging.INFO,
                    format= "%(asctime)s - %(levelname)s - %(message)s")
app = FastAPI()


class UserRequest(BaseModel):
    ticket : str = Field(min_length=5,max_length=500,description="The question of the user")
    type : str = Field(default="general")
    
class LLMResponse(BaseModel):
    category : str = Field(description="Ticket category")
    priority : str = Field(description="Ticket priority",default="low")
    suggested_reply : str = Field(min_length=5,max_length=500,description= "The model's response")
    source : str = Field(default="LLM")
    temprature : float = Field(ge=0,le=1,default=0.5,description = "The model's temprature" )
    confidence : float = Field(ge=0,le=1,default=0.5,description = "The model's confidence")
      

@app.get("/health")
def get_health():
    return({'Status':'Ok'})


@app.post("/llm/regular",response_model=LLMResponse)
def call_llm(request :UserRequest):
    try: 
        logging.info("Request has been recieved")
        result = get_answer(request = request.ticket)
        return LLMResponse(category = result['category'],
                           priority = result['priority'],
                           suggested_reply = result['suggested_reply'],
                           temprature = result['temprature'],
                           confidence = result['confidence'])
    except Exception as e:
        logging.error("Error had happened {e}")
        raise HTTPException(status_code=500,detail="LLM request failed")
                           
            
     
    

    
    
