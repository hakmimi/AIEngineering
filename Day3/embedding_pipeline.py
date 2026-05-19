from chunk import chunk_text
from embeddings import get_embedding
import json

with open("data/docs.json",'+r',encoding='utf8') as f:
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
    with open("data/embedded_chunks.json","w",encoding="utf8") as f:
        json.dump(embeddings_file,f,ensure_ascii=False,indent=2)

            
        
    