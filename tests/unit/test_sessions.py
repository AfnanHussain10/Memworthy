from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memworthy.models import Turn
from memworthy.sources.claude_code import is_person_text, parse_claude_code
from memworthy.sources.codex import parse_codex, parse_output, person_text
from memworthy.sources.episodes import (
    files_edited,
    files_read,
    outcome,
    split_episodes,
    summarize,
)
from memworthy.sources.pipeline import (
    default_candidates,
    parse_session,
    referenced_paths,
    session_files,
)
from memworthy.sources.session import ParsedSession, detect_format, read_jsonl

SESSIONS = Path(__file__).resolve().parents[1] / "fixtures" / "sessions"
CC = SESSIONS / "claude_code"
CX = SESSIONS / "codex"


def test_claude_code_parser_turns_and_tools() -> None:
    s = parse_claude_code(CC / "cc-2.1.251-pagination.jsonl")
    assert s.tool == "claude_code" and s.version == "2.1.251" and s.project == "bookshelf"
    users = [t.text for t in s.turns if t.role == "user"]
    assert users[0].startswith("add cursor pagination") and "commit this" in users
    tools = [t for t in s.turns if t.role == "tool"]
    assert {t.tool_name for t in tools} == {"Bash", "Read", "Edit"}
    assert all(t.tool_output is not None for t in tools)
    pytest_turn = next(t for t in tools if "pytest" in str(t.tool_input))
    assert "14 passed" in (pytest_turn.tool_output or "") and not pytest_turn.tool_error


def test_claude_code_error_results_and_meta_skipped() -> None:
    s = parse_claude_code(CC / "cc-2.1.266-importer-fix.jsonl")
    assert s.version == "2.1.266"
    assert any(t.tool_error for t in s.turns if t.role == "tool")
    login = parse_claude_code(CC / "cc-2.1.281-login-only.jsonl")
    assert login.turns == [] and login.version == "2.1.281"


def test_claude_code_harness_text_filter() -> None:
    assert not is_person_text("<command-name>/login</command-name>")
    assert not is_person_text("<local-command-stdout>ok</local-command-stdout>")
    assert not is_person_text("   ")
    assert is_person_text("fix the bug")


def test_codex_parser() -> None:
    s = parse_codex(CX / "codex-0.107.0-docker.jsonl")
    assert s.tool == "codex" and s.version == "0.107.0-alpha.5" and s.cwd == "/home/dev/bookshelf"
    users = [t.text for t in s.turns if t.role == "user"]
    assert users == ["write a Dockerfile so we can deploy the bookshelf API on a small VPS",
                     "from now on always run ruff format before committing anything in this repo"]
    patch = next(t for t in s.turns if t.tool_name == "apply_patch")
    assert "Add File: Dockerfile" in str(patch.tool_input) and not patch.tool_error
    failed = parse_codex(CX / "codex-0.130.0-mixed.jsonl")
    assert any(t.tool_error for t in failed.turns)


def test_codex_person_text_and_outputs() -> None:
    assert person_text("<environment_context>x</environment_context>") is None
    assert person_text("# AGENTS.md instructions for /x") is None
    assert person_text("\n# Files mentioned by the user:\n\n## My request for Codex:\nfix it") \
        == "fix it"
    assert parse_output("Process exited with code 2\nOutput:\nboom") == (
        "Process exited with code 2\nOutput:\nboom", True)
    assert parse_output(json.dumps({"output": "ok", "metadata": {"exit_code": 0}})) == (
        "ok", False)
    assert parse_output('{"not": "valid json') == ('{"not": "valid json', False)
    assert parse_output(None) == ("", False)


def test_detect_and_read(tmp_path: Path) -> None:
    assert detect_format(read_jsonl(CC / "cc-2.1.251-pagination.jsonl")) == "claude_code"
    assert detect_format(read_jsonl(CX / "codex-0.117.0-explain.jsonl")) == "codex"
    f = tmp_path / "x.jsonl"
    f.write_text('{"a": 1}\nnot json\n\n[1]\n{"type": "weird"}\n')
    assert read_jsonl(f) == [{"a": 1}, {"type": "weird"}]
    assert detect_format(read_jsonl(f)) is None
    assert parse_session(f) is None
    assert len(session_files(SESSIONS)) == 6 and session_files(f) == [f]


def test_unknown_records_are_skipped(tmp_path: Path) -> None:
    f = tmp_path / "cc.jsonl"
    rows = [
        {"type": "brand-new-record", "sessionId": "s1"},
        {"type": "user", "sessionId": "s1", "message": {"role": "user", "content": [
            {"type": "future_block", "x": 1}, {"type": "text", "text": "hello there friend"}]}},
        {"type": "assistant", "sessionId": "s1", "message": "not a dict"},
        {"type": "assistant", "sessionId": "s1", "message": {"content": "plain string reply"}},
        {"type": "user", "sessionId": "s1", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "missing", "content": "x"}]}},
        {"type": "user", "sessionId": "s1", "isSidechain": True,
         "message": {"content": "subagent text"}},
    ]
    f.write_text("\n".join(json.dumps(r) for r in rows))
    s = parse_claude_code(f)
    assert s.id == "s1"
    assert [(t.role, t.text) for t in s.turns] == [
        ("user", "hello there friend"), ("assistant", "plain string reply")]
    g = tmp_path / "cx.jsonl"
    g.write_text("\n".join(json.dumps(r) for r in [
        {"type": "response_item", "payload": {"type": "mystery"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "z"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "shell",
                                               "arguments": "not json", "call_id": "c"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "shell",
                                               "arguments": {"command": ["ls", "-la"]},
                                               "call_id": "d"}},
    ]))
    cx = parse_codex(g)
    assert [t.tool_input for t in cx.turns] == [{"input": "not json"},
                                                {"command": ["ls", "-la"]}]


