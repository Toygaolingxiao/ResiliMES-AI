"""Live evaluation on the PC: every sim-select arm, all held-out seeds, one go.

    python scripts\\run_live_eval.py                 (Windows, from the repo root)
    python scripts/run_live_eval.py --out-dir study_sim_select_live

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

Budgets are only for runtime and safety, set high so no decision is cut
short: no cap on escalations, 1200 s per LLM call (the rule default is applied
if a call exceeds it, and counted as a fallback), ``NEMOTRON_MAX_TOKENS``
16384 (the client retries once at 2x on an empty reply), ``METERLESS_TIMEOUT_S``
900 and ``LLM_MAX_RETRIES`` 5, unless already set in the environment or .env.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULTS = {
    "RESILIMES_MODE": "live",
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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out-dir", default="study_sim_select_live")
    p.add_argument("--seeds", default="9,10,11,12,13")
    p.add_argument("--book", default="heldout_published")
    p.add_argument("--workers", default="3", help="twin fork processes")
    p.add_argument("--skip-baselines", action="store_true")
    p.add_argument("--skip-probe", action="store_true")
    args = p.parse_args()
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
        "--horizon-h", "24", "--fork-h", "8", "--futures", "3",
        "--llm-timeout", "1200", "--progress-s", "60", "--out-dir", str(out),
    ]  # fmt: skip
    for number, arm in enumerate(arms, 1):
        print(f"=== arm {number}/{len(arms)}: {arm}", flush=True)
        study.main(["run", "--arms", arm, *common])
    study.main(["report", *common])
    print(f"=== done {time.strftime('%Y-%m-%d %H:%M:%S')}; report: {out / 'report.md'}")
    return 0


if __name__ == "__main__":  # required for the Windows spawn pool
    sys.exit(main())
