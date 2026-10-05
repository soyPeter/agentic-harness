# JDBI patterns (longer examples)

Code is persistence (adapter) code unless it is marked `domain` (with option `hexagonal-layers`: `infra/`). Imports are
omitted. SQL is PostgreSQL; translate dialect-specific parts for another engine. `@ApplicationScoped` and the `@CommandDb`
qualifier appear only when the quarkus pack is adopted (and the ADR splits command and query datasources); without them,
construct the classes with `new` and pass the `Jdbi` by constructor. Each pattern needs an adapter test against a real
database (SKILL.md → Testing).

## 1. Adapter: Row ↔ domain mapping

```java
// domain
public interface CustomerRepository {
    Optional<Customer> findById(CustomerId id);
    void add(Customer customer);
    void update(Customer customer);              // throws ConcurrentUpdateException on a stale version
}

// persistence adapter
@ApplicationScoped                                   // Quarkus only
class JdbiCustomerRepository implements CustomerRepository {
    private final Jdbi jdbi;
    JdbiCustomerRepository(@CommandDb Jdbi jdbi) { this.jdbi = jdbi; }

    @Override public Optional<Customer> findById(CustomerId id) {
        return jdbi.withExtension(CustomerDao.class, dao -> dao.findById(id.value())).map(CustomerRowMapper::toDomain);
    }
    @Override public void add(Customer c) {
        jdbi.useExtension(CustomerDao.class, dao -> dao.insert(CustomerRowMapper.toRow(c)));
    }
    @Override public void update(Customer c) {
        int n = jdbi.withExtension(CustomerDao.class, dao -> dao.update(CustomerRowMapper.toRow(c)));
        if (n == 0) throw new ConcurrentUpdateException("Customer", c.id().value(), c.version());
    }
}

final class CustomerRowMapper {
    static Customer toDomain(CustomerRow r) {        // goes through the domain factory: invariants re-checked
        return Customer.rehydrate(new CustomerId(r.id()), r.name(), new Email(r.email()),
                CustomerStatus.valueOf(r.status()), r.version(), r.createdAt());
    }
    static CustomerRow toRow(Customer c) {
        return new CustomerRow(c.id().value(), c.name(), c.email().value(), c.status().name(), c.version(), c.createdAt());
    }
    private CustomerRowMapper() {}
}
```

Inside a use-case transaction, the adapter must use the transaction's handle (section 2), not `jdbi.withExtension`.

## 2. One transaction per use case (port + JDBI implementation)

```java
// domain (or app) port: framework-free
public interface TransactionRunner {
    <T> T inTransaction(Supplier<T> work);
}

// adapter: binds the current handle to the thread for the duration of the work
@ApplicationScoped                                   // Quarkus only
class JdbiTransactionRunner implements TransactionRunner {
    private static final ScopedValue<Handle> CURRENT = ScopedValue.newInstance();   // Java 25+; or ThreadLocal
    private final Jdbi jdbi;
    JdbiTransactionRunner(@CommandDb Jdbi jdbi) { this.jdbi = jdbi; }

    @Override public <T> T inTransaction(Supplier<T> work) {
        if (CURRENT.isBound()) return work.get();                                    // join the outer transaction
        return jdbi.inTransaction(h -> ScopedValue.where(CURRENT, h).call(work::get));
    }
    <D> D dao(Class<D> type) {                       // adapters call this to get a DAO on the current handle
        return CURRENT.isBound() ? CURRENT.get().attach(type) : jdbi.onDemand(type);
    }
}
```

- Use case: `return tx.inTransaction(() -> { repo.update(c); events.publish(evt); return c.id(); });`.
  The repository adapter (and an outbox adapter, if used) obtain DAOs through `JdbiTransactionRunner.dao(...)`, so all writes share the handle.
- If the project uses JTA `@Transactional` instead, drop this port. JDBI joins the JTA transaction on the
  enlisted connection. Do not combine both mechanisms.
- `ScopedValue` is final in Java 25 (JEP 506). On Java 21 without previews, use a `ThreadLocal<Handle>` set and cleared in
  try/finally. Never let the handle escape the transaction (no async work holding it).

## 3. Optimistic locking update