def _t(role: str, text: str = "", minutes: float = 0, **kw: object) -> Turn:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return Turn(role=role, text=text, timestamp=ts, **kw)  # type: ignore[arg-type]


def test_split_rules() -> None:
    turns = [
        _t("user", "please add a caching layer to the search endpoint now", 0),
        _t("assistant", "done", 1),
        _t("user", "yes go ahead", 2),  # short reply stays in the episode
        _t("assistant", "ok", 3),
        _t("assistant", "back after a long pause", 60),  # gap starts a new episode
        _t("user", "now please write the documentation for the search endpoint", 61),
    ]
    eps = split_episodes(ParsedSession(id="s", tool="codex", path="p", turns=turns,
                                       cwd="/x/proj"))
    # the assistant-only group after the pause has nothing to remember and is dropped
    assert [len(e.turns) for e in eps] == [4, 1]
    assert all(e.project == "proj" for e in eps)
    assert eps[0].started_at is not None and eps[0].ended_at is not None
    eps2 = split_episodes(ParsedSession(id="s", tool="codex", path="p", turns=turns),
                          min_user_words=3, gap_minutes=600)
    assert [len(e.turns) for e in eps2] == [2, 3, 1]


def _tool(name: str, output: str = "", error: bool = False, **inp: object) -> Turn:
    return Turn(role="tool", tool_name=name, tool_input=dict(inp), tool_output=output,
                tool_error=error)


def test_files_and_outcomes() -> None:
    turns = [
        _tool("Read", file_path="a.py"),
        _tool("exec_command", cmd="sed -n '1,20p' b/c.py && cat README.md | head"),
        _tool("Edit", file_path="a.py"),
        _tool("apply_patch", input="*** Begin Patch\n*** Update File: d.py\n*** Add File: e.py"),
    ]
    assert files_read(turns) == ["a.py", "b/c.py", "README.md"]
    assert files_edited(turns) == ["a.py", "d.py", "e.py"]
    assert outcome([_tool("Bash", command="pytest -q")]) == "tests_passed"
    assert outcome([_tool("Bash", error=True, command="pytest -q")]) == "failed"
    assert outcome([_tool("Bash", error=True, command="pytest"),
                    _tool("Bash", command="pytest")]) == "tests_passed"
    assert outcome([_tool("Bash", command="npm run build")]) == "build_passed"
    assert outcome([_tool("Bash", error=True, command="npx tsc --noEmit")]) == "failed"
    assert outcome([_tool("Bash", error=True, command="pytest"),
                    _tool("Bash", command="git commit -m x")]) == "committed"
    assert outcome([_t("user", "do the thing please now"), _t("user", "great, thanks")]) \
        == "user_confirmed"
    assert outcome([_t("user", "do it")]) == "unknown"


def test_summarize_truncates() -> None:
    long_out = "\n".join(f"line {i}" for i in range(100))
    text = summarize([_t("user", "u"), _t("assistant", "x" * 1000),
                      _tool("Bash", long_out, command="make"),
                      _tool("Read", "secret file body", file_path="f.py"),
                      _tool("apply_patch", input="*** Update File: g.py")])
    assert "User: u" in text and "x" * 400 + "..." in text
    assert "[... 60 lines ...]" in text and "Tool Read: f.py" in text
    assert "secret file body" not in text and "Tool apply_patch: g.py" in text
    big = summarize([_t("user", "y" * 20000)])
    assert "[... transcript truncated ...]" in big and len(big) < 12100


def test_default_candidate_prefers_substantive_answer() -> None:
    s = parse_session(CC / "cc-2.1.251-pagination.jsonl")
    assert s is not None
    first = split_episodes(s)[0]
    [cand] = default_candidates(first)
    assert cand.text.startswith("Added cursor pagination to GET /books")
    assert cand.subject == "bookshelf" and cand.metadata["outcome"] == "committed"
    assert cand.metadata["referenced_files"] == ["app/routes/books.py"]
    assert cand.source.text.startswith("add cursor pagination")
    no_answer = first.model_copy(update={"turns": [t for t in first.turns
                                                   if t.role != "assistant"]})
    assert default_candidates(no_answer) == []


def test_referenced_paths() -> None:
    assert referenced_paths("See app/x.py and README.md, v1.2 and e.g. things", ["README.md"]) \
        == ["app/x.py", "README.md"]
