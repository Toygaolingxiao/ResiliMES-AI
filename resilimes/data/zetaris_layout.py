"""Verified Zetaris layout on the owner's PC (2026-10-24).

Three Postgres databases on container ``fab-mes``, each with schema ``resilimes``.
Zetaris registers one datasource per database. A query must name the datasource,
not a cross-database view. ``DROP DATASOURCE VIEW`` also drops a table of the
same name, so this client never builds those views.

Datasource ``resilimes`` is database ``fab_mes``. ``fab_cmms`` and ``fab_erp``
keep their own names.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET = re.compile(r"^[A-Za-z0-9]+$")
_TABLE_REF = re.compile(r"\bresilimes\.([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE)

# Plant tables whose datasource is not the schema. Every other plant table
# uses the schema argument, which is the ``resilimes`` datasource.
DEFAULT_TABLE_SOURCES: dict[str, str] = {
    "maintenance_logs": "fab_cmms",
    "bom": "fab_erp",
    "materials": "fab_erp",
}

# Kernel tables follow the same ownership: PM with CMMS, orders with ERP.
KERNEL_TABLE_SOURCES: dict[str, str] = {
    **DEFAULT_TABLE_SOURCES,
    "pm_calendar": "fab_cmms",
    "orders": "fab_erp",
}

# Postgres database that owns the table. The schema inside each database is
# ``resilimes``. Kernel tables follow the same ownership as the spec.
DATABASE_FOR_TABLE: dict[str, str] = {
    "equipment": "fab_mes",
    "wip_jobs": "fab_mes",
    "products": "fab_mes",
    "route": "fab_mes",
    "route_steps": "fab_mes",
    "qtime_rule": "fab_mes",
    "reticle": "fab_mes",
    "inhibit": "fab_mes",
    "operators": "fab_mes",
    "lots": "fab_mes",
    "operations": "fab_mes",
    "setup_matrix": "fab_mes",
    "maintenance_logs": "fab_cmms",
    "pm_calendar": "fab_cmms",
    "bom": "fab_erp",
    "materials": "fab_erp",
    "orders": "fab_erp",
}

DATASOURCE_FOR_DATABASE: dict[str, str] = {
    "fab_mes": "resilimes",
    "fab_cmms": "fab_cmms",
    "fab_erp": "fab_erp",
}

# The owner's federated check. Spark SQL: no casts, datasource-qualified names.
# On the sample seed this join is LITHO-02's fault rows, not a fixed 12.
FEDERATED_SQL = """
SELECT e.equipment_id, m.log_id, w.job_id, b.material_id, mat.material_id AS stock_id
FROM resilimes.equipment e
JOIN fab_cmms.maintenance_logs m ON e.equipment_id = m.equipment_id
JOIN resilimes.wip_jobs w ON e.equipment_id = w.assigned_equipment
JOIN fab_erp.bom b ON w.product_id = b.product_id
JOIN fab_erp.materials mat ON b.material_id = mat.material_id
WHERE e.status = 'DOWN'
""".strip()


def validate_ident(value: str, label: str = "identifier") -> str:
    if not _IDENT.match(value or ""):
        raise ValueError(f"{label} is not a safe identifier: {value!r}")
    return value


def parse_table_sources(raw: str) -> dict[str, str]:
    """Parse ``ZETARIS_TABLE_SOURCES`` (``table=datasource`` pairs, comma-separated)."""
    text = (raw or "").strip()
    if not text:
        return {}
    parsed: dict[str, str] = {}
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"ZETARIS_TABLE_SOURCES entry {item!r} needs table=datasource")
        table, source = (piece.strip() for piece in item.split("=", 1))
        parsed[validate_ident(table, "table")] = validate_ident(source, "datasource")
    return parsed


def merged_sources(
    schema: str,
    override: Mapping[str, str] | None = None,
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Defaults plus an override. The schema itself is not copied onto every table.

    An empty override keeps the defaults. A named table replaces that one default.
    """
    validate_ident(schema, "schema")
    mapping = dict(DEFAULT_TABLE_SOURCES if base is None else base)
    if override:
        for table, source in override.items():
            mapping[validate_ident(table, "table")] = validate_ident(source, "datasource")
    return mapping


