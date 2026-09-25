from __future__ import annotations

from pathlib import Path

import pytest

from memgate.pairs import PairError, bundled_pairs_path, expand_pairs, load_pairs


def test_expand_cartesian_and_pair_ids() -> None:
    cases = expand_pairs([{
        "template": "I {verb} {city}",
        "category": "temp",
        "fills": {"city": ["Lahore", "Dubai"]},
        "cases": [{"verb": "live in", "expect": "store"},
                  {"verb": "am visiting", "expect": "reject", "role": "user"}],
    }])
    assert [c.test.input for c in cases] == [
        "I live in Lahore", "I am visiting Lahore", "I live in Dubai", "I am visiting Dubai"]
    assert [c.pair_id for c in cases] == ["0:Lahore"] * 2 + ["0:Dubai"] * 2
    assert {c.category for c in cases} == {"temp"}


def test_fields_are_formatted() -> None:
    [c] = expand_pairs([{"template": "Not {x}", "fills": {"x": ["a"]},
                         "existing": ["I {x}"], "cases": [{"expect": "supersede"}]}])
    assert c.test.existing == ["I a"] and c.category == "template_0"


def test_errors(tmp_path: Path) -> None:
    with pytest.raises(PairError, match="needs 'template'"):
        expand_pairs([{"cases": []}])
    with pytest.raises(PairError, match="no value"):
        expand_pairs([{"template": "I {verb}", "cases": [{"expect": "store"}]}])
    bad = tmp_path / "p.yaml"
    bad.write_text("a: 1\n")
    with pytest.raises(PairError, match="YAML list"):
        load_pairs(bad)


def test_bundled_pairs_expand() -> None:
    path = bundled_pairs_path("personal-memory")
    assert path is not None
    cases = load_pairs(path)
    assert len(cases) >= 250
    assert bundled_pairs_path("nope") is None
