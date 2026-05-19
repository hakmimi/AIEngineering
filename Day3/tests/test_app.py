import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import requests

response = requests.post(
    "http://127.0.0.1:8000/search",
    json={
        "query": "young city with nightlife",
        "top_k": 4
    }
)

print(response.json())