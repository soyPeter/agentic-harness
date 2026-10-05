# Quarkus testing

Quarkus test support runs on JUnit 5 (Jupiter). If the java option `junit5-assertj` is adopted, assert with AssertJ only (no JUnit
`Assertions`, no Hamcrest in new code, except RestAssured's `body(...)` matchers); the examples below use AssertJ.
Run with `HARNESS_TEST_CMD` (Gradle `./gradlew test` · Maven `./mvnw test`). Coverage can be collected by `quarkus-jacoco`
(Gradle `testImplementation("io.quarkus:quarkus-jacoco")`, Maven dependency with `<scope>test</scope>`); the report lands in
`build/jacoco-report/` (Gradle) or `target/jacoco-report/` (Maven); check `quarkus.jacoco.report-location`. Coverage targets come
from `module-testing` and the project rules.

## Pick the cheapest test that proves the behaviour

| Test | What runs | Use for |
|---|---|---|
| Plain JUnit (no annotation) | Your class only | Domain records, use cases with hand-written fakes or mocks of ports. This is most tests. |
| `@QuarkusComponentTest` | ArC with only the listed components, unsatisfied deps auto-mocked | Infra beans whose CDI wiring or config matters, without HTTP or DB |
| `@QuarkusTest` | Whole app in the test JVM with Dev Services (the database, broker etc. the app uses) | Resources (HTTP via RestAssured), persistence adapters against the real database engine, security |
| `@QuarkusIntegrationTest` | Built artifact (jar, native or container) in a separate process | Smoke and end-to-end via HTTP only. No injection. |

Use cases that carry no framework-specific wiring are tested without Quarkus: construct them with `new` and fake or mock ports.
(With option `hexagonal-layers` this holds for all of `app/`.)

## @QuarkusTest

```java
@QuarkusTest
class CustomerResourceTest {

    @InjectMock CreateCustomerUseCase createCustomer;   // must be normal-scoped (e.g. @ApplicationScoped producer)

    @Test
    @TestSecurity(user = "alice", roles = "ADMIN")
    void ac3_createsCustomerAndReturnsLocation() {
        when(createCustomer.execute(any())).thenReturn(new CustomerId(UUID.fromString("0f0e...")));

        var location = given().contentType(ContentType.JSON)
            .body("""
                {"name":"Alice","email":"alice@example.com"}
                """)
            .when().post("/api/v1/customers")
            .then().statusCode(201)
            .extract().header("Location");

        assertThat(location).endsWith("/api/v1/customers/0f0e...");
    }

    @Test
    void ac3_rejectsAnonymousCaller() {
        given().contentType(ContentType.JSON).body("{}").when().post("/api/v1/customers")
            .then().statusCode(401);
    }
}
```

- `@InjectMock` (`io.quarkus.test.InjectMock`, from `quarkus-junit5-mockito` / `quarkus-junit-mockito`) replaces the bean
  for this test class only. It works for normal-scoped beans (`@ApplicationScoped`, `@RequestScoped`). For `@Singleton`
  beans, add `@MockitoConfig(convertScopes = true)` next to `@InjectMock`. This changes the scope for the test, so use it only when needed.
- To assert on JSON bodies with AssertJ, extract them: `var dto = ...extract().as(CustomerResponse.class);`
  `assertThat(dto.name()).isEqualTo("Alice");`.
- The app starts once per test run and is reused across `@QuarkusTest` classes with the same profile and resources.
  Each distinct `@TestProfile` restarts it, so keep few profiles.
- Test names or `@DisplayName` carry the acceptance-criterion id they prove (`ac3_...` or `"AC-3: ..."`).
- Do not use `@Inject` fields in production code. They are fine in test classes.

## Test profiles and config

```java
public class PollerDisabledProfile implements QuarkusTestProfile {     // example: switch off a background job
    @Override public Map<String, String> getConfigOverrides() {
        return Map.of("app.poller.enabled", "false");
    }
}

@QuarkusTest @TestProfile(PollerDisabledProfile.class)
class CustomerWithoutPollerTest { ... }
```

Put test-only config in `%test.` properties in `src/main/resources/application.properties` or in
`src/test/resources/application.properties`. Never point `%test` at a shared database.

## Database tests (persistence adapters)

Data access uses the library the ADR chose (see the jdbi skill if adopted); the rules are library-neutral.

- Use the production database engine through Dev Services (default in `@QuarkusTest` when no `%test` JDBC URL is set), or
  Testcontainers for plain JUnit adapter tests. Do not substitute an in-memory engine such as H2 for another database:
  SQL dialect, locking and JSON types differ.
- Run the real migrations with the migration tool the ADR chose (Flyway: `quarkus.flyway.migrate-at-start=true`), so the
  schema under test is the production schema.
- Isolate tests: each test creates its own rows with unique ids, or truncates the touched tables in `@BeforeEach`
  (if the architecture ADR separates command and query datasources, through the command one). Do not depend on test order.
- Test the adapter contract: mapping (`*Row` to domain), not found → `Optional.empty()`, optimistic-lock conflict →
  domain exception, pagination boundaries, and batch inserts.
- Dev Services and Testcontainers need the engine in `HARNESS_CONTAINER_ENGINE` running. With Docker they use the daemon
  socket directly. **With Podman:** export `DOCKER_HOST` pointing at the Podman socket; if Ryuk cannot start under rootless
  Podman, set `TESTCONTAINERS_RYUK_DISABLED=true` for local runs only and clean up containers manually.

## @QuarkusIntegrationTest

```java
@QuarkusIntegrationTest
class HealthIT {
    @Test
    void ac1_reportsUp() {
        var status = given().when().get("/q/health/ready")
            .then().statusCode(200).extract().path("status");
        assertThat(status).isEqualTo("UP");
    }
}
```

- It runs against the packaged app (Gradle: `./gradlew quarkusIntTest`, native via `testNative`; Maven: `*IT` classes run by
  Failsafe in `./mvnw verify`, add `-DskipITs=false` if the POM skips them, native with `-Dquarkus.native.enabled=true`). Interact over HTTP only, with no
  `@Inject` and no `@InjectMock`.
- The artifact runs with the `prod` profile by default. Override with `quarkus.test.integration-test-profile=test`.
  Dev Services containers started for the test are passed to the launched artifact.
- Mark tests that cannot run against the packaged app with `@DisabledOnIntegrationTest`.
- With the management interface enabled, health is on port 9000 (`container.md`). Probe the URL that production probes use.

## Messaging (if the ADR uses SmallRye Reactive Messaging)

- Use the in-memory connector for channel-level tests (`io.smallrye.reactive:smallrye-reactive-messaging-in-memory`,
  `InMemoryConnector.switchIncomingChannelsToInMemory(...)` in a `QuarkusTestResourceLifecycleManager`). Use the broker's
  Dev Service (e.g. Kafka, RabbitMQ) when you test the real broker binding.
- Example, if the ADR uses a transactional outbox: test it in two parts: (1) the use case writes the event row in the same
  transaction as the state change (and on rollback, no row); (2) the poller publishes and marks rows. Use `Awaitility` for async
  assertions. Never use `Thread.sleep`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `@InjectMock` fails on a bean | Bean is `@Singleton`/`@Dependent` | Make it `@ApplicationScoped`, or use `@MockitoConfig(convertScopes = true)` for `@Singleton` |
| Dev Services do not start | Engine not running, or (Podman) `DOCKER_HOST` not set | Start the Docker daemon, or the Podman machine/socket and export `DOCKER_HOST` |
| Dev Services ignored | A `%test` JDBC URL is configured | Remove it |
| Slow suite | Many distinct `@TestProfile`s or test resources | Merge profiles, and move logic tests to plain JUnit |
| `@Inject` is null in an IT | `@QuarkusIntegrationTest` has no CDI | Test via HTTP |
| Coverage 0% | `quarkus-jacoco` missing | Add it as a test dependency (Gradle `testImplementation`, Maven `<scope>test</scope>`) |
