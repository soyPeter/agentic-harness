---
name: jdbi
description: SQL-first persistence with JDBI 3 - SqlObject and fluent API, row records and mapping to domain types, Jdbi setup (plain or Quarkus CDI), transactions, safe binding, N+1, batching, keyset pagination, optimistic locking, optional command/query split, schema migrations (Flyway with option flyway) and real-database tests. Use before editing persistence adapters, JDBI DAOs, row mappers or migration scripts.
applies-to: jdbi 3.x (examples checked against 3.49-3.55), java>=21; SQL examples in PostgreSQL dialect
last-verified: 2026-10-05
sources: JDBI developer guide (jdbi.org, 3.55.x) and RELEASE_NOTES; agentic-backbone 4-KNOWLEDGE/6-MEMORY/7-CONVENTIONS (SQL-first, *Row records, CQRS lite, outbox, optimistic locking); problem list adapted from agentic-backbone general/jpa-patterns; Quarkus Flyway guide; quarkiverse quarkus-jdbi source; framework, database, migration-tool and layering choices made conditional on the ADRs and jdbi pack options
---

# JDBI (SQL-first)

The accepted ADRs and `backbone/4-KNOWLEDGE.md` override this skill.

SQL is written by hand, reviewed like code, and tested against the database engine the ADR chose. SQL examples here are
**PostgreSQL** examples; translate dialect-specific parts (arrays, `ILIKE`, `jsonb`, `SKIP LOCKED`, partial indexes) for
another engine. If the jdbi option `no-orm` is adopted: no Hibernate ORM, no Panache, no JPA annotations (Hibernate
Validator stays allowed).

## Where things live

Always: ports (or whatever API the rest of the code calls) take and return domain types only; row records, `Handle`, `Jdbi`
and `ResultIterable` stay inside persistence code. The mapping `Row → domain` goes through the domain's constructor or
factory, so domain invariants are re-checked on load.

If the architecture ADR uses hexagonal layering (option `hexagonal-layers`; the guardrail blocks `org.jdbi` in the domain):

| Artifact | Location | Rule |
|---|---|---|
| Domain entity, value objects, repository port | `domain/` | No `org.jdbi`, no `@ColumnName`, no SQL |
| `*Row` records (one per table or projection) | `infra/persistence/<ctx>/` | Flat, column-shaped, JDBI annotations allowed |
| SqlObject interfaces (`*Dao`) | `infra/persistence/<ctx>/` | SQL in text blocks, explicit column lists |
| Adapter `Jdbi<Aggregate>Repository implements <Port>` | `infra/persistence/<ctx>/` | Maps `Row ↔ domain`, translates exceptions |
| `Jdbi` setup (producers or wiring) | `infra/config/` | One place installs plugins and mappers |

Migration scripts: with option `flyway`, `src/main/resources/db/migration/`; otherwise where the ADR's migration tool expects them.

## Setup

Create one `Jdbi` per datasource at startup and share it (it is thread-safe). Install plugins and mappers in one place.

Framework-neutral (plain construction, passed to adapters by constructor):

```java
DataSource ds = ...;                                     // the connection pool the ADR chose
Jdbi jdbi = Jdbi.create(ds)
        .installPlugin(new SqlObjectPlugin())
        .installPlugin(new PostgresPlugin());            // PostgreSQL only (jdbi3-postgres)
var customers = new JdbiCustomerRepository(jdbi);
```

If the quarkus pack is adopted, a CDI producer creates it (see `quarkus-cdi`):

```java
@ApplicationScoped
class JdbiProducer {                                    // infra/config under hexagonal-layers
    @Produces @ApplicationScoped
    Jdbi jdbi(AgroalDataSource ds) {
        return Jdbi.create(ds).installPlugin(new SqlObjectPlugin()).installPlugin(new PostgresPlugin());
    }
}
```

- If the architecture ADR separates command and query datasources: one `Jdbi` per datasource, told apart by qualifiers
  (`@CommandDb`, `@QueryDb`; with Quarkus `@DataSource("command")`/`@DataSource("query")` on the `AgroalDataSource`). Writes,
  transactions and read-your-own-write reads use the command instance; query-side read models use the query instance. Never
  write through the query instance (make its role or connection read-only if the DB allows).
