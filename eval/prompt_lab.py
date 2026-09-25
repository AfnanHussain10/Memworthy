"""Compare prompt variants for one signal against groups of a policy's built-in tests.

Makes live Jev calls (one question per call). Usage:

    python eval/prompt_lab.py personal-memory about_subject variants.yaml

``variants.yaml`` is a list of prompts (or, for choice/score signals, a list of mappings with
``prompt`` plus ``options``/``levels``). Tests are grouped by expected action, so you can see
whether a prompt separates, say, third-party facts (review) from the user's own (store).
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from memgate.engine import build_questions, render_state
from memgate.judges.base import Question
from memgate.judges.jev import JevJudge
from memgate.policy.loader import load_policy
from memgate.policy.schema import ModelSignal
from memgate.testing import existing_memories, test_candidate


def _value(answer: Any, question: Question) -> float:
    if question.kind == "choice" and question.name == "conflict":
        probs = answer.probabilities or {}
        return 1.0 - float(probs.get("none", 0.0))
    return float(answer.value) if not isinstance(answer.value, str) else float("nan")


async def main(policy_ref: str, signal: str, variants_path: str) -> None:
    load_dotenv(Path.cwd() / ".env")
    policy = load_policy(policy_ref)
    variants = yaml.safe_load(Path(variants_path).read_text())
    judge = JevJudge()
    sem = asyncio.Semaphore(8)
    for vi, variant in enumerate(variants):
        spec = variant if isinstance(variant, dict) else {"prompt": variant}
        groups: dict[str, list[tuple[float, str]]] = defaultdict(list)

        async def one(test: Any, spec: dict[str, Any] = spec,
                      groups: dict[str, list[tuple[float, str]]] = groups) -> None:
            cand = test_candidate(test)
            if signal == "conflict":
                qs = build_questions(policy, existing_memories(policy, test))
                q = next((q for q in qs if q.name == "conflict"), None)
                if q is None:
                    return
                q = q.model_copy(update={"prompt": spec["prompt"]})
            elif signal == "type":
                q = Question(name="type", kind="choice",
                             prompt=spec.get("prompt", "What kind of information is this?"),
                             options=spec.get("options", dict(policy.spec.types)))
            else:
                base = policy.spec.signals[signal]
                assert isinstance(base, ModelSignal)
                q = Question(name=signal, kind=base.kind, prompt=spec["prompt"],
                             options=spec.get("options", base.options),
                             levels=spec.get("levels", base.levels))
            async with sem:
                res = await judge.judge(render_state(cand), [q])
            key = f"{test.expect}" + (f"/{test.expect_type}" if test.expect_type else "")
            ans = res.answers[q.name]
            if signal == "type":
                key = f"type:{test.expect_type or '?'}"
                val = (ans.probabilities or {}).get(test.expect_type or "", float("nan"))
                groups[key].append((val, f"{ans.value}: {test.input}"))
                return
            groups[key].append((_value(ans, q), test.input))

        tests = [t for t in policy.spec.tests if t.role == "user"]
        await asyncio.gather(*(one(t) for t in tests))
        print(f"\n=== variant {vi}: {spec['prompt']}")
        for key in sorted(groups):
            vals = [v for v, _ in groups[key]]
            low = sorted(groups[key])[:2]
            print(f"  {key:28s} n={len(vals):3d} mean={statistics.mean(vals):.2f} "
                  f"min={min(vals):.2f}  lowest: {[f'{v:.2f} {t[:30]}' for v, t in low]}")
            if os.environ.get("LAB_SHOW") and key.startswith(os.environ["LAB_SHOW"]):
                for v, t in sorted(groups[key]):
                    print(f"      {v:.2f}  {t}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
