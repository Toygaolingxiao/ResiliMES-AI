"""ResiliTrace quality adapter v0: fault-injection benchmark -> samples.

The quality metrics (``explain.quality``, quality/v0) eat ``AttributionSample``
sequences. This module is the first feeder: it turns the saved output files
of ``insight.study.run_investigator`` -- the fault-injection benchmark, where
the injected fault is the answer key -- into sample dicts in the quality/v0
JSON shape (``sample_id``, ``tier``, ``predicted_cause``, ``true_cause``,
``confidence``).

The adapter computes no rates. Rates are ``quality.evaluate``'s job, and
this module wires it in: :func:`evaluate_adapted` validates each sample
dict as a real ``AttributionSample`` and runs ``evaluate()`` over it
(#88 merged, so the import is real now). The mirror validator
:func:`_validate_sample` stays as a drift guard -- it re-states the
quality/v0 field rules, and the cross-check test pins the two validators
to agree. Merge order: #88 -> this PR. The first real measurement, run
locally against the #88 content, is recorded in
``docs/QUALITY_ADAPTER.md``; the wiring test re-runs it through the real
``evaluate()`` pipeline, so the measurement is reproducible in CI.

Mapping rules (adapter/v0). Changing any of them is a new adapter version,
not an edit:

* truth = the row's ``truth`` (the injected fault). A row without a usable
  truth cannot be scored, so it is skipped and counted under
  ``missing_truth``; it never becomes a sample with ``true_cause=None``.
* predicted = what the operator sees, keyed on ``ai.system.source`` -- the
  field ``explain.investigator._system_answer`` writes:
  ``"ai"`` means the AI's own answer (system.primary == ai.primary);
  ``"rule"`` means the degraded-route rule baseline answer
  (``baseline_rank`` top1), used when the AI answer was unusable;
  ``"none"`` means the system refused (baseline ranking itself failed),
  so predicted is None and the AI answer is NOT resurrected.
  A ``system`` dict without a ``source`` key is tolerated the old way (a
  usable primary is the answer); a malformed ``system`` (not a dict, or a
  primary of the wrong type) is a ``malformed_predicted`` skip -- never a
  silent fallback to the AI answer. Note the in-repo disagreement this rule
  picks a side on: ``study.system_score``, ``api/insight.py`` and
  ``explain/context_investigation.py`` all read the system answer, while
  the evidence page headline still shows the AI's own ``primary_cause``
  with the rule answer only as a warning line. The adapter follows the
  system-score reading; see ``docs/QUALITY_ADAPTER.md``.
* timeout (row ``timeout``, ``ai.timed_out`` or ``ai.timeout``) or error
  (row ``error`` or ``ai.error`` -- any non-None value, including an empty
  string -- or ``stop_reason == "error"`` on the row or on ``ai``) means the
  usable attribution, so predicted is None -- even when a half-finished
  ``primary_cause`` is present (a timeout is a miss, whatever a
  half-finished answer said; same rule as ``study.ai_score``).
* tier = ``"attributed"`` when a cause is named, ``"unknown"`` when nothing
  is named. This is the adapter's own label, and it carries less than the
  Evidence Schema word suggests: schema ``attributed`` means "split from
  what was observed, by a fixed rule" with at least one source, while the
  investigator's ``primary_cause`` is free LLM reasoning (temperature 0.2,
  not a fixed rule) and the adapter drops the row's ``citations`` and
  ``causal_chain``, so samples carry no sources. Here ``"attributed"``
  means only "the system named a cause". Rule-baseline answers (degraded
  route) share the same tier; which samples they are is recoverable from
  ``AdaptedSet.system_answer_sample_ids`` -- the sample dicts themselves
  cannot carry the distinction, because the quality/v0 contract has
  exactly five fields. ``"recorded"`` is never used (an investigator
  answer is an inference, never a recorded fact).
* confidence is always None. Investigator answers carry no confidence, and
  inventing one after the fact would fake calibration. Consequence, stated
  in the docs: calibration over this benchmark is empty by construction
  (``calibration_samples=0``, ECE None) until the investigator emits a
  confidence.
* ``sample_id`` is ``"<source>:<case_id>"``. The caller must name the
  source (``adapt_investigator_file`` uses the file stem); there is no
  default, so two files cannot silently collide. Duplicate ids are a broken
  input file, so they fail the whole run with ``ValueError`` instead of
  being silently deduplicated. An id is only registered once its row
  actually becomes a sample -- a skipped row never blocks a later valid
  row with the same id.
* A predicted cause outside the ``explain.causes`` taxonomy is kept, not
  dropped (quality/v0 does not validate taxonomy membership either), and
  counted in ``out_of_taxonomy_predicted``. The truth-side count
  (``out_of_taxonomy_truth``) is only incremented for rows that become
  samples.
* Rows that cannot be turned into a sample for a structural reason are
  skipped and counted by reason (``missing_case_id``, ``missing_truth``,
  ``malformed_row``, ``malformed_ai``, ``malformed_predicted``). Skips are
  metadata, not silence: the counts travel with the result.

Row shapes: the saved files predate the ``system`` / ``stop_reason`` /
``degraded`` fields (shape ``"legacy"``), current ``run_investigator``
output carries them (shape ``"current"``). Both are accepted. The shape is
a file-level informational label only -- it changes no mapping rule, and a
mixed file is labelled ``"current"`` if any row carries the new keys.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

from resilimes.explain.causes import TAXONOMY
from resilimes.explain.quality import AttributionSample, QualityReport, evaluate
from resilimes.explain.schema import Tier

ADAPTER_VERSION: str = "adapter/v0"

TIER_VALUES: tuple[str, ...] = get_args(Tier)

#: Reasons a row can be skipped, with the count carried in the result.
SKIP_REASONS: tuple[str, ...] = (
    "missing_case_id",
    "missing_truth",
    "malformed_row",
    "malformed_ai",
    "malformed_predicted",
)


@dataclass(frozen=True)
class AdaptedSet:
    """The samples adapted from one benchmark file, with provenance."""

    samples: tuple[dict[str, Any], ...]
    skipped: dict[str, int] = field(default_factory=dict)
    source: str = "investigator"
    shape: str = "legacy"
    system_answers_used: int = 0
    system_answer_sample_ids: tuple[str, ...] = ()
    out_of_taxonomy_predicted: int = 0
    out_of_taxonomy_truth: int = 0

    @property
    def adapter_version(self) -> str:
        return ADAPTER_VERSION


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def _validate_sample(sample: dict[str, Any]) -> None:
    """Check one emitted dict against the quality/v0 field rules.

    Mirrors ``explain.quality.AttributionSample`` without importing it, so
    this module stays usable on main before #88 merges. Any dict that
    passes here must also pass ``AttributionSample`` validation.
    """
    tier = sample.get("tier")
    if tier not in TIER_VALUES:
        raise ValueError(f"{sample.get('sample_id')}: unknown tier {tier!r}")
    predicted = sample.get("predicted_cause")
    if tier == "unknown" and predicted is not None:
        raise ValueError(f"{sample.get('sample_id')}: unknown answer cannot carry a cause")
    if tier != "unknown" and predicted is None:
        raise ValueError(f"{sample.get('sample_id')}: a {tier} answer needs a cause")
    if not _is_nonempty_str(sample.get("sample_id")):
        raise ValueError("sample_id must be a non-empty string")
    confidence = sample.get("confidence")
    if confidence is not None and not (
        isinstance(confidence, (int, float)) and 0.0 <= confidence <= 1.0
    ):
        raise ValueError(f"{sample.get('sample_id')}: confidence out of range: {confidence!r}")
    if set(sample) != {"sample_id", "tier", "predicted_cause", "true_cause", "confidence"}:
        raise ValueError(f"{sample.get('sample_id')}: unexpected sample fields: {sorted(sample)}")


def _ai_primary(ai: dict[str, Any]) -> tuple[str | None, bool]:
    """The AI's own primary cause: (predicted, used_system=False)."""
    primary = ai.get("primary_cause")
    if primary is None:
        return None, False
    if not isinstance(primary, str):
        raise ValueError(f"malformed_predicted: primary_cause is {type(primary).__name__}")
    return (primary if primary != "" else None), False


