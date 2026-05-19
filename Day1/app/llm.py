from openai import OpenAI
from dotenv import load_dotenv
import os
import json

load_dotenv()  # loads .env file

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def classify_question(question : str) -> str:
    q = question.lower()
    if "summarize" in q:
        return "summary"
    elif "explain" in q:
        return "explanation"
    return "general"

def get_answer(question : str) -> dict:
    prompt = f"""
        You are a helpful AI assistant.
        Answer the user's question and return the result in the following JSON format:
        {{
        "answer": "...",
        "confidence": number between 0 and 1,
        "type": "general | explanation | summary"
        }}
        Question: {question}
        """
    response = client.responses.create(
        model = 'gpt-4.1-mini',
        input = prompt,
        temperature=0
    )
    text_output = response.output_text
    q_type = classify_question(question)
    
    try:
        data =  json.loads(text_output)
        return  {
                 "answer":data.get("answer"),
                 "confidence" :data.get("confidence"),
                 "type": q_type
                 }
    except:
        return {
                "answer":text_output,
                "confidence" : 0.5,
                "type": q_type
        }
    
    

