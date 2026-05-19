import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))


from rag import get_rag_answer

# Real data
# response = get_rag_answer("What makes Jerusalem important?", top_k=2)

# Fake data for testing
response = get_rag_answer("What is special about Lumaria?", top_k=2)

print(response["answer"])
print(response["retrieved_chunks"])