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

### 0:00–0:35 — The trade

Idle page. Point at the banner, then at **X-factor dues**. Do not press Run yet. Do not open Tight VIP dues first.

"This book keeps the published routes. Each due is remaining process time times two point seven five. Eighty-seven lots, forty-eight hours, five seeds. ResiliMES beats FIFO and critical ratio by a wide margin: about ninety-seven percent on time, against twenty-one and seventy-two. Against earliest-due it gives up about two of those eighty-seven lots. The misses are one seed at Diffusion_BE_123, three lots, and one seed mostly at Dielectric_BE_28. Re-cleans are thirty-eight against fifty-six. Queue-time violations are four hundred thirty against four hundred fifty-two. On-time does not move if the repair is three hours, five hours, ten hours, or the published lithography repair."

### 0:35–1:05 — The live read

Press **Run** on **X-factor dues**. When the Zetaris node lights, point at the query line under the banner. Leave it on screen.

"This is a live Zetaris read. The SQL is five count queries. The sources are resilimes, fab_cmms, and fab_erp. The row counts are on this line. The banner is the public industry benchmark, SMT2020. One hundred six families, one thousand three hundred thirteen tools, two thousand one hundred fifty-six lots. The clock is the 2018-01-01 snapshot."

### 1:05–1:35 — What the cards are

Read re-cleans, Q-time, weighted tardiness, and on-time with the denominator. Then one sentence on the other two books.

"Seed one is eighty-seven of eighty-seven under both rules, so nobody paid on this seed. The nonempty-queue dispatch time is on the timing line. The headline p50 includes empty wakes. The published-due book is fifty-six lots and earliest-due is slightly ahead, thirty-two of fifty-six against thirty-one on four of the five seeds. The tight VIP button rewrites the dues for a stress test. It is not this book."

### 1:35–2:15 — The stress test, then the critic

Press **Run** on **Tight VIP dues**. Point at the refusal line once the lot id and the tool are visible. Open the Dielectric group and click `Dielectric_BE_28` so the three tools draw across the full day.

"These dues were rewritten. Twenty-one lots. Earliest-due is three of twenty-one on this seed, weighted tardiness seven thousand six hundred seventy-nine point four minutes. ResiliMES is four of twenty-one and four thousand forty-three point eight. Across five seeds that is twenty of one hundred five against thirteen of one hundred five. Init_Lot_2_23 is the save on this book. On the X-factor book, seeds five and six, that same lot is a loss. The critic line is a safety check. The event loop did not select a start on the down tool."

### 2:15–2:40 — Twelve-hour lithography

Press **Run** on **Lithography breakdown**. Point at the study line under the cards.

"Same benchmark, twelve hours, seed one. Both policies are two of nineteen. That is a tie on this click. The five-seed lithography study is forty-eight hours and fifty-six lots, and earliest-due is slightly ahead there. The line under the cards is that study."

### 2:40–3:05 — Nightshift

Hover the Nightshift step. The request id has to be on screen. The model id is `nvidia/nemotron-3.5-lightning-30b-a3b`. The base URL is `http://127.0.0.1:8088/v1`.

"Nightshift is the only model provider. NVIDIA Nemotron writes this one sentence. It does not place the lots. The schedule was already fixed when the request went out. The key stays off screen."

Stop. Aim to cut before 3:15.
