
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from embeddings import get_embedding

vector = get_embedding("Jerusalem is a historic city in Israel")

print(type(vector))
print(len(vector))
print(vector[:10])
