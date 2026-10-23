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

That registers datasources `resilimes`, `fab_cmms`, and `fab_erp` and loads the kernel tables.

What the film may claim, and what it may not:

- Zetaris, when the key, org id, and REST URL are set: five `SELECT COUNT(*)` queries, plus `SELECT station_group_id, from_recipe, to_recipe, setup_time_sec FROM resilimes.setup_matrix`. Rows that match a station family and a recipe replace those setup seconds for this run. `zetaris.called` is true. Routes, WIP, dues, breakdowns, and the PM calendar still load from the local extract. The dispatcher does not issue a SQL query per lot. If the setup query fails, `called` stays true, the error is on the query line, and the run keeps the local setup matrix.
- Zetaris, when those credentials are absent (`make demo`, or `auto` with an empty key): `zetaris.called` is false. The query line says the local extract was used. Do not read a row count off that line as a live result.
- Nightshift, when `METERLESS_RUNTIME_TOKEN` is set: one completion after the schedule is already fixed. The model writes that sentence. It does not place lots, choose tools, or change dues. A request id is on screen only when that completion returns one. This repository has not recorded one.
- Nightshift, when the token is absent: the explainer is the mock narrative. The badge is not `NIGHTSHIFT`. There is no request id. Scout stays on the mock profile. `RESILIMES_MODE=live` selects the Nightshift Scout profile and raises if the token or the Zetaris key is missing. `make demo` forces mock and does not call either service.

Say that. Do not say the Gantt was streamed row by row from SQL.

## Shot list

### 0:00–0:35 — The trade

Idle page. Point at the banner, then at **X-factor dues**. Do not press Run yet. Do not open Tight VIP dues first.

"This click is seed one. Eighty-seven lots, forty-eight hours. Both rules are eighty-seven of eighty-seven on time. Re-cleans go from twenty-four under earliest-due to thirty-one. Queue-time violations go from four hundred twenty-eight to four hundred eighteen. The five-seed mean is a different line: re-cleans thirty-eight against fifty-five point six, queue-time four hundred thirty against four hundred fifty-one point six. On that mean, ResiliMES gives up about two of eighty-seven lots to earliest-due, and it beats FIFO and critical ratio. On-time on the mean does not move if the repair is three hours, five hours, ten hours, or the published lithography repair."

### 0:35–1:05 — The live read

Press **Run** on **X-factor dues**. When the Zetaris node lights, point at the query line under the banner. Leave it on screen.

"This is a live Zetaris read. The SQL is five count queries plus the setup matrix. Matching setup seconds replace the local matrix for this run. Routes, WIP, and dues still come from the local extract. The dispatcher does not read SQL per lot. The sources are resilimes, fab_cmms, and fab_erp. The banner is the public industry benchmark, SMT2020. One hundred six families, one thousand three hundred thirteen tools, two thousand one hundred fifty-six lots. The clock is the 2018-01-01 snapshot."

### 1:05–1:35 — What the cards are

Read re-cleans, Q-time, weighted tardiness, and on-time with the denominator. Then one sentence on the other two books.

"Read the cards. Seed one is eighty-seven of eighty-seven under both rules, re-cleans twenty-four to thirty-one, queue-time four hundred twenty-eight to four hundred eighteen. The line under the cards is the five-seed mean. That mean is not these cards. The nonempty-queue dispatch time is on the timing line. The headline p50 includes empty wakes. The published-due book is fifty-six lots, ten of them already late at the snapshot, so the maximum is forty-six of fifty-six. Earliest-due is slightly ahead there. The tight VIP button rewrites the dues for a stress test. It is a different book."

### 1:35–2:15 — The stress test, then the critic

Press **Run** on **Tight VIP dues**. Point at the refusal line once the lot id and the tool are visible. Open the Dielectric group and click `Dielectric_BE_28` so the three tools draw across the full day.

"These dues were rewritten. Twenty-one lots. Earliest-due is three of twenty-one on this seed, weighted tardiness seven thousand six hundred seventy-nine point four minutes. ResiliMES is four of twenty-one and four thousand forty-three point eight. Across five seeds that is twenty of one hundred five against thirteen of one hundred five. Init_Lot_2_23 is the save on this book. On the X-factor book, seeds five and six, that same lot is a loss. There is no refusal sentence on this click. The event trace has no start on the down tool, so refusal stays empty and the verdict stays accept."

### 2:15–2:40 — Twelve-hour lithography

Press **Run** on **Lithography breakdown**. Point at the study line under the cards.

"Same benchmark, twelve hours, seed one. Both policies are two of nineteen. That is a tie on this click. The five-seed lithography study is forty-eight hours and fifty-six lots, and earliest-due is slightly ahead there. The line under the cards is that study."

### 2:40–3:05 — Nightshift

Hover the Nightshift step. The request id has to be on screen. The model id is `nvidia/nemotron-3.5-lightning-30b-a3b`. The base URL is `http://127.0.0.1:8088/v1`.

"Nightshift writes this one sentence after the schedule is fixed. It does not place the lots. The key stays off screen. Without a token this step is the mock narrative and there is no request id."

Stop. Aim to cut before 3:15.
