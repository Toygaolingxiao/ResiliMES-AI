# Zetaris on the owner's machine

Verified 2026-10-24 against the local bundle. The app never opens JDBC. It sends
`Authorization: Bearer <apiKey>` and `X-Org-ID` to the REST SQL endpoint.
`X-Org-ID` is required. `X-API-Key` alone is rejected.

| Piece | Value |
| --- | --- |
| REST | `http://127.0.0.1:8888/api/v1.0` |
| SQL | `POST /sql-editor/sqls/run-query` body `{"sql": "..."}` |
| UI | `http://localhost:3000` (`POST /api/auth/login`, proxy `/api/proxy/<path>`) |
| Org | `1` |
| Postgres | container `fab-mes`, host `127.0.0.1:5433`, network `fab-net` |
| Driver | `zetaris-driver-1` joined to `fab-net` |

A 200 body is `{headers, data, total, timeUsed}`. Every cell is a string. A 400
body is `{msg}`. `/sql-editor/sqls/run` accepts the same JSON.

## Datasources

Postgres has three databases. Each one has schema `resilimes`. Zetaris registers
one datasource per database. The `schema` JDBC option is required; without it
only `public` is visible. Tables are addressed as `<datasource>.<table>`.

| Database | Datasource | Tables |
| --- | --- | --- |
| `fab_mes` | `resilimes` | equipment, inhibit, operators, products, qtime_rule, reticle, route, route_steps, wip_jobs, lots, operations, setup_matrix, smt_tool, smt_wip, smt_part, smt_route, smt_setup, smt_setupgrp, smt_fromto, smt_files, smt_columns |
| `fab_cmms` | `fab_cmms` | maintenance_logs, pm_calendar, smt_pmcal, smt_attach, smt_downcal |
| `fab_erp` | `fab_erp` | bom, materials, orders, smt_order |

The `smt_*` tables are the SMT2020 fab (next section).

`CREATE DATASOURCE` is sent through `run-query`. `DESCRIBE BY` allows only
`[A-Za-z0-9_.,-]`, so the description is `fab_mes.resilimes` and the JDBC user
and password are alphanumeric. `REGISTER DATASOURCE TABLES FROM <name>` follows.
`DROP DATASOURCE VIEW` also unregisters a table of the same name, so this
recipe never creates those views. A cross-datasource view fails with
`NoSuchElementException`. The client keeps a per-table source map instead.

Defaults, overridable with `ZETARIS_TABLE_SOURCES`:

```
maintenance_logs=fab_cmms,bom=fab_erp,materials=fab_erp
```

`pm_calendar` uses `fab_cmms` and `orders` uses `fab_erp` on the kernel reads.
Every other table uses `ZETARIS_SCHEMA` (datasource `resilimes`).

## SMT2020 master data

The full SMT2020 fab (`data/smt2020`, 106 families, 1313 tools, 2156 WIP lots)
is in Zetaris as raw tables, one per file, every cell `TEXT` exactly as in the
file. `line_no` (1-based data row) keeps file order; `smt_route` holds the ten
route files with a `route_file` column. Tables sit in the datasource of the
system that would own them in a fab.

| Datasource | Table | File(s) | Rows |
| --- | --- | --- | ---: |
| `resilimes` (MES) | `smt_tool` | `tool.txt.1l` | 106 |
| `resilimes` (MES) | `smt_wip` | `WIP.txt` | 2156 |
| `resilimes` (MES) | `smt_part` | `part.txt` | 10 |
| `resilimes` (MES) | `smt_route` | `route_1.txt` … `route_10.txt` | 4013 |
| `resilimes` (MES) | `smt_setup` | `setup.txt` | 13 |
| `resilimes` (MES) | `smt_setupgrp` | `setupgrp.txt` | 9 |
| `resilimes` (MES) | `smt_fromto` | `fromto.txt` | 1 |
| `fab_cmms` (CMMS) | `smt_pmcal` | `pmcal.txt` | 292 |
| `fab_cmms` (CMMS) | `smt_attach` | `attach.txt` | 303 |
| `fab_cmms` (CMMS) | `smt_downcal` | `downcal.txt` | 11 |
| `fab_erp` (ERP) | `smt_order` | `order.txt` | 21 |
| `resilimes` | `smt_files` | catalog: file → table, row count, sha256 | 20 |
| `resilimes` | `smt_columns` | catalog: column → original header, position | |

