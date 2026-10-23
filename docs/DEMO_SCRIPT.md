# Demo script

Target length: 3 minutes. Film the console full screen. Hide `.env`. Do not read a token aloud.

The default console is the SMT2020 LV/HM fab. The six-lot bay is `make demo-bay` and is not this recording. The figures in [SMT2020_SCALE.md](SMT2020_SCALE.md) are five-seed, 48-hour means. A click on this page is one seed and 12 hours, so read the cards on screen. Do not quote the 48-hour table as if it were this click.

## Before you hit record

```bash
make demo
```

Open http://127.0.0.1:8000. The banner must say `data source: smt2020` and list 106 groups, 1,313 tools, 102 litho tools, and 2,156 lots. The rail is station groups, not a six-tool bay.

Optional, only if the local Zetaris platform is already up (UI `localhost:3000`, API `localhost:8888`):

```bash
wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh
```

That loads Postgres and registers `resilimes`, `fab_cmms`, and `fab_erp`. The console you are filming still reads `data/smt2020`. Say that if you show the Zetaris window. Do not claim the Gantt came from a live SQL call.

Optional second clip, only with a Nightshift token, on the sample bay so one real request id is on screen:

```bash
make demo-bay
```

Mask the key. The full-fab book does not call Nightshift.

## Shot list

### 0:00–0:25 — The fab

On the idle page, point at the banner and the Litho row in the rail.

"This is the SMT2020 LV/HM fab. One hundred six tool families, one thousand three hundred thirteen tools, one hundred two lithography tools, two thousand one hundred fifty-six lots in process. The data source on the banner is the SMT2020 extract."

### 0:25–1:20 — Lithography breakdown

Press **Run** on **Lithography breakdown**. Stay on Recover.

"Litho_FE_92-1 is an expose scanner in Litho_FE_92, the largest scanner family. It is down for the published repair, seven hundred five point five nine minutes. Scout signs the contract before the dispatcher runs. The other scanners in that family take the work. The line under the headline is the knock-on: sibling starts, the queue on that family, and the queue downstream."

Hover the Scout step. Point at the query line. It names the extract files.

Open the Litho group in the rail. The Gantt rows are station families. Set the window to the first twelve hours if it is not already. Click `Litho_FE_92` to drill into the tools. Scroll the list. It only draws the rows in view.

"The left chart is EDD. The right chart is ResiliMES. Same breakdown draw. The hatch of work is only the families in view, and only the minutes in the window."

### 1:20–2:05 — The numbers on this click

Read the six cards from the screen. Then one sentence from the study, labeled as the study:

"On-time, weighted tardiness, cycle time, lithography utilization, queue-time violations, and PM interruptions avoided are on these cards. They are this twelve-hour seed. The five-seed, forty-eight-hour study is separate. There, ResiliMES and EDD both finish fifty-seven point one four percent of the fifty-six lots that are due inside the horizon. Ten of those lots are already late at the snapshot. FIFO is about twenty-five percent. ResiliMES does not win every column. Weighted tardiness is a bit higher than EDD and much lower than FIFO."

### 2:05–2:35 — Hot lot, then PM

Press **Run** on **Hot lot**.

"Init_Lot_10_11 is a real normal lot, four steps before a scanner. ResiliMES raises it to VIP with a twelve-hour due. FIFO keeps the published priority. The line under the headline is how many steps that lot completed on each book."

Press **Run** on **PM avoidance**.

"The published weekly PM on Litho_FE_92 opens about seven days out, so a two-day window would never see it. This scenario shifts every day-based calendar by the same offset. The duration stays six point six five hours. ResiliMES will not start a lot that would run across that window. EDD will. The card is the count."

### 2:35–3:00 — Scout, and Nightshift if you have the token

"Scout Intent is the engine in front of the run. The test is tests/test_scout_engine.py. The schedule itself is the dispatcher, not the model."

If you recorded the sample-bay live call, cut it here for ten seconds. Nightshift console on `http://127.0.0.1:8088`, and the request id in the sample console. The model id is `nvidia/nemotron-3.5-lightning-30b-a3b`. The key stays off screen.

"Nightshift is the only model provider. The base URL is the local proxy on port 8088. NVIDIA Nemotron writes the note on that path. It does not place the lots."

Stop.
