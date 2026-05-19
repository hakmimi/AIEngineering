from chunk import chunk_text
from embeddings import get_embedding
import json

from config import settings


# Original script used relative paths, which break when launched from another directory.
with settings.docs_path.open('r',encoding='utf8') as f:
    docs = json.load(f)
    embeddings_file = []
    for i in range(0,len(docs)):
        text = docs[i].get('text')
        chunnked_text = chunk_text(text)
        embeddings = []
        for j in range(0,len(chunnked_text)):
            emb_text = get_embedding(chunnked_text[j])
            chunk_dict = {'doc_id' : docs[i].get('id'),                          
                          'chunk_id' : j,
                           'text': chunnked_text[j],
                           'embedded_text' : emb_text }
            embeddings_file.append(chunk_dict)
    with settings.embedded_chunks_path.open("w",encoding="utf8") as f:
        json.dump(embeddings_file,f,ensure_ascii=False,indent=2)

            
        
    
