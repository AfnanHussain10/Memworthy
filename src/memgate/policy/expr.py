"""Safe rule-expression language.

A hand-written tokenizer and recursive-descent parser compile expressions into a small tree of
Python closures. Nothing here uses ``eval``, ``exec``, ``compile`` or the ``ast`` module.

Grammar::

    expr       := or_expr
    or_expr    := and_expr ("or" and_expr)*
    and_expr   := not_expr ("and" not_expr)*
    not_expr   := "not" not_expr | comparison
    comparison := term (("==" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not in") term)?
    term       := NUMBER | STRING | "true" | "false" | list | name | "(" expr ")"
    list       := "[" (term ("," term)*)? "]"
    name       := IDENT ("." IDENT)*
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

StaticKind = Literal["number", "string", "bool", "any"]
KEYWORDS = frozenset({"and", "or", "not", "in", "true", "false"})
MAX_EXPR_LENGTH = 2000
MAX_DEPTH = 50


class ExprError(Exception):
    """An expression failed to parse or references an unknown name."""

    def __init__(self, message: str, pos: int | None = None) -> None:
        super().__init__(message if pos is None else f"{message} (at column {pos + 1})")
        self.pos = pos


@dataclass(frozen=True)
class NameType:
    """Static information about a name, returned by the policy's resolver."""

    kind: StaticKind = "any"
    allowed: frozenset[str] | None = None  # allowed string literals for equality/membership


Resolver = Callable[[tuple[str, ...]], NameType]


class Scope(Protocol):
    """Runtime name lookup used by compiled expressions."""

    def lookup(self, parts: tuple[str, ...]) -> Any:
        """Return the value of a dotted name, or None when it is not evaluated."""
        ...

    def warn(self, message: str) -> None:
        """Record a non-fatal evaluation warning."""
        ...


