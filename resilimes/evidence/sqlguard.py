"""Guard for SQL an AI agent writes: one SELECT, allowlisted tables, bounded LIMIT.

Rejected: comments, more than one statement, anything not starting with
SELECT (or WITH ... SELECT), any write/DDL/admin keyword anywhere outside a
string literal, any FROM/JOIN target that is not ``<datasource>.<table>`` from
the allowlist (fab_mes = datasource ``resilimes``, fab_cmms, fab_erp,
fab_ops), and table functions. A missing LIMIT is appended; a larger one is
clamped. The guard is purely lexical and deliberately strict: a false reject
costs the agent one retry, a false accept could cost the fab.
"""

from __future__ import annotations

import re

from resilimes.data.zetaris_layout import DATABASE_FOR_TABLE, DATASOURCE_FOR_DATABASE

MAX_LIMIT = 200
DEFAULT_LIMIT = 50

FORBIDDEN = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "CREATE",
    "ALTER",
    "GRANT",
    "REVOKE",
    "TRUNCATE",
    "MERGE",
    "CALL",
    "EXEC",
    "EXECUTE",
    "REGISTER",
    "SET",
    "COPY",
    "ATTACH",
    "DETACH",
    "INTO",
    "SHOW",
    "DESCRIBE",
    "REFRESH",
    "CACHE",
    "UNCACHE",
    "LOAD",
    "PRAGMA",
    "VACUUM",
    "REPLACE",
    "UPSERT",
    "LOCK",
    "COMMIT",
    "ROLLBACK",
    "BEGIN",
    "ANALYZE",
    "MSCK",
    "ADD",
    "USE",
    "DO",
    "IMPORT",
    "EXPORT",
    "OUTFILE",
    "DUMPFILE",
    "SLEEP",
    "PG_SLEEP",
    "PG_READ_FILE",
    "LO_IMPORT",
    "DBLINK",
    "READ_FILES",
    "REFLECT",
    "JAVA_METHOD",
)
_FORBIDDEN_RE = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.IGNORECASE)
_STRING = re.compile(r"'(?:[^']|'')*'")
_QUOTED_IDENT = re.compile(r'"|`|\[')
_TARGET = re.compile(r"\b(FROM|JOIN)\s+([^\s,()]+)", re.IGNORECASE)
_COMMA_JOIN = re.compile(
    r"\b(?:FROM|JOIN)\s+[^\s,()]+(?:\s+(?:AS\s+)?[A-Za-z_]\w*)?\s*,", re.IGNORECASE
)
_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.IGNORECASE)
_LIMIT_ANY = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_CTE_NAME = re.compile(r"(?:\bWITH|,)\s*([A-Za-z_]\w*)\s+AS\s*\(", re.IGNORECASE)


class SqlRejected(ValueError):
    """The statement is not allowed. The message says why (safe to show the model)."""


def allowlist() -> dict[str, set[str]]:
    """Datasource -> allowed tables, from the Zetaris layout (all four sources)."""
    allowed: dict[str, set[str]] = {}
    for table, database in DATABASE_FOR_TABLE.items():
        allowed.setdefault(DATASOURCE_FOR_DATABASE[database], set()).add(table)
    return allowed


def guard(sql: str, *, max_limit: int = MAX_LIMIT, default_limit: int = DEFAULT_LIMIT) -> str:
    """Return the statement to run (LIMIT enforced) or raise ``SqlRejected``."""
    text = (sql or "").strip()
    if not text:
        raise SqlRejected("empty statement")
    if len(text) > 4000:
        raise SqlRejected("statement too long (max 4000 characters)")
    masked = _STRING.sub("''", text)
    if masked.count("'") % 2:
        raise SqlRejected("unbalanced string literal")
    if "--" in masked or "/*" in masked or "*/" in masked or "#" in masked:
        raise SqlRejected("comments are not allowed")
    if _QUOTED_IDENT.search(masked):
        raise SqlRejected("quoted identifiers are not allowed")
    if "\\" in masked:
        raise SqlRejected("backslashes are not allowed")
    body = masked.rstrip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
        text = text.rstrip()[:-1].rstrip()
    if ";" in body:
        raise SqlRejected("only one statement is allowed")
    head = body.lstrip("( \n\t").split(None, 1)[0].upper() if body else ""
    if head not in ("SELECT", "WITH"):
        raise SqlRejected("only SELECT statements are allowed")
    bad = _FORBIDDEN_RE.search(body)
    if bad:
        raise SqlRejected(f"keyword {bad.group(1).upper()} is not allowed")
    ctes = {name.lower() for name in _CTE_NAME.findall(body)} if head == "WITH" else set()
    allowed = allowlist()
    if _COMMA_JOIN.search(body):
        raise SqlRejected("comma joins are not allowed; use JOIN ... ON")
    targets = [match.group(2) for match in _TARGET.finditer(body)]
    if not targets:
        raise SqlRejected("no FROM table")
    for target in targets:
        name = target.strip().rstrip(")")
        if name.lower() in ctes:
            continue
        parts = name.split(".")
        if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z_]\w*", part) for part in parts):
            raise SqlRejected(f"table {name!r} must be written as <datasource>.<table>")
        source, table = parts[0].lower(), parts[1].lower()
        if source not in allowed or table not in allowed[source]:
            raise SqlRejected(f"table {name} is not on the allowlist")
    limit = _LIMIT.search(body)
    if limit:
        value = int(limit.group(1))
        if value > max_limit:
            text = text[: len(text) - len(limit.group(0))] + f"LIMIT {max_limit}"
    elif _LIMIT_ANY.search(body):
        raise SqlRejected("LIMIT must be a single number at the end")
    else:
        text = f"{text} LIMIT {min(default_limit, max_limit)}"
    return text
