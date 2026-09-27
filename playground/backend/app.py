"""Memworthy playground backend: runs the real library; stores nothing but anonymous counts.

    uvicorn playground.backend.app:app --reload

Replay mode uses the recorded Jev answers bundled with Memworthy, so it needs no API key. Live
mode (TYPESAFE_API_KEY set, PLAYGROUND_LIVE not "0") is rate-limited per IP and globally and
has a daily spend cap (PLAYGROUND_DAILY_CAP_USD, default 0.50).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from memworthy import DictStore, Gate, MemoryLedger
from memworthy.engine import render_state
from memworthy.judges.recorded import FixtureFile, bundled_fixture_path
from memworthy.policy.loader import Policy, PolicyError, load_policy, load_policy_text
from memworthy.sources.chat import split_messages
from memworthy.sources.pipeline import episode_question, episode_state, ingest_sessions
from memworthy.stores.markdown import to_markdown
from memworthy.testing import run_tests

from .judge import HybridJudge
from .limits import LiveLimits
from .present import decision_view, memory_view, policy_summary, thresholds

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "playground" / "web"
DATA = ROOT / "playground" / "data"
RESULTS = ROOT / "eval" / "results"
TEMPLATES = ("personal-memory", "dev-sessions")
MAX_MESSAGE, MAX_MESSAGES, MAX_POLICY, MAX_ANSWERS = 300, 12, 100_000, 300
EVENTS = frozenset({"visit", "guided_step4", "free_play", "rule_edit", "session_demo",
                    "eval_page", "integrate_page", "github"})

try:  # the backend may load .env (never the core library)
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=False)
except ImportError:  # pragma: no cover
    pass

app = FastAPI(title="Memworthy playground", docs_url=None, redoc_url=None)
limits = LiveLimits(daily_cap_usd=float(os.environ.get("PLAYGROUND_DAILY_CAP_USD", "0.50")))
counters: Counter[str] = Counter()
_fixtures: dict[str, dict[str, dict[str, Any]]] = {}


def bundled(template: str) -> dict[str, dict[str, Any]]:
    """Recorded answers for a template, loaded once."""
    if template not in _fixtures:
        path = bundled_fixture_path(template)
        _fixtures[template] = FixtureFile(path).entries if path else {}
    return _fixtures[template]


def live_available() -> bool:
    """True when live Jev calls can be made."""
    return bool(os.environ.get("TYPESAFE_API_KEY")) and os.environ.get("PLAYGROUND_LIVE") != "0"


def make_judge(template: str, live: bool, answers: dict[str, Any], ip: str) -> HybridJudge:
    """Recorded answers first, then the client's live answers, then live Jev if allowed."""
    jev = None
    if live and live_available():
        from memworthy.judges.jev import JevJudge

        jev = JevJudge()
    clean = {k: v for k, v in list(answers.items())[:MAX_ANSWERS]
             if isinstance(v, dict) and isinstance(v.get("answers"), dict)}
    return HybridJudge(bundled(template), clean, jev, limits, ip)


def get_policy(template: str, policy_yaml: str | None) -> Policy:
    """The edited policy if given, else the bundled template; 400 with a line on errors."""
    if template not in TEMPLATES:
        raise HTTPException(400, f"unknown template {template!r}")
    if not policy_yaml:
        return load_policy(template)
    if len(policy_yaml) > MAX_POLICY:
        raise HTTPException(400, "policy is too long")
    try:
        return load_policy_text(policy_yaml, source="policy.yaml")
    except PolicyError as exc:
        raise HTTPException(400, {"error": exc.reason, "line": exc.line}) from None


class RunRequest(BaseModel):
    template: str = "personal-memory"
    policy_yaml: str | None = None
    messages: list[dict[str, str]] = Field(default_factory=list)
    live: bool = False
    answers: dict[str, Any] = Field(default_factory=dict)


class SessionRequest(BaseModel):
    policy_yaml: str | None = None
    live: bool = False
    answers: dict[str, Any] = Field(default_factory=dict)


class ValidateRequest(BaseModel):
    template: str = "personal-memory"
    policy_yaml: str


class EventRequest(BaseModel):
    name: str


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


@app.get("/api/config")
def config() -> dict[str, Any]:
    """Templates, their YAML, demo scripts and whether live mode is on."""
    demo = json.loads((ROOT / "src" / "memworthy" / "templates" / "demos" /
                       "personal-memory.chat.json").read_text())
    templates = {}
    for name in TEMPLATES:
        pol = load_policy(name)
        templates[name] = {"yaml": pol.text, "version": pol.version,
                           "types": list(pol.spec.types), **policy_summary(pol)}
    return {"templates": templates, "demo": demo, "live_available": live_available(),
            "limits": {"message_chars": MAX_MESSAGE, "messages": MAX_MESSAGES,
                       "daily_cap_usd": limits.daily_cap_usd}}


@app.post("/api/validate")
def validate(req: ValidateRequest) -> dict[str, Any]:
    """Validate policy YAML without running anything."""
    try:
        pol = load_policy_text(req.policy_yaml[:MAX_POLICY], source="policy.yaml")
    except PolicyError as exc:
        return {"ok": False, "error": exc.reason, "line": exc.line}
    return {"ok": True, "policy": pol.name, "version": pol.version, **policy_summary(pol)}


