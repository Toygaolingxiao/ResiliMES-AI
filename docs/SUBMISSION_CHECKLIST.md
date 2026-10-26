# Submission checklist

Rules source: [hackathon/HACKATHON_RULES.md](hackathon/HACKATHON_RULES.md) and [hackathon/HACKATHON_RULES_original.md](hackathon/HACKATHON_RULES_original.md). Official pages: the [HackOS event](https://hackathon.genai.works/event/open-agent-hackathon-2026) and the [Academy course](https://academy.genai.works/courses/open-agent-hackathon-2026/details). The Academy lesson "How the Week Runs" is login-gated and was not available when these rules were captured. Confirm that lesson before you press submit in case it adds a form field.

Deadline: **27 Oct 2026 23:45 UTC** (= 28 Oct 08:45 JST; code freeze 28 Oct 02:45 JST). Ties break on Impact, then submission timestamp. Submit early.

| Requirement | Where it is satisfied | Still manual |
| --- | --- | --- |
| Build window 22 Oct 2026 00:00 UTC through 27 Oct 2026 23:45 UTC | Git history starts 22 Oct 2026 22:22 UTC. This branch is window work. | If anything existed only outside git, declare it on the form. |
| One primary track | Track 03 — Reasoning Architecture. Justification in the README (head and Positioning) and deck slides 3–4. | Select it in the team workspace. You can change it until the deadline. |
| Team of 1–5, one account each, composition locks at first submission | README team section. | Register, name both people, create the submission once. |
| Integrate Zetaris | `agent/tools_zetaris.py`, `resilimes/data/zetaris_source.py`, `data/sql/seed.sql`, `docs/SPONSOR_TECH.md` | Load the seed into your org. Set `ZETARIS_*`. |
| At least one Meterless engine in a working feature | Scout Intent on every recovery. Tests: `tests/test_scout_engine.py`. Also used: World Model, Markovian. | Name Scout Intent and the test path on the form. |
| Meterless Nightshift as primary AI provider, NVIDIA connected inside it | `resilimes/llm/nightshift.py`. Model id `NEMOTRON_MODEL`. | Install Nemotron in Nightshift. Paste the runtime token. Film one live call. |
| Cursor for development | Event-page rule says required. Academy FAQ says recommended. This repo was built in Cursor. Say so in the sponsor field. | — |
| Demo video, 1–4 minutes | v2 film plan: `docs/DEMO_VIDEO_SCRIPT.md` (v1 cut + two new clips: A = deck slide 7 Q-time first, B = Gantt right-click). Setup in `docs/DEMO_SCRIPT.md`. | Record clips A and B, build v2 (≤ 4:00), re-upload. Timings stay `[TBD after re-record]` until the v2 build. The v1 film already shows one real Nightshift request with secrets off screen. |
| Slide deck | `docs/deck/index.html` (outline: `docs/PITCH_DECK.md`) | v4 (15 slides, positioning "rules decide, AI explains"). Exported to PDF. Open slots: `[SCREENSHOT: Gantt right-click]` (slide 5, take a frame from clip B), `[LIVE: notes extraction P/R]` and `[LIVE: notes A/B/C]` (slide 9), `[LIVE: hard-case rerun]` (slide 11), `[TBD after re-record]` (slide 14). Fill them or leave them labelled; never type a number without a committed source. |
| GitHub repo with source | This repository. | Confirm the repo is public or shared as the form requires. |
| README covers setup, usage, dependencies | `README.md` sections Quick start, Usage, Dependencies. | — |
| Sponsor-tech explanation, including the engine and the test | `docs/SPONSOR_TECH.md` | Paste the short version into HackOS. |
| Declare pre-existing product code | The scaffold and this completion are both inside the window. | If you bring older concept material, declare it. Otherwise state that the git history is the work. |
| No secrets in the repo | `.env` is gitignored. `.env.example` has empty tokens. Logs redact credentials. | Keep it that way in the video. |
| Age, eligibility, one team per person | — | Confirm on the form. Employees of the organizer or judging sponsors cannot take cash prizes. |
| Submit on HackOS | — | https://hackathon.genai.works/event/open-agent-hackathon-2026 |

## Form text you can paste

**Positioning (one line).** The scheduler stays rule-based and auditable, like mainstream APS. AI makes its decisions understandable to the people who run the fab.

**Description.** Paste the ~1,900-character text kept outside the repo (`desc_v4.txt`). Its claims, each from a committed doc: 99.26% true Q-time compliance and 71 avoidable misses (seeds 1–3, 7 d, `docs/HARD_QTIME.md`); EDD only as an infeasible reference (1,719 avoidable); +19 avoidable violations when every deliberate gap is filled (`docs/gap_counterfactual/seed1_48h.md`); 0 AI calls under the shipped trigger (`study_zero_call/zero_call.md`, 0/16 stress books); flat same-budget K-curve (`study_search_curve/k_curve.md`); B/C comparisons are exploratory study mode (`SHIFT_LEAD_ESCALATE=always`).

**Track.** Track 03 — Reasoning Architecture.

**Engine.** Scout Intent. Test: `pytest tests/test_scout_engine.py`. The recovery loop also commits through a World Model event log and runs as Markovian chunks. See `docs/SPONSOR_TECH.md`.

**Zetaris.** Factory tables are queried with the REST SQL editor (`Authorization: Bearer`, `X-Org-ID`, `X-Request-ID`). Seed: `data/sql/seed.sql`. Mock mode runs the same statements against `data/sample` and labels the trace `sample-equivalent`.

**Nightshift and Nemotron.** Chat completions go to the Nightshift OpenAI-compatible base with the runtime token and `meterless-app: resilimes`. `NEMOTRON_MODEL` is the NVIDIA model id installed in Nightshift. Nemotron explains and advises only: Gantt right-click answers, the investigator, the late-lot explainer, the shift handover and notes extraction. Every number is fact-checked; a failure or timeout falls back to the labelled rule result. The rule kernel and the hard Q-time gate make every scheduling decision.

**Cursor.** The system was developed in Cursor.

**Pre-existing code.** Repository history begins after the build window opened on 22 Oct 2026 00:00 UTC. No separate pre-window product is included. Confirm before you submit.
