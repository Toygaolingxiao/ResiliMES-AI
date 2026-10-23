# Demo script

Target length: 3 minutes 30 seconds. Stay inside 1–4 minutes. Film the console full screen at 1920×1080. Hide `.env` and any token. A 12-character HMAC prefix in the console is not the runtime token.

Record the machine-breakdown path on `make demo` even if you also record one live call. The figures below are what mock mode produces for the sample fab. The console speaks scheduled lateness as hours: 784 minutes is 13 h 4 min, 288 minutes is 4 h 48 min. A held lot is not given a finish time, so a stockout does not become a day count.

The Recover tab is the filmed frame. Do not scroll it. Idle shows one empty state, not a row of Waiting cards. No scenario is marked active until you press Run.

## Before you hit record

```bash
make demo
```

Open http://127.0.0.1:8000. Do not click yet. The ground is flat gray, the cards are white, and indigo is only the accent. The amber banner must be visible in mock mode. The header is one line: ResiliMES, the tagline, and a version chip. Idle reads "Recovery for this shift". A six-lot story switches it to "Recovery for one bay". Scale switches it to "Recovery for a 36-tool fab". The version chip opens a one-line note about this layout. The bay lamps already show Running, Idle, Down, Maintenance, or In stock. Language can stay on English; switch to 中文 or 日本語 only if you want that sentence on camera, then switch back before the numbers.

Optional second clip, only if credentials are set: `python -m resilimes recover --scenario litho_down` and show `provider_call.provider` and `provider_call.model` while the token stays off screen.

## Shot list

### 0:00–0:18 — The user and the problem (Impact)

On the idle Recover tab:

"This is for the supervisor on a lithography bay. LOT-1001 is priority 1, blocked on a scanner that just faulted, due 18:00 UTC. Waiting out a 10-hour repair misses it."

Point at the scenario clock: 22 Oct 2026 06:30 UTC. Point at LITHO-02 already reading Down.

### 0:18–0:45 — The disruption and the loop (Demo, Product & UX, Technical)

Press **Run** on **Machine breakdown**. That row is the only one that turns active. LITHO-02's lamp flashes red. The headline is the incident sentence, not a generic "Reading the line." A slim stepper and a thin percent bar fill under it: Scout, Zetaris, Sense, Plan, Critic, Nightshift, Commit. The running station is indigo. Hover a station for its output and its compute time in milliseconds. Each station is a real event from `POST /api/recover/stream`, held about 680 ms so it can be read. The millisecond is compute time, not the hold.

"Scout classifies it and signs a contract. Zetaris, or the sample twin with the same SQL, is the read. The solver builds both books. The critic checks the move. Nemotron turns a sentence into a tool call and writes the note. The world model commits."

### 0:45–1:25 — The decision (Impact, Demo)

When the headline lands, stay on Recover. Read the sentence, then the refusal under it, then the three cards, then both charts. Everything is above the fold.

"LOT-1001 leaves LITHO-02. The refused move was starting that lot on LITHO-02 at time zero. The tool is down until minute 600. On-time delivery goes from 83.3 percent to 100. Weighted tardiness goes from 12 hours 24 minutes to zero. Lots at risk go from one to zero. The badge on the chart row says the list scheduler is within 0% of optimal, proved."

The `?` on a card states the formula. **Details** opens Analyze. Do not click it yet.

Point at the left chart. "The red line is now. The red hatch is the scanner down until the repair. Bar color is the area: indigo lithography, cyan etch, violet CMP, teal deposition, amber metrology, blue clean. 1001 sits on LITHO-02 and finishes late."

Point at the right chart. "The outlined bar is a lot whose tool changed. LOT-1001 moves onto LITHO-01. That is the only move. Deposition, measure, etch, clean, and CMP stay on the tools they already had."

Click By lot, then click the LOT-1001 bar. "Each row is one lot. The gap between steps is the wait, and the popover is that lot's route." Switch back to By tool before the next shot.

Leave the theme on Light. Dark is the control next to the languages, for a second cut only.

### 1:25–1:45 — Why it is allowed (Innovation, Track 03)

Open **Verify**.

"The pill says accepted. Each row is one registered check. Tool calendar passed on the committed book. Open that row for the refused plan that started LOT-1001 on the down scanner. Reticle passes on the committed book: each physical copy is on one scanner. The spare L1 copy is free, so that refused plan is a down-tool miss. The solver commits. The model does not."

Back on **Recover**, hover Nightshift. In this recording the tip reads `mock · resilimes-mock`.

### 1:45–2:05 — The rest of the numbers (Product & UX)

Open **Analyze**. This is the only place that scrolls.

"Makespan goes from 14 h 17 min to 5 h 28 min. Mean lead time goes from 9 h 23 min to 3 h 30 min. Mean wait between steps goes from 2 h 3 min to 24 min. X-factor goes from 4.47 to 1.99. Utilization stays 11.6 percent, gray on purpose. Both books share one window, the longer makespan, 14 h 17 min. LITHO-02 is down 10 hours. That time is listed under the figures and is not in the denominator. DEP-01 is up. Its morning PM is already finished."

The area card has Before and After. The area percents stay flat: Lithography 19.7, Etch 10.8, CMP 13.0, Deposition 10.3, Metrology 7.0, Clean 7.0. The wait card's top row is deposition into etch, about 11 h 32 min while waiting and 2 h 37 min after. The lot table shows LOT-1001 as LITHO, LITHO-02 to LITHO-01. The queue-time card is 100 percent both ways. The bottleneck card names Lithography. The tool labels on that area carry a small mark.

