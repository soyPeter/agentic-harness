---
name: java-test
description: JUnit 5 + AssertJ test rules (java option junit5-assertj) - AssertJ-only assertions, acceptance-criterion ids in test names, AAA, parameterised tests, exception assertions, soft assertions, @TempDir, mocks only at ports, no sleeps, test data factories, Gradle and Maven test and JaCoCo commands. Read before writing or changing any test.
applies-to: java>=21 (examples target Java 25)
last-verified: 2026-10-05
sources: adapted from decebals/claude-code-java test-quality (0d98fe9) and cuioss/plan-marshall testing standards; JUnit assertions, commons-io and Spring content removed; build commands for both Gradle and Maven; contradictory cause assertions fixed; JaCoCo version updated for Java 25
---

# Java tests

Method (what to test, AAA, isolation, coverage targets) comes from `module-testing`; this skill gives the Java mechanics. The accepted ADRs and `backbone/4-KNOWLEDGE.md` override this skill.

## Hard rules

1. JUnit 5 (Jupiter) only. No JUnit 4 (`org.junit.Test`, `@RunWith`, `@Rule`).
2. **AssertJ only**: `import static org.assertj.core.api.Assertions.*`. Never `assertEquals`, `assertTrue`, `assertFalse`, `assertNotNull`, `assertNull` or `assertThrows` from `org.junit.jupiter.api.Assertions`, and no Hamcrest.
3. Every test that proves an acceptance criterion names it: `@DisplayName("AC-2.1-1: returns only matching customers")`. One AC may need several tests; every AC in the task has at least one.
4. Test class mirrors the production class: `CustomerService` -> `CustomerServiceTest` in the same package; package-private test classes and methods (`class CustomerServiceTest`, `void ...()`).
5. Method names describe behaviour: `rejectsBlankName`, `returnsEmptyPageWhenNoMatch`. No `test1`, no `testMethodName`.
6. Arrange / Act / Assert, separated by blank lines; one behaviour per test; act is one call.
7. No `Thread.sleep`, no real time, no random without a fixed seed, no network, no shared mutable static state. Inject a `Clock` (`Clock.fixed(...)`); poll async results with a latch/future timeout.
8. Mock only ports you own (repository, gateway, clock interfaces). Never mock records, value objects, the class under test, or JDK/third-party types; prefer a hand-written in-memory fake for repositories.
9. Test data via static factory methods or records with sensible defaults rather than mutable builders (and no Lombok if option `no-lombok` is adopted).
10. Every bug fix starts with a failing test that reproduces it.
11. Tests are deterministic and order-independent; no `@TestMethodOrder` to make them pass.

## Shape

```java
class CustomerSearchTest {
    private final InMemoryCustomerRepository repository = new InMemoryCustomerRepository();
    private final CustomerSearch search = new CustomerSearch(repository);

    @Test
    @DisplayName("AC-2.1-1: returns only customers whose name matches the query")
    void returnsOnlyMatchingCustomers() {
        repository.save(aCustomer("Ada Lovelace"));
        repository.save(aCustomer("Alan Turing"));

        List<Customer> result = search.byName("ada");

        assertThat(result).extracting(Customer::name).containsExactly("Ada Lovelace");
    }
}
```

## Test data factories

```java
final class TestCustomers {
    private TestCustomers() {}
    static Customer aCustomer() { return aCustomer("Ada Lovelace"); }
    static Customer aCustomer(String name) {
        return new Customer(CustomerId.random(), name, List.of(new Email("ada@example.test")));
    }
}
Customer renamed = aCustomer().withName("Grace Hopper");   // variations via record "with" methods
```

Obviously fake data (`example.test` domains); never real personal data or secrets.

## Parameterised tests

```java
@ParameterizedTest(name = "AC-3.2-1: \"{0}\" is rejected")
@NullAndEmptySource
@ValueSource(strings = {" ", "\t"})
void rejectsBlankNames(String name) {
    assertThatThrownBy(() -> new Customer(CustomerId.random(), name, List.of()))
            .isInstanceOf(IllegalArgumentException.class);
}

@ParameterizedTest(name = "{0} cents with {1}% discount -> {2}")
@CsvSource({"1000, 10, 900", "999, 0, 999", "1, 50, 1"})
void appliesDiscount(long cents, int percent, long expected) {
    assertThat(Pricing.discount(cents, percent)).isEqualTo(expected);
}
```

