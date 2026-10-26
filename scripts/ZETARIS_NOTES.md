# Zetaris integration notes (local, uncommitted)

Verified 2026-10-24 (UTC+9) against the local bundle in WSL `~/zetaris-platform`.

## Endpoints (Windows host and WSL)
- UI:   http://localhost:3000            (Next.js; /api/auth/login, /api/proxy/<path> -> api:8888/api/v1.0/<path>)
- REST: http://127.0.0.1:8888/api/v1.0   (reachable from Windows; prefer this)
- JDBC/Thrift: 127.0.0.1:10000, driver com.zetaris.lightning.jdbc.LightningDriver,
  URL jdbc:zetaris:lightning@localhost:10000, jar ~/zetaris-platform/jdbc/ndp-jdbc-driver-2.4.3.1-7eff043-driver.jar (not needed: REST works)

## Auth
1. POST http://localhost:3000/api/auth/login  {"username": <ADMIN_EMAIL>, "password": <ADMIN_PASSWORD>}
   -> {"idToken": "<JWT, 900 s TTL>", "refreshToken": "...", "orgId": 1}
   Refresh: GET /api/v1.0/auth/refresh with Authorization: Bearer <refreshToken>, X-Org-ID.
2. Long-lived API key (what the app uses):
   POST /api/v1.0/auth/api-key {"name":"resilimes-ai","expiryDate":"2027-01-21T15:27:36.000Z"} -> {"apiKey":"ak…"} (max 3 per user)
   GET /auth/api-key lists masked keys; DELETE /auth/api-key/{id} revokes.
   The API key works as `Authorization: Bearer <apiKey>`. X-Org-ID is REQUIRED (400 without it).
   Current key "resilimes-ai" (id 15f5b3c2-4850-41bc-ab1f-200d651d85d5, expires 2027-01-22 00:27 UTC+9)
   stored in WSL ~/.config/fab-mes/zetaris_api_key (0600).

## Run SQL
POST /api/v1.0/sql-editor/sqls/run-query
Headers: Authorization: Bearer <apiKey|idToken>, X-Org-ID: <orgId>, Content-Type: application/json (X-Request-ID optional, UI sends a UUID)
Body: {"sql": "...", "limit": N (optional; no default cap observed, 5000 rows came back without it)}
200 -> {"headers":[...], "data":[["v",...]], "total":N, "timeUsed":ms}  (all values are strings)
400 -> {"msg": "..."}
Also working: /sql-editor/sqls/run (same shape; UI also sends queryId + "source":"SqlEditor"),
/query/sql/start {"select": "...", "pageLimit": N} -> {"records":[{col:val}], "totalCount", "queryToken", ...}

## Datasource DDL (send through run-query)
CREATE DATASOURCE <name> DESCRIBE BY "<[A-Za-z0-9_.,-] only, no spaces>" OPTIONS (
  jdbcdriver "org.postgresql.Driver", jdbcurl "jdbc:postgresql://fab-mes:5432/<db>",
  username "...", password "...", schema "resilimes", fetchsize "1000")
REGISTER DATASOURCE TABLES FROM <name>
SHOW DATASOURCES / SHOW TABLES FROM <name> / DROP DATASOURCE <name>
Tables are then <name>.<table>. Without `schema` only `public` is seen (?currentSchema= is ignored).
Gotcha: DROP DATASOURCE VIEW x FROM ds also unregisters a same-named table; re-run the setup script.
Plain CREATE VIEW across datasources / into a Lightning database fails (NoSuchElementException), so
the 12 tables cannot be unified under one name; the client needs a per-table source map.

## Layout created by scripts/zetaris_setup.sh
Container fab-mes (postgres:16-alpine, 127.0.0.1:5433->5432, volume fab-mes-data, network fab-net; zetaris-driver-1 attached to fab-net)
Credentials: WSL ~/.config/fab-mes/env (0600)
| Zetaris datasource | PG database.schema | tables |
| resilimes | fab_mes.resilimes  | equipment inhibit operators products qtime_rule reticle route route_steps wip_jobs |
| fab_cmms  | fab_cmms.resilimes | maintenance_logs |
| fab_erp   | fab_erp.resilimes  | bom materials |

Reload (e.g. after swapping seed.sql for SMT2020):
  wsl -d Ubuntu -- bash /mnt/c/code/ResiliMES-AI/scripts/zetaris_setup.sh [path/to/seed.sql]
(idempotent: recreates DBs, reloads, re-registers datasources, runs per-table SELECTs + federated check)

## Federated check
LITHO-02 DOWN x 3 maintenance logs x 2 lots (LOT-1001, LOT-1004) x 2 BOM materials = 12 rows (verified).