```java
@SqlUpdate("""
    UPDATE customer
       SET name = :name, email = :email, status = :status,
           version = version + 1, updated_at = now()
     WHERE id = :id AND version = :version AND deleted_at IS NULL""")
int update(@BindMethods CustomerRow row);            // 0 rows -> stale version (or missing row)
```

- The domain aggregate carries `version`, which is loaded with the row. The adapter compares the update count and throws a domain
  `ConcurrentUpdateException`. The HTTP layer maps it to 409 `application/problem+json` (with Quarkus, a `@ServerExceptionMapper`).
- To tell "not found" (404) apart from "stale" (409), run `SELECT EXISTS(...)` only after a 0-row update.
- Never retry blindly on conflict inside the transaction. Let the client re-read (or retry the whole use case if the ADR says so).

## 4. Joins without N+1: `@UseRowReducer` with records

```java
public record OrderRow(UUID id, String status, Instant createdAt) {}
public record OrderLineRow(UUID id, String sku, int quantity) {}
public record OrderWithLines(OrderRow order, List<OrderLineRow> lines) {}   // mutable list only while reducing

@RegisterConstructorMapper(value = OrderRow.class, prefix = "o")
@RegisterConstructorMapper(value = OrderLineRow.class, prefix = "l")
public interface OrderDao {
    @SqlQuery("""
        SELECT o.id o_id, o.status o_status, o.created_at o_created_at,
               l.id l_id, l.sku l_sku, l.quantity l_quantity
          FROM orders o LEFT JOIN order_line l ON l.order_id = o.id
         WHERE o.customer_id = :customerId
         ORDER BY o.created_at DESC, o.id, l.line_no""")
    @UseRowReducer(OrderReducer.class)
    List<OrderWithLines> findByCustomer(UUID customerId);

    class OrderReducer implements LinkedHashMapRowReducer<UUID, OrderWithLines> {
        @Override public void accumulate(Map<UUID, OrderWithLines> map, RowView rv) {
            var agg = map.computeIfAbsent(rv.getColumn("o_id", UUID.class),
                    id -> new OrderWithLines(rv.getRow(OrderRow.class), new ArrayList<>()));
            if (rv.getColumn("l_id", UUID.class) != null) agg.lines().add(rv.getRow(OrderLineRow.class));
        }
    }
}
```

- The adapter maps to domain with `List.copyOf(lines)`. Prefixed mappers need column aliases (`o_id`), because `SELECT t.*` yields
  unprefixed labels.
- A JOIN that is paginated by root needs the page applied to the roots first:
  `FROM (SELECT ... FROM orders WHERE ... ORDER BY ... LIMIT :limit) o LEFT JOIN order_line l ...`.
- Alternative with two queries: load the roots, then `SELECT ... FROM order_line WHERE order_id = ANY(:ids)`
  (PostgreSQL, `bindArray("ids", UUID.class, ids)`; elsewhere `IN (<ids>)` with `@BindList`) and group by `orderId` in Java.
- JDBI 3.55 adds `JoinRowReducer` (Beta). It links through setter or adder methods, so it suits mutable classes rather than records.

## 5. Keyset pagination

```java
public record CustomerCursor(Instant createdAt, UUID id) {}   // opaque to clients: base64url(createdAt|id)

@SqlQuery("""
    SELECT id, name, email, status, version, created_at FROM customer
     WHERE deleted_at IS NULL
     ORDER BY created_at DESC, id DESC
     LIMIT :limit""")
List<CustomerRow> firstPage(int limit);

@SqlQuery("""
    SELECT id, name, email, status, version, created_at FROM customer
     WHERE deleted_at IS NULL AND (created_at, id) < (:createdAt, :id)
     ORDER BY created_at DESC, id DESC
     LIMIT :limit""")
List<CustomerRow> nextPage(Instant createdAt, UUID id, int limit);
```

- Index (PostgreSQL partial index): `CREATE INDEX customer_created_id_idx ON customer (created_at DESC, id DESC) WHERE deleted_at IS NULL;`
- Fetch `limit + 1` rows to know whether there is a next page. Return a cursor from the last row returned. Cap `limit`
  (for example at 100) in the resource, as a Bean Validation `@Max`.
