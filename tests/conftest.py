"""Shared test setup: load .env for live tests only; never print key values."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

if load_dotenv is not None:
    load_dotenv(ROOT / ".env", override=False)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TYPESAFE_API_KEY"):
        return
    skip = pytest.mark.skip(reason="TYPESAFE_API_KEY not set")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
