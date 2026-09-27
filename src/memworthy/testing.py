"""Run a policy's built-in tests (or expanded contrast pairs) against a judge."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from memworthy.gate import Gate
from memworthy.judges.base import Judge
from memworthy.ledger import MemoryLedger
from memworthy.models import Candidate, Decision, Memory, SourceRef
from memworthy.policy.loader import Policy
from memworthy.policy.schema import PolicyTest
from memworthy.stores.dict import DictStore

EXISTING_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


@dataclass
class TestResult:
    """Outcome of one policy test."""

    index: int
    test: PolicyTest
    decision: Decision
    passed: bool
    reason: str = ""


def test_candidate(test: PolicyTest) -> Candidate:
    """The candidate a PolicyTest describes."""
    return Candidate(
        id="test-" + hashlib.sha256(
            f"{test.input}|{test.role}|{test.context}".encode()).hexdigest()[:16],
        text=test.input,
        subject=test.subject,
        source=SourceRef(role=test.role, text=test.source_text or test.input),
        context=test.context,
        metadata=dict(test.metadata),
    )


def existing_memories(policy: Policy, test: PolicyTest) -> list[Memory]:
    """Seed memories for a test; they take the policy's first type."""
    type_ = "fact" if "fact" in policy.spec.types else next(iter(policy.spec.types))
    return [
        Memory(id=f"e{i}", text=text, type=type_, subject=test.subject,
               created_at=EXISTING_TIME, updated_at=EXISTING_TIME)
        for i, text in enumerate(test.existing)
    ]


def check_result(index: int, test: PolicyTest, decision: Decision) -> TestResult:
    """Compare a decision with the test's expectations."""
    if decision.error:
        return TestResult(index, test, decision, False, f"error: {decision.error}")
    if decision.action not in test.expected:
        return TestResult(index, test, decision, False,
                          f"expected {' or '.join(test.expected)}, got {decision.action}")
    if test.expect_type and decision.type != test.expect_type:
        return TestResult(index, test, decision, False,
                          f"expected type {test.expect_type}, got {decision.type}")
    return TestResult(index, test, decision, True)


async def run_one(policy: Policy, judge: Judge, index: int, test: PolicyTest) -> TestResult:
    """Run one test in a fresh store seeded with its existing memories."""
    store = DictStore(existing_memories(policy, test))
    gate = Gate(policy, store, judge=judge, ledger=MemoryLedger(), apply=False)
    [decision] = await gate.aevaluate([test_candidate(test)])
    return check_result(index, test, decision)


async def run_tests(policy: Policy, judge: Judge, tests: list[PolicyTest] | None = None,
                    concurrency: int = 8) -> list[TestResult]:
    """Run tests concurrently; results keep test order."""
    items = policy.spec.tests if tests is None else tests
    sem = asyncio.Semaphore(concurrency)

    async def guarded(i: int, t: PolicyTest) -> TestResult:
        async with sem:
            return await run_one(policy, judge, i, t)

    return list(await asyncio.gather(*(guarded(i, t) for i, t in enumerate(items))))
