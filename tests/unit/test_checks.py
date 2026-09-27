from __future__ import annotations

import pytest

from memworthy.checks.builtins import (
    date_parse,
    file_was_read,
    outcome_verified,
    source_is_user,
)
from memworthy.checks.dates import classify_timing, parse_now
from memworthy.checks.registry import check, check_names, get_check
from memworthy.checks.secrets import (
    find_secrets,
    redact_candidate,
    redact_text,
    secret_scan,
    shannon_entropy,
)
from memworthy.models import Candidate, SourceRef

# One positive and one negative example per vendored pattern. Values are fake.
SECRETS = {
    "private_key": ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
                    "-----BEGIN PUBLIC KEY-----"),
    "anthropic": ("sk-ant-api03-" + "Ab1" * 10, "sk-ant-short"),
    "openrouter": ("sk-or-v1-" + "0a1b2c3d" * 8, "sk-or-v1-short"),
    "openai": ("sk-proj-" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3", "sk-12"),
    "typesafe": ("apikey_" + "a1b2c3d4e5" * 5, "apikey_short"),
    "aws_access_key": ("AKIA" + "ABCDEFGHIJKLMNOP", "AKIA1234"),
    "github": ("ghp_" + "a" * 36, "ghp_short"),
    "stripe": ("sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc", "sk_live_x"),
    "slack": ("xoxb-" + "123456789012-abcdefghij", "xoxb-1"),
    "google": ("AIza" + "SyA1234567890abcdefghijklmnopqrstuv", "AIzaShort"),
    "jwt": ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
            "eyJhbGciOiJIUzI1NiJ9"),
    "connection_string": ("postgres://admin:hunter2@db.example.com:5432/app",
                          "postgres://db.example.com:5432/app"),
}


@pytest.mark.parametrize("kind", sorted(SECRETS))
def test_each_secret_pattern(kind: str) -> None:
    positive, negative = SECRETS[kind]
    text, kinds = redact_text(f"value: {positive} end")
    assert kind in kinds, kinds
    assert positive not in text and f"[REDACTED:{kind}]" in text
    assert kind not in find_secrets(f"value: {negative} end")


def test_high_entropy_assignment() -> None:
    text, kinds = redact_text("export API_TOKEN=Zq8vN2kLp4Xr7Tb1Wm9Yc3Hd")
    assert kinds == ["assignment"] and text == "export API_TOKEN=[REDACTED:assignment]"
    assert find_secrets("password=aaaaaaaaaaaa") == []  # low entropy
    assert find_secrets("my key is in the drawer") == []
    assert shannon_entropy("") == 0.0
    text, kinds = redact_text("DB_PASSWORD='abc'", {"entropy_threshold": 1.0})
    assert kinds == []  # value shorter than 8 characters


def test_extra_patterns() -> None:
    extra = {"extra_patterns": {"acme": r"ACME-\d{4}-\d{4}"}}
    kinds = find_secrets("internal ACME-1234-5678", extra)
    assert kinds == ["acme"]


def test_secret_scan_and_redact_candidate() -> None:
    key = "ghp_" + "b" * 36
    c = Candidate(text="token here", context=f"see {key}",
                  source=SourceRef(role="user", text=f"my token {key}"))
    assert secret_scan(c, {})
    new, redacted = redact_candidate(c, {})
    assert redacted == "token here"
    assert key not in new.context and key not in new.source.text
    assert not secret_scan(Candidate.from_text("nothing secret"), {})


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I live in Dubai", "none"),
        ("I moved to Riyadh last week", "past"),
        ("Flying to Riyadh tomorrow", "future"),
        ("Moving to Riyadh permanently next month", "future"),
        ("I'm in Lahore this week", "bounded"),
        ("I'm in Lahore until Friday", "bounded"),
        ("Staying here for the next two weeks", "bounded"),
        ("for a week I'll be in Rome", "bounded"),
        ("I've lived in Toronto since 2019", "present"),
        ("I currently work at Acme", "present"),
        ("I graduated three years ago", "past"),
        ("I will start the new job in 2 weeks", "future"),
        ("I used to smoke", "past"),
        ("The launch is on 2030-01-05", "future"),
        ("I married on 2001-05-04", "past"),
        ("My birthday party is on March 3, 2099", "future"),
        ("Born in 1990", "past"),
        ("I'll retire in 2090", "future"),
        ("I'm meeting her on Feb 30", "none"),
    ],
)
def test_classify_timing(text: str, expected: str) -> None:
    assert classify_timing(text, "2026-09-25T12:00:00Z") == expected


def test_timing_relative_to_now() -> None:
    assert classify_timing("It happens on 2026-09-25", "2026-09-25") == "present"
    assert classify_timing("Party on 2026-10-01", "2026-09-25") == "future"
    assert classify_timing("Party on 2026-10-01", "2026-12-25") == "past"
    assert classify_timing("Bad 2026-13-45 date", "2026-09-25") == "none"
    assert parse_now(None).tzinfo is not None
    c = Candidate.from_text("Party on 2026-10-01", metadata={"timestamp": "2026-12-25T00:00:00"})
    assert date_parse(c, {}) == "past"
    assert date_parse(c, {"now": "2026-01-01"}) == "future"


def test_source_is_user() -> None:
    assert source_is_user(Candidate.from_text("x"), {})
    assert not source_is_user(Candidate.from_text("x", role="assistant"), {})
    assert source_is_user(Candidate.from_text("x", role="assistant"),
                          {"allow_roles": ["user", "assistant"]})


def test_file_was_read() -> None:
    c = Candidate.from_text("x", metadata={"referenced_files": ["src/a.py", "b.py"],
                                           "files_read": ["/repo/src/a.py", "./b.py"]})
    assert file_was_read(c, {})
    c2 = Candidate.from_text("x", metadata={"referenced_files": ["src/a.py", "c.py"],
                                            "files_read": ["/repo/src/a.py"]})
    assert not file_was_read(c2, {})
    assert file_was_read(c2, {"min_fraction": 0.5})
    assert not file_was_read(Candidate.from_text("x"), {})


def test_outcome_verified() -> None:
    for outcome in ("tests_passed", "build_passed", "committed", "user_confirmed"):
        assert outcome_verified(Candidate.from_text("x", metadata={"outcome": outcome}), {})
    assert not outcome_verified(Candidate.from_text("x", metadata={"outcome": "failed"}), {})
    assert not outcome_verified(Candidate.from_text("x"), {})
    c = Candidate.from_text("x", metadata={"outcome": "committed"})
    assert not outcome_verified(c, {"accept": ["tests_passed"]})


def test_registry() -> None:
    @check("always")
    def always(candidate: Candidate, args: dict[str, object]) -> bool:
        return True

    assert get_check("always") is always
    assert {"source_is_user", "secret_scan", "date_parse", "file_was_read",
            "outcome_verified", "always"} <= set(check_names())
    assert get_check("missing") is None
