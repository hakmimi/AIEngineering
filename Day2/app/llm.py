from openai import OpenAI
import os
from dotenv import load_dotenv
import json

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

SYSTEM_PROMPT = """
    You are a helpful AI assistant inside a production API.

    Rules:
    - Answer clearly and concisely.
    - Do not invent facts.
    - If you are unsure, say so.
    - Return ONLY valid JSON.
    - Do not add markdown.
"""

PROMPT_VARIATIONS = {
    "simple": """
Answer the question clearly.

Return ONLY valid JSON:
{{
  "answer": "...",
  "confidence": 0.0
}}


Question:
{question}
""",

    "strict": """
Answer the question in a concise and reliable way.

Rules:
- Do not guess.
- If unsure, say "I am not sure".
- Keep the answer under 5 sentences.

Return ONLY valid JSON:
{{

  "answer": "...",
  "confidence": 0.0
}}


Question:
{question}
""",

    "teacher": """
You are explaining to someone learning AI engineering.

Answer simply, step by step, with a practical example.

Return ONLY valid JSON:
{{
  "answer": "...",
  "confidence": 0.0
}}

Question:
{question}
"""
}


TEMPERATURE_BY_STYLE = {
    "strict": 0,
    "simple": 0.3,
    "teacher": 0.5
}



def classify_question(question: str) -> str:
    q = question.lower()

    summary_keywords = ["summarize", "summary", "short version", "brief"]
    explanation_keywords = ["explain", "why", "how", "what is", "what are"]
    classification_keywords = ["classify", "category", "type", "label"]

    if any(keyword in q for keyword in summary_keywords):
        return "summary"

    if any(keyword in q for keyword in explanation_keywords):
        return "explanation"

    if any(keyword in q for keyword in classification_keywords):
        return "classification"

    return "general"

def choose_prompt_style(q_type: str) -> str:
    if q_type == "summary":
        return "strict"
    elif q_type == "explanation":
        return "teacher"
    return "simple"


def build_prompt(question : str, prompt_style : str = "strict"):
    template = PROMPT_VARIATIONS.get(prompt_style,PROMPT_VARIATIONS['strict'])
    return(template.format(question=question))
    
def get_answer(question : str) -> dict:
    q_type = classify_question(question)
    logging.info(f"Question classified as {q_type}")
    
    prompt_style = choose_prompt_style(q_type)
    logging.info(f"Using prompt style of {prompt_style}")
    
    model_temprature = TEMPERATURE_BY_STYLE.get(prompt_style,0)
    logging.info(f"Model temprature which will be use is {model_temprature}")
    user_prompt = build_prompt(question, prompt_style)
    
    logging.info("Calling LLM...")
    response = client.responses.create(
        model = 'gpt-4.1-mini',
        temperature=model_temprature,
        input = [
            {"role":"system",
             "content":SYSTEM_PROMPT},
            {"role" : "user",
             "content" : user_prompt}
        ]
    )
    text_output = response.output_text
    
    
    try:
        data =  json.loads(text_output)
        logging.info("JSON parsed successfully")
        return  {
                 "answer":data.get("answer",""),
                 "confidence" :data.get("confidence",0.5),
                 "type": q_type,
                 "temprature" : model_temprature
                 }
    except Exception as e:
        logging.error(f"JSON parsing failed: {e}")
        return {
                "answer":text_output,
                "confidence" : 0.5,
                "type": q_type,
                "temprature" : model_temprature
        }
    
    

if __name__ == "__main__":
    questions = [
        "Summarize what FastAPI is",
        "Explain APIs",
        "What is Python?"
    ]

    for question in questions:
        print("\nQUESTION:", question)
        print(get_answer(question))