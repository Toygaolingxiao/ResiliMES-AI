"""Live progress for long study runs: one console line and a JSON file.

A study with a slow live model (``qtime_study shift_lead --provider
nightshift``) can run for an hour. ``Progress`` shows whether it is moving:

* the console line (stderr): on a terminal one line rewritten in place with
  ``\\r``; redirected to a file, one plain line every ``log_every`` seconds
  (10 s), so a log fills up while the run is alive;
* ``<out>.progress.json``, rewritten atomically every ``file_every`` seconds
  (2 s) with the same counters and ``status`` running / done / failed, so a
  second process or the API (``/api/shift-lead/status``) can read it.

A background thread keeps both fresh while the simulator is blocked in a
model call (the ``wait`` field counts the seconds of the call in flight).
Everything written is ASCII, so cp932 and other legacy consoles print it.
Progress never changes a run: it only reads counters and the simulated clock,
and a failed write is ignored.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from multiprocessing import TimeoutError as MpTimeout
from pathlib import Path
from typing import Any, TextIO

SCHEMA = 1
FALLBACK_KINDS = ("timeout", "invalid", "guardrail", "budget", "error")
STALE_AFTER_S = 60.0
BAR_WIDTH = 20
_SECRET = re.compile(
    r"(?i)(bearer|token|api[_-]?key|secret|password|authorization)\S*[\s:=]+(?:bearer\s+)?\S+"
)
_KEYLIKE = re.compile(r"\b(?:nvapi|sk|ghp|gho)-?_?[A-Za-z0-9_\-]{8,}")


def fallback_kind(cause: str | None) -> str | None:
    """Group a ``ShiftLead`` fallback cause: timeout, invalid, guardrail, budget, error."""
    if not cause:
        return None
    head = str(cause).split(":")[0].strip()
    if head == "timeout":
        return "timeout"
    if head in ("bad_json", "unknown_option"):
        return "invalid"
    if head == "invariant":
        return "guardrail"
    if head == "budget":
        return "budget"
    return "error"


def redact(text: str, limit: int = 200) -> str:
    """Error text for the progress file: secrets masked, length capped."""
    masked = _SECRET.sub(lambda match: f"{match.group(1)}=***", text)
    return _KEYLIKE.sub("***", masked)[:limit]


def clock_text(seconds: float | None) -> str:
    """``H:MM:SS``; ``?`` when unknown."""
    if seconds is None or seconds != seconds or seconds < 0:
        return "?"
    whole = round(seconds)
    return f"{whole // 3600}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def bar(fraction: float, width: int = BAR_WIDTH) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _now_iso(wall: float) -> str:
    return datetime.fromtimestamp(wall).astimezone().isoformat(timespec="seconds")


def _counters() -> dict[str, Any]:
    return {
        "exceptions": 0,
        "calls": 0,
        "accepted": 0,
        "overrides": 0,
        "fallbacks": dict.fromkeys(FALLBACK_KINDS, 0),
        "latency_sum_ms": 0.0,
        "latency_n": 0,
        "latency_last_ms": None,
    }


def _add(into: dict[str, Any], other: dict[str, Any]) -> None:
    for key in ("exceptions", "calls", "accepted", "overrides", "latency_sum_ms", "latency_n"):
        into[key] += other[key]
    for kind in FALLBACK_KINDS:
        into["fallbacks"][kind] += other["fallbacks"][kind]
    if other["latency_last_ms"] is not None:
        into["latency_last_ms"] = other["latency_last_ms"]


def _public(counts: dict[str, Any]) -> dict[str, Any]:
    n = counts["latency_n"]
    return {
        "exceptions": counts["exceptions"],
        "calls": counts["calls"],
        "accepted": counts["accepted"],
        "overrides": counts["overrides"],
        "fallback": sum(counts["fallbacks"].values()),
        "fallbacks": dict(counts["fallbacks"]),
        "latency_ms": {
            "avg": round(counts["latency_sum_ms"] / n, 1) if n else None,
            "last": counts["latency_last_ms"],
        },
    }


class _Null:
    """Stand-in when progress is off: every hook is a no-op."""

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: None


NULL_PROGRESS: Any = _Null()


class Progress:
    """Counters, ETA, the console line and the progress file for one study.

    ``plan`` is the arm of every run in order (``["rules", "nightshift"]``);
    the ETA of runs not started yet uses the mean wall time of finished runs
    of the same arm. ``clock`` and ``wall`` are injectable for tests.
    """

    def __init__(
        self,
        *,
        study: str,
        plan: Sequence[str],
        provider: str = "",
        budget: int | None = None,
        path: str | os.PathLike[str] | None = None,
        stream: TextIO | None = None,
        console: bool = True,
        tty: bool | None = None,
        tty_every: float = 0.5,
        log_every: float = 10.0,
        file_every: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        background: bool = True,
    ) -> None:
        self.study = study
        self.plan = list(plan)
        self.provider = provider
        self.budget = budget
        self.path = Path(path) if path is not None else None
        self.stream = stream if stream is not None else sys.stderr
        self.console = console
        if tty is None:
            try:
                tty = bool(self.stream.isatty())
            except (AttributeError, ValueError):
                tty = False
        self.tty = tty
        self.every = tty_every if tty else log_every
        self.file_every = file_every
        self.clock = clock
        self.wall = wall
        self.background = background
        self.lock = threading.RLock()
        self.status = "running"
        self.error: str | None = None
        self.started = clock()
        self.started_wall = wall()
        self.done = 0
        self.walls: dict[str, list[float]] = {}
        self.totals = _counters()
        self.current: dict[str, Any] | None = None
        self.run = _counters()
        self.run_started = self.started
        self.sim_t = 0.0
        self.horizon = 0.0
        self.call_since: float | None = None
        self._last_absorb = self.started
        self._last_line = 0.0
        self._last_file = 0.0
        self._width = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # Lifecycle ---------------------------------------------------------------
    def __enter__(self) -> Progress:
        return self.start(self.background)

    def __exit__(self, kind: Any, value: Any, trace: Any) -> None:
        if value is None:
            self.close("done")
        else:
            self.close("failed", f"{type(value).__name__}: {value}")

    def start(self, background: bool = True) -> Progress:
        self.pump(force=True)
        if background:
            self._thread = threading.Thread(target=self._loop, name="progress", daemon=True)
            self._thread.start()
        return self

    def _loop(self) -> None:
        step = min(self.every, self.file_every, 1.0)
        while not self._stop.wait(step):
            self.pump()

    def close(self, status: str = "done", error: str | None = None) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        with self.lock:
            self.status = status
            self.error = redact(error) if error else None
            self.call_since = None
        self.pump(force=True)
        if self.console and self.tty:
            self._write("\n")

    # Hooks -------------------------------------------------------------------
    def begin_run(self, book: str, seed: int, arm: str, horizon_s: float) -> None:
        with self.lock:
            self.current = {"book": book, "seed": seed, "arm": arm, "index": self.done + 1}
            self.run = _counters()
            self.run_started = self.clock()
            self.sim_t = 0.0
            self.horizon = float(horizon_s)
            self.call_since = None
        self.pump(force=True)

    def sim_time(self, t: float) -> None:
        """Simulated clock in seconds (the simulator calls this every few thousand events)."""
        with self.lock:
            self.sim_t = max(self.sim_t, float(t))
        self.pump()

    def call_started(self) -> None:
        with self.lock:
            self.call_since = self.clock()
            self.run["calls"] += 1
        self.pump()

    def call_finished(self) -> None:
        with self.lock:
            if self.call_since is not None:
                latency = (self.clock() - self.call_since) * 1000.0
                self.run["latency_sum_ms"] += latency
                self.run["latency_n"] += 1
                self.run["latency_last_ms"] = round(latency, 1)
            self.call_since = None

    def decision(self, entry: dict[str, Any]) -> None:
        """One ``ShiftLead.log`` entry."""
        with self.lock:
            self.run["exceptions"] += 1
            kind = fallback_kind(entry.get("fallback_cause")) if entry.get("fallback") else None
            if kind is None:
                self.run["accepted"] += 1
            else:
                self.run["fallbacks"][kind] += 1
            if entry.get("differs"):
                self.run["overrides"] += 1
            if "t" in entry:
                self.sim_t = max(self.sim_t, float(entry["t"]))
        self.pump()

    def end_run(self, arm: str | None = None, wall_s: float | None = None) -> None:
        with self.lock:
            name = arm or (self.current or {}).get("arm", "")
            spent = wall_s if wall_s is not None else self.clock() - self.run_started
            self.walls.setdefault(name, []).append(spent)
            self.done += 1
            _add(self.totals, self.run)
            self.sim_t = self.horizon
            self.call_since = None
        self.pump(force=True)
        with self.lock:
            self.current = None

    def absorb(self, row: dict[str, Any]) -> None:
        """A finished run from a worker pool (no live hooks there).

        Its time for the ETA is the gap since the previous finished run, so
        the ETA reflects the pool's throughput, not one run's wall time.
        """
        summary = row.get("shift_lead") or {}
        counts = _counters()
        counts["exceptions"] = int(summary.get("exceptions", 0))
        counts["overrides"] = int(summary.get("differs", 0))
        for cause, count in (summary.get("fallback_causes") or {}).items():
            counts["fallbacks"][fallback_kind(cause) or "error"] += int(count)
        counts["accepted"] = counts["exceptions"] - sum(counts["fallbacks"].values())
        counts["calls"] = counts["exceptions"] - counts["fallbacks"]["budget"]
        with self.lock:
            self.current = {
                "book": row.get("book"),
                "seed": row.get("seed"),
                "arm": row.get("arm") or row.get("policy"),
                "index": self.done + 1,
            }
            self.run = counts
            self.horizon = 0.0
            now = self.clock()
            gap = now - self._last_absorb
            self._last_absorb = now
        self.end_run(str(self.current["arm"]), gap)

    # Numbers -----------------------------------------------------------------
    def fraction(self) -> float | None:
        if self.horizon <= 0:
            return None
        return max(0.0, min(1.0, self.sim_t / self.horizon))

    def run_eta(self) -> float | None:
        """Seconds left in the current run (simulated-time rate, else the arm's mean)."""
        with self.lock:
            if self.current is None:
                return None
            spent = self.clock() - self.run_started
            fraction = self.fraction()
            if fraction is not None and fraction >= 0.005:
                return spent / fraction - spent
            known = self.walls.get(str(self.current["arm"]))
            if not known:
                return None
            return max(0.0, sum(known) / len(known) - spent)

    def eta(self) -> float | None:
        """Seconds left: the current run by its simulated-time rate, later runs by arm means."""
        with self.lock:
            now = self.clock()
            left = 0.0
            projected: float | None = None
            if self.current is not None:
                fraction = self.fraction()
                spent = now - self.run_started
                if fraction is None or fraction < 0.005:
                    known = self.walls.get(str(self.current["arm"]))
                    if not known:
                        return None
                    projected = sum(known) / len(known)
                    left += max(0.0, projected - spent)
                else:
                    projected = spent / fraction
                    left += projected - spent
                first = int(self.current["index"])
            else:
                first = self.done
            for arm in self.plan[first:]:
                known = self.walls.get(arm)
                if known:
                    left += sum(known) / len(known)
                elif self.current is not None and arm == self.current["arm"]:
                    assert projected is not None
                    left += projected
                elif self.walls:
                    every = [value for values in self.walls.values() for value in values]
                    left += sum(every) / len(every)
                else:
                    return None
            return left

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            now = self.clock()
            fraction = self.fraction()
            run = _public(self.run)
            total = _counters()
            _add(total, self.totals)
            if self.current is not None:
                _add(total, self.run)
            wait = None if self.call_since is None else round(now - self.call_since, 1)
            return {
                "schema": SCHEMA,
                "study": self.study,
                "provider": self.provider,
                "status": self.status,
                "error": self.error,
                "pid": os.getpid(),
                "started_at": _now_iso(self.started_wall),
                "updated_at": _now_iso(self.wall()),
                "runs": {"done": self.done, "total": len(self.plan)},
                "current": dict(self.current) if self.current is not None else None,
                "sim": {
                    "t_h": round(self.sim_t / 3600.0, 2),
                    "horizon_h": round(self.horizon / 3600.0, 2),
                    "pct": None if fraction is None else round(100.0 * fraction, 1),
                },
                "ai": {**run, "budget": self.budget, "wait_s": wait},
                "totals": _public(total),
                "elapsed_s": round(now - self.started, 1),
                "eta_s": None if self.status != "running" else _round(self.eta()),
                "run_eta_s": None if self.status != "running" else _round(self.run_eta()),
            }

    def line(self, snap: dict[str, Any] | None = None) -> str:
        snap = snap or self.snapshot()
        runs = snap["runs"]
        current = snap["current"]
        index = current["index"] if current is not None else min(runs["done"] + 1, runs["total"])
        parts = [f"{snap['study']} {index}/{runs['total']}"]
        if snap["status"] != "running":
            parts[0] = f"{snap['study']} {runs['done']}/{runs['total']} {snap['status'].upper()}"
        elif current is not None:
            parts[0] += f" {current['book']} s{current['seed']} {current['arm']}"
        sim = snap["sim"]
        if sim["pct"] is not None and current is not None:
            parts.append(
                f"sim {sim['t_h']:.1f}/{sim['horizon_h']:.0f}h {sim['pct']:3.0f}% "
                + bar(sim["pct"] / 100.0)
            )
        elif runs["total"] > 1:
            share = runs["done"] / runs["total"]
            parts.append(f"runs {runs['done']}/{runs['total']} {100 * share:3.0f}% " + bar(share))
        ai = snap["ai"]
        live = current is not None and sim["pct"] is not None
        if live and current["arm"] != "rules":
            budget = "-" if ai["budget"] is None else ai["budget"]
            text = f"exc {ai['exceptions']} | AI {ai['calls']}/{budget} ok {ai['accepted']}"
            text += f" fb {ai['fallback']}"
            causes = [f"{kind} {count}" for kind, count in ai["fallbacks"].items() if count]
            if causes:
                text += " (" + ", ".join(causes) + ")"
            parts.append(text)
            latency = ai["latency_ms"]
            if latency["avg"] is not None or ai["wait_s"] is not None:
                text = "LLM"
                if latency["avg"] is not None:
                    text += f" avg {_ms(latency['avg'])} last {_ms(latency['last'])}"
                if ai["wait_s"] is not None:
                    text += f" wait {ai['wait_s']:.0f}s"
                parts.append(text)
        elif snap["totals"]["exceptions"]:
            totals = snap["totals"]
            parts.append(
                f"exc {totals['exceptions']} ok {totals['accepted']} fb {totals['fallback']}"
            )
        timing = clock_text(snap["elapsed_s"])
        if snap["status"] == "running":
            if snap["eta_s"] is not None:
                timing += f" ETA {clock_text(snap['eta_s'])}"
            elif snap.get("run_eta_s") is not None:
                # Later runs of an arm not seen yet: the current run's ETA, a lower bound.
                timing += f" ETA >{clock_text(snap['run_eta_s'])}"
            else:
                timing += " ETA ?"
        parts.append(timing)
        if snap["error"]:
            parts.append(snap["error"])
        return " | ".join(parts)

    # Output ------------------------------------------------------------------
    def pump(self, force: bool = False) -> None:
        """Write the line and the file when their interval has passed (or ``force``)."""
        now = self.clock()
        line_due = force or now - self._last_line >= self.every
        file_due = force or now - self._last_file >= self.file_every
        if not (line_due or file_due):
            return
        try:
            snap = self.snapshot()
        except Exception:  # progress must never stop a study
            return
        if line_due and self.console:
            self._last_line = now
            self._emit(self.line(snap))
        if file_due and self.path is not None:
            self._last_file = now
            write_atomic(self.path, snap)

    def _emit(self, text: str) -> None:
        if self.tty:
            width = max(20, shutil.get_terminal_size((120, 20)).columns - 1)
            text = text[:width]
            pad = max(0, self._width - len(text))
            self._width = len(text)
            self._write("\r" + text + " " * pad)
        else:
            self._write(text + "\n")

    def _write(self, text: str) -> None:
        try:
            try:
                self.stream.write(text)
            except UnicodeEncodeError:
                encoding = getattr(self.stream, "encoding", None) or "ascii"
                self.stream.write(text.encode(encoding, "replace").decode(encoding))
            self.stream.flush()
        except (OSError, ValueError):
            pass


def follow(results: Any, progress: Progress, step: float = 1.0) -> Iterator[Any]:
    """Rows of ``pool.imap(...)`` in order, absorbed into ``progress``.

    Waits with a timeout and pumps the line and the file in between, so a
    pool study needs no progress thread (no thread alive when the pool forks
    a worker).
    """
    while True:
        try:
            row = results.next(timeout=step)
        except StopIteration:
            return
        except MpTimeout:
            progress.pump()
            continue
        progress.absorb(row)
        yield row


def _ms(value: float) -> str:
    return f"{value:.0f}ms" if value < 1000 else f"{value / 1000:.1f}s"


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def write_atomic(path: Path, payload: dict[str, Any]) -> bool:
    """Write JSON to ``path`` through a temp file and ``os.replace``; False on failure."""
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temp, path)
                return True
            except PermissionError:  # Windows: a reader holds the file open
                time.sleep(0.05 * (attempt + 1))
    except OSError:
        pass
    with contextlib.suppress(OSError):
        temp.unlink()
    return False


