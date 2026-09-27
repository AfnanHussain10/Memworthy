from __future__ import annotations

from typing import Any

import pytest

from memworthy.policy.expr import (
    ExprError,
    NameType,
    compile_expr,
    parse,
    tokenize,
    truthy,
)


class Scope:
    def __init__(self, **values: Any) -> None:
        self.values = values
        self.warnings: list[str] = []

    def lookup(self, parts: tuple[str, ...]) -> Any:
        return self.values.get(".".join(parts))

    def warn(self, message: str) -> None:
        self.warnings.append(message)


KINDS = {
    "type": NameType("string", frozenset({"fact", "temporary"})),
    "durable": NameType("number"),
    "flag": NameType("bool"),
    "mood": NameType("string", frozenset({"happy", "sad"})),
    "meta.x": NameType("any"),
    "meta.tags": NameType("any"),
}


def resolve(parts: tuple[str, ...]) -> NameType:
    key = ".".join(parts)
    if key not in KINDS:
        raise ExprError(f"unknown name '{key}'")
    return KINDS[key]


def ev(expr: str, **values: Any) -> bool:
    return compile_expr(expr, resolve).evaluate(Scope(**values))


@pytest.mark.parametrize(
    "expr,values,expected",
    [
        ("durable > 0.5", {"durable": 0.7}, True),
        ("durable > 0.5", {"durable": 0.2}, False),
        ("durable >= 0.5 and flag", {"durable": 0.5, "flag": True}, True),
        ("durable < 0.5 or flag", {"durable": 0.9, "flag": False}, False),
        ("not flag", {"flag": False}, True),
        ("not not flag", {"flag": True}, True),
        ("type == 'fact'", {"type": "fact"}, True),
        ("type != 'fact'", {"type": "temporary"}, True),
        ("type in ['fact', 'temporary']", {"type": "fact"}, True),
        ("type not in ['fact']", {"type": "temporary"}, True),
        ("(durable > 0.5 or flag) and type == 'fact'", {"durable": 0.1, "flag": True,
                                                          "type": "fact"}, True),
        ("durable <= 1", {"durable": 1.0}, True),
        ("durable != 0.3", {"durable": 0.3}, False),
        ("flag == true", {"flag": True}, True),
        ("flag == false", {"flag": True}, False),
        ("meta.x == 'a\\'b'", {"meta.x": "a'b"}, True),
        ("meta.x == \"q\"", {"meta.x": "q"}, True),
        ("'go' in meta.x", {"meta.x": "gopher"}, True),
        ("durable > -1", {"durable": 0.0}, True),
        ("durable", {"durable": 0.51}, True),
        ("durable", {"durable": 0.5}, False),
        ("mood == 'happy'", {"mood": "happy"}, True),
        ("meta.tags == []", {"meta.tags": []}, True),
    ],
)
def test_evaluation(expr: str, values: dict[str, Any], expected: bool) -> None:
    assert ev(expr, **values) is expected


def test_precedence_and_binds_tighter_than_or() -> None:
    assert ev("flag or durable > 0.5 and durable < 0.1", flag=True, durable=0.9)
    assert not ev("(flag or durable > 0.5) and durable < 0.1", flag=True, durable=0.9)


def test_null_semantics() -> None:
    # A signal not evaluated is None: comparisons are false, 'not null' is true.
    assert not ev("durable > 0.5")
    assert not ev("durable < 0.5")
    assert not ev("durable != 0.5")
    assert not ev("type in ['fact']")
    assert not ev("type not in ['fact']")
    assert ev("not durable")
    assert not ev("flag")


def test_runtime_type_mismatch_warns() -> None:
    scope = Scope(**{"meta.x": "abc"})
    assert not compile_expr("meta.x > 3", resolve).evaluate(scope)
    assert scope.warnings
    scope = Scope(**{"meta.x": 3})
    assert not compile_expr("meta.x == 'a'", resolve).evaluate(scope)
    scope = Scope(**{"meta.x": 3})
    assert not compile_expr("'a' in meta.x", resolve).evaluate(scope)
    assert scope.warnings


def test_string_ordering() -> None:
    assert ev("meta.x < 'b'", **{"meta.x": "a"})


def test_truthy() -> None:
    assert truthy(True) and not truthy(False) and not truthy(None)
    assert truthy(0.9) and not truthy(0.2)
    assert truthy("past") and not truthy("none") and not truthy("")
    assert truthy([1]) and not truthy([])
    assert not truthy(object())


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",
        "__import__('os').system('ls')",
        "durable.__class__",
        "().__class__.__bases__",
        "open('x')",
        "durable; import os",
        "lambda: 1",
        "durable + 1",
        "durable * 2",
        "`ls`",
        "durable > 0.5 durable",
        "",
        "   ",
        "type == ",
        "(durable > 0.5",
        "[1, 2",
        "durable ** 2",
        "exec('1')",
        "durable if flag else 1",
        "{}",
        "a.b(",
    ],
)
def test_rejects_unsafe_or_invalid(expr: str) -> None:
    with pytest.raises(ExprError):
        compile_expr(expr, resolve)


def test_import_is_rejected_at_parse_time() -> None:
    # Rejected by the grammar itself, before any name resolution.
    with pytest.raises(ExprError):
        parse("__import__('os')")


def test_too_long_and_too_deep() -> None:
    with pytest.raises(ExprError):
        tokenize("durable > 0.5 and " * 200 + "flag")
    with pytest.raises(ExprError):
        parse("not " * 60 + "flag")
    with pytest.raises(ExprError):
        parse("(" * 60 + "flag" + ")" * 60)


@pytest.mark.parametrize(
    "expr,msg",
    [
        ("unknown > 1", "unknown name"),
        ("type == 'factoid'", "not one of"),
        ("type in ['fact', 'nope']", "not one of"),
        ("mood == 'angry'", "not one of"),
        ("durable == 'x'", "cannot compare"),
        ("type > 1", "cannot compare"),
        ("flag < true", "cannot order"),
        ("'factoid' == type", "not one of"),
    ],
)
def test_static_errors(expr: str, msg: str) -> None:
    with pytest.raises(ExprError, match=msg):
        compile_expr(expr, resolve)


def test_error_has_column() -> None:
    with pytest.raises(ExprError, match="column"):
        parse("durable > > 1")


def test_roots_and_names() -> None:
    c = compile_expr("durable > 0.5 and meta.x == 'a'", resolve)
    assert c.roots == {"durable", "meta"}
    assert ("meta", "x") in c.names
