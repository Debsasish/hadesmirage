from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    cast,
    create_engine,
    event,
    func,
    insert,
    select,
    text,
)
from sqlalchemy.engine import Connection, Engine

from mirage.common import now

metadata = MetaData()
SCHEMA_VERSION = 4


def tenant_table(name: str, *columns: Any, **kwargs: Any) -> Table:
    return Table(
        name,
        metadata,
        Column("tenant_id", String(200), primary_key=True),
        Column("id", String(200), primary_key=True),
        *columns,
        **kwargs,
    )


schema_versions = Table(
    "schema_versions",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", String(40), nullable=False),
)
tenants = Table(
    "tenants",
    metadata,
    Column("id", String(200), primary_key=True),
    Column("name", String(200), nullable=False),
)
principals = tenant_table(
    "principals",
    Column("name", String(200), nullable=False),
    Column("kind", String(30), nullable=False),
    Column("roles", JSON, nullable=False),
    Column("status", String(30), nullable=False),
    Column("scopes", JSON, nullable=False),
    Column("parent_id", String(200)),
    Column("root_id", String(200), nullable=False),
    Column("depth", Integer, nullable=False, default=0),
    Column("expires_at", String(40), nullable=False),
    Column("identity_epoch", Integer, nullable=False, default=1),
    Column("owner", String(200), nullable=False),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["tenant_id", "parent_id"], ["principals.tenant_id", "principals.id"]),
)
credentials = Table(
    "credentials",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("tenant_id", String(200), nullable=False),
    Column("principal_id", String(200), nullable=False),
    Column("source", String(30)),
    Column("expires_at", String(40), nullable=False),
    Column("csrf", String(100)),
    Column("kind", String(30), nullable=False),
    ForeignKeyConstraint(["tenant_id", "principal_id"], ["principals.tenant_id", "principals.id"]),
)
policy_versions = tenant_table(
    "policy_versions",
    Column("version", String(100), nullable=False),
    Column("digest", String(64), nullable=False),
    Column("status", String(30), nullable=False),
    Column("document", JSON, nullable=False),
    Column("created_by", String(200), nullable=False),
    Column("reviewed_by", String(200)),
    Column("tested", Boolean, nullable=False, default=False),
    Column("created_at", String(40), nullable=False),
    UniqueConstraint("tenant_id", "version"),
)
runtime = Table(
    "runtime",
    metadata,
    Column("tenant_id", String(200), primary_key=True),
    Column("active_policy_id", String(200), nullable=False),
    Column("engagements_enabled", Boolean, nullable=False),
    Column("model_calls", Integer, nullable=False, default=0),
    Column("model_tokens", Integer, nullable=False, default=0),
)
sessions = tenant_table(
    "sessions",
    Column("principal_id", String(200), nullable=False),
    Column("caller_class", String(30), nullable=False),
    Column("route_mode", String(30), nullable=False),
    Column("route_version", Integer, nullable=False),
    Column("decoy_id", String(200)),
    Column("origin", String(30), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("expires_at", String(40), nullable=False),
    Column("history", JSON, nullable=False),
    ForeignKeyConstraint(["tenant_id", "principal_id"], ["principals.tenant_id", "principals.id"]),
)
events = tenant_table(
    "events",
    Column("sequence", Integer, nullable=False),
    Column("session_id", String(200), nullable=False),
    Column("source", String(30), nullable=False),
    Column("event_type", String(50), nullable=False),
    Column("outcome", String(30), nullable=False),
    Column("received_at", String(40), nullable=False),
    Column("occurred_at", String(40), nullable=False),
    Column("body_digest", String(64), nullable=False),
    Column("body", JSON, nullable=False),
    Column("trusted", Boolean, nullable=False),
    Column("origin", String(30), nullable=False),
    ForeignKeyConstraint(["tenant_id", "session_id"], ["sessions.tenant_id", "sessions.id"]),
    UniqueConstraint("tenant_id", "sequence"),
)
Index("events_correlation", events.c.tenant_id, events.c.session_id, events.c.received_at)
outbox = tenant_table(
    "outbox",
    Column("event_id", String(200), nullable=False),
    Column("processed_at", String(40)),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["tenant_id", "event_id"], ["events.tenant_id", "events.id"]),
)
incidents = tenant_table(
    "incidents",
    Column("number", String(30), nullable=False),
    Column("session_id", String(200), nullable=False),
    Column("principal_id", String(200), nullable=False),
    Column("title", String(200), nullable=False),
    Column("summary", String(2000), nullable=False),
    Column("severity", String(20), nullable=False),
    Column("confidence", String(20), nullable=False),
    Column("status", String(30), nullable=False),
    Column("version", Integer, nullable=False),
    Column("rules", JSON, nullable=False),
    Column("source", String(30), nullable=False),
    Column("origin", String(30), nullable=False),
    Column("investigation", JSON),
    Column("model_error", String(200)),
    Column("model_calls", Integer, nullable=False, default=0),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    ForeignKeyConstraint(["tenant_id", "session_id"], ["sessions.tenant_id", "sessions.id"]),
    UniqueConstraint("tenant_id", "session_id"),
)
incident_events = Table(
    "incident_events",
    metadata,
    Column("tenant_id", String(200), primary_key=True),
    Column("incident_id", String(200), primary_key=True),
    Column("event_id", String(200), primary_key=True),
    ForeignKeyConstraint(["tenant_id", "incident_id"], ["incidents.tenant_id", "incidents.id"]),
    ForeignKeyConstraint(["tenant_id", "event_id"], ["events.tenant_id", "events.id"]),
)
approvals = tenant_table(
    "approvals",
    Column("requester_id", String(200), nullable=False),
    Column("principal_id", String(200), nullable=False),
    Column("session_id", String(200), nullable=False),
    Column("digest", String(64), nullable=False),
    Column("policy_version", String(100), nullable=False),
    Column("invocation", JSON, nullable=False),
    Column("status", String(30), nullable=False),
    Column("approver_id", String(200)),
    Column("expires_at", String(40), nullable=False),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["tenant_id", "session_id"], ["sessions.tenant_id", "sessions.id"]),
)
executions = tenant_table(
    "executions",
    Column("principal_id", String(200), nullable=False),
    Column("session_id", String(200), nullable=False),
    Column("idempotency_key", String(200), nullable=False),
    Column("digest", String(64), nullable=False),
    Column("state", String(30), nullable=False),
    Column("decision", JSON, nullable=False),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["tenant_id", "session_id"], ["sessions.tenant_id", "sessions.id"]),
    UniqueConstraint("tenant_id", "principal_id", "session_id", "idempotency_key"),
)
decoys = tenant_table(
    "decoys",
    Column("session_id", String(200), nullable=False),
    Column("template_id", String(100), nullable=False),
    Column("template_version", String(50), nullable=False),
    Column("state", String(30), nullable=False),
    Column("synthetic_state", JSON, nullable=False),
    Column("requests", Integer, nullable=False),
    Column("model_tokens", Integer, nullable=False),
    Column("expires_at", String(40), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("attestation", JSON, nullable=False),
    Column("cleanup_state", String(30), nullable=False),
    ForeignKeyConstraint(["tenant_id", "session_id"], ["sessions.tenant_id", "sessions.id"]),
    UniqueConstraint("tenant_id", "session_id"),
)
notes = tenant_table(
    "notes",
    Column("incident_id", String(200), nullable=False),
    Column("actor_id", String(200), nullable=False),
    Column("text", String(2000), nullable=False),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["tenant_id", "incident_id"], ["incidents.tenant_id", "incidents.id"]),
)
audit_log = tenant_table(
    "audit_log",
    Column("sequence", Integer, nullable=False),
    Column("actor_id", String(200), nullable=False),
    Column("action", String(100), nullable=False),
    Column("object_id", String(200), nullable=False),
    Column("details", JSON, nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("previous_digest", String(64), nullable=False),
    Column("integrity_digest", String(64), nullable=False),
    UniqueConstraint("tenant_id", "sequence"),
)
idempotency = tenant_table(
    "idempotency",
    Column("principal_id", String(200), nullable=False),
    Column("route", String(300), nullable=False),
    Column("key", String(200), nullable=False),
    Column("digest", String(64), nullable=False),
    Column("response", JSON, nullable=False),
    UniqueConstraint("tenant_id", "principal_id", "route", "key"),
)
imports = tenant_table(
    "imports",
    Column("source", String(100), nullable=False),
    Column("version", String(100), nullable=False),
    Column("digest", String(64), nullable=False),
    Column("observations", JSON, nullable=False),
    Column("created_at", String(40), nullable=False),
)
ai_requests = tenant_table(
    "ai_requests",
    Column("principal_id", String(200), nullable=False),
    Column("purpose", String(40), nullable=False),
    Column("resource_id", String(200), nullable=False),
    Column("resource_version", Integer),
    Column("incident_id", String(200)),
    Column("import_id", String(200)),
    Column("decoy_id", String(200)),
    Column("provider", String(100), nullable=False),
    Column("config_digest", String(64), nullable=False),
    Column("context_digest", String(64), nullable=False),
    Column("route", String(300), nullable=False),
    Column("request_key", String(200), nullable=False),
    Column("state", String(30), nullable=False),
    Column("question", String(1000)),
    Column("output", JSON),
    Column("error_code", String(100)),
    Column("http_status", Integer),
    Column("tokens", Integer),
    Column("budget_units", Integer, nullable=False, default=0),
    Column("started_at", String(40), nullable=False),
    Column("deadline_at", String(40), nullable=False),
    Column("completed_at", String(40)),
    Column("duration_ms", Integer),
    ForeignKeyConstraint(["tenant_id", "principal_id"], ["principals.tenant_id", "principals.id"]),
    ForeignKeyConstraint(
        ["tenant_id", "incident_id"], ["incidents.tenant_id", "incidents.id"], ondelete="CASCADE"
    ),
    ForeignKeyConstraint(
        ["tenant_id", "import_id"], ["imports.tenant_id", "imports.id"], ondelete="CASCADE"
    ),
    ForeignKeyConstraint(
        ["tenant_id", "decoy_id"], ["decoys.tenant_id", "decoys.id"], ondelete="CASCADE"
    ),
    UniqueConstraint("tenant_id", "principal_id", "route", "request_key"),
)
Index("ai_request_work", ai_requests.c.tenant_id, ai_requests.c.state, ai_requests.c.deadline_at)
ai_settings = Table(
    "ai_settings",
    metadata,
    Column("id", String(50), primary_key=True),
    Column("provider", String(30), nullable=False),
    Column("project", String(200), nullable=False),
    Column("location", String(100), nullable=False),
    Column("model", String(200), nullable=False),
    Column("egress_approved", Boolean, nullable=False),
    Column("auto_triage", Boolean, nullable=False),
    Column("decoy_wording", Boolean, nullable=False),
    Column("auto_triage_since", String(40)),
    Column("version", Integer, nullable=False),
    Column("updated_by", String(200), nullable=False),
    Column("updated_at", String(40), nullable=False),
)
rate_limits = tenant_table(
    "rate_limits",
    Column("window", Integer, nullable=False),
    Column("count", Integer, nullable=False),
)
sequence_counters = tenant_table(
    "sequence_counters",
    Column("value", Integer, nullable=False),
)


def row(
    connection: Connection, table: Table, tenant: str, identifier: str
) -> dict[str, Any] | None:
    result = (
        connection.execute(
            select(table).where(table.c.tenant_id == tenant, table.c.id == identifier)
        )
        .mappings()
        .first()
    )
    return dict(result) if result else None


def rows(connection: Connection, query: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in connection.execute(query).mappings()]


def next_sequence(connection: Connection, tenant: str, name: str) -> int:
    if name not in {"events", "incidents"}:
        raise ValueError("Unknown authoritative sequence")
    current = row(connection, sequence_counters, tenant, name)
    if current is not None:
        value = current["value"] + 1
        connection.execute(
            sequence_counters.update()
            .where(
                sequence_counters.c.tenant_id == tenant,
                sequence_counters.c.id == name,
            )
            .values(value=value)
        )
        return value
    if name == "events":
        legacy = connection.execute(
            select(func.coalesce(func.max(events.c.sequence), 0)).where(
                events.c.tenant_id == tenant,
            )
        ).scalar_one()
    else:
        legacy = connection.execute(
            select(
                func.coalesce(func.max(cast(func.substr(incidents.c.number, 4), Integer)), 0)
            ).where(incidents.c.tenant_id == tenant)
        ).scalar_one()
    value = legacy + 1
    connection.execute(insert(sequence_counters).values(tenant_id=tenant, id=name, value=value))
    return value


class Database:
    def __init__(self, url: str) -> None:
        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite:"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        self.engine: Engine = create_engine(url, **kwargs)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def sqlite_setup(dbapi_connection: Any, _record: Any) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=15000")
                cursor.close()

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.connect() as connection:
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
                connection.execute(text("SELECT pg_advisory_xact_lock(482364109)"))
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def migrate(self) -> None:
        with self.transaction() as connection:
            schema_versions.create(connection, checkfirst=True)
            versions = list(connection.execute(select(schema_versions.c.version)).scalars())
            if versions and max(versions) > SCHEMA_VERSION:
                raise RuntimeError(
                    "Unsupported authoritative schema version; do not downgrade shared state"
                )
            metadata.create_all(connection)
            if not versions:
                connection.execute(insert(schema_versions).values(version=1, applied_at=now()))
            for revision in range(2, SCHEMA_VERSION + 1):
                if revision not in versions:
                    connection.execute(
                        insert(schema_versions).values(version=revision, applied_at=now())
                    )

    def close(self) -> None:
        self.engine.dispose()