def _predicted_from_ai(ai: dict[str, Any], row: dict[str, Any]) -> tuple[str | None, bool]:
    """The operator-visible predicted cause for one row, or None.

    Returns ``(predicted, used_system)``: ``used_system`` is True when the
    answer came from the degraded-route rule answer in ``ai.system``.
    A timeout or an error means the system produced no usable attribution,
    even if a half-finished ``primary_cause`` is present.
    """
    if row.get("timeout") or ai.get("timed_out") or ai.get("timeout"):
        return None, False
    if row.get("error") is not None or ai.get("error") is not None:
        return None, False
    if row.get("stop_reason") == "error" or ai.get("stop_reason") == "error":
        return None, False
    system = ai.get("system")
    if system is None:
        return _ai_primary(ai)
    if not isinstance(system, dict):
        raise ValueError("malformed_predicted: system is not an object")
    source = system.get("source")
    if source == "none":
        # The system refused (baseline ranking failed): do not resurrect
        # the AI answer.
        return None, False
    if source in ("ai", "rule"):
        primary = system.get("primary_cause")
        if primary is None and source == "ai":
            return None, False
        if not _is_nonempty_str(primary):
            raise ValueError("malformed_predicted: system.primary_cause is not a usable cause")
        return primary, source == "rule"
    if source is None:
        # No source marker (tolerated legacy shape): a usable primary is
        # the answer; a missing one falls through to the AI answer.
        primary = system.get("primary_cause")
        if _is_nonempty_str(primary):
            return primary, False
        if primary is None:
            return _ai_primary(ai)
        raise ValueError("malformed_predicted: system.primary_cause is not a usable cause")
    raise ValueError(f"malformed_predicted: unknown system.source {source!r}")


