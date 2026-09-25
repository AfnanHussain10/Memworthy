"""In-memory store used by tests and the playground."""

from __future__ import annotations

from memgate.stores.local import LocalStore


class DictStore(LocalStore):
    """Keeps memories in a dict; superseded memories move to ``archive``."""
