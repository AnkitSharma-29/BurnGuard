import json
from datetime import date

import pytest

from burnguard import Budget, BudgetExceeded
from burnguard.budget import weighted_tokens
from burnguard.config import Config
from conftest import assistant, write_lines


def test_weighted_tokens_discounts_cache_reads():
    usage = {
        "input_tokens": 10,
        "output_tokens": 100,
        "cache_creation_input_tokens": 1000,
        "cache_read_input_tokens": 50_000,
    }
    assert weighted_tokens(usage, 0.1) == 10 + 100 + 1000 + 5000
    assert weighted_tokens(usage, 1.0) == 51_110


def test_weighted_tokens_ignores_garbage():
    assert weighted_tokens({"input_tokens": None, "output_tokens": "x"}, 0.1) == 0


def test_record_and_check():
    budget = Budget(Config(daily_token_limit=1000))
    budget.record(600)
    budget.check()
    budget.record(400)
    with pytest.raises(BudgetExceeded):
        budget.check()
    assert budget.status().remaining == 0


def test_no_limit_never_exceeds():
    budget = Budget(Config(daily_token_limit=None))
    budget.record(10**9)
    budget.check()
    assert budget.status().remaining is None


def test_transcript_counts_each_message_once(tmp_path):
    t = tmp_path / "s1.jsonl"
    # Claude Code writes one line per content block, repeating the usage.
    write_lines(t, [assistant("m1", inp=5, out=100)] * 3 + [{"type": "user"}])
    budget = Budget(Config(cache_read_weight=0.1))
    assert budget.sync_transcript(str(t)).used == 105
    # Re-syncing with no new lines adds nothing.
    assert budget.sync_transcript(str(t)).used == 105
    write_lines(t, [assistant("m1", inp=5, out=100), assistant("m2", out=50, cache_read=1000)])
    assert budget.sync_transcript(str(t)).used == 105 + 50 + 100


def test_transcript_partial_line_is_read_later(tmp_path):
    t = tmp_path / "s.jsonl"
    full = json.dumps(assistant("m1", out=10)) + "\n"
    partial = json.dumps(assistant("m2", out=20))
    t.write_text(full + partial[:15], encoding="utf-8")
    budget = Budget(Config())
    assert budget.sync_transcript(str(t)).used == 10
    t.write_text(full + partial + "\n", encoding="utf-8")
    assert budget.sync_transcript(str(t)).used == 30


def test_transcript_includes_subagents(tmp_path):
    t = tmp_path / "abc.jsonl"
    write_lines(t, [assistant("main", out=10)])
    write_lines(tmp_path / "abc" / "subagents" / "agent-1.jsonl", [assistant("sub", out=7)])
    assert Budget(Config()).sync_transcript(str(t)).used == 17


def test_corrupt_lines_and_missing_file_are_ignored(tmp_path):
    t = tmp_path / "s.jsonl"
    t.write_text('not json\n{"type": "assistant", "message": 5}\n', encoding="utf-8")
    budget = Budget(Config())
    assert budget.sync_transcript(str(t)).used == 0
    assert budget.sync_transcript(str(tmp_path / "missing.jsonl")).used == 0


def test_new_day_resets_usage_but_not_offsets(tmp_path, bg_home):
    t = tmp_path / "s.jsonl"
    write_lines(t, [assistant("m1", out=100)])
    budget = Budget(Config())
    budget.sync_transcript(str(t))
    state = json.loads((bg_home / "budget.json").read_text())
    state["day"] = "2000-01-01"
    (bg_home / "budget.json").write_text(json.dumps(state))
    assert budget.status().used == 0  # yesterday's usage does not count
    assert budget.sync_transcript(str(t)).used == 0  # and is not re-counted
    assert json.loads((bg_home / "budget.json").read_text())["day"] == date.today().isoformat()


def test_truncated_transcript_is_reread(tmp_path):
    t = tmp_path / "s.jsonl"
    write_lines(t, [assistant("a", out=10), assistant("b", out=10)])
    budget = Budget(Config())
    budget.sync_transcript(str(t))
    write_lines(t, [assistant("c", out=5)], mode="w")
    assert budget.sync_transcript(str(t)).used == 25


def test_corrupt_state_file_recovers(bg_home):
    bg_home.mkdir(parents=True, exist_ok=True)
    (bg_home / "budget.json").write_text("{broken")
    assert Budget(Config()).record(5).used == 5
