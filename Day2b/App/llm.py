
from openai import OpenAI
from dotenv import load_dotenv
import json
import os
import logging

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s"
                    )
load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
    You are a helpful AI assistant of a commercial airline.
    You shuold treat customer requests kindly and professionally. 
   
    Rules:
    - Answer clearly and concisely.
    - Do not invent facts.
    - If you are unsure, say so.
    - Return ONLY valid JSON.
    - Do not add markdown.
"""


PROMPT_VARIATIONS = {
    "simple": """ Answer the question clearly.
                    Return ONLY valid JSON:
                    {{
                    "suggested_reply": "...",
                    "confidence": 0.0,
                    "priority": "Low | Medium | High"
                    }}

                Ticket:{question}""",

    "strict": """Answer the question in a concise and reliable way.

                Rules:
                - Do not guess.
                - If unsure, say "I am not sure".
                - Keep the answer under 5 sentences.

                Return ONLY valid JSON:
                {{
                "suggested_reply": "...",
                "confidence": 0.0,
                "priority": "Low | Medium | High"
                }}
                Ticket:  {question} """,

    "teacher": """You are helping a customer support agent respond to a customer ticket about a purchased flight.
                  Explain the issue simply and provide concise, step-by-step guidance for how the agent should address the customer’s request.

                Return ONLY valid JSON:
                {{
                "suggested_reply": "...",
                "confidence": 0.0,
                "priority": "Low | Medium | High"
                }}

                Ticket: {question} """
}



def build_prompt(question : str, prompt_style : str = "strict"):
    template = PROMPT_VARIATIONS.get(prompt_style,PROMPT_VARIATIONS['strict'])
    return(template.format(question=question))

def choose_prompt_style(category: str) -> str:
    if category=="billing":
        return "strict"
    if category=="technical":
        return "teacher"
    if category=="account":
        return "teacher"
    else:
        return "simple"
    

TEMPERATURE_BY_STYLE = {
    "strict": 0,
    "simple": 0.3,
    "teacher": 0.5
}



def classify_ticket(ticket: str) -> str:
    t = ticket.lower()

    if any(w in t for w in ["refund", "charged", "invoice", "payment"]):
        return "billing"

    if any(w in t for w in ["login", "password", "account", "access"]):
        return "account"

    if any(w in t for w in ["bug", "error", "crash", "not working"]):
        return "technical"

    return "general"


    
    
def get_answer(request : str) -> dict:
    ticket_category = classify_ticket(request)
    prompt_style = choose_prompt_style(ticket_category)
    ticket_temprature = TEMPERATURE_BY_STYLE.get(prompt_style,0)
    selected_prompt = PROMPT_VARIATIONS.get(prompt_style,PROMPT_VARIATIONS['strict'])
    logging.info(f'Request has been classified with temp of {selected_prompt} and prompt_style of {ticket_temprature} and category of {ticket_category}')
    USER_PROPMPT = selected_prompt.format(question=request)
    logging.info(f'Request has been sent to the model')
    results = client.responses.create(
        model = 'gpt-4.1-nano',
        temperature=ticket_temprature,
        input=({'role':'system',
                'content':SYSTEM_PROMPT },
               {'role':'user',
                'content':USER_PROPMPT 
                }
               ),
       
    )
    logging.info(f'Response is ready')
    results_text = results.output_text
    try:
        response = json.loads(results_text)
        logging.info("JSON parsed successfully")
        return({'category' : ticket_category,
                'priority' : response["priority"],
                'suggested_reply' : response["suggested_reply"],
                'temprature' : ticket_temprature,
                'confidence' : response['confidence']
            
        })
    except Exception as e:
        logging.error(f"JSON parsing failed: {e}")
        return({'category' : ticket_category,
                'priority' : "Low",
                'suggested_reply' : results_text,
                'temprature' : ticket_temprature,
                'confidence' : 0.5
            
        })
        
   
if __name__ == "__main__":
    questions = [
        "I have a problem in my account",
        "I missed my flight",
        "I lost my luggage?"
    ]

    for question in questions:
        print("\nQUESTION:", question)
        print(get_answer(question))