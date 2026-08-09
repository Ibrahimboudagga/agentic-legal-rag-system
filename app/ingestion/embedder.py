from __future__ import annotations

import os
from functools import lru_cache
from typing import List

import numpy as np


@lru_cache(maxsize=1)
def _get_model():
    """Lazy-load sentence-transformers model."""
    from sentence_transformers import SentenceTransformer

    model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    return SentenceTransformer(model_name)


def get_embedding_dim() -> int:
    """Return the embedding dimension for the configured model."""
    return int(os.getenv("EMBEDDING_DIM", "384"))


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a list of texts and return as list of float vectors."""
    model = _get_model()
    embeddings = model.encode(
        texts,
        show_progress_bar=False,
        normalize_embeddings=True,
        batch_size=32,
    )
    return embeddings.tolist()


def embed_query(query: str) -> List[float]:
    """Embed a single query string."""
    return embed_texts([query])[0]
