import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from retrieval import get_relevant_chunks

text1 = "Jerusalem is a historic city in Israel"
result =  get_relevant_chunks(text1)
print(result)

text2 = "Tel Aviv is a young city with beaches, nightlife and startups"
result =  get_relevant_chunks(text2,top_k=2)
print(result)
