from openai import OpenAI
from dotenv import load_dotenv
import os
import json

load_dotenv()  # loads .env file

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_answer(question : str) -> dict:
    prompt = f"""
        You are a helpful AI assistant.
        Answer the user's question and return the result in the following JSON format:
        {{
        "answer": "...",
        "confidence": number between 0 and 1,
        }}
        Question: {question}
        """
    response = client.responses.create(
        model = 'gpt-4.1-mini',
        input = prompt,
        temperature=0
    )
    text_output = response.output_text
   
    
    try:
        data =  json.loads(text_output)
        return  {
                 "answer":data.get("answer"),
                 "confidence" :data.get("confidence"),
                 "score" : data.get('score')
                    }
    except:
        return {
                "answer":text_output,
                "confidence" : 0.5,
                "score" : 0
   
        }
    
    

