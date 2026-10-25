"""Live evaluation on the PC: every sim-select arm, all held-out seeds, one go.

    python scripts\\run_live_eval.py                 (Windows, from the repo root)
    python scripts/run_live_eval.py --out-dir study_sim_select_live
    python scripts/run_live_eval.py --seeds 9 --horizon-h 8   (one seed, 8 h)
    python scripts\\run_live_eval.py --book stress --first 6 --out-dir study_stress_live

``--book stress`` runs the pre-registered stress book
(docs/AI_SHIFT_LEAD_STRESS.md): five incident scenarios, seeds 9-11, 8 h, in
the fixed order seed-major then S1..S5; ``--first N`` keeps the first N
(scenario, seed) pairs (the pre-declared runtime subset). ``--book stress2``
is the second, labelled pre-registration (three harsher scenarios). H-MEM has no
warm-up on the stress book (empty memory per run).

Runs sequentially, one run at a time, and prints a timestamped line per run
plus a sim-time / call-count line every 60 s. Each finished run is written to
``<out-dir>/<arm>/<book>_s<seed>.json``; rerun the same command after a crash
or Ctrl+C and finished runs are skipped. ``<out-dir>/report.md`` is rewritten
after every arm. Output is also appended to ``<out-dir>/live_eval.log``.

Order (pre-registered, nothing tuned on held-out seeds):

1. ``sim_llm``       Nemotron proposes + selects, no memory   (seeds 9-13)
2. ``sim_llm_hmem``  same plus H-MEM cases in both prompts    (warm-up on dev
                     seeds 1-3 first, then seeds 9-13)
3. ``rules``, ``sim``, ``sim_hmem``: the LLM-free baselines on the same
   machine for paired deltas (``--skip-baselines`` to leave them out).

The model is pinned to ``NEMOTRON_MODEL`` (default
nvidia/nemotron-3.5-lightning-30b-a3b; the script refuses any other family).
Every reply's served model (Meterless ``provider_model``, else the response
``model`` field) is counted per run in ``shift_lead.served_models``; a reply
served by anything else (e.g. Gemini) is not used, the rule default is applied,
it is counted as ``non_nemotron`` and flagged after each arm.

Budgets are only for runtime and safety, set high so no decision is cut
short: no cap on escalations, 1200 s per LLM call (the rule default is applied
if a call exceeds it, and counted as a fallback), ``NEMOTRON_MAX_TOKENS``
16384 (the client retries once at 2x on an empty reply), ``METERLESS_TIMEOUT_S``
900 and ``LLM_MAX_RETRIES`` 5, unless already set in the environment or .env.

Rules first: the shift lead (and so Nemotron) is asked only when the twin
projects the rule default to cause an avoidable Q-time violation or a late
hot/VIP lot (``resilimes.agents.sim_select.rule_trigger``); every other
exception is handled by the rule default and counted as ``rule_handled``.
``SHIFT_LEAD_ESCALATE=always`` restores the old kind-based filter
(experiment only).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PINNED_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
DEFAULTS = {
    "RESILIMES_MODE": "live",
    "NEMOTRON_MODEL": PINNED_MODEL,
    "NEMOTRON_MAX_TOKENS": "16384",
    "METERLESS_TIMEOUT_S": "900",
    "LLM_MAX_RETRIES": "5",
}
LIVE_ARMS = ("sim_llm", "sim_llm_hmem")
BASELINES = ("rules", "sim", "sim_hmem")


class _Tee:
    def __init__(self, path: Path) -> None:
        self.file = path.open("a", encoding="utf-8")
        self.stdout = sys.stdout

    def write(self, text: str) -> int:
        self.file.write(text)
        self.file.flush()
        return self.stdout.write(text)

    def flush(self) -> None:
        self.stdout.flush()


def _check_models(out: Path, arm: str, book: str) -> None:
    """Print the models that actually served each run; flag any non-Nemotron."""
    import json

    for path in sorted((out / arm).glob(f"{book}_s*.json")):
        lead = json.loads(path.read_text("utf-8")).get("shift_lead", {})
        served = lead.get("served_models") or {}
        if not served:
            continue
        bad = {m: n for m, n in served.items() if "nemotron" not in m.lower()}
        flag = f"  <-- NON-NEMOTRON replies (not used, rule default applied): {bad}" if bad else ""
        print(f"  {path.name}: served {served}{flag}", flush=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out-dir", default="study_sim_select_live")
    p.add_argument("--seeds", default=None, help="default 9-13 (stress: 9,10,11)")
    p.add_argument("--horizon-h", default=None, help="simulated hours per run (24; stress 8)")
    p.add_argument("--book", default="heldout_published", help="or 'stress' / 'stress2'")
    p.add_argument("--first", default="0", help="stress: first N (scenario, seed) pairs only")
    p.add_argument("--workers", default="3", help="twin fork processes")
    p.add_argument("--skip-baselines", action="store_true")
    p.add_argument("--skip-probe", action="store_true")
    args = p.parse_args()
    stress = args.book in ("stress", "stress2")
    if args.seeds is None:
        args.seeds = "9,10,11" if stress else "9,10,11,12,13"
    if args.horizon_h is None:
        args.horizon_h = "8" if stress else "24"
    for key, value in DEFAULTS.items():
        os.environ.setdefault(key, value)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sys.stdout = _Tee(out / "live_eval.log")
    print(f"=== live eval {time.strftime('%Y-%m-%d %H:%M:%S')} -> {out}", flush=True)

    from resilimes.config import load_settings
    from resilimes.llm.nightshift import probe_nightshift
    from resilimes.smt import sim_select_study as study

    settings = load_settings()
    if not settings.nemotron_model.lower().startswith("nvidia/nemotron"):
        print(
            f"NEMOTRON_MODEL={settings.nemotron_model!r} is not an nvidia/nemotron model; refusing"
        )
        return 4
    print("pinned model:", settings.nemotron_model, flush=True)
    mode = os.environ.get("SHIFT_LEAD_ESCALATE") or "exception"
    print(f"escalation: {mode} (seeds {args.seeds}, horizon {args.horizon_h} h)", flush=True)
    if not settings.use_nightshift:
        print("Nightshift is not configured: set RESILIMES_MODE=live and the token in .env")
        return 2
    if not args.skip_probe:
        live = probe_nightshift(settings, timeout_s=10.0)
        print("nightshift liveness:", live, flush=True)  # no token in it
        if not live.get("ok"):
            print("Nightshift is not answering at", live.get("base_url"), "- start it and rerun")
            return 3
    arms = list(LIVE_ARMS) + ([] if args.skip_baselines else list(BASELINES))
    common = [
        "--book", args.book, "--seeds", args.seeds, "--workers", args.workers,
        "--horizon-h", str(args.horizon_h), "--fork-h", "8", "--futures", "3",
        "--llm-timeout", "1200", "--progress-s", "60", "--out-dir", str(out),
        "--first", str(args.first),
    ]  # fmt: skip
    for number, arm in enumerate(arms, 1):
        print(f"=== arm {number}/{len(arms)}: {arm}", flush=True)
        study.main(["run", "--arms", arm, *common])
        _check_models(out, arm, "stress*" if stress else args.book)
    study.main(["report", *common])
    print(f"=== done {time.strftime('%Y-%m-%d %H:%M:%S')}; report: {out / 'report.md'}")
    return 0


if __name__ == "__main__":  # required for the Windows spawn pool
    sys.exit(main())
