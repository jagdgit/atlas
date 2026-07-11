# Atlas Database

PostgreSQL is Atlas' brain. All schema changes are versioned SQL migrations.

## Schemas

| Schema | Purpose |
|--------|---------|
| `system` | Settings, migrations, services, health |
| `audit` | Events and structured logs |
| `scheduler` | Tasks and task runs |
| `knowledge` | Documents, chunks, embeddings (pgvector) |
| `memory` | Working and long-term memory (future) |

## Migration Roles (Important)

There are two privilege tiers:

| Migration | Run as | Why |
|-----------|--------|-----|
| `0001` | `postgres` (superuser) | Extensions, `public` grants/revokes, and `ALTER ROLE ... search_path` require superuser |
| `0005` | `postgres` (superuser) | Reassigns ownership of superuser-created objects to `atlas` |
| `0002`–`0004`, `0006`+ | `atlas` (app role) via `atlas-db migrate` | Tables should be owned by the app role |

> **pgvector access:** `0001` grants `atlas` `USAGE` on `public` (where the
> `vector` type/operators live) and appends `public` to its `search_path`, while
> keeping `CREATE` on `public` revoked. Without this, `0006` fails with
> `type "vector" does not exist`. Because it's a superuser change, re-run `0001`
> (it is idempotent) after pulling these changes.

When the Python migration runner lands (Sprint 1.4), it connects as `atlas`, so
future migrations are automatically `atlas`-owned. Only bootstrap migrations that
need superuser are run manually as `postgres`.

## Running Migrations Manually

Apply in order (all as postgres for the initial bootstrap):

```bash
sudo -u postgres psql -d atlas -f database/migrations/0001_extensions_and_schemas.sql
sudo -u postgres psql -d atlas -f database/migrations/0002_system_foundation.sql
sudo -u postgres psql -d atlas -f database/migrations/0003_audit_foundation.sql
sudo -u postgres psql -d atlas -f database/migrations/0004_scheduler_foundation.sql
sudo -u postgres psql -d atlas -f database/migrations/0005_grants_and_ownership.sql
```

> **Note:** `0005` fixes the case where `0002`–`0004` were bootstrapped as
> `postgres`. It reassigns all Atlas-schema objects to the `atlas` role so the
> application can use them.

Application-owned migrations (`0006`+) are applied by the runner as `atlas`:

```bash
uv run atlas-db migrate
```

## Verify

```sql
\dn
\dt system.*
\dt audit.*
\dt scheduler.*
\dx
```

After `0005`, all Atlas-schema tables should show `Owner = atlas`:

```bash
sudo -u postgres psql -d atlas -c "\dt system.* audit.* scheduler.*"
```

## Migration Tracking

Once `system.migrations` exists, the Python runner records each applied file with a checksum.
Until then, migrations 0002–0004 can be applied manually.
