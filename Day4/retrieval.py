import json
from similarity import cosine_similarity
from embeddings import get_embedding
import time
import logging
logging.basicConfig(level=logging.INFO,
                       format= "%(asctime)s - %(levelname)s - %(message)s")

start = time.time()


def get_relevant_chunks(query: str,top_k: int=4):
    query_embedding = get_embedding(query)
    with open('data/embedded_chunks.json','r',encoding='utf-8') as f:
        chunks = json.load(f)
        results = []
        for chunk in chunks:
            score = cosine_similarity(query_embedding,chunk['embedded_text'])
            results.append({'doc_id':chunk['doc_id'],
                            'chunk_id':chunk['chunk_id'],
                            'text' : chunk['text'],
                            'score': score
            })
            
        results = sorted(results,key = lambda x: x['score'] , reverse=True)
        logging.info(f"Request took {time.time() - start:.2f} seconds")
        return(results[:top_k])
    
        

# retrieval / llm call

