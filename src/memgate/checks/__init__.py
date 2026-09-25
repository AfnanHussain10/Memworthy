"""Code checks. Importing this package registers the built-in checks."""

from memgate.checks import builtins as builtins
from memgate.checks.registry import check, check_names, get_check, register_check

__all__ = ["builtins", "check", "check_names", "get_check", "register_check"]