_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>-?\d+(?:\.\d+)?|-?\.\d+)
  | (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<op>==|!=|<=|>=|<|>)
  | (?P<punct>[()\[\],.])
  | (?P<ident>[A-Za-z][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    pos: int


def tokenize(text: str) -> list[Token]:
    """Split an expression into tokens, rejecting any character outside the grammar."""
    if len(text) > MAX_EXPR_LENGTH:
        raise ExprError(f"expression longer than {MAX_EXPR_LENGTH} characters")
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if m is None:
            raise ExprError(f"unexpected character {text[pos]!r}", pos)
        kind = m.lastgroup or ""
        if kind != "ws":
            value = m.group()
            if kind == "ident" and value in KEYWORDS:
                kind = "kw"
            tokens.append(Token(kind, value, pos))
        pos = m.end()
    tokens.append(Token("end", "", len(text)))
    return tokens


# ---------------------------------------------------------------- syntax tree


@dataclass(frozen=True)
class Lit:
    value: Any


@dataclass(frozen=True)
class ListLit:
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Name:
    parts: tuple[str, ...]
    pos: int


@dataclass(frozen=True)
class Not:
    operand: Node


@dataclass(frozen=True)
class BoolOp:
    op: Literal["and", "or"]
    operands: tuple[Node, ...]


@dataclass(frozen=True)
class Compare:
    op: str
    left: Node
    right: Node
    pos: int


Node = Lit | ListLit | Name | Not | BoolOp | Compare


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = tokenize(text)
        self.i = 0
        self.depth = 0

    def peek(self) -> Token:
        return self.tokens[self.i]

    def take(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, kind: str, value: str | None = None) -> Token:
        tok = self.peek()
        if tok.kind != kind or (value is not None and tok.value != value):
            want = value or kind
            got = tok.value or "end of expression"
            raise ExprError(f"expected {want!r}, found {got!r}", tok.pos)
        return self.take()

    def parse(self) -> Node:
        node = self.or_expr()
        tok = self.peek()
        if tok.kind != "end":
            raise ExprError(f"unexpected {tok.value!r}", tok.pos)
        return node

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExprError("expression nested too deeply", self.peek().pos)

    def or_expr(self) -> Node:
        items = [self.and_expr()]
        while self.peek().kind == "kw" and self.peek().value == "or":
            self.take()
            items.append(self.and_expr())
        return items[0] if len(items) == 1 else BoolOp("or", tuple(items))

    def and_expr(self) -> Node:
        items = [self.not_expr()]
        while self.peek().kind == "kw" and self.peek().value == "and":
            self.take()
            items.append(self.not_expr())
        return items[0] if len(items) == 1 else BoolOp("and", tuple(items))

    def not_expr(self) -> Node:
        tok = self.peek()
        if tok.kind == "kw" and tok.value == "not":
            self.take()
            self._enter()
            node = Not(self.not_expr())
            self.depth -= 1
            return node
        return self.comparison()

    def comparison(self) -> Node:
        left = self.term()
        tok = self.peek()
        if tok.kind == "op":
            self.take()
            return Compare(tok.value, left, self.term(), tok.pos)
        if tok.kind == "kw" and tok.value == "in":
            self.take()
            return Compare("in", left, self.term(), tok.pos)
        if tok.kind == "kw" and tok.value == "not":
            nxt = self.tokens[self.i + 1]
            if nxt.kind == "kw" and nxt.value == "in":
                self.i += 2
                return Compare("not in", left, self.term(), tok.pos)
        return left

    def term(self) -> Node:
        tok = self.peek()
        if tok.kind == "number":
            self.take()
            num = float(tok.value)
            return Lit(int(num) if num.is_integer() and "." not in tok.value else num)
        if tok.kind == "string":
            self.take()
            return Lit(_unquote(tok.value))
        if tok.kind == "kw" and tok.value in ("true", "false"):
            self.take()
            return Lit(tok.value == "true")
        if tok.kind == "punct" and tok.value == "[":
            self.take()
            items: list[Node] = []
            if not (self.peek().kind == "punct" and self.peek().value == "]"):
                items.append(self.term())
                while self.peek().kind == "punct" and self.peek().value == ",":
                    self.take()
                    items.append(self.term())
            self.expect("punct", "]")
            return ListLit(tuple(items))
        if tok.kind == "punct" and tok.value == "(":
            self.take()
            self._enter()
            node = self.or_expr()
            self.depth -= 1
            self.expect("punct", ")")
            return node
        if tok.kind == "ident":
            self.take()
            parts = [tok.value]
            while self.peek().kind == "punct" and self.peek().value == ".":
                self.take()
                parts.append(self.expect("ident").value)
            nxt = self.peek()
            if nxt.kind == "punct" and nxt.value == "(":
                raise ExprError("function calls are not allowed", nxt.pos)
            return Name(tuple(parts), tok.pos)
        got = tok.value or "end of expression"
        raise ExprError(f"unexpected {got!r}", tok.pos)


def _unquote(raw: str) -> str:
    body = raw[1:-1]
    return re.sub(r"\\(.)", lambda m: m.group(1), body)


def parse(text: str) -> Node:
    """Parse an expression into a syntax tree."""
    if not text.strip():
        raise ExprError("empty expression")
    return _Parser(text).parse()


# ---------------------------------------------------------------- semantics


def truthy(value: Any) -> bool:
    """Boolean meaning of a value: checks as-is, Noul probabilities above 0.5, null is false."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0.5
    if isinstance(value, str):
        return value not in ("", "none")
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    return False


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _compare(op: str, left: Any, right: Any, scope: Scope) -> bool:
    if left is None or right is None:
        return False
    if op in ("in", "not in"):
        if isinstance(right, (list, tuple)):
            found = any(_equal(left, item) for item in right)
        elif isinstance(right, str) and isinstance(left, str):
            found = left in right
        else:
            scope.warn(f"'{op}' needs a list on the right, got {type(right).__name__}")
            return False
        return found if op == "in" else not found
    if op in ("==", "!="):
        if _is_num(left) != _is_num(right) or isinstance(left, bool) != isinstance(right, bool):
            scope.warn(f"compared {type(left).__name__} with {type(right).__name__}")
            return False
        eq = _equal(left, right)
        return eq if op == "==" else not eq
    if _is_num(left) and _is_num(right):
        lf, rf = float(left), float(right)
    elif isinstance(left, str) and isinstance(right, str):
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]
    else:
        scope.warn(f"cannot order {type(left).__name__} and {type(right).__name__}")
        return False
    return {"<": lf < rf, "<=": lf <= rf, ">": lf > rf, ">=": lf >= rf}[op]


def _equal(a: Any, b: Any) -> bool:
    if _is_num(a) and _is_num(b):
        return float(a) == float(b)
    return type(a) is type(b) and bool(a == b)


Evaluator = Callable[[Scope], Any]


def _build(node: Node) -> Evaluator:
    if isinstance(node, Lit):
        value = node.value
        return lambda scope: value
    if isinstance(node, ListLit):
        items = [_build(i) for i in node.items]
        return lambda scope: [f(scope) for f in items]
    if isinstance(node, Name):
        parts = node.parts
        return lambda scope: scope.lookup(parts)
    if isinstance(node, Not):
        inner = _build(node.operand)
        return lambda scope: not truthy(inner(scope))
    if isinstance(node, BoolOp):
        fns = [_build(o) for o in node.operands]
        if node.op == "and":
            return lambda scope: all(truthy(f(scope)) for f in fns)
        return lambda scope: any(truthy(f(scope)) for f in fns)
    left, right, op = _build(node.left), _build(node.right), node.op
    return lambda scope: _compare(op, left(scope), right(scope), scope)


@dataclass
class CompiledExpr:
    """A parsed, statically checked expression ready to evaluate."""

    source: str
    names: set[tuple[str, ...]] = field(default_factory=set)
    _fn: Evaluator | None = None

    @property
    def roots(self) -> set[str]:
        """First component of every referenced name."""
        return {parts[0] for parts in self.names}

    def evaluate(self, scope: Scope) -> bool:
        """Evaluate against a scope, returning the expression's truth value."""
        assert self._fn is not None
        return truthy(self._fn(scope))


def compile_expr(text: str, resolve: Resolver) -> CompiledExpr:
    """Parse, check names and types, and compile an expression into closures."""
    from memgate.policy.expr_check import check_tree

    tree = parse(text)
    names: set[tuple[str, ...]] = set()
    check_tree(tree, resolve, names)
    return CompiledExpr(source=text, names=names, _fn=_build(tree))