- Compile with `-parameters`, so `@Bind` and `@ColumnName` are optional. Keep `@Bind("x")` where the name differs.
- Native image (Quarkus): use `io.quarkiverse.jdbi:quarkus-jdbi` and read the quarkus skill's `native.md` (proxy and record
  registration).

## Querying: SqlObject first, fluent API for dynamic cases

```java
@RegisterConstructorMapper(CustomerRow.class)
public interface CustomerDao {
    @SqlQuery("""
        SELECT id, name, email, status, version, created_at
        FROM customer WHERE id = :id AND deleted_at IS NULL""")
    Optional<CustomerRow> findById(UUID id);

    @SqlUpdate("""
        INSERT INTO customer (id, name, email, status, version, created_at)
        VALUES (:id, :name, :email, :status, 0, :createdAt)""")
    void insert(@BindMethods CustomerRow row);          // record accessors -> :id, :name, ...
}

public record CustomerRow(UUID id, String name, String email, String status, long version, Instant createdAt) {}
```

- Use explicit column lists, never `SELECT *`. Reflective mappers match snake_case columns to camelCase components.
- Return `Optional<T>` for zero-or-one results, `List<T>` for many, and `Stream<T>` only inside a `try`-with-resources
  that runs within the handle's lifetime. Use `.one()` only when exactly one row is guaranteed (it throws otherwise).
- Fluent API, for example `handle.createQuery(sql).bind("id", id).mapTo(CustomerRow.class).findOne()`. Use it when the
  statement shape is built at runtime (optional filters, whitelisted sort). Register mappers on the `Jdbi` or the handle.
- `jdbi.onDemand(Dao.class)` opens a handle per call, which is fine for single statements outside a transaction. Inside a transaction,
  use `handle.attach(Dao.class)` so all calls share the connection.

## Binding and injection safety

- Every value is bound (`:name`, `bind`, `@Bind`, `@BindMethods`, `@BindList`, `bindArray`). Never concatenate or
  `String.format` values into SQL.
- `<placeholder>` attributes (`@Define`, `define(...)`) are rendered into the SQL text without escaping. Use them only for
  whitelisted identifiers or clauses that come from code (an enum to fixed SQL fragment map). Never use them for request data.

```java
enum CustomerSort { NAME("name"), CREATED("created_at");  final String column; CustomerSort(String c) { column = c; } }
// handle.createQuery("SELECT ... ORDER BY <sort> , id LIMIT :limit").define("sort", sort.column)
```

- IN lists: `@BindList("ids") List<UUID> ids` with `WHERE id IN (<ids>)` renders one bound placeholder per element (safe).
  Decide the empty-list behaviour explicitly (return early in the adapter). PostgreSQL: prefer an array,
  `WHERE id = ANY(:ids)` with `bindArray("ids", UUID.class, ids)`. It has one statement shape and is batch-safe.
- LIKE: escape `%` and `_` in user input and bind it (PostgreSQL: `name ILIKE :pattern ESCAPE '\'`).

## Transactions

- One transaction per use case invocation, opened at the boundary, never inside domain code. Use cases depend on
  a port (for example `UnitOfWork`/`TransactionRunner`) or are wrapped by a decorator or interceptor. The
  JDBI implementation uses `jdbi.inTransaction(h -> ...)` (the command instance if split) and attaches DAOs to `h`.
- All writes of one use case go through the same handle (including, if the ADR uses a transactional outbox, the outbox
  row, which then commits or rolls back with the state change).
- SqlObject `@Transaction` on a DAO default method groups its calls into one transaction. A nested call joins the outer one.
- Do not mix mechanisms on one call path. If the project uses JTA (e.g. Quarkus `@jakarta.transaction.Transactional` with
  Narayana + Agroal), connections arrive enlisted with autocommit off, and JDBI's default handler joins that transaction
  instead of committing. Then do not rely on `inTransaction` to commit. Prove it with a rollback test (no partial writes).
- Keep transactions short. No HTTP or broker calls inside them. Pollers lock rows with `SELECT ... FOR UPDATE SKIP LOCKED`
  (PostgreSQL; also MySQL 8+ and Oracle).

## Performance rules (the classic ORM problems still apply)

- N+1: never query in a loop. Use a JOIN plus row reduction (`@UseRowReducer` / `reduceRows`), or one IN (or PostgreSQL `ANY`)
  query for the children followed by grouping in Java. Two queries are fine. N+1 queries are not.
