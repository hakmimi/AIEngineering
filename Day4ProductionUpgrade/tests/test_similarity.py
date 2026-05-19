
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from embeddings import get_embedding
from similarity import cosine_similarity

text1 = "Jerusalem is a historic city in Israel"
text2 = "The Old City has many religious and historical sites"
text3 = "Tel Aviv has startups and technology companies"

emb1 = get_embedding(text1)
emb2 = get_embedding(text2)
emb3 = get_embedding(text3)

print(f'Similarity between text 1 and text 2 is {cosine_similarity(emb1,emb2)}')
print(f'Similarity between text 1 and text 3 is {cosine_similarity(emb1,emb3)}')
print(f'Similarity between text 2 and text 3 is {cosine_similarity(emb2,emb3)}')