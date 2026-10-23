# Demo script

Target length: 3 minutes 20 seconds. Stay inside 1–4 minutes. Film the console full screen at 1920×1080. Hide `.env` and any token. A 12-character HMAC prefix in the console is not the runtime token.

Record the machine-breakdown path on `make demo` even if you also record one live call. The figures below are what mock mode produces for the sample fab. The console speaks them as hours and days: 840 minutes is 14 h, 17280 minutes is 12 d, 120 minutes is 2 h.

The Recover tab is the filmed frame. Do not scroll it. Idle shows one empty state, not a row of Waiting cards. No scenario is marked active until you press Run.

## Before you hit record

```bash
make demo
```

Open http://127.0.0.1:8000. Do not click yet. The ground is flat gray, the cards are white, and indigo is only the accent. The amber banner must be visible in mock mode. The header is one line: ResiliMES, the tagline, and a version chip. The version chip opens a one-line note about this layout. The bay lamps already show Running, Idle, Down, Maintenance, or In stock. Language can stay on English; switch to 中文 or 日本語 only if you want that sentence on camera, then switch back before the numbers.

Optional second clip, only if credentials are set: `python -m resilimes recover --scenario litho_down` and show `provider_call.provider` and `provider_call.model` while the token stays off screen.

## Shot list

### 0:00–0:18 — The user and the problem (Impact)

On the idle Recover tab:

"This is for the supervisor on a lithography bay. LOT-1001 is priority 1, blocked on a scanner that just faulted, due 18:00 UTC. Waiting out a 10-hour repair misses it."

Point at the scenario clock: 22 Oct 2026 06:30 UTC. Point at LITHO-02 already reading Down.

### 0:18–0:45 — The disruption and the loop (Demo, Product & UX, Technical)

Press **Run** on **Machine breakdown**. That row is the only one that turns active. LITHO-02's lamp flashes red. The headline is the incident sentence, not a generic "Reading the line." A slim stepper and a thin percent bar fill under it: Scout, Zetaris, Sense, Plan, Critic, Nightshift, Commit. The running station is indigo. Hover a station for its output and its compute time in milliseconds. Each station is a real event from `POST /api/recover/stream`, held about 680 ms so it can be read. The millisecond is compute time, not the hold.

"Scout classifies it and signs a contract. Zetaris, or the sample twin with the same SQL, is the read. The solver builds both books. The critic checks the move. Nightshift only explains. The world model commits."

### 0:45–1:25 — The decision (Impact, Demo)

When the headline lands, stay on Recover. Read the sentence, then the refusal under it, then the three cards, then both charts. Everything is above the fold.

"LOT-1001 leaves LITHO-02. The refused move was starting that lot on LITHO-02 at time zero. The tool is down until minute 600. On-time delivery goes from 83.3 percent to 100. Weighted tardiness goes from 14 hours to zero. Lots at risk go from one to zero."

The `?` on a card states the formula. **Details** opens Analyze. Do not click it yet.

Point at the left chart. "The red line is now. The red hatch is the scanner down until the repair. Bar color is the area: indigo lithography, cyan etch, violet CMP, teal deposition. 1001 sits on LITHO-02 and finishes late."

Point at the right chart. "The outlined bar is a lot whose tool changed. LOT-1001 moves onto LITHO-01. LOT-1004 stays on LITHO-01 for lithography and moves its etch from ETCH-02 to ETCH-01. Both are in Lots moved, on Analyze."

Click By lot, then click the LOT-1001 bar. "Each row is one lot. The gap between steps is the wait, and the popover is that lot's route." Switch back to By tool before the next shot.

Leave the theme on Light. Dark is the control next to the languages, for a second cut only.

### 1:25–1:45 — Why it is allowed (Innovation, Track 03)

Open **Verify**.

"The pill says accepted. The table is one row per constraint. Equipment status is refused, because the alternative started LOT-1001 on a down scanner. The solver commits. The model does not."

Back on **Recover**, hover Nightshift. In this recording the tip reads `mock · resilimes-mock`.

### 1:45–2:05 — The rest of the numbers (Product & UX)

Open **Analyze**. This is the only place that scrolls.

"Makespan goes from 16 h 5 min to 7 h. Mean lead time goes from 12 h 18 min to 4 h 43 min. Mean wait between steps goes from 4 h 37 min to 44 min. X-factor goes from 7.94 to 3.26. Utilization stays 14.9 percent, gray on purpose. Both books share one window, the longer makespan, 16 h 5 min. LITHO-02 is down 10 hours and DEP-01 is in maintenance 4 hours. That time is listed under the figures and is not in the denominator."

