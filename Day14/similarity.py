import math

def cosine_similarity(a: list[float], b :list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Vectors must have the same dimension")

    dot_product = sum(x * y for x,y in zip(a,b))
    norm_a = math.sqrt(sum(x * x for x in a ))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        raise ValueError("Vectors must not be zero vectors")

    return ( dot_product / (norm_a * norm_b))
