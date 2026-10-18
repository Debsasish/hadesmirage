"""Generate dialect-specific DDL references from the same tested migration metadata."""

from pathlib import Path

from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from mirage import db
from mirage import telegram as _telegram_tables  # noqa: F401  (registers Telegram tables)

ROOT = Path(__file__).resolve().parents[1]

for name, dialect in (("sqlite", sqlite.dialect()), ("postgresql", postgresql.dialect())):
    lines = [
        f"-- Generated DDL reference for authoritative schema revision {db.SCHEMA_VERSION}.",
        "-- Apply migrations with: python -m mirage migrate",
        "-- Revisions: 1 initial tables; 2 retention-safe sequences; 3 bounded advisory AI requests.",
        "-- Native gateway registry tables are intentionally separate.",
    ]
    for table in db.metadata.sorted_tables:
        lines.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in table.indexes:
            lines.append(str(CreateIndex(index).compile(dialect=dialect)) + ";")
    path = ROOT / "migrations" / f"schema-v{db.SCHEMA_VERSION}-{name}.sql"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
    print(path)