- The tie-breaker (`id`) is mandatory, because timestamps are not unique. The row-value comparison must use the same columns and
  direction as the `ORDER BY`.
- Validate and decode the cursor at the boundary. A malformed cursor gives 400, never a SQL error.

## 6. Batching

```java
@SqlBatch("""
    INSERT INTO order_line (id, order_id, sku, quantity, line_no)
    VALUES (:l.id, :orderId, :l.sku, :l.quantity, :l.lineNo)""")
void insertLines(@Bind("orderId") UUID orderId, @BindMethods("l") List<OrderLineInsert> lines);
```

- A constant parameter (`orderId`) is bound for every element. Iterable parameters are zipped per element (this is the documented
  `@BindBean("user") User...` pattern).
- Fluent equivalent: `PreparedBatch b = handle.prepareBatch(sql); for (...) b.bind(...).add(); int[] counts = b.execute();`.
- Check `counts` when every element must affect exactly one row.
- For very large loads, split into chunks (for example 1,000 rows per execute) inside the same transaction, or use the engine's
  bulk loader (PostgreSQL `COPY` through the driver) for imports. Never use `@BindList`/`<placeholders>` in a batch, because the rendered statement is cached for all elements.

## 7. Example: outbox write (if the ADR uses a transactional outbox)

```java
@SqlUpdate("""
    INSERT INTO outbox (id, aggregate_type, aggregate_id, event_type, payload, created_at)
    VALUES (:id, :aggregateType, :aggregateId, :eventType, CAST(:payload AS jsonb), now())""")
void insert(@BindMethods OutboxRow row);

@SqlQuery("""
    SELECT id, aggregate_type, aggregate_id, event_type, payload::text AS payload, created_at
      FROM outbox WHERE published_at IS NULL
     ORDER BY created_at, id
     LIMIT :limit
       FOR UPDATE SKIP LOCKED""")
List<OutboxRow> lockBatch(int limit);
```

- The use case's state change and `insert` run on the same handle (section 2). The poller runs `lockBatch` and then
  publishes and marks `published_at` in its own short transaction. Concurrent pollers skip each other's rows.
- The payload is serialized (e.g. with Jackson) in the adapter. In Quarkus native builds, register payload records for reflection.
- Consumers must be idempotent (store processed event ids), because delivery is at-least-once.

## 8. Dynamic filters without injection

```java
List<CustomerRow> search(Handle h, CustomerFilter f, CustomerSort sort, int limit) {
    var where = new ArrayList<String>(List.of("deleted_at IS NULL"));
    var q = new HashMap<String, Object>();
    if (f.status() != null) { where.add("status = :status"); q.put("status", f.status().name()); }
    if (f.nameLike() != null) { where.add("name ILIKE :name ESCAPE '\\'");   // PostgreSQL ILIKE
        q.put("name", "%" + escapeLike(f.nameLike()) + "%"); }
    return h.createQuery("SELECT id, name, email, status, version, created_at FROM customer WHERE <where> ORDER BY <sort>, id LIMIT :limit")
            .define("where", String.join(" AND ", where))      // fragments are code constants only
            .define("sort", sort.column)                         // enum whitelist
            .bindMap(q).bind("limit", limit)
            .mapTo(CustomerRow.class).list();
}
```

Only code-owned strings go into `define`. Every user-supplied value is bound.

## 9. Migration examples (Flyway file names, PostgreSQL DDL)

```sql
-- V7__add_customer_phone.sql  (expand: nullable column, no rewrite of existing rows)
ALTER TABLE customer ADD COLUMN phone text;

-- V8__index_order_customer_fk.sql
CREATE INDEX IF NOT EXISTS order_customer_id_idx ON orders (customer_id);

-- later release, after code stops reading the old column (contract):
-- V12__drop_customer_legacy_phone.sql
ALTER TABLE customer DROP COLUMN legacy_phone;
```

- Use one logical change per file. Do not mix DDL with large data backfills. Write backfills as batched, restartable migrations.
- PostgreSQL: add `NOT NULL` in two steps on large tables: add `CHECK (col IS NOT NULL) NOT VALID`, `VALIDATE CONSTRAINT`, then
  `SET NOT NULL`.
