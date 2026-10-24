"""Register the three verified datasources. Secrets stay out of stdout.

The setup shell script loads Postgres, then calls ``python -m resilimes.data.zetaris_admin``.
Login is ``POST {ZETARIS_BASE_URL}/api/auth/login``. SQL is
``POST {ZETARIS_REST_URL}/sql-editor/sqls/run-query`` with Bearer and ``X-Org-ID``.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any

from resilimes.data.zetaris_layout import (
    DATABASE_FOR_TABLE,
    DATASOURCE_FOR_DATABASE,
    FEDERATED_SQL,
    SMT_DATABASE_FOR_TABLE,
    datasource_ddl,
    scrub,
)

Post = Callable[[str, dict[str, Any], dict[str, str]], tuple[int, dict[str, Any] | str]]


def login_body(email: str, password: str) -> dict[str, str]:
    return {"username": email, "password": password}


def api_key_body() -> dict[str, str]:
    return {"name": "resilimes-ai", "expiryDate": "2099-01-01T00:00:00.000Z"}


def select_sql(tables: Collection[str] | None = None) -> list[str]:
    """``SELECT *`` per loaded table, plus the federated join when the sample tables are loaded.

    ``tables`` is what the setup script just loaded (``None`` means every known
    table), so a reload with only some seeds does not probe tables it never made.
    """
    wanted = set(DATABASE_FOR_TABLE) if tables is None else set(tables) & set(DATABASE_FOR_TABLE)
    queries = [
        f"SELECT * FROM {DATASOURCE_FOR_DATABASE[database]}.{table}"
        for table, database in sorted(DATABASE_FOR_TABLE.items())
        if table in wanted
    ]
    if any(table not in SMT_DATABASE_FOR_TABLE for table in wanted):
        queries.append(FEDERATED_SQL)
    return queries


def loaded_tables(value: str | None) -> list[str] | None:
    """Parse ``RESILIMES_LOADED_TABLES`` (comma separated) from the setup script."""
    if not value or not value.strip():
        return None
    return [name.strip().lower() for name in value.split(",") if name.strip()]


def _rows(payload: dict[str, Any] | str) -> list[list[Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [row for row in payload["data"] if isinstance(row, list)]
    return []


def register(
    post: Post,
    *,
    base_url: str,
    rest_url: str,
    email: str,
    password: str,
    jdbc_user: str,
    jdbc_password: str,
    api_key: str = "",
    tables: Collection[str] | None = None,
    mint_api_key: bool = True,
) -> tuple[list[str], str]:
    """Login, (re)register the three datasources, probe, then make sure an API key exists.

    Follows the owner's verified script: the setup SQL runs with the login
    ``idToken`` (Bearer + ``X-Org-ID``), ``SHOW DATASOURCES`` decides whether to
    ``DROP`` first, then ``CREATE`` / ``REGISTER`` / ``SHOW TABLES FROM``, then
    ``SELECT *`` per loaded table and the federated join. The app itself needs
    an API key, so one is minted only when none is stored; a failed mint is
    reported but does not fail the reload.

    Returns scrubbed log lines and the API key (existing, new, or ""). The key
    is not part of the log.
    """
    secrets = [password, jdbc_password, api_key, email]
    lines: list[str] = []

    def note(text: str) -> None:
        lines.append(scrub(text, secrets))

    status, body = post(
        f"{base_url.rstrip('/')}/api/auth/login",
        login_body(email, password),
        {"Content-Type": "application/json"},
    )
    if status != 200 or not isinstance(body, dict) or not body.get("idToken"):
        note(f"login failed status={status}")
        return lines, api_key
    token = str(body.get("idToken") or "")
    org = str(body.get("orgId") or "1")
    secrets.extend([token, str(body.get("refreshToken") or "")])
    note(f"login ok orgId={org}")
    sql_url = f"{rest_url.rstrip('/')}/sql-editor/sqls/run-query"

    def run(statement: str) -> tuple[int, dict[str, Any] | str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Org-ID": org,
            "Content-Type": "application/json",
            "X-Request-ID": str(uuid.uuid4()),
        }
        return post(sql_url, {"sql": statement}, headers)

    status, shown = run("SHOW DATASOURCES")
    existing: set[str] | None = None
    if status == 200:
        existing = {str(row[0]) for row in _rows(shown) if row}
    else:
        note(f"show datasources status={status}; dropping blindly")
    for database in ("fab_mes", "fab_cmms", "fab_erp"):
        name = DATASOURCE_FOR_DATABASE[database]
        for statement in datasource_ddl(database, user=jdbc_user, password=jdbc_password):
            if statement.startswith("DROP") and existing is not None and name not in existing:
                note(f"drop {database} skipped (not registered)")
                continue
            status, payload = run(statement)
            if statement.startswith("DROP") and status == 400:
                note(f"drop {database} skipped status=400")
                continue
            if status != 200:
                note(f"sql failed status={status} database={database}")
                return lines, api_key
            note(f"sql ok database={database} status={status} bytes={len(statement)}")
            del payload
        status, listed = run(f"SHOW TABLES FROM {name}")
        names = sorted(str(row[0]).split(".")[-1] for row in _rows(listed) if row)
        note(f"datasource {name} -> {database}.resilimes: {len(names)} tables {' '.join(names)}")
    for statement in select_sql(tables):
        status, payload = run(statement)
        rows = 0
        cols = 0
        if isinstance(payload, dict):
            data = payload.get("data")
            total = str(payload.get("total"))
            rows = int(total) if total.isdigit() else len(data) if isinstance(data, list) else 0
            cols = len(payload.get("headers") or [])
        label = "federated" if "JOIN" in statement else statement.split("FROM", 1)[-1].strip()
        note(f"probe {label} status={status} rows={rows} cols={cols}")
        if status != 200:
            return lines, api_key
    key = api_key
    if not key and mint_api_key:
        status, created = post(
            f"{rest_url.rstrip('/')}/auth/api-key",
            api_key_body(),
            {
                "Authorization": f"Bearer {token}",
                "X-Org-ID": org,
                "Content-Type": "application/json",
            },
        )
        if status == 200 and isinstance(created, dict) and created.get("apiKey"):
            key = str(created["apiKey"])
            secrets.append(key)
            note("api key created name=resilimes-ai")
        else:
            note(f"api key not created status={status}; set ZETARIS_API_KEY in .env yourself")
    return lines, key


def _read_env_file(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        if text.startswith("export "):
            text = text[len("export ") :].strip()
        key, value = text.split("=", 1)
        found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def credentials(
    admin: dict[str, str], fab: dict[str, str], environ: dict[str, str]
) -> dict[str, str]:
    """Resolve logins the way the owner's script does. Values are secrets; never print them.

    Zetaris admin: ``ZETARIS_ADMIN_EMAIL`` / ``ZETARIS_ADMIN_PASSWORD`` from
    ``$ZETARIS_HOME/.env``, else ``ZETARIS_USER`` / ``ZETARIS_PASSWORD`` from the
    fab-mes env file or the environment; the email defaults to admin@zetaris.com.
    Postgres: ``FAB_PG_USER`` / ``FAB_PG_PASSWORD``, else the older
    ``POSTGRES_USER`` / ``POSTGRES_PASSWORD``.
    """

    def first(*values: str | None) -> str:
        return next((value for value in values if value), "")

    return {
        "email": first(
            admin.get("ZETARIS_ADMIN_EMAIL"),
            fab.get("ZETARIS_USER"),
            environ.get("ZETARIS_USER"),
            "admin@zetaris.com",
        ),
        "password": first(
            admin.get("ZETARIS_ADMIN_PASSWORD"),
            fab.get("ZETARIS_PASSWORD"),
            environ.get("ZETARIS_PASSWORD"),
        ),
        "jdbc_user": first(fab.get("FAB_PG_USER"), fab.get("POSTGRES_USER"), "fab"),
        "jdbc_password": first(fab.get("FAB_PG_PASSWORD"), fab.get("POSTGRES_PASSWORD")),
        "rest_url": first(
            environ.get("ZETARIS_REST_URL"),
            environ.get("ZETARIS_API"),
            fab.get("ZETARIS_REST_URL"),
            fab.get("ZETARIS_API"),
            "http://127.0.0.1:8888/api/v1.0",
        ),
        "base_url": first(
            environ.get("ZETARIS_BASE_URL"), fab.get("ZETARIS_BASE_URL"), "http://localhost:3000"
        ),
    }


def main() -> int:
    """Entry point used by scripts/zetaris_setup.sh. Prints only scrubbed lines."""
    import requests

    home = Path.home()
    zetaris_home = Path(os.getenv("ZETARIS_HOME") or home / "zetaris-platform")
    conf = home / ".config" / "fab-mes"
    found = credentials(
        _read_env_file(zetaris_home / ".env"),
        _read_env_file(conf / "env"),
        dict(os.environ),
    )
    if not found["password"] or not found["jdbc_password"]:
        print(
            "Missing the Zetaris admin password ($ZETARIS_HOME/.env) or the fab-mes "
            "Postgres password (~/.config/fab-mes/env FAB_PG_PASSWORD).",
            file=sys.stderr,
        )
        return 1
    key_path = conf / "api-key"
    existing = key_path.read_text(encoding="utf-8").strip() if key_path.is_file() else ""
    existing = existing or os.getenv("ZETARIS_API_KEY", "")

    def post(
        url: str, body: dict[str, Any], headers: dict[str, str]
    ) -> tuple[int, dict[str, Any] | str]:
        response = requests.post(url, json=body, headers=headers, timeout=600)
        try:
            parsed: dict[str, Any] | str = response.json()
        except ValueError:
            parsed = response.text[:300]
        return response.status_code, parsed

    lines, key = register(
        post,
        base_url=found["base_url"],
        rest_url=found["rest_url"],
        email=found["email"],
        password=found["password"],
        jdbc_user=found["jdbc_user"],
        jdbc_password=found["jdbc_password"],
        api_key=existing,
        tables=loaded_tables(os.getenv("RESILIMES_LOADED_TABLES")),
    )
    for line in lines:
        print(line)
    if key and not existing:
        key_path.write_text(key + "\n", encoding="utf-8")
        key_path.chmod(0o600)
        print(f"api key stored in {key_path} (not printed)")
    if any(line.startswith(("sql failed", "login failed")) for line in lines):
        return 1
    if any(line.startswith("probe ") and "status=200" not in line for line in lines):
        return 1
    tables = loaded_tables(os.getenv("RESILIMES_LOADED_TABLES"))
    if FEDERATED_SQL in select_sql(tables) and not any(
        line.startswith("probe federated") for line in lines
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main())
