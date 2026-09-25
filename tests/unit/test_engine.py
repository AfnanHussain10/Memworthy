from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from memgate import Candidate, DictStore, Gate, MemoryLedger, MockJudge, rule
from memgate.engine import RuleContext, build_questions, render_state
from memgate.judges.base import JudgeResult, Question
from memgate.models import Memory, SourceRef
from memgate.policy.loader import load_policy_text
from memgate.stores.base import StoreError
from tests.unit.policies import BASIC

FACT = {"type": "fact", "durable": 0.9, "sensitivity": 0.2, "mood": "happy"}


def gate(judge: MockJudge, store: DictStore | None = None, policy: str = BASIC,
         apply: bool = True) -> tuple[Gate, DictStore, MemoryLedger]:
    store = store or DictStore()
    ledger = MemoryLedger()
    return Gate(load_policy_text(policy), store, judge=judge, ledger=ledger,
                apply=apply), store, ledger


def mem(text: str, id_: str = "m1", **meta: object) -> Memory:
    now = datetime.now(timezone.utc)
    return Memory(id=id_, text=text, type="fact", created_at=now, updated_at=now,
                  metadata=dict(meta))


def test_store_path_records_signals() -> None:
    judge = MockJudge(defaults=FACT)
    g, store, ledger = gate(judge)
    [d] = g.evaluate([Candidate.from_text("I live in Lahore")])
    assert d.action == "store" and d.rule == "rules[8]"
    assert d.type == "fact"
    assert d.signals["durable"] is not None and d.signals["durable"].value == 0.9
    assert d.signals["from_user"] is not None and d.signals["from_user"].value is True
    assert d.signals["timing"] is not None and d.signals["timing"].value == "none"
    assert d.signals["only_intent"] is None  # masked by applies_to
    assert d.signals["conflict"] is None  # empty store -> no conflict question
    assert d.judge == "mock" and d.model == "mock"
    assert d.policy == "basic" and d.policy_version == "1.0"
    assert len(store.memories) == 1
    assert ledger.decisions == [d]
    assert [q.name for q in judge.calls[0][1]] == [
        "type", "durable", "mood", "sensitivity", "only_intent"]


def test_rule_order_first_match_wins() -> None:
    # temporary is rejected by 'temp' even though durable is low too.
    g, *_ = gate(MockJudge(defaults={**FACT, "type": "temporary", "durable": 0.1}))
    [d] = g.evaluate([Candidate.from_text("In Dubai")])
    assert (d.action, d.rule) == ("reject", "temp")
    g, *_ = gate(MockJudge(defaults={**FACT, "durable": 0.1}))
    assert g.evaluate([Candidate.from_text("x")])[0].rule == "weak"
    g, *_ = gate(MockJudge(defaults={**FACT, "sensitivity": "High"}))
    assert g.evaluate([Candidate.from_text("x")])[0].rule == "sensitive"


def test_applies_to_masking_changes_outcome() -> None:
    g, *_ = gate(MockJudge(defaults={**FACT, "type": "intent", "only_intent": 0.95}))
    [d] = g.evaluate([Candidate.from_text("I plan to move")])
    assert d.rule == "firm_intent"
    assert d.signals["only_intent"] is not None
    g, *_ = gate(MockJudge(defaults={**FACT, "type": "fact", "only_intent": 0.95}))
    [d] = g.evaluate([Candidate.from_text("I live here")])
    assert d.signals["only_intent"] is None


def test_short_circuit_skips_judge() -> None:
    judge = MockJudge(defaults=FACT)
    g, store, _ = gate(judge)
    [d] = g.evaluate([Candidate.from_text("I am an assistant guess", role="assistant")])
    assert (d.action, d.rule) == ("reject", "not_user")
    assert judge.calls == []
    assert d.type == "unknown" and d.model is None
    assert d.signals["durable"] is None
    assert store.memories == {}


def test_future_date_rejected_by_code_check() -> None:
    g, *_ = gate(MockJudge(defaults=FACT))
    [d] = g.evaluate([Candidate.from_text("Flying to Riyadh tomorrow")])
    assert (d.action, d.rule) == ("reject", "future")


def test_secret_redacted_before_judge() -> None:
    judge = MockJudge(defaults=FACT)
    g, store, ledger = gate(judge)
    key = "sk-proj-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4"
    [d] = g.evaluate([Candidate.from_text(f"My OpenAI key is {key}",
                                          context=f"earlier: {key}")])
    assert d.action == "redact"
    assert d.redacted_text == "My OpenAI key is [REDACTED:openai]"
    assert "redacted" in d.labels
    state, _ = judge.calls[0]
    assert key not in state
    assert key not in d.candidate.text + d.candidate.context + d.candidate.source.text
    assert key not in ledger.to_jsonl()
    [m] = store.memories.values()
    assert m.text == "My OpenAI key is [REDACTED:openai]"


