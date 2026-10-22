# ResiliMES

**Autonomous Multi-Agent Rescheduling & Fault Recovery for Smart Manufacturing**

ResiliMES is a self-healing, constraint-aware **Manufacturing Execution System (MES)** and **Advanced Planning & Scheduling (APS)** multi-agent system built for the [Open Agent Hackathon 2026](https://hackathon.genai.works/event/open-agent-hackathon-2026).

When a tool fails (e.g. *“Machine Litho-02 Down”*), agents discover plant state, propose reschedules, and critic-check them against due dates, setup times, and operator capacity before anything is committed.

## Problem

Factories run on fragmented signals: equipment status, WIP, BOM/routes, and maintenance logs. A single downtime event cascades into missed due dates unless APS can react with constraint-aware recovery — fast enough for the floor, explainable enough for planners.

## Architecture

| Agent | Role |
| --- | --- |
| **Planner** | Parses incident logs and proposes rescheduling strategies (JSON). |
| **Specialist (Data/APS)** | Queries factory tables (Zetaris / local samples) and surfaces APS facts. |
| **Evaluator / Critic** | Validates proposals against physical constraints before commit. |

```text
Incident → Planner → Specialist (Zetaris / samples) → Evaluator → Accepted schedule delta
                ↑______________ Nemotron (Meterless Nightshift) ______________↑
```

## Sponsor tech

| Layer | Sponsor | How ResiliMES uses it |
| --- | --- | --- |
| **Data** | [Zetaris](https://www.zetaris.com/) | REST SQL over factory tables (`Bearer` + `X-Org-ID` + `X-Request-ID`). |
| **Power** | [Meterless Nightshift](https://meterless.ai/) + **NVIDIA Nemotron** | OpenAI-compatible local/runtime LLM for Planner & Critic. |
| **Build** | [Cursor](https://cursor.com/) | Agent-assisted scaffolding, iteration, and demo workflow. |

## Repository layout

```text
data/sample/          Synthetic equipment, WIP, BOM, maintenance logs (<5MB)
prompts/              System prompts (Planner, Specialist, Evaluator)
agent/
  llm.py              Meterless / Nemotron OpenAI-compatible client
  tools_zetaris.py    Zetaris REST SQL wrapper
  planner.py          Incident → reschedule plan (JSON)
  evaluator.py        Constraint critic (JSON)
smoke_test.py         Zetaris Web + REST SQL + Nemotron connectivity
.env.example          Env template (no secrets)
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Fill ZETARIS_*, METERLESS_*, NEMOTRON_* — never commit .env

python smoke_test.py
```

### Offline / local samples

Planner and Evaluator can reason over `data/sample/` without live Zetaris:

```bash
python -m agent.evaluator          # deterministic constraint check demo
```

With Meterless Nightshift running and `.env` configured:

```bash
python -m agent.planner "Machine Litho-02 Down"
```

## Environment variables

See [`.env.example`](.env.example). Required for the smoke test:

| Variable | Purpose |
| --- | --- |
| `ZETARIS_BASE_URL` | Web UI origin (liveness). |
| `ZETARIS_REST_URL` | REST API base ending in `/api/v1.0`. |
| `ZETARIS_ORG_ID` | Numeric organisation ID. |
| `ZETARIS_API_KEY` | Bearer token for REST SQL. |
| `ZETARIS_SQL_PATH` | Default `/sql-editor/sqls/run`. |
| `METERLESS_BASE_URL` | Nightshift OpenAI base (e.g. `http://127.0.0.1:8088/v1`). |
| `METERLESS_RUNTIME_TOKEN` | Nightshift runtime token (not `rt-local`). |
| `NEMOTRON_MODEL` | Model / routing id served by Nightshift. |

**Secrets stay in `.env` only.** They are gitignored.

## Agent I/O contract

Agents exchange **structured JSON** (schemas in `prompts/*_system.md`):

- Planner → `{ incident_id, parsed_incident, affected_jobs, strategy, fallbacks, ... }`
- Specialist → `{ query, facts[], constraints[], warnings[], ... }`
- Evaluator → `{ verdict, score, violations[], metrics, rationale, ... }`

## Track fit

ResiliMES targets **Track 03 — Reasoning Architecture** (data → knowledge → reliable scheduling decisions), with strong **Track 01** (fragmented factory data via Zetaris) and **Track 02** (explainable critic rationale) overlap. Wildcard entries must integrate **both** Zetaris and Meterless — this scaffold wires both.

## License

Hackathon prototype — team to finalize license before submission.