def progress_path(out: str) -> str:
    return f"{out}.progress.json"


def find_progress(where: str | os.PathLike[str] | None = None) -> Path | None:
    """``RESILIMES_PROGRESS_FILE``, else the newest ``*.progress.json`` in ``where``
    (``RESILIMES_PROGRESS_DIR``, default the working directory)."""
    explicit = os.environ.get("RESILIMES_PROGRESS_FILE")
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    folder = Path(where or os.environ.get("RESILIMES_PROGRESS_DIR") or ".")
    try:
        found = [path for path in folder.glob("*.progress.json") if path.is_file()]
    except OSError:
        return None
    if not found:
        return None
    return max(found, key=lambda path: path.stat().st_mtime)


def read_progress(path: Path | None = None, *, now: float | None = None) -> dict[str, Any]:
    """The progress file plus ``age_s`` and ``stale`` (running, no update for 60 s)."""
    path = path if path is not None else find_progress()
    if path is None:
        return {"available": False}
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except (OSError, ValueError):
        return {"available": False}
    if not isinstance(body, dict):
        return {"available": False}
    body["available"] = True
    body["file"] = path.name
    body["age_s"] = round(max(0.0, age), 1)
    body["stale"] = body.get("status") == "running" and age > STALE_AFTER_S
    return body
