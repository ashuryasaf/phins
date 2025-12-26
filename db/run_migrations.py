from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class Migration:
    name: str
    path: Path
    sha256: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_like_postgres(dsn: str) -> bool:
    d = (dsn or "").strip().lower()
    return d.startswith("postgres://") or d.startswith("postgresql://")


def _split_sql_statements(sql: str) -> List[str]:
    """
    Split SQL into statements while respecting:
      - single quotes
      - dollar-quoted strings ($$...$$ or $tag$...$tag$)
      - line comments (--)
      - block comments (/* */)

    This is sufficient for our migration files (DO $$...$$; etc.).
    """
    out: List[str] = []
    buf: List[str] = []

    i = 0
    n = len(sql)
    in_single = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: Optional[str] = None

    def flush():
        s = "".join(buf).strip()
        if s:
            out.append(s)
        buf.clear()

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        # End line comment
        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        # End block comment
        if in_block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 2
                in_block_comment = False
            else:
                i += 1
            continue

        # Dollar-quoted string handling
        if dollar_tag is not None:
            buf.append(ch)
            # check tag close at current pos
            if ch == "$":
                tag = dollar_tag
                # attempt match full tag
                if sql.startswith(tag, i):
                    buf.append(tag[1:])  # we already added one '$'
                    i += len(tag)
                    dollar_tag = None
                    continue
            i += 1
            continue

        # Single-quoted string handling
        if in_single:
            buf.append(ch)
            if ch == "'" and nxt == "'":
                # escaped quote
                buf.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue

        # Start comments
        if ch == "-" and nxt == "-":
            buf.append(ch)
            buf.append(nxt)
            i += 2
            in_line_comment = True
            continue
        if ch == "/" and nxt == "*":
            buf.append(ch)
            buf.append(nxt)
            i += 2
            in_block_comment = True
            continue

        # Start single-quoted string
        if ch == "'":
            buf.append(ch)
            in_single = True
            i += 1
            continue

        # Start dollar-quoted string
        if ch == "$":
            # Parse tag $...$
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < n and sql[j] == "$":
                tag = sql[i : j + 1]  # includes both $
                dollar_tag = tag
                buf.append(tag)
                i = j + 1
                continue

        # Statement delimiter
        if ch == ";":
            buf.append(ch)
            flush()
            i += 1
            continue

        buf.append(ch)
        i += 1

    flush()
    return out


def _list_migrations(migrations_dir: Path) -> List[Migration]:
    files = sorted([p for p in migrations_dir.glob("*.sql") if p.is_file()], key=lambda p: p.name)
    out: List[Migration] = []
    for p in files:
        out.append(Migration(name=p.name, path=p, sha256=_sha256_file(p)))
    return out


def run_phins_migrations(
    *,
    database_url: str,
    migrations_dir: str | Path,
    schema: str = "phins",
    table: str = "schema_migrations",
) -> Tuple[int, List[str]]:
    """
    Execute raw SQL migrations in order, exactly-once per DB, recording in schema.table.

    Returns (applied_count, applied_names).
    """
    if not database_url:
        return (0, [])
    if not _looks_like_postgres(database_url):
        # only designed for Postgres (Railway)
        return (0, [])

    try:
        import psycopg2  # type: ignore
    except Exception as e:
        raise RuntimeError("psycopg2 is required to run migrations") from e

    mig_dir = Path(migrations_dir)
    if not mig_dir.exists():
        return (0, [])

    migrations = _list_migrations(mig_dir)
    if not migrations:
        return (0, [])

    conn = psycopg2.connect(database_url)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {schema}.{table} (
                  name text PRIMARY KEY,
                  sha256 char(64) NOT NULL,
                  applied_at timestamptz NOT NULL DEFAULT now()
                );
                """
            )

            cur.execute(f"SELECT name, sha256 FROM {schema}.{table};")
            rows = cur.fetchall()
            applied = {r[0]: r[1] for r in rows}

            applied_names: List[str] = []
            for m in migrations:
                prev = applied.get(m.name)
                if prev:
                    if prev != m.sha256:
                        raise RuntimeError(
                            f"Migration {m.name} was already applied with different sha256 "
                            f"(db={prev}, file={m.sha256}). Refusing to continue."
                        )
                    continue

                sql = m.path.read_text(encoding="utf-8", errors="replace")
                statements = _split_sql_statements(sql)
                # Execute all statements. We keep autocommit on (needed for CREATE INDEX CONCURRENTLY).
                for stmt in statements:
                    s = stmt.strip()
                    if not s or s == ";":
                        continue
                    cur.execute(s)

                cur.execute(
                    f"INSERT INTO {schema}.{table} (name, sha256) VALUES (%s, %s);",
                    (m.name, m.sha256),
                )
                applied_names.append(m.name)

            return (len(applied_names), applied_names)
    finally:
        conn.close()


def run_if_configured() -> None:
    """
    Run on app startup when DATABASE_URL is set.
    Toggle via PHINS_RUN_MIGRATIONS=0/false/no.
    """
    flag = (os.environ.get("PHINS_RUN_MIGRATIONS", "") or "").strip().lower()
    if flag in ("0", "false", "no"):
        return
    db_url = (os.environ.get("DATABASE_URL") or os.environ.get("SQLALCHEMY_DATABASE_URL") or "").strip()
    if not db_url:
        return
    migrations_dir = Path(__file__).resolve().parent / "migrations"
    applied_count, names = run_phins_migrations(database_url=db_url, migrations_dir=migrations_dir)
    if applied_count:
        print(f"✓ Applied {applied_count} PHINS migrations: {', '.join(names)}")

