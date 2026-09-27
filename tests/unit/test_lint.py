from __future__ import annotations

from memworthy.checks.registry import register_rule
from memworthy.policy.lint import LintWarning, lint, similarity
from memworthy.policy.loader import load_policy_text


def codes(text: str) -> list[str]:
    return [w.code for w in lint(load_policy_text(text))]


BASE = """\
policy: p
version: "1"
types:
{types}
signals:
  sure: {{noul: "Is the person certain about this statement?"}}
  mood: {{choice: "Which mood does the message express?", options: {{happy: Happy, sad: Sad}}}}
rules:
{rules}
  - {{else: store}}
"""


def test_too_many_types_and_clean() -> None:
    many = "\n".join(f"  t{i}: Kind number {i} of something distinct {i}" for i in range(13))
    rules = ("  - {when: \"sure < 0.5 or mood == 'sad' or mood.happy > 0.2\", "
             "then: reject}")
    assert "too-many-types" in codes(BASE.format(types=many, rules=rules))
    two = "  a: Apples and orchards\n  b: Bicycles and roads"
    assert codes(BASE.format(types=two, rules=rules)) == ["unused-conflict"]


def test_constant_and_threshold_rules() -> None:
    two = "  a: Apples and orchards\n  b: Bicycles and roads"
    rules = "\n".join([
        "  - {when: \"false\", then: reject}",
        "  - {when: \"not (sure < 0.0)\", then: review}",
        "  - {when: \"mood.p >= 1.0 and conflict.p > 2\", then: review}",
        "  - {when: \"sure <= 0.0 or mood.happy >= 1\", then: review}",
        "  - {when: \"true\", then: store}",
        "  - {when: \"mood == 'happy'\", then: update}",
    ])
    got = codes(BASE.format(types=two, rules=rules))
    assert got.count("constant-rule") == 2
    assert got.count("impossible-threshold") == 2  # 'sure < 0.0' and 'conflict.p > 2'
    assert "unused-conflict" not in got


def test_py_rules_skip_unused_signal_check() -> None:
    register_rule("lint_noop", lambda ctx: None)
    two = "  a: Apples and orchards\n  b: Bicycles and roads"
    rules = "  - {when: \"py:lint_noop\", then: review}\n  - {when: \"py:lint_noop\", then: reject}"
    got = codes(BASE.format(types=two, rules=rules))
    assert "unused-signal" not in got and "unreachable-rule" in got


def test_similarity_and_str() -> None:
    assert similarity("", "x") == 0.0
    assert similarity("a short trip", "a trip that is short") == 1.0
    assert str(LintWarning("x", "msg", 3)) == "line 3: [x] msg"
    assert str(LintWarning("x", "msg")) == "[x] msg"
