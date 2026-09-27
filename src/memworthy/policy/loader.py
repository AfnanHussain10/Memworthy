"""Load policy YAML, validate it with line-numbered errors, and compile its rules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from memworthy.checks.registry import get_check, get_rule
from memworthy.policy.expr import CompiledExpr, ExprError, NameType, compile_expr
from memworthy.policy.schema import CheckSignal, ModelSignal, PolicySpec, Rule

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED = frozenset(
    {"type", "conflict", "candidate", "meta", "true", "false", "and", "or", "not", "in"}
)
CONFLICT_ACTIONS = frozenset({"update", "merge", "supersede"})
ON_ERROR_ACTIONS = frozenset({"review", "reject", "store"})
ROLES = frozenset({"user", "assistant", "tool", "system", "unknown"})
MAX_MODEL_SIGNALS = 60
MAX_TYPES = 255
Path_ = tuple[str | int, ...]


class PolicyError(Exception):
    """An invalid policy; the message names the file and YAML line."""

    def __init__(self, message: str, file: str = "<policy>", line: int | None = None) -> None:
        where = f"{file}:{line}" if line is not None else file
        super().__init__(f"{where}: {message}")
        self.file = file
        self.line = line
        self.reason = message


@dataclass
class CompiledRule:
    """A rule with its compiled condition."""

    index: int
    rule: Rule
    expr: CompiledExpr | None
    py: str | None
    pre_judge: bool
    line: int | None

    @property
    def id(self) -> str:
        """The rule's name, or ``rules[i]``."""
        return self.rule.name or f"rules[{self.index}]"


@dataclass
class Policy:
    """A loaded, validated policy ready for the engine."""

    spec: PolicySpec
    rules: list[CompiledRule]
    source: str = "<policy>"
    text: str = ""
    lines: dict[Path_, int] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """Policy name."""
        return self.spec.policy

    @property
    def version(self) -> str:
        """Policy version string."""
        return self.spec.version

    @property
    def model_signals(self) -> dict[str, ModelSignal]:
        """Signals answered by the judge, in declaration order."""
        return {k: v for k, v in self.spec.signals.items() if isinstance(v, ModelSignal)}

    @property
    def check_signals(self) -> dict[str, CheckSignal]:
        """Code-check signals, in declaration order."""
        return {k: v for k, v in self.spec.signals.items() if isinstance(v, CheckSignal)}

    @property
    def uses_conflict(self) -> bool:
        """True when the engine should shortlist conflicting memories."""
        return self.spec.conflict.enabled and any(
            r.rule.then in CONFLICT_ACTIONS for r in self.rules
        )

    def line_of(self, path: Path_) -> int | None:
        """YAML line (1-based) of the longest known prefix of ``path``."""
        for n in range(len(path), 0, -1):
            if path[:n] in self.lines:
                return self.lines[path[:n]]
        return None


def template_names() -> list[str]:
    """Names of the bundled policy templates."""
    root = resources.files("memworthy") / "templates"
    if not root.is_dir():
        return []
    return sorted(p.name[:-5] for p in root.iterdir() if p.name.endswith(".yaml"))


def template_path(name: str) -> Path | None:
    """Filesystem path of a bundled template, or None."""
    p = resources.files("memworthy") / "templates" / f"{name}.yaml"
    return Path(str(p)) if p.is_file() else None


def load_policy(ref: str | Path | PolicySpec | Policy) -> Policy:
    """Load a policy from a template name, a file path, a spec, or return a Policy as is."""
    if isinstance(ref, Policy):
        return ref
    if isinstance(ref, PolicySpec):
        return compile_policy(ref, source=f"<{ref.policy}>")
    ref_str = str(ref)
    tpl = template_path(ref_str) if re.fullmatch(r"[a-z0-9_-]+", ref_str) else None
    path = tpl or Path(ref_str).expanduser()
    if not path.is_file():
        raise PolicyError("policy file not found", ref_str)
    return load_policy_text(path.read_text(encoding="utf-8"), source=str(path))


def _line_map(node: yaml.Node, path: Path_, out: dict[Path_, int]) -> None:
    out.setdefault(path, node.start_mark.line + 1)
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            key = k.value if isinstance(k, yaml.ScalarNode) else str(k)
            out[(*path, key)] = k.start_mark.line + 1
            _line_map(v, (*path, key), out)
    elif isinstance(node, yaml.SequenceNode):
        for i, item in enumerate(node.value):
            _line_map(item, (*path, i), out)


