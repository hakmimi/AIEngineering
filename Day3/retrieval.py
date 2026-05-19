import json
from similarity import cosine_similarity
from embeddings import get_embedding

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
        return(results[:top_k])
    
        