def _row_shape(rows: list[Any]) -> str:
    for row in rows:
        if not isinstance(row, dict):
            continue
        if "system_score" in row:
            return "current"
        ai = row.get("ai")
        if isinstance(ai, dict) and ("system" in ai or "stop_reason" in ai or "degraded" in ai):
            return "current"
    return "legacy"


def adapt_investigator_rows(rows: list[dict[str, Any]], *, source: str) -> AdaptedSet:
    """Turn ``run_investigator`` output rows into quality/v0 sample dicts.

    ``source`` is required: it names the file the rows came from, so sample
    ids stay unique per file. Raises ``ValueError`` on duplicate ``case_id``
    values (among rows that become samples) or on a non-list ``rows``;
    malformed single rows are skipped and counted.
    """
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    shape = _row_shape(rows)
    samples: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    seen: set[str] = set()
    system_answer_sample_ids: list[str] = []
    system_answers_used = 0
    out_of_taxonomy_predicted = 0
    out_of_taxonomy_truth = 0

    def _skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for row in rows:
        if not isinstance(row, dict):
            _skip("malformed_row")
            continue
        case_id = row.get("case_id")
        if not _is_nonempty_str(case_id):
            _skip("missing_case_id")
            continue
        sample_id = f"{source}:{case_id}"
        if sample_id in seen:
            raise ValueError(f"duplicate case_id in source {source!r}: {case_id!r}")
        truth = row.get("truth")
        if not _is_nonempty_str(truth):
            _skip("missing_truth")
            continue
        ai = row.get("ai")
        if ai is None:
            predicted: str | None = None
            used_system = False
        elif not isinstance(ai, dict):
            _skip("malformed_ai")
            continue
        else:
            try:
                predicted, used_system = _predicted_from_ai(ai, row)
            except ValueError:
                _skip("malformed_predicted")
                continue
        sample = {
            "sample_id": sample_id,
            "tier": "attributed" if predicted is not None else "unknown",
            "predicted_cause": predicted,
            "true_cause": truth,
            "confidence": None,
        }
        _validate_sample(sample)
        seen.add(sample_id)
        if predicted is not None and predicted not in TAXONOMY:
            out_of_taxonomy_predicted += 1
        if truth not in TAXONOMY:
            out_of_taxonomy_truth += 1
        if used_system:
            system_answers_used += 1
            system_answer_sample_ids.append(sample_id)
        samples.append(sample)

    return AdaptedSet(
        samples=tuple(samples),
        skipped=skipped,
        source=source,
        shape=shape,
        system_answers_used=system_answers_used,
        system_answer_sample_ids=tuple(system_answer_sample_ids),
        out_of_taxonomy_predicted=out_of_taxonomy_predicted,
        out_of_taxonomy_truth=out_of_taxonomy_truth,
    )