The area card has Before and After. The area percents stay flat: Lithography 17.7, Etch 14.2, CMP 23.8, Deposition 0. The wait card shows etch into CMP, about 1 h 16 min on average. The lot table shows LOT-1004 as ETCH, ETCH-02 to ETCH-01. The queue-time card is 100 percent both ways, with one at-risk pair while waiting and none after. The bottleneck card names Lithography. The tool labels on that area carry a small mark.

Return to **Recover** before the next disruption.

### 2:05–2:25 — A decision that refuses a fake win (Innovation)

Press **Run** on **Rush order**. After the stepper:

"LOT-2001 finishes 15 minutes late. The dashed tick on the after chart is its due, three hours out. On-time delivery falls from 100 to 85.7 percent. Weighted tardiness rises by 2 hours. Lots at risk go from zero to one. Pulling a running lot off its tool was refused: LOT-1002 is already running on LITHO-01. LOT-2001 is a new lot, so it is not in Lots moved."

Hover Scout on the stepper if you want the confidence. The canned rush sentence clears 92 percent.

### 2:25–2:50 — The stockout (Sponsor tech)

Press **Run** on **Material shortage**. RESIST-UV flashes. After the loop, still on Recover:

"Two lots wait on RESIST-UV. On-time delivery falls to 66.7 percent. Weighted tardiness rises to 12 days, which is the hold, not a silent zero. Lots at risk go from zero to two. Starting lithography without the resist was refused."

Open Analyze and point at the gray rows. "Makespan, mean lead time, X-factor, and changeovers look shorter only because held lots left the book. They stay gray. The note says they are not a win. The lot that moved is LOT-1002."

### 2:50–3:05 — The sponsor stack (Sponsor tech)

Back on Recover for machine breakdown if you need the contract line again. Hover Zetaris and Nightshift.

"Live, that SQL is a Zetaris call, and that Nightshift tip is Meterless Nightshift calling NVIDIA Nemotron. Scout Intent is the engine. The test that proves the signature, the expiry, the injection block, and the trigger scan is `tests/test_scout_engine.py`. The stream itself is `tests/test_stream.py`. World Model stores the assignments. Markovian keeps each chunk on a checkpoint."

If you have the live clip, cut it here for five seconds: the JSON `provider` and `model` fields, token not visible.

### 3:05–3:20 — Close (Impact, Demo)

"The supervisor gets a schedule they can defend: what moved, what was refused, and the due-date delta in hours, not a raw minute count. Next we point the same loop at the plant's Zetaris tables and the team's Nightshift token. The banner already says which path you are on."

Stop. Do not add a chatbot ending.

### Optional — Rework, only if the cut is still under four minutes

Press **Run** on **Lithography rework**. Stay on Recover.

"LOT-1004 re-enters lithography. Overlay failed, so the book strips and re-exposes once. The limit is one. The striped bar is the re-expose. On-time delivery stays 100 percent. Lithography's share of the window rises."

Open **Verify** only if you also want the queue-time row. That row is the next preset, not this one.

### Optional — Queue time, still inside four minutes

Press **Run** on **Queue time**.

"LOT-1003 misses the etch queue time. Etch finished before 06:30, and CMP had 15 minutes. The book holds the lot. On-time delivery goes from 100 to 83.3 percent. Weighted tardiness goes from zero to 2 days. The refused plan started CMP at minute 120."

On **Verify**, the queue-time row says Refused. On **Analyze**, compliance goes from 100 percent to 80, with one hold.

## Judging map

| Criterion | Where it is on screen |
| --- | --- |
| Impact 30 | Idle problem, Recover headline, three numbers, both charts, the close |
| Technical 20 | Stepper filling from the stream, contract on hover, critic table on Verify |
| Innovation 15 | Solver commits, model explains; rush refuses preemption; shortage stays gray |
| Demo 15 | Lamp, then the stepper, then three disruptions with readable durations |
| Product & UX 10 | Empty state, three cards, Analyze and Verify, by-lot toggle, language and theme, truthful banner |
| Sponsor tech 10 | Zetaris hover, Scout contract, Nightshift line or the live cut |

## If something looks different

The numbers above are from the sample data and the 600-minute repair overlay. If you edit `data/sample` or the scenario clock, re-run `python -m resilimes recover --scenario litho_down` and update the spoken figures before you film. Do not quote numbers you did not just see.
