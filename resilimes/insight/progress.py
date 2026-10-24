"""One-line progress for long AI eval runs (same look as the shift-lead study line).

On a terminal the line is rewritten in place; redirected to a file, one line is
written every ``log_every`` seconds. ASCII only, secrets masked, and it never
changes a run.
"""

from __future__ import annotations

import contextlib
import re
import sys
import time
from typing import TextIO

BAR_WIDTH = 20
_SECRET = re.compile(
    r"(?i)(bearer|token|api[_-]?key|secret|password|authorization)\S*[\s:=]+(?:bearer\s+)?\S+"
)
_KEYLIKE = re.compile(r"\b(?:nvapi|sk|ghp|gho)-?_?[A-Za-z0-9_\-]{8,}")


def redact(text: str, limit: int = 200) -> str:
    """Error text safe to print: secrets and key-like tokens masked, length capped."""
    masked = _SECRET.sub(lambda match: f"{match.group(1)}=***", text)
    return _KEYLIKE.sub("***", masked)[:limit]


def clock_text(seconds: float | None) -> str:
    if seconds is None or seconds != seconds or seconds < 0:
        return "?"
    whole = round(seconds)
    return f"{whole // 3600}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def bar(fraction: float, width: int = BAR_WIDTH) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


class Progress:
    """``label 5/24 21% [####----] | elapsed 0:01:02 | eta 0:03:50 | <extra>``."""

    def __init__(
        self,
        label: str,
        total: int,
        *,
        stream: TextIO | None = None,
        log_every: float = 10.0,
    ) -> None:
        self.label = label
        self.total = max(1, total)
        self.done = 0
        self.stream = stream or sys.stderr
        self.log_every = log_every
        self.started = time.monotonic()
        self._last = 0.0
        self._tty = bool(getattr(self.stream, "isatty", lambda: False)())

    def line(self, extra: str = "") -> str:
        elapsed = time.monotonic() - self.started
        fraction = self.done / self.total
        eta = elapsed / self.done * (self.total - self.done) if self.done else None
        parts = [
            f"{self.label} {self.done}/{self.total} {round(fraction * 100)}% {bar(fraction)}",
            f"elapsed {clock_text(elapsed)}",
            f"eta {clock_text(eta)}",
        ]
        if extra:
            parts.append(redact(extra))
        return " | ".join(parts).encode("ascii", "replace").decode("ascii")

    def update(self, done: int | None = None, extra: str = "", force: bool = False) -> None:
        if done is not None:
            self.done = done
        now = time.monotonic()
        if not force and not self._tty and now - self._last < self.log_every:
            return
        self._last = now
        text = self.line(extra)
        try:
            if self._tty:
                self.stream.write("\r" + text[:200].ljust(120))
            else:
                self.stream.write(text + "\n")
            self.stream.flush()
        except (OSError, ValueError):
            pass

    def finish(self, extra: str = "") -> None:
        self.done = self.total if self.done < self.total else self.done
        self.update(extra=extra, force=True)
        if self._tty:
            with contextlib.suppress(OSError, ValueError):
                self.stream.write("\n")