def test_conflict_update_builds_patch() -> None:
    store = DictStore([mem("I live in Dubai")])
    judge = MockJudge(defaults={**FACT, "conflict": {"m0": 0.9, "none": 0.1}})
    g, store, _ = gate(judge, store)
    [d] = g.evaluate([Candidate.from_text("I moved to Riyadh last week, I live in Riyadh",
                                          context="user: I live in Dubai")])
    assert d.action == "update" and d.rule == "upd"
    assert d.target is not None and d.target.id == "m1"
    assert d.patch is not None and d.patch.old_text == "I live in Dubai"
    assert store.memories["m1"].text.startswith("I moved to Riyadh")
    assert store.memories["m1"].metadata["previous_text"] == "I live in Dubai"
    q = next(q for q in judge.calls[0][1] if q.name == "conflict")
    assert q.options == {"m0": "I live in Dubai",
                         "none": "No existing memory is updated or contradicted"}


def test_conflict_none_does_not_update() -> None:
    store = DictStore([mem("I live in Dubai")])
    g, store, _ = gate(MockJudge(defaults={**FACT, "conflict": "none"}), store)
    [d] = g.evaluate([Candidate.from_text("I live in Dubai and love it")])
    assert d.action == "store" and d.target is None


RESTORE = BASIC.replace(
    "  - {name: upd, when: \"conflict and conflict.p > 0.7\", then: update}",
    "  - {name: retract, when: \"meta.retract == true and conflict\", then: supersede, "
    "restore: true}\n"
    "  - {name: upd, when: \"conflict and conflict.p > 0.7\", then: update}")


def test_supersede_restore_rolls_back_update() -> None:
    store = DictStore([mem("I moved to Riyadh", previous_text="I live in Dubai")])
    judge = MockJudge(defaults={**FACT, "conflict": {"m0": 0.9, "none": 0.1}})
    g, store, _ = gate(judge, store, policy=RESTORE)
    [d] = g.evaluate([Candidate.from_text("Actually I'm only considering Riyadh",
                                          metadata={"retract": True})])
    assert d.action == "supersede" and d.patch is not None and d.patch.restore
    [current] = store.memories.values()
    assert current.text == "I live in Dubai" and current.type == "fact"
    assert store.archive["m1"].metadata["superseded_by"] == current.id


def test_supersede_restore_without_history_archives_only() -> None:
    store = DictStore([mem("I live in Riyadh")])
    judge = MockJudge(defaults={**FACT, "conflict": {"m0": 0.9, "none": 0.1}})
    g, store, _ = gate(judge, store, policy=RESTORE)
    [d] = g.evaluate([Candidate.from_text("Actually no, not Riyadh",
                                          metadata={"retract": True})])
    assert d.action == "supersede" and d.patch is None
    assert store.memories == {} and "m1" in store.archive


def test_judge_error_uses_on_error() -> None:
    g, store, ledger = gate(MockJudge(fail=True))
    [d] = g.evaluate([Candidate.from_text("I live in Lahore")])
    assert d.action == "review" and d.rule == "on_error"
    assert d.error and "fail" in d.error
    assert store.memories == {} and ledger.decisions == [d]


def test_unknown_option_is_judge_error() -> None:
    g, *_ = gate(MockJudge(defaults={**FACT, "type": "banana"}))
    [d] = g.evaluate([Candidate.from_text("I live in Lahore")])
    assert d.action == "review" and d.error and "banana" in d.error


def test_missing_answer_is_judge_error() -> None:
    class Partial:
        name = "partial"

        async def judge(self, state: str, questions: list[Question]) -> JudgeResult:
            raise KeyError("boom")

    g = Gate(load_policy_text(BASIC), DictStore(), judge=Partial(), ledger=MemoryLedger())
    [d] = g.evaluate([Candidate.from_text("I live in Lahore")])
    assert d.action == "review" and d.error and "KeyError" in d.error


def test_dry_run_does_not_apply() -> None:
    g, store, ledger = gate(MockJudge(defaults=FACT), apply=False)
    [d] = g.evaluate([Candidate.from_text("I live in Lahore")])
    assert d.action == "store" and store.memories == {} and ledger.decisions


def test_store_failure_is_recorded_and_raised() -> None:
    class Broken(DictStore):
        async def apply(self, decision):  # type: ignore[no-untyped-def]
            raise StoreError("disk full")

    ledger = MemoryLedger()
    g = Gate(load_policy_text(BASIC), Broken(), judge=MockJudge(defaults=FACT), ledger=ledger)
    with pytest.raises(StoreError):
        g.evaluate([Candidate.from_text("I live in Lahore")])
    assert ledger.decisions[0].error == "store apply failed: disk full"


def test_ledger_failure_never_blocks() -> None:
    class BadLedger(MemoryLedger):
        def record(self, decision):  # type: ignore[no-untyped-def]
            raise OSError("read-only")

    g = Gate(load_policy_text(BASIC), DictStore(), judge=MockJudge(defaults=FACT),
             ledger=BadLedger())
    assert g.evaluate([Candidate.from_text("I live in Lahore")])[0].action == "store"


