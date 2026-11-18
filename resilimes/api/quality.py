"""Read-only quality API: the project's own first measurement, served live.

``GET /api/quality?variant=v2`` (default) or ``?variant=v1`` returns the
quality/v0 report computed at request time from the stored fault-injection
benchmark file (``results_pc/investigator_nightshift_v2.json`` /
``investigator_nightshift_v1.json``) via
``insight.quality_adapter.evaluate_file()``. The report a caller gets is
the report of exactly the samples the adapter produces from that file;
skips travel with it in ``summary``. No stored report, no cache: the
files are 24 rows each, so recomputing is trivial and there is nothing
stale to serve.

The Quality page's trust view consumes this endpoint (see
``docs/QUALITY_PAGE.md``); the file-load path stays as the fallback for
reports the server does not hold.

Read-only on purpose: nothing here changes a schedule, a KPI, or a
benchmark file. Contract: ``docs/API_QUALITY.md`` (``quality-api/v0``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from resilimes.explain.quality import METRICS_VERSION
from resilimes.insight.quality_adapter import ADAPTER_VERSION, evaluate_file, summarize

router = APIRouter(prefix="/api/quality", tags=["quality"])

API_VERSION = "quality-api/v0"

REPO_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = REPO_ROOT / "results_pc"

#: variant -> stored benchmark file, relative to ``BENCHMARK_DIR``.
#: Only these two files exist as the first measurement; a new benchmark
#: run is a new variant, not an edit to this map's values.
VARIANT_FILES: dict[str, str] = {
    "v1": "investigator_nightshift_v1.json",
    "v2": "investigator_nightshift_v2.json",
}


@router.get("")
def quality(variant: str = Query(default="v2", max_length=10)) -> dict[str, Any]:
    """The quality/v0 report for one stored benchmark variant. Read-only."""
    filename = VARIANT_FILES.get(variant)
    if filename is None:
        raise HTTPException(status_code=404, detail="Unknown variant.")
    path = BENCHMARK_DIR / filename
    try:
        adapted, report = evaluate_file(path, source=path.stem)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # The file is server-side data, not client input: a missing or
        # broken benchmark file is a data-source failure (503), matching
        # the repo's other data-source handlers.
        raise HTTPException(status_code=503, detail=str(exc)[:300]) from exc
    return {
        "api_version": API_VERSION,
        "variant": variant,
        "source": f"results_pc/{filename}",
        "adapter_version": ADAPTER_VERSION,
        "metrics_version": METRICS_VERSION,
        "report": report.model_dump(mode="json"),
        "summary": summarize(adapted, report),
    }