Also `@EnumSource(value = OrderStatus.class, names = {"SHIPPED", "CANCELLED"})` and `@MethodSource("invalidOrders")` (a `static Stream<Arguments>`). Cover boundaries: empty, one, many, max, max+1, zero, negative.

## Exceptions, soft assertions, files

```java
assertThatThrownBy(() -> service.place(order))
        .isInstanceOf(PaymentFailedException.class)
        .hasMessageContaining(order.id().toString())
        .hasCauseInstanceOf(GatewayTimeoutException.class);     // never also hasNoCause()
assertThatCode(() -> validator.validate(validOrder)).doesNotThrowAnyException();

SoftAssertions.assertSoftly(softly -> {                         // several properties of one result
    softly.assertThat(invoice.total()).isEqualByComparingTo("118.00");
    softly.assertThat(invoice.status()).isEqualTo(InvoiceStatus.ISSUED);
});

@Test
void writesReport(@TempDir Path dir) throws IOException {        // JUnit cleans up; no commons-io
    Path out = dir.resolve("report.csv");

    exporter.export(orders, out);

    assertThat(out).content().contains("order-1");
}

assertThat(future).succeedsWithin(Duration.ofSeconds(2)).isEqualTo(expected);   // async, no sleep
```

## Mocks (ports only; Mockito shown, if the ADR accepts it)

```java
@ExtendWith(MockitoExtension.class)                  // import static org.mockito.BDDMockito.*
class PlaceOrderTest {
    @Mock PaymentGateway gateway;                    // port interface you own
    private final InMemoryOrders orders = new InMemoryOrders();

    @Test
    @DisplayName("AC-4.1-3: a declined payment leaves the order unpaid")
    void declinedPaymentLeavesOrderUnpaid() {
        given(gateway.charge(any())).willReturn(new Declined("insufficient funds"));
        var placeOrder = new PlaceOrder(gateway, orders, FIXED_CLOCK);

        Order order = placeOrder.handle(aCommand());

        assertThat(order.status()).isEqualTo(OrderStatus.PAYMENT_DECLINED);
        then(gateway).should().charge(argThat(c -> c.amountCents() == 1000));
    }
}
```

Assert outcomes; verify only interactions that are the observable effect (payment charged, message sent). Strict stubs fail on unused stubbing: delete it.

## Running tests and coverage

Run the suite with `HARNESS_TEST_CMD` from `backbone/harness.conf`. Single tests and coverage by build tool:

```bash
# Gradle (option gradle)
./gradlew test --tests 'com.example.customer.CustomerSearchTest'
./gradlew test --tests '*CustomerSearchTest.rejectsBlankQuery'
./gradlew test jacocoTestReport          # build/reports/jacoco/test/html/index.html
# Maven (option maven)
./mvnw test -Dtest=CustomerSearchTest
./mvnw test -Dtest='CustomerSearchTest#rejectsBlankQuery'
./mvnw verify                            # with jacoco-maven-plugin bound: target/site/jacoco/index.html
```

JaCoCo 0.8.14 or later is required for Java 25 class files. Gradle: `jacoco { toolVersion = "0.8.14" }` (or later) and the `jacocoTestReport` task. Maven: `org.jacoco:jacoco-maven-plugin` 0.8.14 or later with the `prepare-agent` and `report` goals.

Read `assertj.md` when you need an assertion for collections, maps, records, optionals, exceptions, dates, numbers, futures or custom conditions.

## Linked skills

- `module-testing`: test method, AAA, coverage targets, what to test.
- `java`: production code rules the tests exercise.
- `java-review`: judging whether the tests prove the ACs.
- `quarkus` (if adopted): `@QuarkusTest`, dev services, REST-assured component tests.
- `jdbi` (if adopted): repository tests against a real database.