@app.post("/api/run")
async def run(req: RunRequest, request: Request) -> dict[str, Any]:
    """Gate a chat conversation step by step with per-step memory snapshots."""
    msgs = [m for m in req.messages if m.get("role") == "user"][:MAX_MESSAGES]
    if any(len(m.get("content", "")) > MAX_MESSAGE for m in msgs):
        raise HTTPException(400, f"messages are limited to {MAX_MESSAGE} characters")
    policy = get_policy(req.template, req.policy_yaml)
    judge = make_judge(req.template, req.live, req.answers, _client_ip(request))
    store, ledger = DictStore(), MemoryLedger()
    gate = Gate(policy, store, judge=judge, ledger=ledger)
    steps = []
    for cand in split_messages([{"role": "user", "content": m["content"]} for m in msgs]):
        [decision] = await gate.aevaluate([cand])
        label = judge.sources.get(render_state(decision.candidate), "rules")
        steps.append({
            "decision": decision_view(policy, decision, label),
            "memories": [memory_view(m) for m in await store.all()],
            "archive": [memory_view(m) for m in store.archive.values()],
        })
    counters["run_live" if req.live else "run_replay"] += 1
    return {"steps": steps, "ledger": ledger.to_jsonl(), "new_answers": judge.new_entries,
            "blocked": judge.blocked, "thresholds": thresholds(policy),
            "policy": {"name": policy.name, "version": policy.version}}


@app.post("/api/sessions")
async def sessions(req: SessionRequest, request: Request) -> dict[str, Any]:
    """The recorded dev-sessions demo: episodes, noise, decisions and Markdown entries."""
    policy = get_policy("dev-sessions", req.policy_yaml)
    judge = make_judge("dev-sessions", req.live, req.answers, _client_ip(request))
    ing = await ingest_sessions(policy, judge, DATA / "sessions")
    q = episode_question(policy)
    episodes = []
    dropped = {e.id for e in ing.dropped}
    for ep in ing.episodes:
        probs: dict[str, float] = {}
        try:
            res = await judge.judge(episode_state(ep), [q])
            probs = res.answers["episode_type"].probabilities or {}
        except Exception:
            probs = {}
        first = next((t.text for t in ep.turns if t.role == "user"), "")
        episodes.append({"id": ep.id, "request": first[:200], "outcome": ep.outcome,
                         "type": ep.episode_type, "noise": probs.get("noise", 0.0),
                         "dropped": ep.id in dropped, "files_edited": ep.files_edited,
                         "files_read": ep.files_read})
    store, ledger = DictStore(), MemoryLedger()
    gate = Gate(policy, store, judge=judge, ledger=ledger)
    decisions = await gate.aevaluate(ing.candidates)
    views = [decision_view(policy, d, judge.sources.get(render_state(d.candidate), "rules"))
             for d in decisions]
    for v, d in zip(views, decisions, strict=True):
        v["episode_id"] = d.candidate.metadata.get("episode_id")
    files = [{"path": f"{m.type}/{m.id[:8]}.md", "markdown": to_markdown(m),
              "memory": memory_view(m)} for m in await store.all()]
    counters["sessions"] += 1
    return {"episodes": episodes, "decisions": views, "files": files,
            "ledger": ledger.to_jsonl(), "new_answers": judge.new_entries,
            "blocked": judge.blocked, "thresholds": thresholds(policy)}


@app.post("/api/test")
async def test_policy(req: ValidateRequest, request: Request) -> dict[str, Any]:
    """Run the policy's built-in tests on recorded answers (no live calls)."""
    policy = get_policy(req.template, req.policy_yaml)
    judge = make_judge(req.template, False, {}, _client_ip(request))
    results = await run_tests(policy, judge)
    needs_live = sum(1 for r in results if r.decision.error and "live" in r.decision.error)
    passed = sum(r.passed for r in results)
    failures = [{"input": r.test.input, "reason": r.reason} for r in results
                if not r.passed and not (r.decision.error and "live" in r.decision.error)]
    return {"total": len(results), "passed": passed, "needs_live": needs_live,
            "failures": failures[:20]}


@app.get("/api/eval")
def eval_results() -> dict[str, Any]:
    """Evaluation numbers straight from eval/results (never typed by hand)."""
    out: dict[str, Any] = {}
    for name in TEMPLATES:
        path = RESULTS / name / "metrics.json"
        if path.exists():
            data = json.loads(path.read_text())
            data["plots"] = sorted(p.name for p in (RESULTS / name).glob("*.png"))
            out[name] = data
    lme = RESULTS / "longmemeval" / "metrics.json"
    out["longmemeval"] = json.loads(lme.read_text()) if lme.exists() else {"status": "pending"}
    return out


@app.post("/api/event")
def event(req: EventRequest) -> dict[str, bool]:
    """Count an anonymous event (no content, no identifiers)."""
    if req.name in EVENTS:
        counters[req.name] += 1
    return {"ok": True}


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    """Anonymous counters and today's live spend."""
    return {"counters": dict(counters), "live_spend_usd": round(limits.spent_usd, 6)}


if RESULTS.exists():
    app.mount("/results", StaticFiles(directory=RESULTS), name="results")


@app.get("/")
def index() -> FileResponse:
    """The single-page app (never cached: it names the hashed asset files of the current build)."""
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=WEB), name="web")
