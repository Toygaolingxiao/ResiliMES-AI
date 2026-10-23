# ResiliMES

Autonomous multi-agent rescheduling and fault recovery for smart manufacturing. Built for the [Open Agent Hackathon 2026](https://hackathon.genai.works/event/open-agent-hackathon-2026).

A production supervisor gets a line-down, a rush order, a material shortage, a lithography rework, or a queue-time miss. ResiliMES reads the plant, classifies the disruption, builds a constraint-safe schedule, and shows the before/after Gantt with the KPI delta and the reason each move was allowed or refused.

**Primary track: Track 03 — Reasoning Architecture.** The product turns fragmented factory data, a signed intent contract, a world-model event log, and bounded agent steps into a schedule a supervisor can commit. Explainability is part of that decision, not a separate product. See [why this track](#track).

## Default console: public industry benchmark (SMT2020)

`make demo` opens the public industry benchmark (SMT2020), not the six-lot bay. The extract is 106 station families, 1,313 tools, 102 `Litho_*` tools (82 expose scanners and 20 `Litho_REG`), 10 products, and 2,156 initial WIP lots. The banner reads `public industry benchmark (SMT2020)`. The lithography scenario holds `Litho_FE_92-1` for the published 705.59-minute lithography repair. Tool state is aggregated by station group; the Gantt is virtualized to the selected group and time window.

The honest comparison is the **X-factor book**: published routes and priorities, each due equal to remaining process time times 2.75, horizon 48 hours, 87 lots due, five seeds, `Litho_FE_92-1` down. On-time is the same at a 180, 300, 600, or 705.59 minute repair. At 600 minutes, ResiliMES is 87/87, 83/87, 86/87, 87/87, 81/87 (mean 97.47%). EDD is 87/87, 86/87, 86/87, 87/87, 87/87 (mean 99.54%). FIFO is 20.7% and CR is 71.7%, so ResiliMES beats both by a wide margin. Versus EDD it gives up about 2 of 87 lots. Seed 2 is three lots waiting at `Diffusion_BE_123`. Seed 5 is five lots at `Dielectric_BE_28` plus `Init_Lot_1_10` at `WE_BE_14`. Re-cleans are 38 against 56 (means 38 and 55.6). Q-time violations are 430 against 452. `Init_Lot_2_23` is on time under EDD and late under ResiliMES on seeds 5 and 6 (2.67 h and 4.26 h). That same lot is the save on the tight stress test below.

The **published-due** book, 48 hours, 56 lots, does not show a loss either. ResiliMES is 31/56, 31/56, 32/56, 32/56, 32/56 (mean 56.43%). EDD is 31/56, 32/56, 32/56, 32/56, 32/56 (mean 56.78%) and slightly ahead on weighted tardiness, 21,526 minutes against 21,988. Seed 1 of that book ties at 31/56.

**Tight VIP dues** rewrites the dues for a stress test. It is not the published order book. Eight lots at `Dielectric_BE_28` become VIP and are due at 8 hours. Thirteen normal lots in that same queue are due at 7.2 hours. `Dielectric_BE_28-1` is down for the published dielectric repair, 604.8 minutes. Denominator 21 lots per seed. ResiliMES is 4/21 on every seed, 20/105 pooled. EDD is 3/21, 3/21, 2/21, 2/21, 3/21, 13/105 pooled. FIFO is 0/21. CR is 2/21. Seed 1 weighted tardiness is 7,679.4 under EDD and 4,043.8 under ResiliMES. On that seed `Init_Lot_2_23` is 5.43 hours late under EDD and on time under ResiliMES. The drill-down for this click is `Dielectric_BE_28-1` through `-3` over the full 24 hours.

The WIP number on a ResiliMES run is a candidate cap: `choose()` keeps 8 lots instead of 24 once a family exceeds max(8, two lots per tool), and also keeps a lot whose slack is at or under 7200 seconds. It does not replan. On seeds 9–13 that slack exception matched the shipped score on both books, so it stays. The adjacent Wet_Etch look-ahead fired 0 times on the published books. A retarget onto the 44 adjacent 1-hour dry-etch to wet-etch pairs, counting lots already queued downstream, was reverted: seeds 9–13 kept X-factor on-time and cut its Q-time, and raised published-due Q-time from 1,821 to 1,850. `macro_aps_ms` (286.0 ms, 30,625 scanner steps) does not feed `dpi()`. Feeding the expose-step due into `dpi()` was reverted on the same seeds: X-factor on-time rose from 407 to 420 of 435, and published-due on-time fell from 156 to 155 of 280. `rank()` does call `dispatch_score`. Headline dispatch 0.0002 ms p50 and about 0.007 ms p95 includes empty wakes. Nonempty-queue decisions on the X-factor ResiliMES runs are about 0.010 ms p50 and 0.25 ms p95 (seeds 1–5: p50 0.0090–0.0107, p95 0.244–0.250). The 12-hour lithography click is a seed-1 tie, 2/19 under both policies. It is not the 48-hour five-seed lithography study, where EDD is slightly ahead (56.78% against 56.43%, 56 lots).

A down tool releases at the later end when a forced outage overlaps an MTTF draw. Queuing only the first end left some tools down for the rest of the horizon. Seeds 1–5 on-time on the X-factor book, the published-due book, and the tight book are unchanged.

`make demo-live` is the same fab with Zetaris and Nightshift when those credentials are set. `make demo` does not call them. The film notes are in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md). Tables are in [docs/SMT2020_SCALE.md](docs/SMT2020_SCALE.md). What the extract contains and what the simulator leaves out is in [docs/SMT2020_PROVENANCE.md](docs/SMT2020_PROVENANCE.md).

`make demo-bay` is the six-lot sample used by the unit tests below.

## Sample bay (unit tests)

Sample fab FAB-A, scenario clock 22 Oct 2026 06:30 UTC. Machine breakdown (`litho_down`):

| KPI | Wait for repair | Rescheduled |
| --- | ---: | ---: |
| On-time delivery | 83.3% | 100% |
| Priority-weighted tardiness | 784 min (13 h 4 min) | 0 min |
| Makespan | 857 min | 328 min |
| Priority-1/2 lots at risk | 1 | 0 |

LOT-1001 is priority 1, blocked on LITHO-02 (laser fault, revised repair 600 minutes), due 18:00 UTC. Waiting finishes it 98 minutes late: the frozen book mounts RET-A28-L1-1 on LITHO-02, and that mount takes 5 minutes. The recovery moves the lot to LITHO-01, which shares `litho_193nm` and the setup family already on the tool, reuses the copy the running lot releases, and finishes it at t=253. A naive plan that starts the lot on the down tool immediately is rejected. A second L1 copy is free, so the refusal is the tool status. Lithography stays the bottleneck, and the move keeps it on an up tool.

A sixth preset, **Scale**, is a separate seeded fab of 1,000 lots and 36 tools. Ordinary lots carry 14 days of slack, and up to 24 priority-1 lots are pinned on the down scanner. It ties EDD on on-time delivery and weighted tardiness, so it is performance data only and it was not retuned. The table is in [docs/SCALE_APPENDIX.md](docs/SCALE_APPENDIX.md). The six-lot `litho_down` baseline is still a frozen assignment. The SMT2020 lithography and X-factor baselines are EDD.

The committed book stays that list scheduler. An optional CP-SAT model of the same rules is the optimality reference: tool eligibility, inhibits, family-change setups, down windows, one physical reticle copy per scanner, release times, re-entrant routes, queue-time max lag, and material holds. The objective is the same priority-weighted tardiness, with makespan as the tie-break. Held lots are scored the same way as the KPI: no finish time is invented for them. The console prints the gap on the chart row. On the six-lot stories the search proves the list scheduler's weighted tardiness. Lithography and the stockout match makespan as well. The rush book keeps tardiness at 288 minutes and shortens makespan from 342 to 293. Overlay rework shortens makespan from 402 to 326. Queue time shortens makespan from 285 to 256. On the 1,000-lot fab the two-second neighborhood does not beat the list schedule, so makespan stays 5,116 and the badge says the heuristic was kept. The list schedule is ready first, and it is what the cards commit. Analyze lists the steps the reference moved. Without OR-Tools the gap line stays hidden and recovery still completes. CI installs `ortools`. Locally it is the `solver` extra.

The other sample disruptions are one click away. A three-hour rush order finishes 36 min late. The running lot stays on LITHO-01 with RET-A28-L1-1. The spare copy exposes the hot lot on LITHO-02, and the rest of the route still misses the due. A photoresist stockout holds the lots which still need lithography. An overlay fail on LOT-1004 strips the resist, re-exposes once, and measures again. A second loop is not inserted. A queue-time miss holds LOT-1003 because the wet clean finished before the clock and the next film would start after a 15-minute window. The critic refuses that late deposition start.

## Architecture

```mermaid
flowchart TD
  user[Supervisor console] --> scout[Scout Intent]
  scout -->|signed execution contract| loop[Markovian chunks]
  loop --> specialist[Specialist]
  specialist --> data[Zetaris SQL or sample twin]
  loop --> planner[Deterministic planner]
  planner --> critic[Constraint critic]
  critic -->|accept| world[World Model event log]
  critic -->|reject| refused[Commit refused]
  loop --> explain[Explainer lane]
  nightshift[Meterless Nightshift] --> nemotron[NVIDIA Nemotron]
  user --> intents[POST /api/intents]
  intents --> nemotron
  intents -->|user confirms| txn[Lock, apply, re-dispatch]
  nemotron --> explain
  world --> user
  explain --> user
```

Nemotron turns a dispatcher sentence into one tool call, and later turns the engine result into a business note. Every number in that note is checked against the engine. The committed plan comes from a list scheduler. CP-SAT scores that same objective, and the critic checks both books. That split is the reliability argument for Track 03.

| Piece | Role |
| --- | --- |
| Scout Intent | Classifies the disruption, checks role, surface, and prompt injection, and signs an execution contract. Downstream engines refuse unsigned, expired, or out-of-scope contracts. |
| Specialist | Reads equipment, WIP, routes, materials, and maintenance. In live mode those reads are Zetaris SQL. In mock mode the same SQL is recorded and answered from `data/sample`. |
| Planner | Builds the frozen schedule and the recovered schedule. A labeled safety-test alternative gives the critic something real to reject. That alternative is not a model proposal. |
| Critic | A registry of independent checks: tool status, capability, overlap, WIP, operators, material, route order, preemption, queue time, rework limit, reticle, tool inhibit, and lot release. A hold is listed and does not by itself reject the book. |
| Markovian | Runs sense → plan → critique → explain → commit as bounded chunks. Each chunk sees a checkpoint, not the growing transcript. The size comparison is `len(json) // 4`, not a model token count. |
| World Model | Append-only plant log. Assignments are ingested under the contract and replayed. |
| Nightshift | OpenAI-compatible hotspot. Nemotron parses dispatch intents and writes feedback and the supervisor narrative when a runtime token is configured. The planner and the critic stay deterministic code. A Nightshift outage uses the regex parser and the deterministic narrative, and that fallback is labeled. |

`POST /api/intents` validates the tool call, checks lot and tool ids, and asks Scout to sign. Nothing is applied until `POST /api/intents/confirm`. The confirm path takes a machine `lock_token`, applies the change, and re-dispatches. `check_inventory` runs the BOM check first. `notify_pe` is a trace line for the UI. It does not send email or any other message. The contract is [docs/API.md](docs/API.md). `REDIS_URL` selects `RedisStateStore` for that same engine. Empty keeps the in-memory store.

Nightshift can point `NEMOTRON_MODEL` at a local on-prem model and keep the same lanes. This repo does not add a second client for that. Nightshift stays the provider.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Sponsor write-up: [docs/SPONSOR_TECH.md](docs/SPONSOR_TECH.md).

## Quick start

Python 3.11 or 3.12. On Debian or Ubuntu, `python -m venv` fails with `ensurepip is not available` until the venv package is installed (`sudo apt install python3-venv`, or `python3.12-venv` for that interpreter).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
make demo
```

Open http://127.0.0.1:8000. Choose a disruption. The console waits, so the stack light and the agent loop are visible when you click. No API keys are required. The amber banner means both providers are on their offline twins. In mock mode the stream pauses about 680 ms between real steps so a recording can read them. Pass `pace_ms: 0` to `POST /api/recover/stream` to skip that pause.

Headless check:

```bash
make smoke
python -m resilimes recover --scenario litho_down
```

Docker:

```bash
docker build -t resilimes .
docker run --rm -p 8000:8000 resilimes
```

The image sets `RESILIMES_MODE=mock`.

## Switching from mock to Nightshift and Zetaris

`RESILIMES_MODE=auto` (the default if you do not use `make demo`) turns each provider on independently when its credentials exist.

1. Install a NVIDIA Nemotron model in [Meterless Nightshift](https://meterless.ai/) and copy the runtime token from `<stateDir>/proxy-token`. Do not use the placeholder `rt-local`.
2. Set `METERLESS_BASE_URL`, `METERLESS_RUNTIME_TOKEN`, and `NEMOTRON_MODEL` to the id `GET /v1/models` returns.
3. Load Postgres and register the three datasources. From Windows:

```bash
wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh
```

The same script on the Linux tree is `bash scripts/zetaris_setup.sh`. It writes the API key to `~/.config/fab-mes/api-key` and does not print it. The recipe is [docs/ZETARIS.md](docs/ZETARIS.md).

4. Set `ZETARIS_REST_URL`, `ZETARIS_ORG_ID`, `ZETARIS_API_KEY`, `ZETARIS_TABLE_SOURCES`, and `ZETARIS_TIMEOUT_S`. The SQL path default is `/sql-editor/sqls/run-query`.
5. Start with `make demo-live` or `RESILIMES_MODE=auto python -m resilimes serve`.

`RESILIMES_MODE=live` refuses to start the recovery loop unless both providers are configured. The full variable list is in [.env.example](.env.example). Nothing in that file is a real secret.

Live connectivity, with secrets staying in `.env`:

```bash
cp .env.example .env
python smoke_test.py
```

Mask the token if you film that command. The console never prints it. A recovery report includes the model id, lane, and latency, and only a 12-character prefix of the contract HMAC.

## Troubleshooting

### Windows reserved ports

On Windows with Hyper-V, WSL, or Docker, Windows may reserve TCP port ranges. Check them with:

```bat
netsh interface ipv4 show excludedportrange protocol=tcp
```

The range 8001–8100 is common. Nightshift's default 8088 can then fail with `listen EACCES ... 127.0.0.1:8088` in `%LOCALAPPDATA%\ai.meterless.runtime\logs\engine-0.log`.

Nightshift rewrites `config.toml` on every start, and its Console has no port setting. From an elevated (Administrator) PowerShell, reserve the default ports so Hyper-V and WSL dynamic reservations leave them free:

```powershell
net stop winnat
netsh int ipv4 add excludedportrange protocol=tcp startport=8088 numberofports=1 store=persistent
netsh int ipv4 add excludedportrange protocol=tcp startport=11435 numberofports=1 store=persistent
net start winnat
```

That keeps 8088 (the public API) and 11435 (Nightshift's internal fabric port) as administered exclusions. Restart Nightshift after the commands finish.

ResiliMES probes the one base URL in `METERLESS_BASE_URL`. The default is `http://127.0.0.1:8088/v1`. If Nightshift listens on a different port, set `METERLESS_BASE_URL` to that origin plus `/v1`.

## Usage

The console is the product. Five presets:

- **Machine breakdown** — LITHO-02 down for 10 hours. Compare “wait for repair” with a recovered schedule. Lithography is the bottleneck, and the recovery keeps it on an up tool.
- **Rush order** — insert priority-1 LOT-2001 due in three hours. The running lot keeps its scanner and one L1 copy. The spare copy exposes the hot lot on the other scanner. The promise is still 36 min late.
- **Material shortage** — RESIST-UV on hand is zero. Lots that still need lithography are held. LOT-1002 is already running and keeps its resist.
- **Overlay rework** — overlay failed on LOT-1004 at metrology. The book strips on the wet bench, re-exposes once, and measures again. The rework limit is 1. The re-measure bar is striped.
- **Queue time** — clean to the next film on PROD-B14 must start within 15 minutes. LOT-1003 already missed that window. A naive start at t=120 is refused.

Each layer of PROD-A28 is deposition, lithography (coat, expose, and develop as one step), overlay and CD metrology, etch, wet clean, and CMP. L2 repeats the six steps. DEP-01 runs the film. MEAS-01 measures. WET-01 strips and cleans. Lots released through CMP stay on the first layer today. Queue time is surface exposure: 480 minutes from clean end to the next deposition. On A28 that next film is DEP-L2, with CMP between them, so the limit covers the polish. The 15-minute scenario tightens the adjacent B14 pair, clean to the cap film. Each A28 layer has two physical reticles. A copy sits on one scanner at a time, and mounting it on a different scanner takes 5 minutes. Analyze shows compliance and the bottleneck. Verify lists every registered check. A lithography bar tooltip names the copy.

Or type an incident. Scout classifies it. A viewer role, or a prompt-injection attempt, is refused before any schedule is written.

```bash
python -m resilimes recover --scenario rush_order
python -m resilimes recover --incident "Machine ETCH-02 Down, repair ETA 300 minutes"
```

HTTP: `GET /api/health`, `GET /api/scenarios`, `POST /api/recover`, `POST /api/recover/stream` (server-sent steps, then the report), `GET /docs`.

## Tests

```bash
make check
```

That is ruff, mypy, and pytest. The Meterless engine proofs are:

| Engine | Test |
| --- | --- |
| Scout Intent (the required engine) | `tests/test_scout_engine.py` |
| World Model | `tests/test_engines.py` |
| Markovian | `tests/test_engines.py` |

`tests/test_recovery.py` runs the whole loop in mock mode, including the viewer refusal and the Zetaris header contract against a fake HTTP response.

## Repository layout

```text
resilimes/            Product: domain, engines, agents, API, console
agent/                Live connectors only: Nightshift client and Zetaris REST
data/sample/          Offline plant
data/sql/seed.sql     Zetaris DDL and inserts, generated from data/sample
data/sql/scale_seed.sql  Same catalog for the 1,000-lot fab
data/zetaris/         CSV twin of the sample tables
data/zetaris/scale/   CSV twin of the scale fab
prompts/              Specialist prompt. The recovery loop does not load it.
tests/                Unit and API tests
docs/                 Architecture, sponsor write-up, demo script, pitch, checklist
```

## Dependencies

Runtime (`requirements.txt`): `openai`, `python-dotenv`, `requests`, `fastapi`, `uvicorn`, `pydantic`.

Development (`requirements-dev.txt`): `pytest`, `ruff`, `mypy`, `httpx`, `ortools`. OR-Tools is optional at runtime (`pip install -e ".[solver]"`). The recovery path runs without it.

Verified on Python 3.12.3 with ruff 0.17.2. CI runs 3.11 and 3.12.

## Sponsor technology

| Layer | Technology | Where it shows up |
| --- | --- | --- |
| Data | Zetaris | `agent/tools_zetaris.py`, `resilimes/data/zetaris_source.py`, `data/sql/seed.sql` |
| Power | Meterless Nightshift routing to NVIDIA Nemotron | `resilimes/llm/nightshift.py` |
| Engines | Scout Intent, World Model, Markovian | `resilimes/engines/` |
| Build | Cursor | This repository was written in Cursor: architecture, scheduler, engines, console, tests, and docs. |

The offline twins implement the same interfaces. Mock mode is labeled in the console and in every recovery report. It is not a silent fallback that pretends a model answered.

## Track

Track 03 — Reasoning Architecture.

The challenge is to turn data, knowledge, memory, and reasoning into reliable decisions and actions. ResiliMES does that for a named user: the production supervisor on shift when a tool fails. The decision is a schedule. The action is the set of assignments written to the world model. Memory is the event log and the Markovian checkpoint. The critic is what makes the decision reliable: an unsafe plan is not committed, including a plan that would look better on a KPI by preempting a running lot or starting work on a down tool.

Track 02 (explain why) is a property of the same loop, visible in the narrative, the rejected alternative, and the fact list. It is not the primary track, because the product is the decision, not only the explanation. Track 01 is how the specialist reads fragmented tables. Wildcard would score only the increment on a prior product and pays less; the git history of this repository starts inside the build window (first commit 22 Oct 2026 22:22 UTC, window opened 22 Oct 2026 00:00 UTC), so the whole system is window work.

## Team

Two people. Put both names on the slide deck and the HackOS form before you submit. Team composition locks when the first submission is created.

## Hackathon packet

- Rules: [docs/hackathon/HACKATHON_RULES.md](docs/hackathon/HACKATHON_RULES.md)
- Sponsor write-up: [docs/SPONSOR_TECH.md](docs/SPONSOR_TECH.md)
- Demo script (about 3 minutes): [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)
- Slide outline: [docs/PITCH_DECK.md](docs/PITCH_DECK.md)
- Submission checklist: [docs/SUBMISSION_CHECKLIST.md](docs/SUBMISSION_CHECKLIST.md)
- API assumptions: [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md)

License: MIT.