def _normalize(raw: dict[str, Any], source: str, lines: dict[Path_, int]) -> dict[str, Any]:
    data = dict(raw)
    signals = data.get("signals") or {}
    if not isinstance(signals, dict):
        raise PolicyError("'signals' must be a mapping", source, lines.get(("signals",)))
    norm_signals: dict[str, Any] = {}
    for name, sig in signals.items():
        line = lines.get(("signals", name))
        if not isinstance(sig, dict):
            raise PolicyError(f"signal '{name}' must be a mapping", source, line)
        sig = dict(sig)
        kinds = [k for k in ("noul", "choice", "score") if k in sig]
        if len(kinds) > 1 or (kinds and "check" in sig):
            raise PolicyError(f"signal '{name}' has more than one kind", source, line)
        if kinds:
            kind = kinds[0]
            sig["kind"], sig["prompt"] = kind, sig.pop(kind)
        elif "check" not in sig and "kind" not in sig:
            raise PolicyError(
                f"signal '{name}' needs one of noul, choice, score or check", source, line
            )
        norm_signals[str(name)] = sig
    data["signals"] = norm_signals
    rules = data.get("rules")
    if isinstance(rules, list):
        out_rules = []
        for i, r in enumerate(rules):
            line = lines.get(("rules", i))
            if not isinstance(r, dict):
                raise PolicyError("each rule must be a mapping", source, line)
            r = dict(r)
            if "if" in r:
                raise PolicyError("use 'when:' instead of 'if:' in rules", source, line)
            if "else" in r:
                if "when" in r or "then" in r:
                    raise PolicyError("an else rule cannot have 'when' or 'then'", source, line)
                r["then"] = r.pop("else")
                r["when"] = None
                r["_else"] = True
            elif r.get("when") is None:
                raise PolicyError("rule needs 'when:' (or be the final 'else:')", source, line)
            out_rules.append(r)
        data["rules"] = out_rules
    return data


def load_policy_text(text: str, source: str = "<policy>") -> Policy:
    """Parse and validate policy YAML text."""
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        raw = yaml.safe_load(text)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line + 1 if mark is not None else None
        raise PolicyError(f"YAML syntax error: {exc.problem or exc}", source, line) from None
    except yaml.YAMLError as exc:
        raise PolicyError(f"YAML error: {exc}", source) from None
    if not isinstance(raw, dict) or node is None:
        raise PolicyError("policy must be a YAML mapping", source, 1)
    lines: dict[Path_, int] = {}
    _line_map(node, (), lines)
    data = _normalize(raw, source, lines)
    is_else = [bool(r.pop("_else", False)) for r in data.get("rules") or []]
    try:
        spec = PolicySpec.model_validate(data)
    except ValidationError as exc:
        err = exc.errors()[0]
        loc = tuple(err["loc"])
        where = ".".join(str(p) for p in loc) or "policy"
        raise _err(f"{where}: {err['msg']}", source, lines, *loc) from None
    return compile_policy(spec, source=source, text=text, lines=lines, else_flags=is_else)


def _err(msg: str, source: str, lines: dict[Path_, int], *path: str | int) -> PolicyError:
    for n in range(len(path), 0, -1):
        if path[:n] in lines:
            return PolicyError(msg, source, lines[path[:n]])
    return PolicyError(msg, source)


def compile_policy(
    spec: PolicySpec,
    source: str = "<policy>",
    text: str = "",
    lines: dict[Path_, int] | None = None,
    else_flags: list[bool] | None = None,
) -> Policy:
    """Validate a parsed spec and compile its rule expressions."""
    lines = lines or {}
    _validate_names(spec, source, lines)
    resolve = make_resolver(spec)
    rules = spec.rules
    flags = else_flags or [r.when is None for r in rules]
    if not rules:
        raise _err("at least one rule is required", source, lines, "rules")
    else_idx = [i for i, f in enumerate(flags) if f]
    if len(else_idx) != 1 or else_idx[0] != len(rules) - 1:
        misplaced = [i for i in else_idx if i != len(rules) - 1]
        bad = misplaced[0] if misplaced else len(rules) - 1
        raise _err("exactly one 'else' rule is required, and it must be last",
                   source, lines, "rules", bad)
    checks = set(spec.signals) - set(k for k, v in spec.signals.items()
                                     if isinstance(v, ModelSignal))
    compiled: list[CompiledRule] = []
    for i, r in enumerate(rules):
        line = lines.get(("rules", i))
        if r.then == "store_labeled" and not r.label:
            raise PolicyError("store_labeled rules need a 'label'", source, line)
        if r.restore and r.then != "supersede":
            raise PolicyError("'restore' is only allowed on supersede rules", source, line)
        if r.then in CONFLICT_ACTIONS and not spec.conflict.enabled:
            raise PolicyError(f"'{r.then}' rules require conflict.enabled", source, line)
        expr: CompiledExpr | None = None
        py: str | None = None
        pre = False
        if r.when is not None:
            if r.when.startswith("py:"):
                py = r.when[3:].strip()
                if get_rule(py) is None:
                    raise PolicyError(f"unknown Python rule 'py:{py}'", source, line)
            else:
                try:
                    expr = compile_expr(r.when, resolve)
                except ExprError as exc:
                    raise PolicyError(f"rule expression {r.when!r}: {exc}", source, line) from None
                pre = expr.roots <= (checks | {"candidate", "meta"})
        compiled.append(CompiledRule(i, r, expr, py, pre, line))
    return Policy(spec=spec, rules=compiled, source=source, text=text, lines=lines)


