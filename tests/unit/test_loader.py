from __future__ import annotations

from pathlib import Path

import pytest

from memgate.checks.registry import register_rule
from memgate.policy.loader import (
    PolicyError,
    load_policy,
    load_policy_text,
    template_names,
)
from memgate.policy.schema import CheckSignal, ModelSignal, PolicySpec, json_schema
from tests.unit.policies import BASIC


def test_basic_loads_and_normalizes() -> None:
    p = load_policy_text(BASIC, "basic.yaml")
    assert p.name == "basic"
    assert p.version == "1.0"  # float version coerced to string
    assert isinstance(p.spec.signals["durable"], ModelSignal)
    assert p.spec.signals["durable"].kind == "noul"
    assert isinstance(p.spec.signals["from_user"], CheckSignal)
    assert p.rules[-1].rule.when is None
    assert p.rules[-1].id == "rules[8]"
    assert p.rules[0].id == "secrets"
    assert p.uses_conflict
    # Pre-judge rules reference only checks and candidate fields.
    assert [r.pre_judge for r in p.rules[:3]] == [True, True, False]
    assert list(p.model_signals) == ["durable", "mood", "sensitivity", "only_intent"]
    assert set(p.check_signals) == {"from_user", "secret", "timing"}


def test_line_of() -> None:
    p = load_policy_text(BASIC, "basic.yaml")
    assert p.line_of(("rules", 1)) == 17
    assert p.line_of(("rules", 1, "nope")) == 17
    assert p.line_of(("nothing",)) is None


def _replace(old: str, new: str) -> str:
    assert old in BASIC
    return BASIC.replace(old, new)


def _line_of(text: str, needle: str) -> int:
    return next(i for i, line in enumerate(text.splitlines(), 1) if needle in line)


@pytest.mark.parametrize(
    "old,new,needle,msg",
    [
        ("  - {name: weak, when: \"durable < 0.6\", then: reject}",
         "  - {name: weak, when: \"durable < < 0.6\", then: reject}", "name: weak", "expected"),
        ("  - {name: weak, when: \"durable < 0.6\", then: reject}",
         "  - {name: weak, when: \"durabl < 0.6\", then: reject}", "name: weak", "unknown name"),
        ("  - {name: weak, when: \"durable < 0.6\", then: reject}",
         "  - {name: weak, when: \"durable < 0.6\", then: explode}", "name: weak", "then"),
        ("  - {name: temp, when: \"type in ['temporary', 'intent']\", then: reject}",
         "  - {name: temp, when: \"type in ['temporary', 'plan']\", then: reject}",
         "name: temp", "not one of"),
        ("  timing: {check: date_parse}", "  timing: {check: no_such_check}",
         "timing:", "unknown check"),
        ("  mood: {choice: \"What mood?\", options: {happy: Happy, sad: Sad}}",
         "  mood: {choice: \"What mood?\", options: {happy: Happy}}", "mood:", "2-20 options"),
        ("  sensitivity: {score: \"How sensitive?\", levels: [Low, Medium, High]}",
         "  sensitivity: {score: \"How sensitive?\", levels: [Low]}", "sensitivity:",
         "2-10 levels"),
        ("  durable: {noul: \"Will this still be true in a year?\"}",
         "  Durable: {noul: \"Will this still be true in a year?\"}", "Durable:", "must match"),
        ("  durable: {noul: \"Will this still be true in a year?\"}",
         "  conflict: {noul: \"Will this still be true in a year?\"}", "conflict:", "reserved"),
        ("  durable: {noul: \"Will this still be true in a year?\"}",
         "  durable: {noul: \"x\", choice: \"y\"}", "durable:", "more than one kind"),
        ("  durable: {noul: \"Will this still be true in a year?\"}",
         "  durable: {prompt: \"x\"}", "durable:", "needs one of"),
        ("  durable: {noul: \"Will this still be true in a year?\"}",
         "  durable: {noul: \"x\", options: {a: A, b: B}}", "durable:", "takes no options"),
        ("  only_intent: {noul: \"Is it firm?\", applies_to: [intent]}",
         "  only_intent: {noul: \"Is it firm?\", applies_to: [plan]}", "only_intent:",
         "unknown type"),
        ("  - {name: weak, when: \"durable < 0.6\", then: reject}",
         "  - {name: weak, if: \"durable < 0.6\", then: reject}", "name: weak", "use 'when:'"),
        ("  - {name: weak, when: \"durable < 0.6\", then: reject}",
         "  - {name: weak, then: reject}", "name: weak", "needs 'when:'"),
        ("  - {name: weak, when: \"durable < 0.6\", then: reject}",
         "  - {name: weak, when: \"durable < 0.6\", then: store_labeled}", "name: weak",
         "need a 'label'"),
        ("  - {name: weak, when: \"durable < 0.6\", then: reject}",
         "  - {name: weak, when: \"durable < 0.6\", then: reject, restore: true}", "name: weak",
         "only allowed on supersede"),
        ("  - {name: weak, when: \"durable < 0.6\", then: reject}",
         "  - {name: weak, when: \"py:not_registered\", then: reject}", "name: weak",
         "unknown Python rule"),
        ("  - {name: weak, when: \"durable < 0.6\", then: reject}",
         "  - {else: reject}", "else: reject", "exactly one 'else'"),
        ("  - {else: store}", "  - {name: last, when: \"durable > 0.1\", then: store}",
         "name: last", "exactly one 'else'"),
        ("  - {else: store}", "  - {else: store, when: \"x\"}", "else: store", "cannot have"),
        ("  - {else: store}", "  - 3", "  - 3", "must be a mapping"),
        ("  durable: {noul: \"Will this still be true in a year?\"}", "  durable: 3",
         "durable: 3", "must be a mapping"),
        ("tests:\n  - {input: \"I live in Lahore\", expect: store}",
         "tests:\n  - {input: \"I live in Lahore\", expect: store, expect_type: nope}",
         "expect_type", "not a declared type"),
        ("types:\n", "on_error: update\ntypes:\n", "on_error", "on_error must be"),
    ],
)
def test_errors_report_line(old: str, new: str, needle: str, msg: str) -> None:
    text = _replace(old, new)
    with pytest.raises(PolicyError, match=msg) as info:
        load_policy_text(text, "bad.yaml")
    assert info.value.file == "bad.yaml"
    assert info.value.line == _line_of(text, needle), str(info.value)
    assert str(info.value).startswith(f"bad.yaml:{info.value.line}:")


