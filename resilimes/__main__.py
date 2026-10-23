"""CLI: serve the console, run one recovery, or run the offline check."""

from __future__ import annotations

import argparse
import json
import sys

from resilimes.config import get_settings
from resilimes.logging_config import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="resilimes", description="ResiliMES recovery console")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Start the console (default)")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    recover = sub.add_parser("recover", help="Run one recovery and print JSON")
    recover.add_argument("--scenario", default="litho_down")
    recover.add_argument("--incident", default=None)
    recover.add_argument("--role", default="planner")

    sub.add_parser("check", help="Offline self-check used by make demo and CI")

    args = parser.parse_args(argv)
    command = args.command or "serve"
    settings = get_settings()
    configure_logging(settings.log_level)

    if command == "serve":
        import uvicorn

        from resilimes.api.app import create_app

        host = args.host or settings.host
        port = args.port or settings.port
        uvicorn.run(create_app(settings), host=host, port=port, log_level="info")
        return 0
    if command == "recover":
        from resilimes.agents.orchestrator import RecoverInput, run_recovery

        report = run_recovery(
            settings,
            RecoverInput(scenario=args.scenario, incident=args.incident, actor_role=args.role),
        )
        print(json.dumps(report.model_dump(), indent=2))
        return 0 if not report.blocked else 2
    if command == "check":
        return _check(settings)
    parser.print_help()
    return 1


def _check(settings: object) -> int:
    from resilimes.agents.orchestrator import RecoverInput, run_recovery
    from resilimes.config import Settings

    assert isinstance(settings, Settings)
    report = run_recovery(settings, RecoverInput(scenario="litho_down"))
    kpis = report.kpis or {}
    delta = kpis.get("delta") or {}
    print(
        f"[check] mode={report.mode.get('label')} verdict={report.verdict and report.verdict.get('verdict')} "
        f"otd_delta={delta.get('on_time_delivery_pct')} "
        f"tardiness_delta={delta.get('weighted_tardiness_min')} "
        f"contract={report.contract and report.contract.get('verified')} "
        f"chunks={report.markovian.get('chunks')}"
    )
    ok = (
        report.verdict is not None
        and report.verdict.get("verdict") == "accept"
        and report.contract is not None
        and report.contract.get("verified") is True
        and float(delta.get("weighted_tardiness_min", 0)) < 0
        and int(report.markovian.get("chunks", 0)) == 5
    )
    print("[PASS] offline recovery" if ok else "[FAIL] offline recovery")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
