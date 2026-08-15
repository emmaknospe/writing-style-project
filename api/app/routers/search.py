"""Corpus search for the source picker.

Same two calls the agent's search_corpus tool makes (app/agent.py), but it
returns structured hits including the Qdrant point id, so a hit can be posted
straight back to POST /api/sections/{id}/sources.
"""
import asyncio

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.embeddings import embed_query
from app.schemas import SearchHit, SearchRequest
from app.vector_store import search as vector_search

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=list[SearchHit])
async def search_corpus(payload: SearchRequest):
    try:
        vector = await asyncio.to_thread(embed_query, payload.query)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="embedding request failed") from exc

    hits = await asyncio.to_thread(vector_search, vector, payload.top_k or settings.rag_top_k)
    return [SearchHit.model_validate(hit) for hit in hits]