def _validate_names(spec: PolicySpec, source: str, lines: dict[Path_, int]) -> None:
    if not spec.types:
        raise _err("at least one type is required", source, lines, "types")
    if len(spec.types) > MAX_TYPES:
        raise _err(f"at most {MAX_TYPES} types are allowed", source, lines, "types")
    for t in spec.types:
        if not NAME_RE.match(t):
            raise _err(f"type name '{t}' must match {NAME_RE.pattern}", source, lines, "types", t)
    n_model = 0
    for name, sig in spec.signals.items():
        at = ("signals", name)
        if not NAME_RE.match(name):
            raise _err(f"signal name '{name}' must match {NAME_RE.pattern}", source, lines, *at)
        if name in RESERVED:
            raise _err(f"'{name}' is a reserved name", source, lines, *at)
        if isinstance(sig, CheckSignal):
            if get_check(sig.check) is None:
                raise _err(f"unknown check '{sig.check}'", source, lines, *at)
            continue
        n_model += 1
        if sig.kind == "choice":
            if not sig.options or not 2 <= len(sig.options) <= 20:
                raise _err(f"choice signal '{name}' needs 2-20 options", source, lines, *at)
            for opt in sig.options:
                if not NAME_RE.match(opt):
                    raise _err(f"option '{opt}' must match {NAME_RE.pattern}",
                               source, lines, *at)
        elif sig.kind == "score":
            if not sig.levels or not 2 <= len(sig.levels) <= 10:
                raise _err(f"score signal '{name}' needs 2-10 levels", source, lines, *at)
        elif sig.options or sig.levels:
            raise _err(f"noul signal '{name}' takes no options or levels", source, lines, *at)
        for t in sig.applies_to or []:
            if t not in spec.types:
                raise _err(f"applies_to names unknown type '{t}'", source, lines, *at)
    if n_model > MAX_MODEL_SIGNALS:
        raise _err(f"at most {MAX_MODEL_SIGNALS} model signals are allowed",
                   source, lines, "signals")
    for i, test in enumerate(spec.tests):
        if test.expect_type is not None and test.expect_type not in spec.types:
            raise _err(f"expect_type '{test.expect_type}' is not a declared type",
                       source, lines, "tests", i)
    if spec.on_error not in ON_ERROR_ACTIONS:
        raise _err(f"on_error must be one of {', '.join(sorted(ON_ERROR_ACTIONS))}",
                   source, lines, "on_error")


def make_resolver(spec: PolicySpec) -> Any:
    """Build the static name resolver used to check rule expressions."""
    types = frozenset(spec.types)

    def resolve(parts: tuple[str, ...]) -> NameType:
        root, rest = parts[0], parts[1:]
        if root == "type" and not rest:
            return NameType("string", types)
        if root == "conflict":
            if not rest:
                return NameType("bool")
            if rest == ("p",):
                return NameType("number")
        if root == "candidate" and rest in (("role",), ("subject",)):
            return NameType("string", ROLES if rest == ("role",) else None)
        if root == "meta" and rest:
            return NameType("any")
        sig = spec.signals.get(root)
        if isinstance(sig, CheckSignal) and not rest:
            return NameType("any")
        if isinstance(sig, ModelSignal):
            if sig.kind == "noul" and not rest:
                return NameType("number")
            if sig.kind == "choice":
                opts = frozenset(sig.options or {})
                if not rest:
                    return NameType("string", opts)
                if rest == ("p",) or (len(rest) == 1 and rest[0] in opts):
                    return NameType("number")
            if sig.kind == "score":
                if not rest or rest == ("p",):
                    return NameType("number")
                if rest == ("top",):
                    return NameType("string", frozenset(sig.levels or []))
        raise ExprError(f"unknown name '{'.'.join(parts)}'")

    return resolve
