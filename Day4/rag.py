from llm import get_answer
from retrieval import get_relevant_chunks
import logging
logging.basicConfig(level=logging.INFO,
                    format= '%(asctime)s - %(levelname)s - %(message)s')



def build_context(chunks : list[float]) -> str:
    context = "" 
    for chunk in chunks:
        context += chunk['text'] + "\n\n"
    return context

def get_rag_answer(question : str,top_k:int =3) -> dict:
    chunks = get_relevant_chunks(question,top_k)
    best_score = chunks[0]['score'] if len(chunks)>0  else 0
    logging.info(f'"BEST SCORE:", {best_score}')
    

        
    if best_score < 0.55:
        logging.info(f'"Using Fallback logic, no chunks available')
        llm_response = get_answer(question)
        return({'question' : question,
            'answer' : llm_response.get('answer'),
            'confidence' : llm_response.get('confidence'),
            'score' : llm_response.get('score'),
            'retrieved_chunks' : [],
            'source': 'llm_fallback'
            
            })
    else:
        logging.info(f"Using RAG based on {len(chunks)} chunks")
        context = build_context(chunks)
        rag_prompt = f"""
        You are a helpful AI assistant.
        Use ONLY the provided context to answer the question.
       
        Context: {context}
        Question: {question}
        """
        llm_response = get_answer(rag_prompt)
        return({'question' : question,
                'answer' : llm_response.get('answer'),
                'confidence' : llm_response.get('confidence'),
                'score' : llm_response.get('score'),
                'retrieved_chunks' : chunks,
                'source': 'embeddings'
            
        })
    
        