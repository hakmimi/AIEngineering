from fastapi import FastAPI
import json
from retrieval import get_relevant_chunks
from pydantic import BaseModel , Field
import logging
from rag import get_rag_answer
logging.basicConfig(level=logging.INFO,
                       format= "%(asctime)s - %(levelname)s - %(message)s")
app = FastAPI()


@app.get('/health')
def get_health():
    return({'Status':'Ok'})


@app.get('/docs-count')
def docs_count():
    with open('data/docs.json','r',encoding='utf8') as f:
        docs = json.load(f)
    
    return {
        'documents' : len(docs)
    }

class SearchRequest(BaseModel):
    query : str
    top_k : int = Field(default=4)

@app.post('/search')
def search_docs(request : SearchRequest) -> dict :
    logging.info(f"Search query: {request.query}")
    
    response = get_relevant_chunks(request.query,request.top_k)
    logging.info(f"Top K: {request.top_k}")
    logging.info(f"Retrieved chunks: {len(response)}")
    
    return({'results':response})

@app.post('/rag')
def get_rag_llm(request : SearchRequest) -> dict:
    logging.info(f"Search query: {request.query}")
    response = get_rag_answer(request.query,request.top_k)
    logging.info(f"Top K: {request.top_k}")
    logging.info(f"Retrieved chunks: {len(response.get('retrieved_chunks', []))}")
    
    return({'results':response})
    

