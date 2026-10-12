"""Judge providers by name: built-ins plus plugins from the ``memworthy.judges`` entry points.

A plugin package registers a zero-argument callable (usually its judge class) that reads its
own configuration from the environment::

    [project.entry-points."memworthy.judges"]
    myprovider = "memworthy_myprovider:MyJudge"
"""

from __future__ import annotations

import importlib
import logging
import os
from importlib.metadata import entry_points

from memworthy.judges.base import Judge, JudgeError

log = logging.getLogger("memworthy.judges.registry")

ENTRY_POINT_GROUP = "memworthy.judges"
DEFAULT_JUDGE = "jev"
BUILTIN_JUDGES = {
    "jev": "memworthy.judges.jev:JevJudge",
    "openai": "memworthy.judges.openai_decisions:OpenAIDecisionsJudge",
}


def available_judges() -> dict[str, str]:
    """Map each provider name to its ``module:attr`` target; built-ins win over plugins."""
    found = dict(BUILTIN_JUDGES)
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        if ep.name in BUILTIN_JUDGES:
            log.warning("judge plugin %r (%s) ignored: the name is built in", ep.name, ep.value)
            continue
        found.setdefault(ep.name, ep.value)
    return found


def default_judge_name() -> str:
    """The provider named by MEMWORTHY_JUDGE, else ``jev``."""
    return os.environ.get("MEMWORTHY_JUDGE") or DEFAULT_JUDGE


def get_judge(name: str | None = None) -> Judge:
    """Build the named provider's judge (default :func:`default_judge_name`).

    Raises JudgeError for an unknown name, a target that fails to import, a factory that
    fails (for example a missing API key) or a result that is not a Judge.
    """
    name = name or default_judge_name()
    judges = available_judges()
    target = judges.get(name)
    if target is None:
        raise JudgeError(f"unknown judge {name!r}; available: {', '.join(sorted(judges))}")
    module_name, _, attr = target.partition(":")
    try:
        factory: object = importlib.import_module(module_name)
        for part in attr.split(".") if attr else []:
            factory = getattr(factory, part)
    except (ImportError, AttributeError) as exc:
        raise JudgeError(f"judge {name!r} failed to load from {target}: {exc}") from None
    if not callable(factory):
        raise JudgeError(f"judge {name!r} target {target} is not callable")
    try:
        judge = factory()
    except JudgeError:
        raise
    except Exception as exc:
        raise JudgeError(f"judge {name!r} failed to start: {exc}") from None
    if not isinstance(judge, Judge):
        raise JudgeError(f"judge {name!r} from {target} does not implement the Judge protocol")
    log.debug("using judge %r from %s", name, target)
    return judge
