# Demo script

Target length: 3 minutes 10 seconds. Stay inside 1–4 minutes. Film the console full screen. If you also show a terminal for the live Nightshift call, hide `.env` and any token. A 12-character HMAC prefix in the console is not the runtime token.

Record the machine-breakdown path on `make demo` even if you also record one live call. The KPIs below are what mock mode produces for the sample fab.

## Before you hit record

```bash
make demo
```

Open http://127.0.0.1:8000. The amber banner must be visible if you are in mock mode. Do not open `.env`. Zoom the browser to 110% so the KPI numbers are readable. Optional second clip, only if credentials are set: `python -m resilimes recover --scenario litho_down` and show `provider_call.provider` and `provider_call.model` while the token stays off screen.

## Shot list

### 0:00–0:20 — The user and the problem (Impact)

On camera, over the empty-state line or the loaded console:

"This is for the supervisor on a lithography bay, not for a chat window. LOT-1001 is a priority-1 lot blocked on a scanner that just faulted. The due time is 18:00 UTC. Waiting for a 10-hour repair misses it. Rebuilding the shift by hand is how these lots slip."

Point at the scenario clock: 22 Oct 2026 06:30 UTC.

### 0:20–0:35 — The product (Product & UX)

Click **Machine breakdown** if it is not already selected. Let the page settle. Scroll just enough to show the banner, the three disruption buttons, and the narrative sentence.

"One button. The banner says this recording is on the offline twins, so nothing here is pretending to be a live model call."

### 0:35–1:15 — The decision (Impact, Demo)

Leave the narrative on screen, then the four KPI cards.

"On-time delivery goes from 83.3 percent to 100. Priority-weighted tardiness goes from 840 minutes to zero. Makespan goes from 965 minutes to 420. Lots at risk go from one to zero."

Point at the left Gantt. "LITHO-02 is hatched until the repair. LOT-1001 sits on it and finishes late."

Point at the right Gantt. "The recovery puts LOT-1001 on LITHO-01, behind the lot that is already running, same lithography capability, no setup change. It finishes at t=250, inside the due time. LOT-1002 was not pulled off the tool."

### 1:15–1:45 — Why it is allowed (Innovation, Track 03)

Scroll to **Why the critic committed this** and the agent trace.

"The committed schedule comes from a constraint solver. Scout signed the contract before anything ran. The critic rejected the obvious bad idea: start LOT-1001 on LITHO-02 immediately. The trace is Scout, the specialist's SQL, the planner, the critic, five Markovian chunks, and a world-model commit."

Read the rejected line if it fits: "LITHO-02 is DOWN until t=600."

### 1:45–2:15 — A decision that refuses a fake win (Innovation, Technical)

Click **Rush order**. Wait for the KPIs.

"A customer wants a hot lot in three hours. On-time delivery falls to 85.7 percent. Weighted tardiness rises by 120 minutes, which is the hot lot, 15 minutes late. The critic rejected preempting LOT-1002, the lot already on the scanner. ResiliMES will not break a running lot to make the new promise look true."

### 2:15–2:35 — Evidence from the data (Sponsor tech, Track overlap)

Click **Material shortage**.

"Photoresist on hand is zero. LOT-1001 and LOT-1004 are held. LOT-1002 keeps running because that bottle was already consumed. The critic rejects a plan that would start lithography anyway. Those rows are the materials table, the same shape Zetaris serves."

### 2:35–2:55 — The sponsor stack (Sponsor tech)

Back on machine breakdown, point at the trace evidence lines that contain `SELECT` and `sample-equivalent`, then at the explainer line `mock · resilimes-mock`.

"Live, that SQL is a Zetaris call with a bearer token and an org id, and that explainer line is Meterless Nightshift calling NVIDIA Nemotron. Scout Intent is the engine. The test that proves the signature, the expiry, the injection block, and the 16 millisecond trigger scan is `tests/test_scout_engine.py`. World Model stores the assignments. Markovian keeps each agent step on a checkpoint instead of the whole transcript."

If you have the live clip, cut it here for five seconds: the JSON `provider` and `model` fields, token not visible.

### 2:55–3:10 — Close (Impact, Demo)

"The supervisor gets a schedule they can defend: what moved, what was refused, and the due-date delta. Next we point the same loop at the plant's real Zetaris tables and the team's Nightshift token. The console already knows the difference."

Stop. Do not add a chatbot ending.

## Judging map

| Criterion | Where it is on screen |
| --- | --- |
| Impact 30 | Opening user, KPI cards, the close |
| Technical 20 | Trace: contract, chunks, event log, critic verdict |
| Innovation 15 | Solver commits, model explains; rush order refuses preemption |
| Demo 15 | One workflow, three disruptions, numbers readable |
| Product & UX 10 | One-click presets, before/after Gantt, banner that tells the truth |
| Sponsor tech 10 | SQL line, Scout contract, Nightshift/Nemotron line or the live cut |

## If something looks different

The numbers above are from the sample data and the 600-minute repair overlay. If you edit `data/sample` or the scenario clock, re-run `python -m resilimes recover --scenario litho_down` and update the spoken figures before you film. Do not quote numbers you did not just see.
