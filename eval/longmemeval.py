"""LongMemEval knowledge-update comparison: a simple memory pipeline with and without MemGate.

Both arms share one LLM fact extraction per chunk of sessions (cached), so the only difference
is the gate:

- baseline: every extracted fact is stored;
- memgate: facts are gated in chronological order by the personal-memory policy (store, update,
  supersede, reject, review), with Jev calls recorded to a fixture file so reruns are free.

Each arm answers from its top-10 BM25 memories with the same LLM, and one LLM call grades both
answers with LongMemEval's knowledge-update rule (the updated answer must be given; mentioning
the old one as well is fine). Dataset: xiaowu0162/longmemeval-cleaned (MIT),
``longmemeval_s_cleaned.json``.

    python eval/longmemeval.py DATA.json --limit 10 [--max-llm-calls 45]

Uses OPENROUTER_API_KEY/EXTRACTOR_MODEL for the LLM and TYPESAFE_API_KEY for Jev (from .env).
Progress is cached under eval/results/longmemeval/cache, so a run can resume after a daily
limit. Results: eval/results/longmemeval/metrics.json and summary.md.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from memgate import Candidate, DictStore, Gate, MemoryLedger
from memgate.extractors import OPENROUTER_BASE_URL, OpenAICompatibleClient, parse_entries
from memgate.judges.jev import JevJudge
from memgate.judges.recorded import FixtureFile, RecordingJudge
from memgate.models import Memory, SourceRef, utcnow
from memgate.stores.rank import bm25_rank

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results" / "longmemeval"
SESSIONS_PER_CHUNK = 12
TOP_K = 10


class Budget(Exception):
    """The LLM call budget or rate limit was reached; progress is cached."""


class LLM:
    def __init__(self, client: Any, model: str, max_calls: int, cache: Path) -> None:
        self.client, self.model, self.max_calls, self.cache = client, model, max_calls, cache
        self.calls = 0
        cache.mkdir(parents=True, exist_ok=True)

    async def ask(self, key: str, messages: list[dict[str, str]]) -> str:
        path = self.cache / f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.json"
        if path.exists():
            return str(json.loads(path.read_text())["reply"])
        if self.calls >= self.max_calls:
            raise Budget(f"LLM call budget of {self.max_calls} reached")
        self.calls += 1
        try:
            reply = await self.client.complete(self.model, messages)
        except Exception as exc:  # 429 or daily cap on free tiers
            raise Budget(f"LLM call failed ({type(exc).__name__}: {str(exc)[:120]})") from None
        path.write_text(json.dumps({"reply": reply}))
        return reply


EXTRACT = ("Extract every fact about the user from these chat messages, one short sentence each, "
           "written in the first person as the user would say it (\"I ...\"). Keep numbers, "
           "names and dates exact. Skip requests to the assistant that contain no fact. Reply "
           'with JSON only: {"entries": [{"date": "<session date>", "text": "<fact>"}]}.')
ANSWER = ("Answer the question using only the memories. Memories are dated; when they disagree, "
          "the most recent one is current. Answer in one short sentence; say \"I don't know\" "
          "if the memories do not contain the answer.")
GRADE = ("You grade answers for a knowledge-update question. An answer is correct if it gives "
         "the updated reference answer; it may also mention the earlier value. It is wrong if it "
         "gives only an outdated value, a different value, or no answer. Reply with JSON only: "
         '{"a": true|false, "b": true|false}.')


def chunks(q: dict[str, Any]) -> list[list[tuple[str, list[dict[str, Any]]]]]:
    order = sorted(zip(q["haystack_dates"], q["haystack_sessions"], strict=True),
                   key=lambda x: x[0])
    return [order[i:i + SESSIONS_PER_CHUNK] for i in range(0, len(order), SESSIONS_PER_CHUNK)]


async def extract(llm: LLM, q: dict[str, Any]) -> list[tuple[str, str]]:
    facts: list[tuple[str, str]] = []
    for part in chunks(q):
        text = "\n\n".join(f"[Session {date}]\n" + "\n".join(
            f"user: {t['content']}" for t in sess if t["role"] == "user") for date, sess in part)
        reply = await llm.ask(f"extract|{q['question_id']}|{text}", [
            {"role": "system", "content": EXTRACT}, {"role": "user", "content": text}])
        try:
            entries = parse_entries(reply)
        except (ValueError, json.JSONDecodeError):
            entries = []
        facts += [(str(e.get("date", part[0][0])), str(e["text"])) for e in entries]
    return sorted(facts, key=lambda f: f[0])


def _iso(date: str) -> str:
    # LongMemEval dates look like "2023/05/20 (Sat) 02:21"
    d = date.split(" ")[0].replace("/", "-")
    return f"{d}T12:00:00+00:00" if len(d) == 10 else ""


async def gate_facts(facts: list[tuple[str, str]], judge: Any) -> tuple[DictStore, dict[str, int]]:
    store = DictStore()
    gate = Gate("personal-memory", store, judge=judge, ledger=MemoryLedger())
    cands = [Candidate(text=t, source=SourceRef(role="user", text=t),
                       metadata={"timestamp": _iso(d), "date": d}) for d, t in facts]
    decisions = await gate.aevaluate(cands)
    counts: dict[str, int] = {}
    for dec in decisions:
        counts[dec.action] = counts.get(dec.action, 0) + 1
    return store, counts


def baseline_store(facts: list[tuple[str, str]]) -> DictStore:
    now = utcnow()
    return DictStore([Memory(id=f"b{i}", text=t, type="fact", created_at=now, updated_at=now,
                             metadata={"date": d}) for i, (d, t) in enumerate(facts)])


def top_memories(store: DictStore, question: str) -> list[str]:
    mems = list(store.memories.values())
    ranked = [mems[i] for i, _ in bm25_rank(question, [m.text for m in mems], TOP_K)]
    ranked.sort(key=lambda m: str(m.metadata.get("date", "")))
    return [f"({m.metadata.get('date', '?')}) {m.text}" for m in ranked]


async def answer(llm: LLM, arm: str, q: dict[str, Any], memories: list[str]) -> str:
    body = (f"Today is {q['question_date']}.\nMemories:\n" + ("\n".join(memories) or "(none)")
            + f"\n\nQuestion: {q['question']}")
    return (await llm.ask(f"answer|{arm}|{body}", [{"role": "system", "content": ANSWER},
                                                  {"role": "user", "content": body}])).strip()


async def grade(llm: LLM, q: dict[str, Any], a: str, b: str) -> tuple[bool, bool]:
    body = (f"Question: {q['question']}\nReference answer: {q['answer']}\n\nAnswer a: {a}\n"
            f"Answer b: {b}")
    reply = await llm.ask(f"grade|{body}", [{"role": "system", "content": GRADE},
                                            {"role": "user", "content": body}])
    start, end = reply.find("{"), reply.rfind("}")
    data = json.loads(reply[start:end + 1]) if start != -1 else {}
    return bool(data.get("a")), bool(data.get("b"))


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data")
    ap.add_argument("--limit", type=int, default=78)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--max-llm-calls", type=int, default=45)
    args = ap.parse_args()
    load_dotenv(ROOT.parent / ".env")
    key, model = os.environ.get("OPENROUTER_API_KEY"), os.environ.get("EXTRACTOR_MODEL")
    if not key or not model:
        sys.exit("OPENROUTER_API_KEY and EXTRACTOR_MODEL must be set")
    data = [q for q in json.loads(Path(args.data).read_text())
            if q["question_type"] == "knowledge-update"][args.offset:args.offset + args.limit]
    llm = LLM(OpenAICompatibleClient(OPENROUTER_BASE_URL, key), model, args.max_llm_calls,
              OUT / "cache")
    fixtures = FixtureFile(OUT / "jev_fixtures.json")
    judge = RecordingJudge(JevJudge(), fixtures)
    rows_path = OUT / "questions.jsonl"
    done = {json.loads(line)["question_id"]: json.loads(line)
            for line in rows_path.read_text().splitlines()} if rows_path.exists() else {}
    stopped = None
    for q in data:
        if q["question_id"] in done:
            continue
        try:
            facts = await extract(llm, q)
            gated, counts = await gate_facts(facts, judge)
            base = baseline_store(facts)
            a = await answer(llm, "baseline", q, top_memories(base, q["question"]))
            b = await answer(llm, "memgate", q, top_memories(gated, q["question"]))
            ok_a, ok_b = await grade(llm, q, a, b)
        except Budget as exc:
            stopped = str(exc)
            break
        finally:
            fixtures.save()
        row = {"question_id": q["question_id"], "question": q["question"],
               "reference": q["answer"], "facts": len(facts), "memgate_actions": counts,
               "memgate_memories": len(gated.memories), "baseline_answer": a,
               "memgate_answer": b, "baseline_correct": ok_a, "memgate_correct": ok_b}
        done[q["question_id"]] = row
        with rows_path.open("a") as fh:
            fh.write(json.dumps(row) + "\n")
        print(f"{q['question_id']}: baseline={ok_a} memgate={ok_b} facts={len(facts)}")
    rows = list(done.values())
    summary = {
        "questions_done": len(rows), "questions_selected": len(data),
        "baseline_accuracy": sum(r["baseline_correct"] for r in rows) / len(rows) if rows else None,
        "memgate_accuracy": sum(r["memgate_correct"] for r in rows) / len(rows) if rows else None,
        "llm_calls_this_run": llm.calls, "stopped": stopped,
        "complete": len(rows) >= 78, "judge_model": "jev-1.13.0",
        "llm": "EXTRACTOR_MODEL from .env (value not recorded)",
    }
    (OUT / "metrics.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
