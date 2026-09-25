"""Registries for code checks and Python rules referenced from policy YAML."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from memgate.models import Candidate

if TYPE_CHECKING:
    from memgate.engine import RuleContext
    from memgate.models import Action

CheckFn = Callable[[Candidate, dict[str, Any]], "bool | str"]
RuleFn = Callable[["RuleContext"], "Action | None"]
F = TypeVar("F", bound=Callable[..., Any])

_CHECKS: dict[str, CheckFn] = {}
_RULES: dict[str, RuleFn] = {}


def register_check(name: str, fn: CheckFn) -> None:
    """Register a code check under ``name``, replacing any previous one."""
    _CHECKS[name] = fn


def get_check(name: str) -> CheckFn | None:
    """Return the registered check, or None."""
    return _CHECKS.get(name)


def check_names() -> list[str]:
    """Names of all registered checks."""
    return sorted(_CHECKS)


def check(name: str) -> Callable[[F], F]:
    """Decorator registering a function ``(candidate, args) -> bool | str`` as a check."""

    def deco(fn: F) -> F:
        register_check(name, fn)
        return fn

    return deco


def register_rule(name: str, fn: RuleFn) -> None:
    """Register a Python rule usable as ``when: "py:<name>"``."""
    _RULES[name] = fn


def get_rule(name: str) -> RuleFn | None:
    """Return the registered Python rule, or None."""
    return _RULES.get(name)


def rule(name: str) -> Callable[[F], F]:
    """Decorator registering a function ``(RuleContext) -> Action | None`` as a rule."""

    def deco(fn: F) -> F:
        register_rule(name, fn)
        return fn

    return deco
