"""Study progress: counters, ETA, console line, atomic progress file."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from resilimes.smt.progress import (
    Progress,
    bar,
    clock_text,
    fallback_kind,
    read_progress,
    redact,
    write_atomic,
)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _progress(tmp_path: Path | None = None, **kwargs: Any) -> tuple[Progress, Clock, io.StringIO]:
    clock = Clock()
    stream = io.StringIO()
    options: dict[str, Any] = {
        "study": "shift_lead",
        "plan": ["rules", "nightshift"],
        "provider": "nightshift",
        "budget": 200,
        "stream": stream,
        "tty": False,
        "clock": clock,
        "wall": lambda: 1_790_000_000.0,
    }
    if tmp_path is not None:
        options["path"] = tmp_path / "out.json.progress.json"
    options.update(kwargs)
    return Progress(**options), clock, stream


def _entry(cause: str | None = None, differs: bool = False, t: float = 0.0) -> dict[str, Any]:
    return {"fallback": cause is not None, "fallback_cause": cause, "differs": differs, "t": t}


def test_fallback_kinds_group_the_shift_lead_causes() -> None:
    assert fallback_kind(None) is None
    assert fallback_kind("timeout: no reply in 30 s") == "timeout"
    assert fallback_kind("bad_json: no object") == "invalid"
    assert fallback_kind("unknown_option") == "invalid"
    assert fallback_kind("invariant: makes a hot/VIP lot late") == "guardrail"
    assert fallback_kind("budget: 200 decider calls used") == "budget"
    assert fallback_kind("provider_error: ConnectError") == "error"
    assert fallback_kind("error: KeyError") == "error"


def test_counters_latency_and_line() -> None:
    progress, clock, _stream = _progress()
    progress.begin_run("published", 1, "nightshift", 48 * 3600.0)
    for cause, differs, latency in (
        (None, True, 8.0),
        (None, False, 4.0),
        ("timeout: no reply in 30 s", False, 30.0),
        ("bad_json: x", False, 2.0),
        ("invariant: makes a hot/VIP lot late", False, 6.0),
    ):
        progress.call_started()
        clock.t += latency
        progress.call_finished()
        progress.decision(_entry(cause, differs, t=3600.0))
    progress.decision(_entry("budget: 200 decider calls used", t=7200.0))
    progress.sim_time(12 * 3600.0)
    snap = progress.snapshot()
    ai = snap["ai"]
    assert ai["exceptions"] == 6
    assert ai["calls"] == 5
    assert ai["accepted"] == 2
    assert ai["overrides"] == 1
    assert ai["fallback"] == 4
    assert ai["fallbacks"] == {
        "timeout": 1,
        "invalid": 1,
        "guardrail": 1,
        "budget": 1,
        "error": 0,
    }
    assert ai["latency_ms"] == {"avg": 10000.0, "last": 6000.0}
    assert ai["budget"] == 200
    assert snap["sim"] == {"t_h": 12.0, "horizon_h": 48.0, "pct": 25.0}
    assert snap["status"] == "running"
    line = progress.line(snap)
    assert line.startswith("shift_lead 1/2 published s1 nightshift")
    assert "sim 12.0/48h  25% [#####---------------]" in line
    assert "AI 5/200 ok 2 fb 4 (timeout 1, invalid 1, guardrail 1, budget 1)" in line
    assert "LLM avg 10.0s last 6.0s" in line
    assert line.isascii()


def test_wait_shows_a_call_in_flight() -> None:
    progress, clock, _stream = _progress()
    progress.begin_run("published", 1, "nightshift", 3600.0)
    progress.call_started()
    clock.t += 17.0
    snap = progress.snapshot()
    assert snap["ai"]["wait_s"] == 17.0
    assert "wait 17s" in progress.line(snap)


def test_eta_from_sim_rate_then_arm_means() -> None:
    progress, clock, _stream = _progress(plan=["rules", "nightshift", "rules", "nightshift"])
    assert progress.eta() is None
    progress.begin_run("published", 1, "rules", 100.0)
    clock.t += 10.0
    progress.sim_time(25.0)  # 25 % in 10 s: 30 s left in this run
    # Later runs: rules (no finished run yet: projected 40 s), nightshift unknown.
    assert progress.eta() is None
    progress.end_run()
    assert progress.walls == {"rules": [10.0]}
    progress.begin_run("published", 1, "nightshift", 100.0)
    clock.t += 50.0
    progress.sim_time(50.0)  # 50 s left here, then rules 10 s, nightshift 100 s
    assert progress.eta() == 160.0
    snap = progress.snapshot()
    assert snap["eta_s"] == 160.0
    assert snap["elapsed_s"] == 60.0
    assert "0:01:00 ETA 0:02:40" in progress.line(snap)


def test_eta_without_sim_time_uses_the_arm_mean() -> None:
    progress, clock, _stream = _progress(plan=["rules", "rules"])
    progress.begin_run("published", 1, "rules", 100.0)
    clock.t += 30.0
    progress.end_run()
    progress.begin_run("published", 2, "rules", 100.0)
    clock.t += 10.0
    assert progress.eta() == 20.0


def test_absorb_counts_a_worker_row() -> None:
    progress, clock, _stream = _progress(plan=["rules", "mock", "rules", "mock"])
    clock.t += 12.0
    progress.absorb({"book": "hot", "seed": 2, "arm": "rules", "wall_s": 24.0})
    clock.t += 20.0
    summary = {
        "exceptions": 10,
        "differs": 3,
        "fallback_causes": {"timeout": 2, "budget": 1, "invariant": 1},
    }
    progress.absorb(
        {"book": "hot", "seed": 2, "arm": "mock", "wall_s": 20.0, "shift_lead": summary}
    )
    snap = progress.snapshot()
    assert snap["runs"] == {"done": 2, "total": 4}
    assert snap["eta_s"] == 32.0
    line = progress.line(snap)
    assert "runs 2/4  50% [##########----------]" in line
    assert "exc 10 ok 6 fb 4" in line
    assert snap["totals"]["exceptions"] == 10
    assert snap["totals"]["accepted"] == 6
    assert snap["totals"]["calls"] == 9
    assert snap["totals"]["fallbacks"]["guardrail"] == 1
    assert progress.walls == {"rules": [12.0], "mock": [20.0]}


def test_log_lines_are_periodic_when_not_a_tty() -> None:
    progress, clock, stream = _progress(log_every=10.0)
    progress.start(background=False)
    progress.begin_run("published", 1, "rules", 100.0)
    lines = stream.getvalue().count("\n")
    for _ in range(9):
        clock.t += 1.0
        progress.sim_time(clock.t - 1000.0)
    assert stream.getvalue().count("\n") == lines
    clock.t += 1.5
    progress.sim_time(11.0)
    assert stream.getvalue().count("\n") == lines + 1
    assert "\r" not in stream.getvalue()


def test_tty_rewrites_one_line() -> None:
    progress, clock, stream = _progress(tty=True)
    progress.start(background=False)
    progress.begin_run("published", 1, "rules", 100.0)
    clock.t += 1.0
    progress.sim_time(50.0)
    progress.close("done")
    text = stream.getvalue()
    assert text.count("\r") >= 3
    assert text.endswith("\n")
    assert text.count("\n") == 1


def test_file_is_written_atomically_and_marks_done(tmp_path: Path) -> None:
    progress, clock, _stream = _progress(tmp_path)
    progress.start(background=False)
    path = tmp_path / "out.json.progress.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["status"] == "running"
    assert body["runs"] == {"done": 0, "total": 2}
    progress.begin_run("published", 1, "rules", 100.0)
    clock.t += 3.0
    progress.sim_time(40.0)
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["sim"]["pct"] == 40.0
    progress.end_run()
    progress.close("done")
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["status"] == "done"
    assert body["eta_s"] is None
    assert list(tmp_path.iterdir()) == [path]


def test_failed_status_redacts_secrets(tmp_path: Path) -> None:
    progress, _clock, _stream = _progress(tmp_path)
    progress.start(background=False)
    progress.close("failed", "RuntimeError: Authorization: Bearer abc123 refused")
    body = json.loads((tmp_path / "out.json.progress.json").read_text(encoding="utf-8"))
    assert body["status"] == "failed"
    assert "abc123" not in body["error"]
    assert redact("token=xyz") == "token=***"


def test_context_manager_marks_failure(tmp_path: Path) -> None:
    progress, _clock, _stream = _progress(tmp_path)
    try:
        with progress:
            raise ValueError("boom")
    except ValueError:
        pass
    body = json.loads((tmp_path / "out.json.progress.json").read_text(encoding="utf-8"))
    assert body["status"] == "failed"
    assert body["error"] == "ValueError: boom"


def test_cp932_stream_never_raises() -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp932", errors="strict")
    progress, _clock, _stream = _progress(stream=stream)
    progress._write("AI班长 ✓ progress\n")
    stream.flush()
    assert raw.getvalue().decode("cp932").startswith("AI")


def test_read_progress_flags_stale_runs(tmp_path: Path) -> None:
    path = tmp_path / "a.progress.json"
    assert read_progress(tmp_path / "missing.progress.json") == {"available": False}
    write_atomic(path, {"status": "running", "runs": {"done": 0, "total": 2}})
    fresh = read_progress(path)
    assert fresh["available"] is True
    assert fresh["stale"] is False
    old = read_progress(path, now=path.stat().st_mtime + 120.0)
    assert old["stale"] is True
    write_atomic(path, {"status": "done"})
    assert read_progress(path, now=path.stat().st_mtime + 120.0)["stale"] is False


def test_helpers() -> None:
    assert clock_text(None) == "?"
    assert clock_text(3725.0) == "1:02:05"
    assert bar(0.5, 10) == "[#####-----]"
    assert bar(2.0, 4) == "[####]"


def test_redact_masks_key_like_values() -> None:
    assert "nvapi-abcdefgh1234" not in redact("401 for key nvapi-abcdefgh1234")
    assert redact("Bearer abc.def") == "Bearer=***"


def test_eta_at_the_end_of_a_run_counts_the_runs_left() -> None:
    progress, clock, _stream = _progress(plan=["rules", "rules", "rules"])
    progress.begin_run("published", 1, "rules", 100.0)
    clock.t += 30.0
    progress.sim_time(100.0)
    assert progress.eta() == 60.0
    progress.end_run()
    assert progress.eta() == 60.0


def test_unknown_later_arm_shows_a_lower_bound() -> None:
    progress, clock, _stream = _progress()
    progress.begin_run("published", 1, "rules", 100.0)
    clock.t += 10.0
    progress.sim_time(50.0)
    snap = progress.snapshot()
    assert snap["eta_s"] is None
    assert snap["run_eta_s"] == 10.0
    assert progress.line(snap).endswith("0:00:10 ETA >0:00:10")


def test_follow_pumps_while_waiting_and_keeps_order() -> None:
    from multiprocessing import TimeoutError as MpTimeout

    from resilimes.smt.progress import follow

    class Results:
        def __init__(self) -> None:
            self.steps: list[Any] = [
                MpTimeout(),
                {"book": "b", "seed": 1, "arm": "rules"},
                MpTimeout(),
                {"book": "b", "seed": 1, "arm": "mock"},
            ]

        def next(self, timeout: float) -> Any:
            if not self.steps:
                raise StopIteration
            step = self.steps.pop(0)
            if isinstance(step, Exception):
                raise step
            return step

    progress, _clock, _stream = _progress(plan=["rules", "mock"])
    rows = list(follow(Results(), progress, step=0.01))
    assert [row["arm"] for row in rows] == ["rules", "mock"]
    assert progress.snapshot()["runs"]["done"] == 2
