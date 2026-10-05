# AssertJ cookbook

`import static org.assertj.core.api.Assertions.*;` Always start with `assertThat(actual)` and add `.as("context")` before the assertion when the failure would otherwise be unclear.

## Basics

```java
assertThat(name).isEqualTo("Ada").startsWith("A").hasSize(3);
assertThat(name).isBlank();  assertThat(name).isNotBlank();
assertThat(text).containsIgnoringCase("error").doesNotContain("password");
assertThat(code).matches("[A-Z]{3}-\\d{4}");
assertThat(flag).isTrue();
assertThat(value).isNull();  assertThat(value).isNotNull();
assertThat(a).isSameAs(b);   // identity, rarely needed
```

## Numbers and money

```java
assertThat(count).isPositive().isLessThanOrEqualTo(100).isBetween(1, 100);
assertThat(ratio).isCloseTo(0.33, within(0.01));
assertThat(amount).isEqualByComparingTo("118.00");      // BigDecimal: ignores scale (118.0 == 118.00)
assertThat(amount).isEqualTo(new BigDecimal("118.00")); // BigDecimal: scale must match too
```

## Collections

```java
assertThat(list).hasSize(3).isNotEmpty();
assertThat(list).isEmpty();
assertThat(list).containsExactly(a, b, c);              // order matters, nothing else
assertThat(list).containsExactlyInAnyOrder(c, a, b);
assertThat(list).contains(a).doesNotContain(d);
assertThat(list).containsOnly(a, b);                    // any order, duplicates allowed
assertThat(list).doesNotHaveDuplicates();
assertThat(list).allMatch(o -> o.total().signum() > 0);
assertThat(list).anySatisfy(o -> assertThat(o.status()).isEqualTo(PAID));
assertThat(list).allSatisfy(o -> assertThat(o.customerId()).isEqualTo(id));
assertThat(list).singleElement().extracting(Order::id).isEqualTo(orderId);
assertThat(list).first().isEqualTo(a);
assertThat(list).isSortedAccordingTo(Comparator.comparing(Order::createdAt));
```

Extract fields (records use accessor method references):

```java
assertThat(customers).extracting(Customer::name).containsExactly("Ada", "Alan");
assertThat(customers)
        .extracting(Customer::name, c -> c.emails().size())
        .containsExactly(tuple("Ada", 1), tuple("Alan", 2));
assertThat(orders).filteredOn(o -> o.status() == PAID).hasSize(2);
assertThat(orders).flatExtracting(Order::lines).hasSize(5);
```

Unmodifiable result:

```java
assertThatThrownBy(() -> result.add(x)).isInstanceOf(UnsupportedOperationException.class);
```

## Maps

```java
assertThat(map).hasSize(2).containsEntry("a", 1).doesNotContainKey("z");
assertThat(map).containsOnlyKeys("a", "b");
assertThat(map).containsExactlyInAnyOrderEntriesOf(Map.of("a", 1, "b", 2));
assertThat(map).extractingByKey("a").isEqualTo(1);
```

## Records and objects

Records have value equality: compare whole records when every field is deterministic.

```java
assertThat(actual).isEqualTo(new Customer(id, "Ada", List.of(email)));
```

When some fields are generated (ids, timestamps), compare the rest:

```java
assertThat(actual).usingRecursiveComparison()
        .ignoringFields("id", "createdAt")
        .isEqualTo(expected);

assertThat(actual).usingRecursiveComparison()
        .withComparatorForType(BigDecimal::compareTo, BigDecimal.class)
        .isEqualTo(expected);

assertThat(actual).extracting(Customer::name, Customer::status).containsExactly("Ada", ACTIVE);
assertThat(actual).returns("Ada", from(Customer::name)).returns(ACTIVE, from(Customer::status));
assertThat(actual).satisfies(c -> {
    assertThat(c.name()).isEqualTo("Ada");
    assertThat(c.emails()).hasSize(1);
});
assertThat(result).isInstanceOf(Approved.class);
assertThat(result).asInstanceOf(type(Approved.class))   // import static ...InstanceOfAssertFactories.type
       .extracting(Approved::authCode).isEqualTo("A1");
```

## Optional

```java
assertThat(repository.findById(id)).isPresent().get().extracting(Customer::name).isEqualTo("Ada");
assertThat(repository.findById(id)).hasValue(expectedCustomer);
assertThat(repository.findById(id)).hasValueSatisfying(c -> assertThat(c.name()).isEqualTo("Ada"));
assertThat(repository.findById(unknown)).isEmpty();
```

