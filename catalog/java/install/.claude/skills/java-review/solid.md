# SOLID for Java reviews

| Principle | Rule | Typical violation | Fix |
|---|---|---|---|
| **S**ingle responsibility | a class has one reason to change | service that validates, persists, emails and formats | split by responsibility; one use case per application service |
| **O**pen/closed | add behaviour by adding code, not editing a central switch | `if (type == ...)` chains repeated in several places | sealed interface + one record per variant with exhaustive switch in one place, or a strategy per variant |
| **L**iskov substitution | subtypes honour the supertype contract | override throws `UnsupportedOperationException`, strengthens preconditions, weakens results | composition; split the interface; do not inherit to reuse code |
| **I**nterface segregation | clients depend only on methods they use | `CustomerRepository` with 20 methods injected where 1 is used | small role interfaces (`CustomerFinder`, `CustomerWriter`) |
| **D**ependency inversion | policy depends on abstractions it owns; details implement them | domain/application class instantiates a JDBC/HTTP client or imports its types | port interface in the domain/application package, adapter in infrastructure, constructor injection |

## Detection

- SRP: class name with `Manager`/`Helper`/`Util`/`And`; > 500 lines; > 7 injected dependencies; methods that share no fields; a change for one feature touches unrelated methods.
- OCP: the same `switch`/`instanceof` chain appears in more than one class; adding a variant needs edits in many files.
- LSP: `instanceof` checks on a supertype parameter; overrides that throw or do nothing; tests of the subclass that cannot reuse the supertype's tests.
- ISP: implementations with empty or throwing methods; mocks stubbing one method of a wide interface.
- DIP: `new` of infrastructure classes inside domain/application code; imports of `java.sql`, `java.net.http`, `org.jdbi`, `io.quarkus`, `jakarta.ws.rs` in domain packages; static calls to global singletons; `Instant.now()` instead of an injected `Clock`.

## DIP example

```java
// domain/application package: owns the port
public interface PaymentGateway {
    PaymentResult charge(Charge charge);
}
public record Charge(OrderId orderId, long amountCents, String currency) {
    public Charge { Objects.requireNonNull(orderId, "orderId"); Objects.requireNonNull(currency, "currency"); }
}

public final class PlaceOrder {
    private final PaymentGateway gateway;
    private final Orders orders;
    private final Clock clock;

    public PlaceOrder(PaymentGateway gateway, Orders orders, Clock clock) {   // constructor injection
        this.gateway = Objects.requireNonNull(gateway, "gateway");
        this.orders = Objects.requireNonNull(orders, "orders");
        this.clock = Objects.requireNonNull(clock, "clock");
    }

    public Order handle(PlaceOrderCommand cmd) {
        var order = Order.create(cmd, clock.instant());
        var result = gateway.charge(new Charge(order.id(), order.totalCents(), "EUR"));
        return orders.save(order.withPayment(result));
    }
}

// infrastructure package: implements the port, owns the HTTP details
final class HttpPaymentGateway implements PaymentGateway {
    private final HttpClient client;
    private final URI endpoint;
    HttpPaymentGateway(HttpClient client, URI endpoint) { this.client = client; this.endpoint = endpoint; }
    @Override public PaymentResult charge(Charge charge) { /* map to HTTP, translate errors */ }
}
```

`PlaceOrder` is testable with an in-memory `Orders` and a fake or mocked `PaymentGateway`; the wiring (CDI producer or `main`) is the only place that knows the concrete classes.

## Checklist

- [ ] Each new class can be described in one sentence without "and".
- [ ] Variants are modelled once (sealed type or strategy), not as repeated conditionals.
- [ ] No override throws `UnsupportedOperationException` or silently does nothing.
- [ ] Injected interfaces are narrow; no class depends on methods it does not call.
- [ ] Domain and application code depend on ports they own; adapters live in infrastructure.
- [ ] Dependencies arrive through the constructor; no `new` of collaborators with side effects, no static singletons, time via `Clock`.
- [ ] Composition over inheritance; inheritance only for true is-a with a stable contract.
- [ ] Do not add an interface with a single implementation unless it is a port across a layer boundary or needed for tests (YAGNI).
