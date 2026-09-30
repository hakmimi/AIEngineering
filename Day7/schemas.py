from pydantic import BaseModel, Field

from config import settings


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=settings.max_query_length)
    top_k: int = Field(default=4, ge=1, le=settings.max_top_k)
