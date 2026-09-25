"""Bounded retrieval and deterministic rank fusion across query variants.

Inspired by JoyDataAgent's bounded TableRAG retrieval. RRF uses ranks, so
Qdrant cosine scores and Elasticsearch BM25 scores need not be comparable.
No candidate is discarded here; metadata completion and filtering follow.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")
U = TypeVar("U")
MAX_TERMS = 24


def retrieval_terms(query: str, keywords: list[str], expanded: object) -> list[str]:
    if not isinstance(expanded, list) or any(not isinstance(x, str) for x in expanded):
        raise ValueError("检索词扩展格式无效，请重试。")
    # Preserve the full question, then semantic expansion and Jieba keywords.
    return list(dict.fromkeys(x.strip() for x in [query, *expanded, *keywords] if x.strip()))[:MAX_TERMS]


async def bounded_map(items: Sequence[T], operation: Callable[[T], Awaitable[U]], concurrency: int = 4) -> list[U]:
    semaphore = asyncio.Semaphore(concurrency)

    async def call(item):
        async with semaphore:
            return await operation(item)

    tasks = [asyncio.create_task(call(item)) for item in items]
    try:
        return await asyncio.gather(*tasks)
    finally:
        # A failed or cancelled query must not leave background requests running.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def fuse_ranked(lists: Sequence[Sequence[T]]) -> list[T]:
    entities, scores = {}, {}
    for hits in lists:
        seen = set()
        rank = 0
        for hit in hits:
            if hit.id in seen:
                continue  # Synonym vector points are not independent evidence.
            seen.add(hit.id)
            rank += 1
            entities.setdefault(hit.id, hit)
            scores[hit.id] = scores.get(hit.id, 0) + 1 / (60 + rank)
    return [entities[key] for key in sorted(entities, key=lambda key: (-scores[key], key))]


async def vector_recall(terms, embedding_client, repository):
    async with asyncio.timeout(30):
        vectors = await embedding_client.aembed_documents(terms)
        if len(vectors) != len(terms):
            raise ValueError("Embedding 返回数量与检索词不一致")
        return fuse_ranked(await bounded_map(vectors, repository.search))


async def value_recall(terms, repository):
    async with asyncio.timeout(30):
        return fuse_ranked(await bounded_map(terms, repository.search))