def adapt_investigator_file(path: str | Path, *, source: str | None = None) -> AdaptedSet:
    """Adapt one saved ``run_investigator`` JSON file.

    ``source`` defaults to the file stem, so sample ids stay stable per
    file (``investigator_nightshift_v2:tool_down-s1``).
    """
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise ValueError(f"{path}: expected a JSON object with a 'rows' list")
    return adapt_investigator_rows(payload["rows"], source=source or path.stem)


def evaluate_adapted(adapted: AdaptedSet) -> QualityReport:
    """Run the quality/v0 evaluation over an adapted set.

    Every sample dict is validated as a real ``AttributionSample`` first,
    so a dict that passed only the mirror validator cannot reach
    ``evaluate()``. Pure function of its input: no I/O, the adapted set
    is not mutated. An empty set evaluates to a report whose rates are
    all ``None`` (denominator 0: not enough data, never 0.0).
    """
    samples = [AttributionSample(**sample) for sample in adapted.samples]
    return evaluate(samples)


def evaluate_file(
    path: str | Path, *, source: str | None = None
) -> tuple[AdaptedSet, QualityReport]:
    """Adapt one saved investigator file and evaluate it in one step.

    Adapt -> evaluate -> report, with nothing in between: the report a
    caller gets is the report of exactly the samples the adapter
    produced from this file, skips included in the summary.
    """
    adapted = adapt_investigator_file(path, source=source)
    return adapted, evaluate_adapted(adapted)


def _report_summary(report: QualityReport) -> dict[str, Any]:
    """The report's headline numbers, denominators attached, for stdout."""
    return {
        "total_samples": report.total_samples,
        "truth_known": report.truth_known,
        "misattribution": report.misattribution.model_dump(mode="json"),
        "over_unknown": report.over_unknown.model_dump(mode="json"),
        "unknown_share": report.unknown_share.model_dump(mode="json"),
        "calibration_samples": report.calibration_samples,
        "expected_calibration_error": report.expected_calibration_error,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: adapt a saved investigator file, print the summary as JSON.

    ``python -m resilimes.insight.quality_adapter <file> [--out samples.json] [--report report.json]``

    Run from the repository root with the project venv. ``--out`` writes a
    self-describing object: the sample list plus the summary metadata, so a
    downstream holder of only that file can still recover the skips and
    provenance. ``--report`` writes a self-describing object: the full
    quality/v0 report plus the same summary, so a holder of only that file
    can still recover what was measured and what was skipped. The stdout
    summary always carries the report's headline rates (with denominators),
    whether or not ``--report`` is given.
    """
    parser = argparse.ArgumentParser(prog="quality_adapter", description=__doc__)
    parser.add_argument("file", help="saved run_investigator JSON file")
    parser.add_argument("--out", help="write samples plus summary metadata as JSON here")
    parser.add_argument("--report", help="write the quality/v0 report plus summary as JSON here")
    args = parser.parse_args(argv)

    try:
        adapted = adapt_investigator_file(args.file)
        report = evaluate_adapted(adapted)
        summary = {
            "adapter_version": ADAPTER_VERSION,
            "source": adapted.source,
            "shape": adapted.shape,
            "samples": len(adapted.samples),
            "skipped": adapted.skipped,
            "system_answers_used": adapted.system_answers_used,
            "system_answer_sample_ids": list(adapted.system_answer_sample_ids),
            "out_of_taxonomy_predicted": adapted.out_of_taxonomy_predicted,
            "out_of_taxonomy_truth": adapted.out_of_taxonomy_truth,
            "report": _report_summary(report),
        }
        if args.out:
            Path(args.out).write_text(
                json.dumps(
                    {"samples": list(adapted.samples), "summary": summary},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        if args.report:
            Path(args.report).write_text(
                json.dumps(
                    {
                        "report": report.model_dump(mode="json"),
                        "summary": summary,
                        "adapter_version": ADAPTER_VERSION,
                        "metrics_version": report.metrics_version,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"quality_adapter: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