def test_yaml_syntax_error_reports_line() -> None:
    text = BASIC.replace("  fact: A durable fact", "  fact: [A durable fact")
    with pytest.raises(PolicyError, match="YAML syntax error") as info:
        load_policy_text(text, "syntax.yaml")
    # The unclosed flow sequence is reported at or just after the offending line.
    assert info.value.line is not None
    assert _line_of(text, "fact: [") <= info.value.line <= _line_of(text, "fact: [") + 2


def test_yaml_syntax_error_exact_line() -> None:
    text = "policy: x\nversion: '1'\ntypes:\n  a: A\n  b: B\n rules: oops\n"
    with pytest.raises(PolicyError) as info:
        load_policy_text(text, "x.yaml")
    assert info.value.line == 6


def test_update_requires_conflict_enabled() -> None:
    text = BASIC + "conflict: {enabled: false}\n"
    with pytest.raises(PolicyError, match=r"require conflict\.enabled") as info:
        load_policy_text(text, "c.yaml")
    assert info.value.line == _line_of(text, "name: upd")


def test_not_a_mapping_and_missing_types() -> None:
    with pytest.raises(PolicyError, match="YAML mapping"):
        load_policy_text("- a\n- b\n")
    with pytest.raises(PolicyError, match="at least one type"):
        load_policy_text("policy: x\nversion: '1'\ntypes: {}\nrules:\n  - {else: store}\n")
    with pytest.raises(PolicyError, match="rules"):
        load_policy_text("policy: x\nversion: '1'\ntypes: {a: A}\n")
    with pytest.raises(PolicyError, match="signals"):
        load_policy_text("policy: x\nversion: '1'\ntypes: {a: A}\nsignals: [1]\n"
                         "rules:\n  - {else: store}\n")
    with pytest.raises(PolicyError, match="at least one rule"):
        load_policy_text("policy: x\nversion: '1'\ntypes: {a: A}\nrules: []\n")


def test_bad_type_name() -> None:
    with pytest.raises(PolicyError, match="type name"):
        load_policy_text("policy: x\nversion: '1'\ntypes: {Bad: A}\nrules:\n  - {else: store}\n")


def test_py_rule_allowed_when_registered() -> None:
    register_rule("always_review", lambda ctx: "review")
    text = _replace("  - {name: weak, when: \"durable < 0.6\", then: reject}",
                    "  - {name: weak, when: \"py:always_review\", then: reject}")
    p = load_policy_text(text)
    assert p.rules[5].py == "always_review"


def test_load_policy_from_path_spec_and_policy(tmp_path: Path) -> None:
    f = tmp_path / "p.yaml"
    f.write_text(BASIC)
    p = load_policy(f)
    assert p.source == str(f)
    assert load_policy(p) is p
    spec = PolicySpec.model_validate({
        "policy": "s", "version": "1", "types": {"a": "A"},
        "rules": [{"when": None, "then": "store"}],
    })
    assert load_policy(spec).name == "s"
    with pytest.raises(PolicyError, match="not found"):
        load_policy(tmp_path / "missing.yaml")
    with pytest.raises(PolicyError, match="not found"):
        load_policy("no-such-template")


def test_templates_are_discoverable() -> None:
    names = template_names()
    for name in names:
        assert load_policy(name).name == name


def test_json_schema() -> None:
    schema = json_schema()
    assert schema["title"] == "PolicySpec"
    assert "rules" in schema["properties"]


def test_choice_option_names_and_score_attrs() -> None:
    text = _replace("  - {name: sensitive, when: \"sensitivity >= 1.5\", then: review}",
                    "  - {name: sensitive, when: \"sensitivity.top == 'High' or "
                    "sensitivity.p > 0.9 or mood.happy > 0.5 or mood.p > 0.5 or "
                    "candidate.role == 'user' or meta.foo.bar == 1\", then: review}")
    load_policy_text(text)
    bad = _replace("  - {name: sensitive, when: \"sensitivity >= 1.5\", then: review}",
                   "  - {name: sensitive, when: \"mood.angry > 0.5\", then: review}")
    with pytest.raises(PolicyError, match="unknown name"):
        load_policy_text(bad)
    bad = _replace("  - {name: sensitive, when: \"sensitivity >= 1.5\", then: review}",
                   "  - {name: sensitive, when: \"candidate.role == 'robot'\", then: review}")
    with pytest.raises(PolicyError, match="not one of"):
        load_policy_text(bad)
    bad = BASIC.replace("  mood: {choice: \"What mood?\", options: {happy: Happy, sad: Sad}}",
                        "  mood: {choice: \"What mood?\", options: {Happy: H, sad: S}}")
    with pytest.raises(PolicyError, match="option 'Happy'"):
        load_policy_text(bad)
