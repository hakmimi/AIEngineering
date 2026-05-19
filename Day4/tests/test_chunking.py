
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from chunk import chunk_text

text = """
Israel has many historical places.
Jerusalem is one of the oldest cities.
Tel Aviv is a startup hub.
"""

chunks = chunk_text(text, chunk_size=5)

print(chunks)