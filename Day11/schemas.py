from pydantic import BaseModel, Field

from config import settings


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=settings.max_query_length)
    top_k: int = Field(default=4, ge=1, le=settings.max_top_k)
    category: str | None = Field(default=None, max_length=50, description="Optional metadata filter, e.g. nature")
    topic: str | None = Field(default=None, max_length=100, description="Optional exact topic filter")

    def filters(self) -> dict | None:
        return {k: v for k, v in (("category", self.category), ("topic", self.topic)) if v} or None
