"""Generate the session fixtures in tests/fixtures/sessions.

The record layouts (keys, nesting, record types, tool-output formats) are copied from real
Claude Code 2.1.251-2.1.281 and Codex 0.107-0.130 session files. The content is invented: a
toy "bookshelf" API. No real project or personal data is included. Secrets are fake.

    python scripts/make_session_fixtures.py
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sessions"
CWD = "/home/dev/bookshelf"
NS = uuid.UUID("7d3f1c2a-0000-4000-8000-000000000000")
FAKE_KEY = "sk-proj-Ex4mpleKeyN0tRealAbCdEf12"


def uid(*parts: object) -> str:
    return str(uuid.uuid5(NS, "/".join(map(str, parts))))


class Clock:
    def __init__(self, start: str) -> None:
        self.t = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)

    def tick(self, seconds: float = 4) -> str:
        self.t += timedelta(seconds=seconds)
        return self.t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ------------------------------------------------------------------ Claude Code


class ClaudeSession:
    def __init__(self, name: str, version: str, start: str, branch: str = "main") -> None:
        self.name, self.version, self.branch = name, version, branch
        self.sid = uid("cc", name)
        self.clock = Clock(start)
        self.records: list[dict[str, Any]] = []
        self.parent: str | None = None
        self.n = 0
        self.prompt = uid(self.sid, "prompt", 0)

    def _base(self) -> dict[str, Any]:
        self.n += 1
        return {"parentUuid": self.parent, "isSidechain": False}

    def _tail(self, rec: dict[str, Any], ts: str) -> dict[str, Any]:
        rec.update({"uuid": uid(self.sid, self.n), "timestamp": ts, "userType": "external",
                    "entrypoint": "cli", "cwd": CWD, "sessionId": self.sid,
                    "version": self.version, "gitBranch": self.branch})
        self.parent = rec["uuid"]
        self.records.append(rec)
        return rec

    def meta(self) -> None:
        self.records += [
            {"type": "permission-mode", "permissionMode": "auto", "sessionId": self.sid},
            {"type": "mode", "mode": "normal", "sessionId": self.sid},
        ]
        rec = self._base()
        rec.update({"attachment": {}, "type": "attachment"})
        self._tail(rec, self.clock.tick(1))

    def user(self, text: str) -> None:
        self.prompt = uid(self.sid, "prompt", self.n)
        self.records.append({"type": "file-history-snapshot", "messageId": uid(self.sid, "m",
                             self.n), "snapshot": {}, "isSnapshotUpdate": False})
        rec = self._base()
        rec.update({"promptId": self.prompt, "type": "user",
                    "message": {"role": "user", "content": text}, "permissionMode": "auto",
                    "origin": {"kind": "human"}, "promptSource": "typed"})
        self._tail(rec, self.clock.tick(20))

    def command(self, text: str, meta: bool = False) -> None:
        rec = self._base()
        rec.update({"type": "user", "message": {"role": "user", "content": text}})
        if meta:
            rec["isMeta"] = True
        self._tail(rec, self.clock.tick(1))

    def _assistant(self, content: list[dict[str, Any]], stop: str) -> None:
        rec = self._base()
        rec.update({"message": {
            "model": "claude-sonnet-5", "id": f"msg_{uid(self.sid, 'msg', self.n)[:24]}",
            "type": "message", "role": "assistant", "content": content, "stop_reason": stop,
            "stop_sequence": None, "stop_details": None,
            "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1200,
                      "cache_read_input_tokens": 30000, "output_tokens": 150,
                      "service_tier": "standard"}},
            "requestId": f"req_{uid(self.sid, 'req', self.n)[:24]}", "type": "assistant"})
        self._tail(rec, self.clock.tick(3))

    def say(self, text: str) -> None:
        self._assistant([{"type": "thinking", "thinking": "", "signature": "[removed]"}],
                        "tool_use")
        self._assistant([{"type": "text", "text": text}], "end_turn")

    def tool(self, name: str, tool_input: dict[str, Any], output: str,
             is_error: bool = False, result: dict[str, Any] | None = None) -> None:
        tid = f"toolu_{uid(self.sid, 'tool', self.n)[:24]}"
        self._assistant([{"type": "tool_use", "id": tid, "name": name, "input": tool_input,
                          "caller": {"type": "direct"}}], "tool_use")
        rec = self._base()
        if result is None:
            result = {"stdout": output, "stderr": "", "interrupted": False, "isImage": False,
                      "noOutputExpected": False}
        rec.update({"promptId": self.prompt, "type": "user",
                    "message": {"role": "user", "content": [
                        {"tool_use_id": tid, "type": "tool_result", "content": output,
                         "is_error": is_error}]},
                    "toolUseResult": result,
                    "sourceToolAssistantUUID": self.parent, "session_id": self.sid})
        self._tail(rec, self.clock.tick(2))

    def read(self, path: str, body: str) -> None:
        lines = "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(body.splitlines()))
        self.tool("Read", {"file_path": f"{CWD}/{path}"}, lines,
                  result={"type": "text", "file": {"filePath": f"{CWD}/{path}",
                                                    "content": body}})

    def edit(self, path: str, old: str, new: str) -> None:
        self.tool("Edit", {"replace_all": False, "file_path": f"{CWD}/{path}",
                           "old_string": old, "new_string": new},
                  f"The file {CWD}/{path} has been updated successfully.",
                  result={"filePath": f"{CWD}/{path}", "oldString": old, "newString": new,
                          "originalFile": "", "structuredPatch": [], "userModified": False,
                          "replaceAll": False})

    def bash(self, command: str, output: str, is_error: bool = False) -> None:
        self.tool("Bash", {"command": command, "description": "Run command"}, output, is_error)

    def finish(self, title: str) -> None:
        self.records += [
            {"type": "ai-title", "aiTitle": title, "sessionId": self.sid},
            {"type": "last-prompt", "leafUuid": self.parent, "sessionId": self.sid},
            {"type": "cost-state", "sessionId": self.sid, "totalCostUSD": 0.21,
             "totalLinesAdded": 12, "totalLinesRemoved": 3, "hasUnknownModelCost": False},
        ]
        write(OUT / "claude_code" / f"{self.name}.jsonl", self.records)


# ------------------------------------------------------------------ Codex


class CodexSession:
    def __init__(self, name: str, version: str, start: str) -> None:
        self.name, self.version = name, version
        self.sid = uid("codex", name)
        self.clock = Clock(start)
        self.records: list[dict[str, Any]] = []
        self.turn = ""
        self.n = 0

    def _add(self, rtype: str, payload: dict[str, Any], seconds: float = 2) -> None:
        self.records.append({"timestamp": self.clock.tick(seconds), "ordinal": len(self.records),
                             "type": rtype, "payload": payload})

    def meta(self) -> None:
        self._add("session_meta", {
            "session_id": self.sid, "id": self.sid, "timestamp": self.clock.tick(0), "cwd": CWD,
            "originator": "Codex Desktop", "cli_version": self.version, "source": "vscode",
            "model_provider": "openai", "base_instructions": {}, "history_mode": "paginated",
            "git": {"commit_hash": uid(self.sid, "git").replace("-", "")[:40],
                    "branch": "main", "repository_url": "git@example.com:dev/bookshelf.git"}})

    def user(self, text: str) -> None:
        self.n += 1
        self.turn = uid(self.sid, "turn", self.n)
        self._add("event_msg", {"type": "task_started", "turn_id": self.turn,
                                "model_context_window": 258400,
                                "collaboration_mode_kind": "default"}, 30)
        if self.n == 1:
            self._add("response_item", {"type": "message", "role": "developer", "content": [
                {"type": "input_text", "text": "<permissions instructions>\n[removed]"}]}, 0)
            self._add("response_item", {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "# AGENTS.md instructions for " + CWD +
                 "\n\n<INSTRUCTIONS>\n[removed]\n</INSTRUCTIONS>"},
                {"type": "input_text", "text": f"<environment_context>\n  <cwd>{CWD}</cwd>\n"
                 "  <shell>zsh</shell>\n</environment_context>"}]}, 0)
        self._add("turn_context", {"turn_id": self.turn, "cwd": CWD,
                                   "current_date": self.clock.t.date().isoformat(),
                                   "approval_policy": "on-request",
                                   "model": "gpt-5.3-codex", "effort": "high",
                                   "summary": "auto"}, 0)
        self._add("response_item", {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": text + "\n"}]}, 0)
        self._add("event_msg", {"type": "token_count", "info": None, "rate_limits": None}, 1)

    def say(self, text: str, final: bool = False) -> None:
        self._add("response_item", {"type": "reasoning", "summary": [], "content": None,
                                    "encrypted_content": "[removed]"}, 3)
        self._add("response_item", {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": text}],
            "phase": "final_answer" if final else "commentary"}, 1)
        if final:
            self._add("event_msg", {"type": "task_complete", "turn_id": self.turn,
                                    "last_agent_message": text}, 0)

    def exec(self, cmd: str, output: str, code: int = 0) -> None:
        call = f"call_{uid(self.sid, 'call', len(self.records))[:24]}"
        self._add("response_item", {"type": "function_call", "name": "exec_command",
                                    "arguments": json.dumps({"cmd": cmd, "workdir": CWD}),
                                    "call_id": call})
        body = (f"Chunk ID: {call[5:11]}\nWall time: 0.0521 seconds\nProcess exited with code "
                f"{code}\nOriginal token count: {len(output) // 4}\nOutput:\n{output}")
        self._add("response_item", {"type": "function_call_output", "call_id": call,
                                    "output": body})

    def patch(self, action: str, path: str, body: str) -> None:
        call = f"call_{uid(self.sid, 'call', len(self.records))[:24]}"
        patch = f"*** Begin Patch\n*** {action} File: {path}\n{body}\n*** End Patch"
        self._add("response_item", {"type": "custom_tool_call", "status": "completed",
                                    "call_id": call, "name": "apply_patch", "input": patch})
        letter = {"Add": "A", "Update": "M", "Delete": "D"}[action]
        out = {"output": f"Success. Updated the following files:\n{letter} {path}\n",
               "metadata": {"exit_code": 0, "duration_seconds": 0.1}}
        self._add("response_item", {"type": "custom_tool_call_output", "call_id": call,
                                    "output": json.dumps(out)})

    def finish(self) -> None:
        write(OUT / "codex" / f"{self.name}.jsonl", self.records)


def write(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


# ------------------------------------------------------------------ sessions


def cc_pagination() -> None:
    s = ClaudeSession("cc-2.1.251-pagination", "2.1.251", "2026-08-31T09:00:00")
    s.meta()
    s.user("add cursor pagination to the GET /books endpoint so the mobile app can page "
           "through results")
    s.bash("grep -rn \"def list_books\" app", "app/routes/books.py:18:def list_books():")
    s.read("app/routes/books.py", "from flask import Blueprint, request\n\nbp = Blueprint("
           "'books', __name__)\n\n@bp.get('/books')\ndef list_books():\n    return "
           "jsonify([b.to_dict() for b in Book.query.all()])")
    s.edit("app/routes/books.py", "    return jsonify([b.to_dict() for b in Book.query.all()])",
           "    limit = min(int(request.args.get('limit', 20)), 100)\n    cursor = "
           "request.args.get('cursor')\n    return jsonify(paginate(Book.query, cursor, limit))")
    s.bash("pytest tests/test_books.py -q", "..............\n14 passed in 0.42s")
    s.say("Added cursor pagination to GET /books in app/routes/books.py: clients pass `limit` "
          "(max 100) and the `cursor` returned by the previous page. The book tests pass.")
    s.user("commit this")
    s.bash("git add app/routes/books.py && git commit -m \"feat(books): cursor pagination\"",
           "[main 4f2a9c1] feat(books): cursor pagination\n 1 file changed, 4 insertions(+), "
           "1 deletion(-)")
    s.say("Committed as 4f2a9c1.")
    s.user("why cursor pagination instead of offset pagination for the books list?")
    s.say("Cursor pagination stays stable when books are added while a client is paging, and it "
          "avoids slow OFFSET scans on large tables. Offset pagination was rejected for those "
          "two reasons.")
    s.user("agreed, keep cursors everywhere")
    s.say("Noted: list endpoints in bookshelf use cursor pagination.")
    s.user("hi, can you start the dev server for me please")
    s.bash("flask --app app run --port 5000 &", " * Running on http://127.0.0.1:5000")
    s.say("The dev server is running on port 5000.")
    s.finish("Add cursor pagination to books endpoint")


def cc_importer() -> None:
    s = ClaudeSession("cc-2.1.266-importer-fix", "2.1.266", "2026-09-02T14:00:00")
    s.meta()
    s.user("the import script crashes when a CSV row has an empty ISBN column, please fix it")
    s.read("scripts/import_books.py", "def parse_row(row):\n    isbn = row['isbn'].strip()\n"
           "    return Book(isbn=isbn, title=row['title'])")
    s.bash("pytest tests/test_import.py -q", "F.......\nFAILED tests/test_import.py::"
           "test_blank_isbn - AttributeError: 'NoneType' object has no attribute 'strip'\n"
           "1 failed, 7 passed in 0.31s", is_error=True)
    s.edit("scripts/import_books.py", "    isbn = row['isbn'].strip()",
           "    isbn = (row.get('isbn') or '').strip()\n    if not isbn:\n        return None")
    s.bash("pytest tests/test_import.py -q", "........\n8 passed in 0.29s")
    s.say("Fixed the importer crash: parse_row called .strip() on a missing ISBN value. Rows with "
          "a blank ISBN are now skipped in scripts/import_books.py, and the import tests pass.")
    s.user("the search endpoint is slow, can you speed it up with some caching")
    s.edit("app/routes/search.py", "def search(q):", "@lru_cache(maxsize=512)\ndef search(q):")
    s.say("Added an lru_cache around search().")
    s.user("revert it, use an index instead")
    s.edit("app/routes/search.py", "@lru_cache(maxsize=512)\ndef search(q):", "def search(q):")
    s.edit("migrations/0007_title_index.py", "", "op.create_index('ix_books_title', 'books', "
           "['title'])")
    s.bash("pytest tests/test_search.py -q", "......\n6 passed in 0.22s")
    s.say("Reverted the cache and added a database index on books.title in "
          "migrations/0007_title_index.py; search tests pass.")
    s.user("set up the goodreads client with my key so the sync job can call their API")
    s.bash("cat .env", f"GOODREADS_API_KEY={FAKE_KEY}")
    s.edit("sync/goodreads.py", "API_KEY = None", "API_KEY = os.environ['GOODREADS_API_KEY']")
    s.say(f"Configured sync/goodreads.py to read GOODREADS_API_KEY (currently {FAKE_KEY}) and "
          "a test request succeeded.")
    s.user("great, works")
    s.finish("Fix importer crash on blank ISBN")


def cc_login() -> None:
    s = ClaudeSession("cc-2.1.281-login-only", "2.1.281", "2026-09-20T08:00:00")
    s.meta()
    s.command("<local-command-caveat>Caveat: The messages below were generated by the user "
              "while running local commands.</local-command-caveat>", meta=True)
    s.command("<command-name>/login</command-name>\n<command-message>login</command-message>")
    s.command("<local-command-stdout>Login successful</local-command-stdout>")
    s.records.append({"type": "last-prompt", "leafUuid": s.parent, "sessionId": s.sid})
    write(OUT / "claude_code" / f"{s.name}.jsonl", s.records)


def codex_docker() -> None:
    s = CodexSession("codex-0.107.0-docker", "0.107.0-alpha.5", "2026-03-02T10:00:00")
    s.meta()
    s.user("write a Dockerfile so we can deploy the bookshelf API on a small VPS")
    s.say("I'll check the app entry point and dependencies first.")
    s.exec("ls", "README.md\napp\nrequirements.txt\ntests\nwsgi.py")
    s.exec("sed -n '1,40p' requirements.txt", "flask==3.0.3\ngunicorn==22.0.0\nsqlalchemy==2.0.30")
    s.patch("Add", "Dockerfile", "+FROM python:3.12-slim\n+WORKDIR /app\n+COPY . .\n+RUN pip "
            "install -r requirements.txt\n+CMD [\"gunicorn\", \"-b\", \"0.0.0.0:8000\", "
            "\"wsgi:app\"]")
    s.exec("docker build -t bookshelf .", "Successfully built 3f2a1b9c\nSuccessfully tagged "
           "bookshelf:latest")
    s.say("Added a Dockerfile that runs the API with gunicorn on port 8000 from "
          "python:3.12-slim; the image builds.", final=True)
    s.user("from now on always run ruff format before committing anything in this repo")
    s.say("Understood: in bookshelf I'll run `ruff format` before every commit.", final=True)
    s.finish()


def codex_explain() -> None:
    s = CodexSession("codex-0.117.0-explain", "0.117.0-alpha.12", "2026-03-26T16:00:00")
    s.meta()
    s.user("explain how the recommendation scoring works in this codebase, step by step")
    s.exec("sed -n '1,80p' app/recommend/score.py", "def score(user, book):\n    f = "
           "features(user, book)\n    return 0.5 * f.genre + 0.3 * f.author + 0.2 * f.recency")
    s.exec("sed -n '1,60p' app/recommend/features.py", "def features(user, book):\n    ...")
    s.say("Recommendations are scored in app/recommend/score.py: app/recommend/features.py "
          "computes genre overlap, author affinity and recency, score() weights them 0.5, 0.3 "
          "and 0.2, and the top 10 books are returned.", final=True)
    s.finish()


def codex_mixed() -> None:
    s = CodexSession("codex-0.130.0-mixed", "0.130.0-alpha.5", "2026-05-11T16:00:00")
    s.meta()
    s.user("do you have access to this repository and its test suite?")
    s.exec("ls", "README.md\napp\ntests")
    s.say("Yes, I can see the repository and the tests folder.", final=True)
    s.user("the book cover upload fails for PNG files larger than 5 MB, please fix")
    s.patch("Update", "app/uploads.py", "-MAX_UPLOAD = 5 * 1024 * 1024\n+MAX_UPLOAD = 10 * 1024 "
            "* 1024")
    s.exec("pytest tests/test_uploads.py -q", ".F..\nFAILED tests/test_uploads.py::"
           "test_large_png - AssertionError: 413 != 201\n1 failed, 3 passed", code=1)
    s.say("Raised the upload limit to 10 MB in app/uploads.py, which should fix large PNG "
          "cover uploads; test_large_png still fails, so the proxy limit may also need "
          "changing.", final=True)
    s.user("should we move the background jobs from cron to a proper task queue like RQ?")
    s.say("A queue gives retries and visibility; cron is simpler and has no extra service to "
          "run. It depends on how many jobs we expect.", final=True)
    s.user("not sure yet, let's revisit next sprint")
    s.say("Okay, leaving cron in place for now.", final=True)
    s.finish()


def main() -> None:
    for fn in (cc_pagination, cc_importer, cc_login, codex_docker, codex_explain, codex_mixed):
        fn()
    for p in sorted(OUT.rglob("*.jsonl")):
        print(p.relative_to(OUT), sum(1 for _ in p.open()), "records")


if __name__ == "__main__":
    main()
