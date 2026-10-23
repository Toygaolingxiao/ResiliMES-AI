# Demo script

Target length: 2:45–3:15. English narration. Film the console full screen. Hide `.env`. Do not read a token aloud.

This recording is the live path on the public industry benchmark (SMT2020). `make demo` forces mock mode and is not this shot. The six-lot bay is `make demo-bay` and is not this shot either.

The sample-bay weighted tardiness of 784 minutes is 13 hours 4 minutes. This film does not use that number.

## Before you hit record

Put the Nightshift runtime token and the Zetaris API key, org id, and REST URL in `.env`. Mask the file. Then:

```bash
make demo-live
```

That target sets `RESILIMES_MODE=auto` and `RESILIMES_FAB=smt2020`. With both credentials present, the console calls Zetaris and Nightshift. Open http://127.0.0.1:8000.

Do not start recording until all of these are true:

- The badge says `NIGHTSHIFT`, not a mock label.
- The banner says `public industry benchmark (SMT2020)` and lists 106 groups, 1,313 tools, 102 litho tools, and 2,156 lots.
- A rehearsal Run shows `Zetaris` on the query line, names `resilimes`, `fab_cmms`, and `fab_erp`, and shows row counts. If it says `local extract (Zetaris not called)`, stop. That is not this film. Reload the page before the count-in so the recording starts on the idle console.

Mock mode inserts a 680 ms pause after each stepper event so a viewer can read the rail. `make demo-live` with a Nightshift token sets that pause to 0. This recording uses the 0 ms pace. The 680 ms delay is not part of the dispatcher.

If the local Zetaris platform is not loaded yet (UI `localhost:3000`, API `localhost:8888`):

```bash
wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh
```

That registers datasources `resilimes`, `fab_cmms`, and `fab_erp` and loads the kernel tables. The query line is the live `SELECT COUNT(*)` against those datasources. The dispatcher still runs in process on the same benchmark files. Say that. Do not say the Gantt was streamed row by row from SQL.

## Shot list

### 0:00–0:25 — The loss

Idle page. Point at the banner, then at **Tight VIP dues**. Do not press Run yet.

"Dielectric_BE_28-1 is down for the published dielectric repair, six hundred four point eight minutes. Eight VIP lots in that queue are due in eight hours. Thirteen normal lots in the same queue are due forty-eight minutes sooner, so earliest-due serves them first. One of the VIP lots, Init_Lot_2_23, finishes five point four three hours late on that rule."

### 0:25–0:55 — The live read

Press **Run** on **Tight VIP dues**. When the Zetaris node lights, point at the query line under the banner. Leave it on screen.

"This is a live Zetaris read. The SQL is five count queries. The sources are resilimes, fab_cmms, and fab_erp. The row counts are on this line. The banner is the public industry benchmark, SMT2020. One hundred six families, one thousand three hundred thirteen tools, two thousand one hundred fifty-six lots."

### 0:55–1:25 — The critic

Stay on the refusal line. Do not move on until the lot id and the tool are visible.

"The critic rejects a start of Init_Lot_1_3 on Dielectric_BE_28-1. The tool is down. That plan does not get a slot. The lots that run are placed by the dispatcher, on the two tools in that family that are up."

### 1:25–2:05 — The cards

Read the on-time, weighted tardiness, and queue-time cards from the screen. They are seed 1 and 24 hours. Then one sentence from the study:

"On this seed, earliest-due is fourteen point two nine percent on time and seven thousand six hundred seventy-nine minutes of weighted tardiness. ResiliMES is nineteen point zero five percent and four thousand forty-four minutes. Queue-time violations fall from four hundred fifteen to one hundred eighty-seven. Init_Lot_2_23 is five point four three hours late under earliest-due and on time here. Those thirteen normal lots give up thirty-one point seven hours in total. Across five seeds the means are nineteen point zero five percent against twelve point three eight, and four thousand three hundred twenty-nine minutes against seven thousand nine hundred eighty-six. FIFO is zero percent on time. Critical ratio is nine point five two. On the X-factor book, earliest-due is slightly ahead. That book is not this shot."

### 2:05–2:35 — The same fab, one scanner

Press **Run** on **Lithography breakdown**. Point at the refusal line, then open the Litho group.

"Same benchmark, different incident. Litho_FE_92-1, an expose scanner, is down for the published lithography repair, seven hundred five point five nine minutes. The critic blocks a lot on that scanner. The other tools in Litho_FE_92 take the work. The Gantt draws the group and the time window in view."

### 2:35–3:05 — Nightshift

Hover the Nightshift step. The request id has to be on screen. The model id is `nvidia/nemotron-3.5-lightning-30b-a3b`. The base URL is `http://127.0.0.1:8088/v1`.

"Nightshift is the only model provider. NVIDIA Nemotron writes this one sentence. It does not place the lots. The schedule was already fixed when the request went out. The key stays off screen."

Stop. Aim to cut before 3:15.
