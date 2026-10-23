# Demo script

Target length: 3 minutes 20 seconds. Stay inside 1–4 minutes. Film the console full screen at 1920×1080, or 1280×800 if that is the laptop. Hide `.env` and any token. A 12-character HMAC prefix in the console is not the runtime token.

Record the machine-breakdown path on `make demo` even if you also record one live call. The figures below are what mock mode produces for the sample fab. The console speaks them as hours and days: 840 minutes is 14 h, 17280 minutes is 12 d, 120 minutes is 2 h.

## Before you hit record

```bash
make demo
```

Open http://127.0.0.1:8000. Do not click yet. The amber banner must be visible in mock mode. The headline asks which disruption to recover. The bay lamps are steady. Language can stay on English; switch to 中文 or 日本語 only if you want that sentence on camera, then switch back before the numbers.

Optional second clip, only if credentials are set: `python -m resilimes recover --scenario litho_down` and show `provider_call.provider` and `provider_call.model` while the token stays off screen.

## Shot list

### 0:00–0:18 — The user and the problem (Impact)

On the idle console:

"This is for the supervisor on a lithography bay. LOT-1001 is priority 1, blocked on a scanner that just faulted, due 18:00 UTC. Waiting out a 10-hour repair misses it."

Point at the scenario clock: 22 Oct 2026 06:30 UTC.

### 0:18–0:45 — The disruption and the loop (Demo, Product & UX, Technical)

Click **Machine breakdown**. LITHO-02's lamp flashes red. Do not scroll. Let the agent row fill: Scout, Zetaris, Sense, Plan, Critic, Nightshift, Commit. Each step is a real event from `POST /api/recover/stream`, held about 680 ms so it can be read. The millisecond on the node is compute time, not the hold.

"Scout classifies it and signs a contract. Zetaris, or the sample twin with the same SQL, is the read. The planner builds both books. The critic checks the move. Nightshift only explains. The world model commits."

If a SQL line is on screen, point at `SELECT` and `sample-equivalent`.

### 0:45–1:20 — The decision (Impact, Demo)

When the headline lands, read it, then the three bullets, then the four figures.

"LOT-1001 leaves LITHO-02. On-time delivery goes from 83.3 percent to 100. Weighted tardiness goes from 14 hours to zero. Makespan goes from 16 h 5 min to 7 h. Lots at risk go from one to zero."

Point at the left chart. "The red line is now. The hatch is the scanner down until the repair. 1001 sits on LITHO-02 and finishes late."

Point at the right chart. "The same lot is outlined because it moved, onto LITHO-01, behind the lot already running. The legend is priority, not a new color per lot. Hover a bar if you need the clock times."

### 1:20–1:40 — Why it is allowed (Innovation, Track 03)

Stay on **Why the critic committed this**.

"The critic accepted the schedule. The refused alternative was starting LOT-1001 on LITHO-02 immediately. The solver commits. The model does not."

### 1:40–2:05 — A decision that refuses a fake win (Innovation)

Click **Rush order**. Watch the loop once, shorter if you are tight on time. Then the headline.

"A hot lot is due in 3 hours. LOT-2001 finishes 15 minutes late. On-time delivery falls to 85.7 percent. Weighted tardiness rises by 2 hours. Pulling a running lot off its tool was refused."

### 2:05–2:30 — The stockout (Sponsor tech)

Click **Material shortage**. RESIST-UV flashes. After the loop:

"On-hand is zero. Two lots wait. On-time delivery falls to 66.7 percent. Weighted tardiness rises to 12 days, which is the hold, not a silent zero. Starting lithography without the resist was refused. Those rows are the materials table Zetaris serves."

### 2:30–2:55 — The sponsor stack (Sponsor tech)

Back on machine breakdown if you need the contract line again. Point at the Nightshift node and the explainer line `mock · resilimes-mock`.

"Live, that SQL is a Zetaris call, and that explainer line is Meterless Nightshift calling NVIDIA Nemotron. Scout Intent is the engine. The test that proves the signature, the expiry, the injection block, and the trigger scan is `tests/test_scout_engine.py`. The stream itself is `tests/test_stream.py`. World Model stores the assignments. Markovian keeps each chunk on a checkpoint."

If you have the live clip, cut it here for five seconds: the JSON `provider` and `model` fields, token not visible.

### 2:55–3:20 — Close (Impact, Demo)

"The supervisor gets a schedule they can defend: what moved, what was refused, and the due-date delta in hours, not a raw minute count. Next we point the same loop at the plant's Zetaris tables and the team's Nightshift token. The banner already says which path you are on."

Stop. Do not add a chatbot ending.

## Judging map

| Criterion | Where it is on screen |
| --- | --- |
| Impact 30 | Idle problem, headline, KPI strip, the close |
| Technical 20 | Agent row filling from the stream, contract, SQL, critic |
| Innovation 15 | Solver commits, model explains; rush refuses preemption |
| Demo 15 | Lamp, then the loop, then three disruptions with readable durations |
| Product & UX 10 | Headline and three bullets, legend, before/after chart, language toggle, truthful banner |
| Sponsor tech 10 | Zetaris node, Scout contract, Nightshift line or the live cut |

## If something looks different

The numbers above are from the sample data and the 600-minute repair overlay. If you edit `data/sample` or the scenario clock, re-run `python -m resilimes recover --scenario litho_down` and update the spoken figures before you film. Do not quote numbers you did not just see.
