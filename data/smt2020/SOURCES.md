# SMT2020 LV/HM

Kopp, Hassoun, Kalir, and Mönch, “SMT2020 — A Semiconductor Manufacturing Testbed,”
IEEE Transactions on Semiconductor Manufacturing, vol. 33, no. 4, 2020.
doi: [10.1109/TSM.2020.3001933](https://doi.org/10.1109/TSM.2020.3001933).

The paper says the dataset is open to public use. These files are the AutoSched
TSV export from PySCFabSim-release commit `0dbff6a`, directory
`datasets/SMT2020_LVHM`. `resilimes.data.smt2020_kernel` reads them and writes
`data/sql/kernel.sql`.

## What is copied

- `PTIME` is the published uniform mean, in minutes, converted to seconds.
  `per_piece` is multiplied by `PIECES` (25). `per_lot` is used as published.
  `per_batch` is the furnace cycle and is not divided by the lot size.
- `CQT` is the limit on the from-step. `route_1` records `CQTUNITS` as `hr`.
  Step 30 `034_Wet_Etch` (`WE_FE_84`) has `STEP_CQT` 31 and `CQT` 2 hours.
  Step 36 `041_Dry_Etch` (`DE_FE_71`) has `CQT` 1 hour targeting step 37
  `042_Wet_Etch`. There is no wet-to-dry limit in that pair.
- `setup.txt` wins over route `STIME`. `DE_BE_13_1` to `DE_BE_13_2` is 7 minutes
  (420 seconds). The group is the `IGNORE` column. A blank `CURSETUP` is stored
  as an empty from-recipe.
- `order.txt` `REPEAT` is the release interval. `RPT#` is not a demand count.
  `LOTSPERRPT` is 1 and `PIECES` is 25, so one release is 25 wafers.
  `PRIOR` 10 / 20 / 30 maps to normal / hot / VIP. The `HOTLOT` column is `no`
  on the hot orders and is not used.
- `pmcal.txt` joined to `attach.txt` where `CALTYPE` is `pm` and `MTBPMUNITS`
  is a time unit (`day` on this extract, 79 rows). First start is `FOA`.
  Interval is `MTBPM`. Duration is the `MTTR` mean, not a draw. The other 213
  calendars count `pieces` and are not a wall-clock window, so they are left
  out of `pm_calendar`. A blank `FOAUNITS` would be read as minutes.
- Scanner families are `STNFAM` values that start with `Litho_` and do not
  contain `Track`, `Met`, or `REG`. `STNQTY` is the published tool count.
- The snapshot clock for DPI is 2018-01-01. `ped_remaining_sec` is null because
  WIP has no step-start time.

## Derived, and labeled as derived

- `customer` is `derived:` plus the order id. There is no customer master.
- `margin_tier` is `unpriced`. SMT2020 has no price.
- `order_class` is derived from `PRIOR`.
- `dpi`, `late`, and `lot_value` are computed at the snapshot from the
  published mean process times. The provenance column on each generated row
  says so.

## Not loaded into these tables

`StepPercent`, `PartInterval`, `fromto` transport, `LTIME` / `ULTIME` (they are
not added to `PTIME`), fractional `REWORK`, WIP tool assignment (the file has
none), `MINRUN`, and the `Delay_32` station family.
MIMAC operator groups are not in this extract. `SVESTN` / `FORSTEP` are not
columns in the kernel SQL. The event simulator does read them: a later litho
layer stays on the scanner this run chose for the first layer of that chain.