Return to **Recover** before the next disruption.

### 2:05–2:25 — A decision that refuses a fake win (Innovation)

Press **Run** on **Rush order**. After the stepper:

"LOT-2001 finishes 36 minutes late. The dashed tick on the after chart is its due, three hours out. LOT-1002 keeps RET-A28-L1-1 on LITHO-01. The hot lot takes the spare copy, RET-A28-L1-2, on LITHO-02 and finishes at 3 h 36 min. On-time delivery falls from 100 to 85.7 percent. Weighted tardiness rises by 4 h 48 min. Lots at risk go from zero to one. Pulling a running lot off its tool was refused: LOT-1002 is already running on LITHO-01. Hover a lithography bar for the copy id. LOT-2001 is a new lot, so it is not in Lots moved."

Hover Scout on the stepper if you want the confidence. The canned rush sentence clears 92 percent.

### 2:25–2:50 — The stockout (Sponsor tech)

Press **Run** on **Material shortage**. RESIST-UV flashes. After the loop, still on Recover:

"Two lots wait on RESIST-UV. On-time delivery falls to 66.7 percent. Lots at risk go from zero to two. Weighted tardiness stays flat: the held lots are blocked until the resist is replenished, and the model does not assume a delivery time. The after chart marks those lots held. Starting lithography without the resist was refused."

Open Analyze and point at the gray rows. "Makespan, mean lead time, X-factor, and changeovers look shorter only because held lots left the book. They stay gray. The note says they are not a win. The lot that moved is LOT-1002."

### 2:50–3:05 — The sponsor stack (Sponsor tech)

Back on Recover for machine breakdown if you need the contract line again. In mock mode the stepper says Plant read and Explainer. Hover them.

"Live, those two nodes are named Zetaris and Nightshift: the SQL is a Zetaris call, and Nightshift calls NVIDIA Nemotron. This recording is the offline twin, and the banner says so. Scout Intent is the engine. The test that proves the signature, the expiry, the injection block, and the trigger scan is `tests/test_scout_engine.py`. The stream itself is `tests/test_stream.py`. World Model stores the assignments and replays the jobs. Markovian keeps each chunk on a checkpoint."

If you have the live clip, cut it here for five seconds: the JSON `provider` and `model` fields, token not visible.

### 3:05–3:15 — Scale, ten seconds

Press **Run** on **Scale**. Stay on Recover. Do not scroll. This frame is a tool strip, not a lot Gantt.

"A thousand lots, 36 tools, one scanner down. The left strip is EDD dispatch: it already meets every due date, and the 24 priority-1 lots are on scanners that are up. Priority recovery matches on-time delivery, weighted tardiness, and lots at risk. All three stay at 100%, zero, and zero. The hatch is the down scanner. Schedule and critic, under a second. The badge says no improvement, heuristic kept. The three cards stay on the list schedule."

Point at the chart title "vs. EDD dispatch". Point at the stat line: schedule, critic, 1,000 lots, 36 tools, 3,426 steps, 14 passed. The three cards are flat. The strip is the first 12 hours. CMP stays the bottleneck, about 84.7%. The refused line names LITHO-03 down until minute 600.

### 3:15–3:30 — Close (Impact, Demo)

"The supervisor gets a schedule they can defend: what moved, what was refused, and the due-date delta in hours, not a raw minute count. Next we point the same loop at the plant's Zetaris tables and the team's Nightshift token. The banner already says which path you are on."

Stop. Do not add a chatbot ending.

### Optional — Rework, only if the cut is still under four minutes

Press **Run** on **Overlay rework**. Stay on Recover.

"LOT-1004 re-measures after overlay. The measure failed, so the book strips on the wet bench, re-exposes once, and measures again. The limit is one. The striped bar is the re-measure. On-time delivery stays 100 percent. Makespan grows from 5 h 28 min to 7 h 19 min. The badge says weighted tardiness matches optimal and the reference makespan is 36 minutes shorter. Analyze lists the steps that differ. The committed chart stays the list schedule."

Open **Verify** only if you also want the queue-time row. That row is the next preset, not this one.

### Optional — Queue time, still inside four minutes

Press **Run** on **Queue time**.

"LOT-1003 misses the clean queue time. Clean finished before 06:30, and the next film had 15 minutes. The book holds LOT-1003. On-time delivery goes from 100 to 83.3 percent. That hold is not given a finish time, so weighted tardiness stays flat. Lots at risk stay at zero because this lot is priority 3. The after chart marks the lot held. The refused plan started deposition at minute 120."

On **Verify**, queue time passed on the committed book. Open the row for the refused plan that started the cap film after the window. On **Analyze**, compliance goes from 100 percent to 50, with one hold.

## Judging map

| Criterion | Where it is on screen |
| --- | --- |
| Impact 30 | Idle problem, Recover headline, three numbers, both charts, the close |
| Technical 20 | Stepper filling from the stream, contract on hover, critic table on Verify |
| Innovation 15 | Solver commits, model writes the note; rush refuses preemption; shortage stays gray |
| Demo 15 | Lamp, then the stepper, then three disruptions with readable durations |
| Product & UX 10 | Empty state, three cards, Analyze and Verify, by-lot toggle, language and theme, truthful banner |
| Sponsor tech 10 | Zetaris hover, Scout contract, Nightshift line or the live cut |

## If something looks different

The numbers above are from the sample data and the 600-minute repair overlay. If you edit `data/sample` or the scenario clock, re-run `python -m resilimes recover --scenario litho_down` and update the spoken figures before you film. Do not quote numbers you did not just see.