Column names are the headers lower-cased, `#` → `_no`, other symbols → `_`,
and a `_col` suffix on SQL keywords (`DESC` → `desc_col`, `STEP` → `step_col`,
`RPT#` → `rpt_no`). `smt_columns` maps them back.

`data/sql/smt2020_seed.sql` is generated (about 1.2 MB):

```bash
python scripts/export_smt2020_sql.py
```

A test fails if the committed seed differs from the files.

### Which source the app uses

`RESILIMES_SMT_SOURCE` picks where `load_fab` reads the fab from:

| Value | Behaviour | Label in the API |
| --- | --- | --- |
| `auto` (default) | Zetaris when it is configured and `RESILIMES_MODE` is not `mock`; otherwise files. A failed Zetaris read falls back to the files, retried after 60 s. | `SMT2020 via Zetaris`, or `SMT2020 local extract (Zetaris read failed, file fallback)` |
| `zetaris` | Zetaris only. A failed read raises; `/api/scenarios` returns 503. | `SMT2020 via Zetaris` |
| `file` | `data/smt2020` only. | `SMT2020 local extract (data/smt2020)` |

The read is 13 `SELECT`s (two catalog reads, then one per table, each
`ORDER BY line_no LIMIT 100000`, body `limit` 100000). The fab is cached for
the process after the first good read. The source is in `/api/health`
(`smt_source`), `/api/scenarios` (`smt_source`), every SMT run (`smt_source`,
`mode.master_data`) and the "Full fab" step of the run trace.

The fab built from Zetaris is the same as the one built from the files: same
`fab_digest`, so the simulation and every number on the console are unchanged.
In mock mode (or with no Zetaris settings) nothing is queried and the fab is
the same object as before.

### Load and verify from the Windows PC

```bash
wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh
```

loads `data/sql/seed.sql` and `data/sql/smt2020_seed.sql` (and `kernel.sql`).
Seeds can be listed explicitly:

```bash
wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh data/sql/seed.sql data/sql/smt2020_seed.sql
```

Then, from the repository with the app's Python and `.env`:

```bash
python scripts/check_zetaris_smt.py
```

or inside WSL (needs `pydantic`, `python-dotenv`, `requests` there):

```bash
wsl -d Ubuntu -- bash -lc "cd /mnt/c/code/ResiliMES-AI && python3 scripts/check_zetaris_smt.py"
```

It prints per-table row counts and row hashes through Zetaris next to the local
files, the fab digest both ways, and `PARITY OK` (exit 0) or `PARITY FAIL`
(exit 1). Exit 2 means Zetaris is not configured. It never prints the URL, org
id or key. Expected:

```
table          datasource  zetaris    files  row hash          ok
smt_tool       resilimes       106      106  7c429434294d7d36  yes
smt_wip        resilimes      2156     2156  6e8ca728405e5921  yes
smt_part       resilimes        10       10  e3abdb584b1ad39b  yes
smt_route      resilimes      4013     4013  f0eb34df662b9c13  yes
smt_setup      resilimes        13       13  02fdcd255c2714ed  yes
smt_setupgrp   resilimes         9        9  d67edb4e3b940648  yes
smt_fromto     resilimes         1        1  cddc90a0a533c565  yes
smt_pmcal      fab_cmms        292      292  4a4f5cd336c76d0a  yes
smt_attach     fab_cmms        303      303  6b0132f18f7ec301  yes
smt_downcal    fab_cmms         11       11  8492fe19b08e4db4  yes
smt_order      fab_erp          21       21  9359cade2db2cfb7  yes
total                         6935     6935
rows hash   zetaris 414b041fb0b40a9a  files 414b041fb0b40a9a
fab digest  zetaris 539b166cfb2b0e53  files 539b166cfb2b0e53
queries 13
PARITY OK
```

Then start the app with `RESILIMES_SMT_SOURCE=zetaris` (strict) or `auto`
and check `GET /api/health` → `smt_source.label`.

### Limits

