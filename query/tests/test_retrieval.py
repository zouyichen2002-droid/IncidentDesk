import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.retrieval import bounded_map, fuse_ranked, retrieval_terms, vector_recall


class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    def test_duplicate_aliases_do_not_outvote_independent_hits(self):
        a, b = SimpleNamespace(id="a"), SimpleNamespace(id="b")
        self.assertEqual([x.id for x in fuse_ranked([[a, a, a, b], [b]])], ["b", "a"])
        self.assertEqual([x.id for x in fuse_ranked([[b], [a]])], ["a", "b"])

    def test_question_is_retained_and_expansion_is_bounded(self):
        self.assertEqual(retrieval_terms("华东销售额", ["华东", "销售额"], ["成交额", " 成交额 "]), ["华东销售额", "成交额", "华东", "销售额"])
        self.assertEqual(len(retrieval_terms("原问题", [], [str(i) for i in range(100)])), 24)
        for bad in ("text", {"terms": []}, [12]):
            with self.assertRaises(ValueError):
                retrieval_terms("query", [], bad)

    async def test_concurrency_is_bounded_and_order_stable(self):
        active, peak = 0, 0

        async def operation(i):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.01)
                return i
            finally:
                active -= 1

        self.assertEqual(await bounded_map(list(range(10)), operation, 3), list(range(10)))
        self.assertEqual(peak, 3)
        self.assertEqual(active, 0)

    async def test_failure_cancels_other_requests(self):
        active = 0

        async def operation(i):
            nonlocal active
            active += 1
            try:
                if i == 0:
                    await asyncio.sleep(0)
                    raise RuntimeError("backend unavailable")
                await asyncio.sleep(10)
            finally:
                active -= 1

        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            await bounded_map([0, 1, 2, 3], operation)
        self.assertEqual(active, 0)

    async def test_embeddings_are_batched_and_partial_responses_rejected(self):
        embedding = SimpleNamespace(aembed_documents=AsyncMock(return_value=[[1], [2]]))
        repo = SimpleNamespace(search=AsyncMock(side_effect=lambda v: [SimpleNamespace(id=str(v[0]))]))
        result = await vector_recall(["amount", "sales"], embedding, repo)
        self.assertEqual([x.id for x in result], ["1", "2"])
        embedding.aembed_documents.assert_awaited_once_with(["amount", "sales"])
        embedding.aembed_documents.return_value = [[1]]
        with self.assertRaises(ValueError):
            await vector_recall(["amount", "sales"], embedding, repo)


if __name__ == "__main__":
    unittest.main()
