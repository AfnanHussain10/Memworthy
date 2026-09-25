"""Load-time checks for rule expressions: known names and compatible types."""

from __future__ import annotations

from typing import Any

from memgate.policy.expr import (
    BoolOp,
    Compare,
    ExprError,
    ListLit,
    Lit,
    Name,
    NameType,
    Node,
    Not,
    Resolver,
    _is_num,
)


def _static_kind(node: Node, resolve: Resolver) -> NameType:
    if isinstance(node, Lit):
        v = node.value
        if isinstance(v, bool):
            return NameType("bool")
        return NameType("number" if _is_num(v) else "string")
    if isinstance(node, Name):
        return resolve(node.parts)
    if isinstance(node, ListLit):
        return NameType("any")
    return NameType("bool")


def _check(node: Node, resolve: Resolver, names: set[tuple[str, ...]]) -> None:
    if isinstance(node, Name):
        try:
            resolve(node.parts)
        except ExprError as exc:
            raise ExprError(str(exc), node.pos) from None
        names.add(node.parts)
    elif isinstance(node, ListLit):
        for item in node.items:
            _check(item, resolve, names)
    elif isinstance(node, Not):
        _check(node.operand, resolve, names)
    elif isinstance(node, BoolOp):
        for o in node.operands:
            _check(o, resolve, names)
    elif isinstance(node, Compare):
        _check(node.left, resolve, names)
        _check(node.right, resolve, names)
        _check_compare(node, resolve)


def _check_compare(node: Compare, resolve: Resolver) -> None:
    left = _static_kind(node.left, resolve)
    if node.op in ("in", "not in"):
        if isinstance(node.right, ListLit):
            literals = [i for i in node.right.items if isinstance(i, Lit)]
            _check_allowed(left, [i.value for i in literals], node.pos)
        return
    right = _static_kind(node.right, resolve)
    pair = {left.kind, right.kind}
    if "any" not in pair and len(pair) > 1:
        raise ExprError(f"cannot compare {left.kind} with {right.kind}", node.pos)
    if node.op not in ("==", "!=") and pair == {"bool"}:
        raise ExprError(f"'{node.op}' cannot order booleans", node.pos)
    if isinstance(node.right, Lit):
        _check_allowed(left, [node.right.value], node.pos)
    if isinstance(node.left, Lit):
        _check_allowed(right, [node.left.value], node.pos)


def _check_allowed(kind: NameType, values: list[Any], pos: int) -> None:
    if kind.allowed is None:
        return
    for v in values:
        if isinstance(v, str) and v not in kind.allowed:
            options = ", ".join(sorted(kind.allowed))
            raise ExprError(f"{v!r} is not one of: {options}", pos)


def check_tree(node: Node, resolve: Resolver, names: set[tuple[str, ...]]) -> None:
    """Check every name and comparison in ``node``, collecting referenced names."""
    _check(node, resolve, names)
