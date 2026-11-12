import json
import os
import time

from burnguard import LoopDetector
from burnguard.loops import SessionLoops, fingerprint, prune_sessions, repeats


def test_same_call_same_result_is_a_loop():
    d = LoopDetector(max_repeats=3)
    assert not d.is_loop("pytest", "1 failed")
    assert not d.is_loop("pytest", "1 failed")
    assert d.is_loop("pytest", "1 failed")


def test_same_call_with_changing_result_is_progress():
    d = LoopDetector(max_repeats=3)
    for i in range(10):
        assert not d.is_loop("pytest", f"{i} failed")


def test_interleaved_calls_still_detected():
    d = LoopDetector(max_repeats=3)
    for _ in range(2):
        d.record("ls", "a b")
        d.record("cat x", "hello")
    d.record("ls", "a b")
    assert d.would_loop("ls")
    assert not d.would_loop("cat x")


def test_window_forgets_old_calls():
    d = LoopDetector(max_repeats=3, window=4)
    d.record("x", "r")
    d.record("x", "r")
    for i in range(3):
        d.record(f"other{i}", "r")
    assert not d.would_loop("x")


def test_fingerprint_ignores_description():
    a = {"command": "npm test", "description": "Run tests"}
    b = {"command": "npm test", "description": "Re-run the tests"}
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(a) != fingerprint({"command": "npm test -- -x"})


def test_repeats_helper():
    assert repeats([("c", "r1"), ("c", "r1")], "c") == 2
    assert repeats([("c", "r1"), ("c", "r2")], "c") == 0
    assert repeats([], "c") == 0


def test_session_loops_persist_across_instances():
    for _ in range(3):
        SessionLoops("s1").record("Bash", {"command": "make"}, {"stdout": "error 1"})
    assert SessionLoops("s1").check("Bash", {"command": "make"}) == 3
    assert SessionLoops("s2").check("Bash", {"command": "make"}) == 0


def test_session_id_is_sanitized(bg_home):
    SessionLoops("../../evil").record("Bash", {}, "")
    files = list((bg_home / "sessions").glob("*.json"))
    assert len(files) == 1 and files[0].parent == bg_home / "sessions"


def test_prune_sessions(bg_home):
    SessionLoops("old").record("Bash", {}, "")
    SessionLoops("new").record("Bash", {}, "")
    old = bg_home / "sessions" / "old.json"
    past = time.time() - 10 * 86400
    os.utime(old, (past, past))
    assert prune_sessions() == 1
    assert not old.exists()


def test_session_fingerprint_ignores_nested_description():
    s = SessionLoops("d")
    for desc in ("first try", "second try", "third try"):
        s.record("Bash", {"command": "make", "description": desc}, {"stdout": "err"})
    assert s.check("Bash", {"command": "make", "description": "fourth"}) == 3


def test_stale_reservations_expire():
    s = SessionLoops("ttl")
    for i in range(3):
        assert s.reserve("Bash", {"command": "x"}, f"id{i}", limit=3) == i
    assert s.reserve("Bash", {"command": "x"}, "id3", limit=3) == 3
    state = json.loads(s.path.read_text())
    for v in state["pending"].values():
        v[1] = time.time() - 3600
    s.path.write_text(json.dumps(state))
    assert s.reserve("Bash", {"command": "x"}, "id4", limit=3) == 0


def test_record_clears_reservation():
    s = SessionLoops("clr")
    s.reserve("Bash", {"command": "x"}, "id0", limit=3)
    s.record("Bash", {"command": "x"}, "out", "id0")
    assert json.loads(s.path.read_text())["pending"] == {}
