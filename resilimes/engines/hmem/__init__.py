"""H-MEM: a local Python port of the public H-MEM memory spec (meterless).

Not meterlessd: no meterlessd API was found, so this is an in-process port of
the published spec (AGENTS.md, Apache 2.0) checked against its conformance
vectors (``vectors.json``, vendored unchanged). ``shift_memory`` adapts it to
the shift lead's escalated decisions.
"""

from resilimes.engines.hmem.engine import HMEM, Memory
from resilimes.engines.hmem.shift_memory import ShiftMemory

__all__ = ["HMEM", "Memory", "ShiftMemory"]
