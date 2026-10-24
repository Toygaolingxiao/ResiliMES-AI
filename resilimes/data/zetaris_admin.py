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
    """One probe per loaded table, plus the federated join when the sample tables are loaded.

    ``tables`` is what the setup script just loaded (``None`` means every known
    table), so a reload with only some seeds does not probe tables it never made.
    """
    wanted = set(DATABASE_FOR_TABLE) if tables is None else set(tables) & set(DATABASE_FOR_TABLE)
    queries = [
        f"SELECT * FROM {DATASOURCE_FOR_DATABASE[database]}.{table} LIMIT 1"
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
) -> tuple[list[str], str]:
    """Login, reuse or mint an API key, then DROP/CREATE/REGISTER and probe.

    Returns scrubbed log lines and the API key. The key is not part of the log.
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
    if status != 200 or not isinstance(body, dict):
        note(f"login failed status={status}")
        return lines, ""
    token = str(body.get("idToken") or "")
    org = str(body.get("orgId") or "1")
    secrets.append(token)
    note(f"login ok orgId={org}")
    key = api_key
    if not key:
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
            note(f"api key was not created status={status}")
            return lines, ""
    headers = {
        "Authorization": f"Bearer {key}",
        "X-Org-ID": org,
        "Content-Type": "application/json",
        "X-Request-ID": str(uuid.uuid4()),
    }
    sql_url = f"{rest_url.rstrip('/')}/sql-editor/sqls/run-query"
    for database in ("fab_mes", "fab_cmms", "fab_erp"):
        for statement in datasource_ddl(database, user=jdbc_user, password=jdbc_password):
            status, payload = post(sql_url, {"sql": statement}, headers)
            if statement.startswith("DROP") and status == 400:
                note(f"drop {database} skipped status=400")
                continue
            if status != 200:
                note(f"sql failed status={status} database={database}")
                return lines, key
            note(f"sql ok database={database} status={status} bytes={len(statement)}")
            del payload
    for statement in select_sql(tables):
        status, payload = post(sql_url, {"sql": statement}, headers)
        rows = 0
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                rows = len(data)
        label = "federated" if "JOIN" in statement else statement.split("FROM", 1)[-1].strip()
        note(f"probe {label} status={status} rows={rows}")
        if status != 200:
            return lines, key
    return lines, key


def _read_env_file(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def main() -> int:
    """Entry point used by scripts/zetaris_setup.sh. Prints only scrubbed lines."""
    import requests

    home = Path.home()
    admin = _read_env_file(home / "zetaris-platform" / ".env")
    fab = _read_env_file(home / ".config" / "fab-mes" / "env")
    email = admin.get("ZETARIS_ADMIN_EMAIL", "")
    password = admin.get("ZETARIS_ADMIN_PASSWORD", "")
    jdbc_password = fab.get("POSTGRES_PASSWORD", "")
    if not email or not password or not jdbc_password:
        print("Missing admin login or fab-mes password file.", file=sys.stderr)
        return 1
    key_path = home / ".config" / "fab-mes" / "api-key"
    existing = key_path.read_text(encoding="utf-8").strip() if key_path.is_file() else ""
    base = os.getenv("ZETARIS_BASE_URL", "http://localhost:3000")
    rest = os.getenv("ZETARIS_REST_URL", "http://127.0.0.1:8888/api/v1.0")
    tables = loaded_tables(os.getenv("RESILIMES_LOADED_TABLES"))

    def post(
        url: str, body: dict[str, Any], headers: dict[str, str]
    ) -> tuple[int, dict[str, Any] | str]:
        response = requests.post(url, json=body, headers=headers, timeout=60)
        try:
            parsed: dict[str, Any] | str = response.json()
        except ValueError:
            parsed = response.text[:300]
        return response.status_code, parsed

    lines, key = register(
        post,
        base_url=base,
        rest_url=rest,
        email=email,
        password=password,
        jdbc_user=fab.get("POSTGRES_USER", "fab"),
        jdbc_password=jdbc_password,
        api_key=existing,
        tables=tables,
    )
    for line in lines:
        print(line)
    if key and not existing:
        key_path.write_text(key + "\n", encoding="utf-8")
        key_path.chmod(0o600)
        print(f"api key stored in {key_path} (not printed)")
    if any(line.startswith("sql failed") or line.startswith("login failed") for line in lines):
        return 1
    if any(line.startswith("probe ") and "status=200" not in line for line in lines):
        return 1
    if FEDERATED_SQL in select_sql(tables) and not any(
        line.startswith("probe federated") for line in lines
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    raise SystemExit(main())