def test_py_rule() -> None:
    @rule("lahore_review")
    def lahore(ctx: RuleContext) -> str | None:
        return "review" if "Lahore" in ctx.candidate.text else None

    text = BASIC.replace("  - {name: weak, when: \"durable < 0.6\", then: reject}",
                         "  - {name: py, when: \"py:lahore_review\", then: reject}")
    g, *_ = gate(MockJudge(defaults=FACT), policy=text)
    assert g.evaluate([Candidate.from_text("I live in Lahore")])[0].action == "review"
    assert g.evaluate([Candidate.from_text("I live in Karachi")])[0].action == "store"


def test_update_without_target_falls_back_to_store() -> None:
    text = BASIC.replace("  - {name: weak, when: \"durable < 0.6\", then: reject}",
                         "  - {name: weak, when: \"durable > 0.8\", then: update}")
    g, _, _ = gate(MockJudge(defaults=FACT), policy=text)
    [d] = g.evaluate([Candidate.from_text("I live in Lahore")])
    assert d.action == "store" and d.warnings


def test_runtime_warning_recorded() -> None:
    text = BASIC.replace("  - {name: weak, when: \"durable < 0.6\", then: reject}",
                         "  - {name: weak, when: \"meta.n > 3\", then: reject}")
    g, *_ = gate(MockJudge(defaults=FACT), policy=text)
    [d] = g.evaluate([Candidate.from_text("x", metadata={"n": "many"})])
    assert d.warnings and d.action == "store"


def test_store_labeled_and_single_type() -> None:
    text = """\
policy: one
version: "2"
types: {note: A note}
signals:
  useful: {noul: "Useful?"}
rules:
  - {when: "useful < 0.5", then: store_labeled, label: weak}
  - {else: store}
"""
    judge = MockJudge(defaults={"useful": 0.1})
    g, store, _ = gate(judge, policy=text)
    [d] = g.evaluate([Candidate.from_text("hello")])
    assert d.action == "store_labeled" and d.labels == ["weak"] and d.type == "note"
    assert [q.name for q in judge.calls[0][1]] == ["useful"]
    [m] = store.memories.values()
    assert m.labels == ["weak"]


def test_same_subject_runs_in_order_and_output_order_kept() -> None:
    order: list[str] = []

    class Slow(MockJudge):
        async def judge(self, state, questions):  # type: ignore[no-untyped-def]
            text = state.splitlines()[0]
            await asyncio.sleep(0.02 if "first" in text else 0.0)
            order.append(text)
            return await super().judge(state, questions)

    g, *_ = gate(Slow(defaults=FACT))
    cands = [Candidate.from_text("first a"), Candidate.from_text("second b"),
             Candidate.from_text("other", subject="bob")]
    ds = g.evaluate(cands)
    assert [d.candidate.text for d in ds] == ["first a", "second b", "other"]
    assert order.index("Candidate memory: first a") < order.index("Candidate memory: second b")


def test_evaluate_inside_loop_raises() -> None:
    g, *_ = gate(MockJudge(defaults=FACT))

    async def inner() -> None:
        with pytest.raises(RuntimeError, match="event loop"):
            g.evaluate([Candidate.from_text("x")])

    asyncio.run(inner())


def test_render_state_and_questions() -> None:
    c = Candidate(text="Uses pytest", subject="project",
                  source=SourceRef(role="assistant", text="We use pytest here"),
                  context="user: what test runner?",
                  metadata={"files_read": ["a.py", "b.py"], "outcome": "tests_passed",
                            "dependency_versions": {"pytest": "8.0"}, "timestamp": "x"})
    assert render_state(c) == (
        "Candidate memory: Uses pytest\nAbout: project\nSource: assistant message\n"
        "Original message: We use pytest here\nContext: user: what test runner?\n"
        "Episode outcome: tests_passed\nFiles read in session: a.py, b.py\n"
        "Dependency versions: pytest 8.0")
    p = load_policy_text(BASIC)
    qs = build_questions(p, [])
    assert qs[0].name == "type" and qs[0].options == dict(p.spec.types)


def test_default_judge_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from memgate.judges.base import JudgeError

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(JudgeError, match="TYPESAFE_API_KEY"):
        Gate(load_policy_text(BASIC), DictStore(), ledger=MemoryLedger())


def test_ingest_messages() -> None:
    g, _, _ = gate(MockJudge(defaults=FACT))
    ds = g.ingest_messages([
        {"role": "user", "content": "I live in Lahore"},
        {"role": "assistant", "content": "Nice!"},
        {"role": "user", "content": "I work as a teacher"},
    ])
    assert [d.candidate.text for d in ds] == ["I live in Lahore", "I work as a teacher"]
    assert "assistant: Nice!" in ds[1].candidate.context
