# Sponsor technology

ResiliMES uses Zetaris as the plant's data layer, Meterless Nightshift as the primary model provider with NVIDIA Nemotron behind it, and three Meterless engines. Scout Intent is the engine this submission claims. World Model and Markovian are wired behind the contract Scout signs, which is how the public engine stack is specified to compose.

Cursor was the development environment for the recovery loop, the console, the tests, and these docs.

## Which engine, and the test that shows it works

**Engine: Scout Intent** (`resilimes/engines/scout/engine.py`).

Scout is the gate in front of every recovery. The console does not reschedule from a raw sentence. It reschedules from a signed execution contract: intent, bound entities, risk, tool plan, model profile, scope, expiry, HMAC.

The test file is `tests/test_scout_engine.py`. Run it with:

```bash
pytest tests/test_scout_engine.py -q
```

What that file proves:

| Behavior | Test |
| --- | --- |
| "Machine Litho-02 Down" classifies as `plant.machine_down`, binds `LITHO-02`, and verifies the HMAC | `test_machine_down_classifies_and_signs` |
| Rush orders and material shortages classify and bind product or material ids | `test_rush_and_shortage_intents` |
| The rework and queue-time sentences classify at 0.92 or better | `test_rework_and_qtime_clear_the_floor` |
| Prompt injection yields `risk.level = block` and no contract | `test_prompt_injection_is_blocked` |
| A viewer cannot invoke a reschedule | `test_viewer_cannot_reschedule` |
| An emergency stop on a disallowed surface is blocked | `test_surface_is_enforced` |
| A mutated contract fails signature checks, and a contract past `expiresAt` is refused | `test_tamper_and_expiry_are_refused` |
| A high-risk contract with no approval is refused by the downstream verifier | `test_high_risk_without_approval_is_refused_downstream` |
| `replan` keeps the trace id and sets `parentId` | `test_replan_keeps_trace_and_sets_parent` |
| The deterministic trigger scan stays under 16 ms median | `test_trigger_scan_stays_under_16ms` |
| An intent with no examples is rejected at load | `test_registry_requires_examples` |
| Live mode selects a local Nightshift profile whose model id is a Nemotron | `test_live_profile_is_local_nemotron` |

`tests/test_recovery.py::test_orchestrator_litho_path_is_explainable` shows the same contract on the real feature: a machine breakdown produces a verified contract, five Markovian chunks, a world-model commit, and a tardiness reduction. `test_viewer_and_injection_do_not_commit` shows the guard on that feature.