- Projections: read models select exactly the columns they need (a dedicated `*View` record), not whole rows.
- Batching: `@SqlBatch` or `PreparedBatch` for many inserts or updates. Do not use `@BindList` or `<placeholders>` in batches.
- Bulk updates: one set-based `UPDATE ... WHERE ...` instead of load-modify-save loops. Remember that it bypasses
  domain invariants, so use it only for rules that are defined in SQL by design.
- Pagination: keyset for large or growing tables (`WHERE (created_at, id) < (:createdAt, :id) ORDER BY created_at DESC, id DESC
  LIMIT :limit`, with a matching index). Use OFFSET only for small bounded tables. Always cap `limit` server-side.
- Optimistic locking: the `version` column, `UPDATE ... SET ..., version = version + 1 WHERE id = :id AND version = :version`.
  An update count of 0 means a conflict, so throw a domain `ConcurrentUpdateException` (HTTP 409 per `api-design`).
- Soft delete (if used): every read filters `deleted_at IS NULL` (in each query or a view); PostgreSQL partial indexes
  `WHERE deleted_at IS NULL` keep them small.

## Schema migrations

Use the migration tool the ADR chose. These rules hold for any tool:

- Never edit, rename or delete an applied migration. Fix forward with a new one.
- Changes are backward compatible with the running version (expand → migrate code → contract in a later release).
  Do not drop or rename a column the previous release still reads. Add columns as nullable or with a default. Backfill in batches.
- Every FK column and every column in a frequent `WHERE`/`ORDER BY`/`JOIN` gets an index. On big PostgreSQL tables, build it
  with `CREATE INDEX CONCURRENTLY`, which cannot run in a transaction; check the tool's per-script non-transactional mode.
- Constraints live in the DB too: `NOT NULL`, `CHECK`, `UNIQUE`, FKs. The DB is the last line of defence for invariants.

With option `flyway`:

- Name versioned files `V<n>__<snake_desc>.sql` (two underscores, monotonically increasing) in `src/main/resources/db/migration/`.
  Use `R__` only for views and functions. `repair` is for metadata only.
- Add the database module (PostgreSQL: `org.flywaydb:flyway-database-postgresql`). With Quarkus, `quarkus-flyway` and
  `quarkus.flyway.migrate-at-start=true`; if command and query datasources are split, migrate only the command one
  (`quarkus.flyway."command".migrate-at-start=true`).

## Testing

- Use the production database engine: Quarkus Dev Services in `@QuarkusTest` (if the quarkus pack is adopted), or
  Testcontainers for plain JUnit adapter tests. Do not substitute H2 or another in-memory engine.
- Real migrations build the schema. Tests own their data (unique ids, or truncate in `@BeforeEach`).
- For each adapter, test: the mapping round-trip, not found, the conflict on a stale version, pagination boundaries (empty,
  exact page, last page), the batch path, soft-deleted rows being excluded, and transaction rollback (no partial writes).
- Use cases are tested with fake ports, without a database.

## Checklist

- [ ] Row records, handles and SQL stay in persistence code and are mapped to domain types in the adapter (`hexagonal-layers`: none in `domain/`).
- [ ] All values are bound. `<placeholders>` only take whitelisted, code-owned fragments.
- [ ] No query in a loop. Batches use `@SqlBatch`/`PreparedBatch`. Lists are paginated with a capped limit.
- [ ] Writes of one use case share one transaction (on the command `Jdbi` if split). Version checks map to 409.
- [ ] Each migration is new, append-only, backward compatible, and indexed for its FKs and predicates.
- [ ] Adapter tests run against the production database engine with the real migrations.

Read `patterns.md` when you implement joins and row reducers, keyset pagination, optimistic-lock updates,
batches, the transaction port, or an outbox write.

## Linked skills

- quarkus-cdi (if adopted): `Jdbi` producers, qualifiers, layer placement.
- quarkus (if adopted): datasources, Dev Services, `native.md` for JDBI in native images.
- architecture: ports and adapters, command/query separation. adr-writing: record database, migration, transaction and pagination choices.
- java, java-test (if adopted), java-review, module-testing, code-quality, security (SQL injection, least-privilege DB roles).