## Exceptions

```java
assertThatThrownBy(() -> service.place(order))
        .isInstanceOf(PaymentFailedException.class)
        .hasMessage("payment failed for order %s", order.id())
        .hasCauseInstanceOf(GatewayTimeoutException.class)
        .hasRootCauseMessage("read timed out");

assertThatExceptionOfType(IllegalArgumentException.class)
        .isThrownBy(() -> new Email("not-an-email"))
        .withMessageContaining("email")
        .withNoCause();                                  // only when no cause is expected

assertThatIllegalArgumentException().isThrownBy(() -> Quantity.of(-1));
assertThatIllegalStateException().isThrownBy(() -> order.ship());
assertThatNullPointerException().isThrownBy(() -> new Customer(null, "Ada", List.of())).withMessage("id");

assertThatCode(() -> validator.validate(order)).doesNotThrowAnyException();

Throwable thrown = catchThrowable(() -> service.place(order));     // when you need the instance
assertThat(thrown).isInstanceOf(PaymentFailedException.class);
var ex = catchThrowableOfType(PaymentFailedException.class, () -> service.place(order));
assertThat(ex.orderId()).isEqualTo(order.id());
```

A single chain must be consistent: `hasCauseInstanceOf` and `withNoCause`/`hasNoCause` contradict each other.

## Dates and times

```java
assertThat(order.createdAt()).isEqualTo(FIXED_NOW);                      // with an injected Clock
assertThat(order.createdAt()).isAfter(start).isBeforeOrEqualTo(end);
assertThat(token.expiresAt()).isCloseTo(FIXED_NOW.plus(Duration.ofMinutes(15)), within(1, ChronoUnit.SECONDS));
```

## Files and paths

```java
assertThat(path).exists().isRegularFile().hasExtension("csv");
assertThat(path).content(StandardCharsets.UTF_8).contains("order-1");
assertThat(path).hasContent("id,total\norder-1,10.00");
assertThat(dir).isDirectoryContaining("glob:**.csv");
```

## Futures

```java
assertThat(future).succeedsWithin(Duration.ofSeconds(2)).isEqualTo(expected);
assertThat(future).failsWithin(Duration.ofSeconds(2))
        .withThrowableOfType(ExecutionException.class)
        .withCauseInstanceOf(PaymentFailedException.class);
```

## Soft assertions

```java
SoftAssertions.assertSoftly(softly -> {
    softly.assertThat(invoice.number()).startsWith("INV-");
    softly.assertThat(invoice.total()).isEqualByComparingTo("118.00");
    softly.assertThat(invoice.lines()).hasSize(2);
});
```

Or as an extension:

```java
@ExtendWith(SoftAssertionsExtension.class)
class InvoiceTest {
    @InjectSoftAssertions SoftAssertions softly;
    @Test void issuesInvoice() { softly.assertThat(issue().status()).isEqualTo(ISSUED); }   // assertAll() is implicit
}
```

## Custom conditions and reusable assertions

```java
Condition<Order> paid = new Condition<>(o -> o.status() == PAID, "paid");
assertThat(order).is(paid);
assertThat(orders).areExactly(2, paid);
assertThat(orders).haveAtLeastOne(new Condition<>(o -> o.lines().size() > 3, "more than 3 lines"));
```

For a domain type asserted in many tests, a small static helper keeps tests readable:

```java
static void assertPaid(Order order, long expectedCents) {
    assertThat(order.status()).as("status of %s", order.id()).isEqualTo(PAID);
    assertThat(order.totalCents()).as("total of %s", order.id()).isEqualTo(expectedCents);
}
```

## JUnit to AssertJ translation

| JUnit (forbidden) | AssertJ |
|---|---|
| `assertEquals(expected, actual)` | `assertThat(actual).isEqualTo(expected)` |
| `assertTrue(list.isEmpty())` | `assertThat(list).isEmpty()` |
| `assertTrue(x > 0)` | `assertThat(x).isPositive()` |
| `assertNotNull(x)` | `assertThat(x).isNotNull()` (usually assert something stronger) |
| `assertNull(x)` | `assertThat(x).isNull()` |
| `assertThrows(E.class, () -> f())` | `assertThatThrownBy(() -> f()).isInstanceOf(E.class)` |
| `assertDoesNotThrow(() -> f())` | `assertThatCode(() -> f()).doesNotThrowAnyException()` |
| `assertAll(...)` | `SoftAssertions.assertSoftly(...)` |
| `assertIterableEquals(a, b)` | `assertThat(b).containsExactlyElementsOf(a)` |