The implementation follows the public spec at [engines/scout-intent](https://github.com/Meterless/Meterless/blob/main/engines/scout-intent/AGENTS.md). `@meterless/scout` is not a published package. Canonical JSON is specified as HMAC input but not pinned to an RFC. ResiliMES uses sorted-key compact UTF-8 JSON with nulls removed. That choice is in [ASSUMPTIONS.md](ASSUMPTIONS.md).

## How the other two engines are used

They are not extra demos. The recovery refuses to run without them.

**World Model** (`resilimes/engines/world_model/engine.py`) is the plant log. After the critic accepts, each tool observation and each lot assignment is ingested under the Scout contract. `world.sync` is required to observe, `schedule.commit` is required to assign, and a second ingest with the same idempotency key does not duplicate the event. Replay is how the report counts committed jobs. A payload field cannot overwrite the entity type, so a job assignment stays a job. Tests live in `tests/test_engines.py` (`test_ingest_is_idempotent_and_replayable`, `test_world_model_refuses_unsigned_and_out_of_scope`).

**Markovian** (`resilimes/engines/markovian/engine.py`) is the agent loop. Sense, plan, critique, explain, and commit are chunks. Each chunk receives a checkpoint. A raised exception stays inside its chunk. Transcript fields are dropped. The litho run reports checkpoint units against the cost of resending history (about 500 versus about 1600). Those units are `len(json) // 4`, not model tokens. Tests: `test_compress_drops_transcript_and_keeps_decisions`, `test_chunk_failure_is_contained`, `test_checkpoint_size_stays_below_replayed_history`, `test_markovian_refuses_a_contract_without_memory_write`. A critic verdict of `reject` commits no assignments.

A read-only "what is the fab status?" contract does not carry `memory.write`, so Markovian will not start a recovery from it.

## Zetaris

Zetaris is the system of record for equipment, WIP, routes, route steps, queue-time rules, BOM, stock, operators, and maintenance.

The client is the scaffold in `agent/tools_zetaris.py`:

- `POST {ZETARIS_REST_URL}{ZETARIS_SQL_PATH}`
- `Authorization: Bearer <ZETARIS_API_KEY>`
- `X-Org-ID: <ZETARIS_ORG_ID>`
- `X-Request-ID: <uuid>`
- Body: `{"sql": "<one statement>"}`

`resilimes/data/zetaris_source.py` issues one `SELECT` per table from `resilimes/data/sql_catalog.py` and builds the same `Plant` the scheduler uses. The schema identifier is validated so it cannot carry a second statement.

`data/sql/seed.sql` and `data/zetaris/*.csv` are generated from `data/sample` by `python scripts/export_zetaris_sql.py`. `tests/test_sql_export.py` fails if those files drift. `scripts/zetaris_setup.sh` loads that seed, plus `data/sql/kernel.sql` when it exists, into Postgres and registers datasources `resilimes` (MES, including lots, operations, and the setup matrix), `fab_cmms` (maintenance logs and the PM calendar), and `fab_erp` (BOM, materials, orders). `scripts/load_zetaris.py` only points at that script.

The default console does not send those reads through Zetaris. It loads `data/smt2020` in process: `tool.txt.1l`, `WIP.txt`, `route_1.txt`–`route_10.txt`, `setup.txt`, `pmcal.txt`, `attach.txt`, and `downcal.txt`. The banner and the log line say `data source: smt2020`, and the query line names those files. A live Zetaris round-trip per dispatch would dominate the latency the scale study measures, and this repository does not assume the platform container is up. The federated sample query in `resilimes.data.zetaris_layout.FEDERATED_SQL` joins `resilimes.equipment`, `fab_cmms.maintenance_logs`, `resilimes.wip_jobs`, `fab_erp.bom`, and `fab_erp.materials`. That query is for the sample catalog. It is not what the full-fab simulator executes.

Assumption to check on the owner's platform: `scripts/zetaris_setup.sh` still registers those three datasources, `POST /sql-editor/sqls/run-query` still returns string cells, and `X-Org-ID` is still required. The full-fab numbers in [SMT2020_SCALE.md](SMT2020_SCALE.md) do not depend on that call.

In mock mode the specialist still records those SQL strings and answers them from the sample files. The trace labels the mode `sample-equivalent`, so a recording does not imply a live warehouse call. `tests/test_recovery.py::test_zetaris_headers_and_row_shape` checks the bearer token, org header, request id, URL, and the `headers` + `data` row shape, including a body wrapped in `result`.

`python smoke_test.py` (no `--mock`) is the live probe: Zetaris web origin, `SELECT 1`, and a Nightshift chat completion.

## Meterless Nightshift and NVIDIA Nemotron

Nightshift is the only model provider on the live path. The client is `resilimes/llm/nightshift.py`, shared with `agent/llm.py`.

- Base URL normalized to `<origin>/v1`. A pasted `/v1/chat/completions` or `/healthz` does not become `/v1/v1`.
- `Authorization: Bearer <METERLESS_RUNTIME_TOKEN>`. The placeholder `rt-local` is rejected.
- `meterless-app: resilimes` and `meterless-scope: user` on chat calls.
- Nemotron, via `NEMOTRON_MODEL`, turns dispatcher text into a tool call and writes feedback and the supervisor narrative. The planner and the critic do not call the model. The critic is `critique_schedule`.
- Timeout defaults to 180 seconds. Rate limits and connection errors retry three times.
- Logs record lane, model id, and latency. They do not record the token.

The committed schedule does not come from the model. The model rewrites the supervisor narrative from a fact sheet, and it writes the business note after a confirmed tool call. If it fails, or a number or id is not in the engine result, the deterministic text stands and the schedule is unchanged. That is a deliberate use of Nemotron: language in the lane where language helps, a solver in the lane where a wrong digit moves a wafer. Nightshift can route the same calls to a local model for an on-prem fab by serving that model under `NEMOTRON_MODEL`. This repository does not add a second provider.

Mock mode uses `MockProvider` with the same `complete()` signature. The report field `provider_call.mocked` is true, and the console banner says offline mock. `make demo` forces this mode so a fresh machine can film the product. To film the required live request, set the token and run `python -m resilimes recover --scenario litho_down`. The JSON includes `provider_call.provider = "nightshift"`, the Nemotron model id, and latency. Crop or scroll so `.env` is not on screen.

`tests/test_recovery.py::test_nightshift_retries_rate_limits` drives two 429s and then a successful completion without a real hotspot.

## Cursor

The scaffold (`agent/`, `prompts/`, the original sample files, `smoke_test.py`) and this completion were written in Cursor. Cursor's agent mode produced the scheduler, the three engines, the console, the test suite, CI, and the submission docs in this branch. The team should say that on the slide and in the HackOS sponsor field: Cursor was the build environment, not a runtime dependency of the fab.

## Full SMT2020 fab

The working feature on `make demo` is dispatch of the public industry benchmark (SMT2020) LV/HM fab. Scout still classifies the scenario sentence and signs the contract before the run. The test that proves Scout is `tests/test_scout_engine.py`. The test that proves the fab counts, the tight-due book, and a short full-tool dispatch is `tests/test_smt_fab.py`.

Nightshift remains the only model provider. Base URL `METERLESS_BASE_URL`, default `http://127.0.0.1:8088/v1`. The model id is `nvidia/nemotron-3.5-lightning-30b-a3b`. On the sample-bay path it rewrites the supervisor note and the tool-call text. On the full-fab path, `make demo-live` with a runtime token sends one completion after the schedule is fixed. The request id is `explain.meterless_request_id` and the Nightshift step. The schedule is still the dispatcher. `make demo` does not make that call.

When Zetaris credentials are set, the same live path runs `SELECT COUNT(*)` against datasources `resilimes`, `fab_cmms`, and `fab_erp`. The console shows the SQL, those source names, and the row counts. Without credentials the line says the local extract was used and Zetaris was not called.

Measured means are in [SMT2020_SCALE.md](SMT2020_SCALE.md). The lead table is the constructed 24-hour book: ResiliMES on-time 19.05% against EDD 12.38%, weighted tardiness 4,293 minutes against 8,013. Dispatch on that book is 0.005 ms p50 and 0.149 ms p95. The published-due 48-hour book is an appendix: on-time ties EDD at 57.14%, dispatch p50/p95 is 0.004 ms / 0.138 ms, macro APS is 312.8 ms, and one 48-hour ResiliMES run is about 1.4 s.

## Pre-existing code declaration

The build window opens 2026-10-22 00:00 UTC (2026-10-22 09:00 JST) and closes 2026-10-27 23:45 UTC (2026-10-28 08:45 JST). That window is in [hackathon/HACKATHON_RULES.md](hackathon/HACKATHON_RULES.md).

`git log --reverse` shows the first commit at 2026-10-22 22:22 UTC (`83f37fc`, "Initial commit"). There is no commit before the window opened. There is no separate pre-window product in this repository. The scaffold (`agent/`, `prompts/`, the original sample files, `smoke_test.py`), the six-lot sample bay, Scout, World Model, Markovian, the Nightshift client, and the sample console were written in this repository after that first commit and inside the window. They are not an imported third-party application template. This branch adds the SMT2020 kernel tables, the Zetaris datasource layout, the optional Redis state store, and the full-fab simulator.

Third-party skill texts under `.cursor/skills/`, copied in, not rewritten. Licenses are in the folders and in `.cursor/skills/CREDITS.md`.

| Path | Origin | License |
| --- | --- | --- |
| `.cursor/skills/design-taste-frontend/` | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill), `SKILL.md` and `references/app-screens.md`, fetched 2026-10-23 | MIT, Copyright (c) 2026 Leonxlnx |
| `.cursor/skills/frontend-design/` | [anthropics/skills](https://github.com/anthropics/skills), `skills/frontend-design`, fetched 2026-10-23 | Apache License 2.0, Copyright Anthropic |

Runtime dependencies in `pyproject.toml`: `fastapi`, `uvicorn`, `pydantic`, `openai`, `requests`, `python-dotenv`. OR-Tools (`ortools>=9.11`) is an optional extra (`pip install -e ".[solver]"`). It is the CP-SAT reference on the sample bay. The SMT2020 dispatcher does not import it. CI installs it with the dev extra.

## What is unusual about the combination

Most hackathon agents let the model both decide and explain. Here the model is behind Nightshift, the decision is a tested scheduler, and Scout will not let the loop run without a fresh contract. The sample bay reads lots and tools from Zetaris, or from the sample twin with the same SQL. The full-fab dispatcher reads the public industry benchmark (SMT2020) in process, and the live console asks Zetaris for the count queries before that run. The world model is the only place a committed assignment exists. A viewer, an injection, an expired contract, or a missing approval stops the write. That is the sponsor stack used as the control plane of a manufacturing decision, not as three logos on a chat window.