This was built and tested against a fake Zetaris (SQLite serving the same
seed through the same REST shape), not the live bundle. Guarded quirks:
headers are lower-cased and cells are strings (a `null` becomes `""`);
column names avoid Spark/Postgres keywords; rows are re-sorted client-side by
`line_no`; a reply with fewer rows than `total`, or line numbers that are not
exactly `1..row_count` from `smt_files`, is an error rather than a short fab.
If the live editor caps rows below 4013 despite the body `limit`, `smt_route`
fails loudly and `auto` falls back to files with the fallback label.

## One-command reload

From Windows:

```bash
wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh [seed.sql ...]
```

With no argument it loads `data/sql/seed.sql` and `data/sql/smt2020_seed.sql`.
Arguments replace that list (paths may be relative to the repository).
`data/sql/kernel.sql` is loaded as well when that file is present. The script
is idempotent: every run rebuilds schema `resilimes` in all three databases from
exactly the seeds given, so list every seed you want to keep.

1. Create or start Docker network `fab-net` and container `fab-mes`
   (`postgres:16-alpine`, `127.0.0.1:5433`).
2. Attach `zetaris-driver-1` when that container exists.
3. Write `~/.config/fab-mes/env` once (`POSTGRES_USER`, `POSTGRES_PASSWORD`,
   mode `0600`). A later run reuses it. If the container already exists and
   the file is missing, the script stops instead of inventing a password.
4. Read `ZETARIS_ADMIN_EMAIL` and `ZETARIS_ADMIN_PASSWORD` from
   `~/zetaris-platform/.env`.
5. Split the SQL by table. Each database file starts with
   `DROP SCHEMA IF EXISTS resilimes CASCADE` and then only that database's
   tables, so a reload does not leave another source's tables behind.
6. `DROP` / `CREATE` / `REGISTER` the three datasources. A missing datasource
   makes `DROP` return 400, which is ignored.
7. Login at `POST http://localhost:3000/api/auth/login`. The id token lasts
   about 900 seconds. Mint `POST /auth/api-key` with name `resilimes-ai` when
   `~/.config/fab-mes/api-key` is absent (mode `0600`). A user can hold three
   keys, so the file is reused.
8. `SELECT * FROM <datasource>.<table> LIMIT 1` for every table that was
   loaded, then the federated join below when the sample tables were loaded.

The script never prints the password, the admin password, the id token, or the
API key. Those strings are scrubbed from the registration log.

`scripts/load_zetaris.py` does not send SQL anymore. It prints this recipe.

## Federated check

Spark SQL, no casts:

```sql
SELECT e.equipment_id, m.log_id, w.job_id, b.material_id, mat.material_id AS stock_id
FROM resilimes.equipment e
JOIN fab_cmms.maintenance_logs m ON e.equipment_id = m.equipment_id
JOIN resilimes.wip_jobs w ON e.equipment_id = w.assigned_equipment
JOIN fab_erp.bom b ON w.product_id = b.product_id
JOIN fab_erp.materials mat ON b.material_id = mat.material_id
WHERE e.status = 'DOWN'
```

On the owner's loaded plant this returned 12 rows in 0.7–2.1 s. A fresh load of
`data/sql/seed.sql` is smaller: only LITHO-02 is `DOWN`, so the same join is
that tool's maintenance rows times its WIP times its BOM lines. The script
prints the probe row count. It does not expect 12.

`array_contains(split(...))` is valid Spark SQL on this bundle. The statements
the app sends are plain `SELECT`s with datasource-qualified names.

## App settings

```
ZETARIS_REST_URL=http://127.0.0.1:8888/api/v1.0
ZETARIS_SQL_PATH=/sql-editor/sqls/run-query
ZETARIS_ORG_ID=1
ZETARIS_SCHEMA=resilimes
ZETARIS_BASE_URL=http://localhost:3000
ZETARIS_API_KEY=
ZETARIS_TABLE_SOURCES=maintenance_logs=fab_cmms,bom=fab_erp,materials=fab_erp
ZETARIS_TIMEOUT_S=30
RESILIMES_SMT_SOURCE=auto
```

`/api/scenarios` and `/api/recover` return 503 when the warehouse read fails.
The plant `SELECT` list is still the original twelve tables, so a bundle
without the kernel tables can serve recovery. Kernel reads are separate.
