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
| `fab_mes` | `resilimes` | equipment, inhibit, operators, products, qtime_rule, reticle, route, route_steps, wip_jobs, lots, operations, setup_matrix |
| `fab_cmms` | `fab_cmms` | maintenance_logs, pm_calendar |
| `fab_erp` | `fab_erp` | bom, materials, orders |

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

## One-command reload

From Windows:

```bash
wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh
```

An optional argument replaces `data/sql/seed.sql`. `data/sql/kernel.sql` is
loaded as well when that file is present. The script is idempotent.

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
8. `SELECT * FROM <datasource>.<table> LIMIT 1` for every table, then the
   federated join below.

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
```

`/api/scenarios` and `/api/recover` return 503 when the warehouse read fails.
The plant `SELECT` list is still the original twelve tables, so a bundle
without the kernel tables can serve recovery. Kernel reads are separate.
