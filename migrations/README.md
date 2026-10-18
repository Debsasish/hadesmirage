# Authoritative storage migrations

Run `.\.venv\Scripts\python.exe -m mirage migrate` from the root.

`mirage.db.Database.migrate` is the migration runner used by startup and tests. It serializes changes through the same SQLite/PostgreSQL transaction lock, creates required metadata tables and records revisions:

| Revision | Change |
| --- | --- |
| 1 | Initial tenant/principal/policy/session/event/outbox/case/approval/execution/decoy/audit state |
| 2 | Tenant-scoped monotonic event and incident counters, including adoption of existing sequences |
| 3 | Tenant/principal-bound advisory AI requests, source references, pending/deadline state, validated output and usage/history |
| 4 | Portal-managed AI settings (provider, project, region, model, egress approval, auto-review) and Telegram users, one-time action tokens, deliveries and bot state |

The current generated `schema-v4-sqlite.sql` and `schema-v4-postgresql.sql` files are DDL inspection references from that same metadata, not substitute gateway registry migrations or proof that PostgreSQL was run. Regenerate with `python tools\export_schema.py`. The `schema-v2-*` and `schema-v3-*` files remain historical references. Existing cases/counters are preserved when revision 3 adds its request table; future unknown revisions are rejected before further metadata creation.

Do not point fixture initialization at a production database. The native gateway registry remains separate and must use the upstream migration, signer roles and signature verification.
