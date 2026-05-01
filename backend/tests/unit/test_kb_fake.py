"""Tests for the KnowledgeBase interface contract via the in-memory fake.

The Fake is what the rest of the test suite uses, so its behaviour must be
exercised carefully here so other tests can rely on it.
"""

from __future__ import annotations

import pytest

from app.kb.fake import FakeKB


@pytest.fixture
def kb() -> FakeKB:
    return FakeKB()


class TestRemember:
    async def test_remember_returns_id(self, kb: FakeKB) -> None:
        mid = await kb.remember("hello world")
        assert isinstance(mid, str) and mid

    async def test_remember_assigns_unique_ids(self, kb: FakeKB) -> None:
        a = await kb.remember("a")
        b = await kb.remember("b")
        assert a != b

    async def test_metadata_is_stored(self, kb: FakeKB) -> None:
        mid = await kb.remember("with meta", metadata={"source": "doc1.pdf"})
        records = kb.dump()
        assert records[0]["id"] == mid
        assert records[0]["metadata"] == {"source": "doc1.pdf"}


class TestRecall:
    async def test_empty_kb_returns_empty(self, kb: FakeKB) -> None:
        assert await kb.recall("anything") == []

    async def test_recall_returns_substring_matches(self, kb: FakeKB) -> None:
        await kb.remember("the cat sat on the mat")
        await kb.remember("dogs are great pets")
        await kb.remember("a cat is a small feline")

        results = await kb.recall("cat")
        contents = {r["content"] for r in results}
        assert "the cat sat on the mat" in contents
        assert "a cat is a small feline" in contents
        assert "dogs are great pets" not in contents

    async def test_recall_limit(self, kb: FakeKB) -> None:
        for i in range(10):
            await kb.remember(f"cat number {i}")
        results = await kb.recall("cat", k=3)
        assert len(results) == 3

    async def test_recall_case_insensitive(self, kb: FakeKB) -> None:
        await kb.remember("The Eiffel Tower is in Paris")
        results = await kb.recall("eiffel")
        assert len(results) == 1


class TestHealth:
    async def test_fake_kb_is_always_healthy(self, kb: FakeKB) -> None:
        assert await kb.health() is True

    async def test_fake_kb_can_be_marked_unhealthy(self, kb: FakeKB) -> None:
        kb.set_healthy(False)
        assert await kb.health() is False
