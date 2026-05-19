from openai import OpenAI
from dotenv import load_dotenv
import os
load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_answer(question : str) -> str:
    response = client.responses.create(
         model = 'gpt-4.1-mini',
         input = question 
    )
    return response.output_text

def get_answer_summary(question : str) -> str:
    prompt = f'Summarize the answer for "{question}" in 3 rows'
    response = get_answer(prompt)
    return response

def get_answer_explain(question : str) -> str:
    prompt = f'Explain the answer to "{question}" in 10 rows - make it concrete'
    response = get_answer(prompt)
    return response

def get_answer_classify(question : str) -> str:
    prompt = f'Classify the topic of "{question}" in 4 levels '
    response = get_answer(prompt)
    return response