def qualify(
    table: str,
    schema: str,
    sources: Mapping[str, str] | None = None,
    *,
    base: Mapping[str, str] | None = None,
) -> str:
    mapping = merged_sources(schema, sources, base=base)
    source = mapping.get(table, validate_ident(schema, "schema"))
    return f"{validate_ident(source, 'datasource')}.{validate_ident(table, 'table')}"


def _sql_statements(sql: str) -> list[str]:
    """Split on semicolons that are outside single-quoted literals."""
    parts: list[str] = []
    buf: list[str] = []
    quoted = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'" and quoted and index + 1 < len(sql) and sql[index + 1] == "'":
            buf.append("''")
            index += 2
            continue
        if char == "'":
            quoted = not quoted
            buf.append(char)
            index += 1
            continue
        if char == ";" and not quoted:
            parts.append("".join(buf))
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1
    if buf:
        parts.append("".join(buf))
    return parts


def split_sql(sql: str) -> dict[str, str]:
    """Route each ``resilimes.<table>`` statement to the database that owns it."""
    buckets: dict[str, list[str]] = {name: [] for name in DATASOURCE_FOR_DATABASE}
    for raw in _sql_statements(sql):
        lines = [
            line for line in raw.splitlines() if line.strip() and not line.strip().startswith("--")
        ]
        statement = "\n".join(lines).strip()
        if not statement:
            continue
        tables = {name.lower() for name in _TABLE_REF.findall(statement)}
        if not tables:
            raise ValueError(f"SQL does not name a resilimes table: {statement[:80]}")
        databases = set()
        for table in tables:
            if table not in DATABASE_FOR_TABLE:
                raise ValueError(f"No database owner for table {table}")
            databases.add(DATABASE_FOR_TABLE[table])
        if len(databases) != 1:
            raise ValueError(f"Statement spans databases {sorted(databases)}: {statement[:80]}")
        buckets[databases.pop()].append(statement + ";")
    return {
        name: "\n".join(statements) + ("\n" if statements else "")
        for name, statements in buckets.items()
    }


def datasource_ddl(database: str, *, user: str, password: str) -> list[str]:
    """DROP, CREATE, REGISTER for one datasource. Password must be alphanumeric."""
    if database not in DATASOURCE_FOR_DATABASE:
        raise ValueError(f"Unknown database {database!r}")
    if not _SECRET.match(user or ""):
        raise ValueError("JDBC username must be alphanumeric")
    if not _SECRET.match(password or ""):
        raise ValueError("JDBC password must be alphanumeric so it cannot break the DDL")
    name = DATASOURCE_FOR_DATABASE[database]
    describe = f"{database}.resilimes"
    jdbc = f"jdbc:postgresql://fab-mes:5432/{database}"
    options = (
        f'jdbcdriver "org.postgresql.Driver", '
        f'jdbcurl "{jdbc}", '
        f'username "{user}", '
        f'password "{password}", '
        f'schema "resilimes", '
        f'fetchsize "1000"'
    )
    create = f'CREATE DATASOURCE {name} DESCRIBE BY "{describe}" OPTIONS ({options})'
    if re.search(r"[^A-Za-z0-9_.,-]", describe):
        raise ValueError(f"DESCRIBE BY rejects {describe!r}")
    return [
        f"DROP DATASOURCE {name}",
        create,
        f"REGISTER DATASOURCE TABLES FROM {name}",
    ]


def write_split(sql_paths: list[Path], directory: Path) -> dict[str, Path]:
    """Write one SQL file per database. Each file replaces schema ``resilimes``."""
    chunks = [path.read_text(encoding="utf-8") for path in sql_paths if path.is_file()]
    if not chunks:
        raise ValueError("No SQL files to split")
    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    header = "DROP SCHEMA IF EXISTS resilimes CASCADE;\nCREATE SCHEMA resilimes;\n"
    for database, body in split_sql("\n".join(chunks)).items():
        destination = directory / f"{database}.sql"
        destination.write_text(header + body, encoding="utf-8")
        written[database] = destination
    return written


def scrub(text: str, secrets: list[str]) -> str:
    """Replace any secret of length >= 4. Shorter tokens are left alone."""
    cleaned = text
    for secret in secrets:
        if secret and len(secret) >= 4:
            cleaned = cleaned.replace(secret, "***")
    return cleaned
