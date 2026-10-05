---
name: quarkus
description: Quarkus 3 application rules - Gradle and Maven build commands, configuration and profiles, Quarkus REST resources, Bean Validation, exception mapping to problem JSON, security (SmallRye JWT shown), Dev Services, health, logging, with stack choices taken from the ADRs and quarkus pack options. Use before editing application*.properties/yaml, the build file or REST resources.
applies-to: quarkus 3.x, java>=21, gradle or maven
last-verified: 2026-10-05
sources: agentic-backbone skills/quarkus/java-quarkus (+ backbone 4-KNOWLEDGE, 6-MEMORY, 7-CONVENTIONS); plan-marshall pm-dev-java java-quarkus (rest-validation, testing, templates); Quarkus guides rest, validation, cdi-reference, gradle-tooling, maven-tooling, logging, management-interface-reference, checked 2026-10-05; origin-project choices made conditional on the ADRs
---

# Quarkus

The accepted ADRs and `backbone/4-KNOWLEDGE.md` override this skill.

This skill assumes Quarkus REST (formerly RESTEasy Reactive) with Jackson and ArC. Everything else is a stack ADR decision:
the build tool (java option `gradle` or `maven`), the container engine (`HARNESS_CONTAINER_ENGINE`), the data-access library
(see the jdbi skill if adopted), the database, migrations, messaging and authentication. Hibernate **Validator** (Bean
Validation) is assumed for input validation.

## Build commands

| Task | Gradle | Maven |
|---|---|---|
| Dev mode (live reload, Dev Services, Dev UI) | `./gradlew quarkusDev` | `./mvnw quarkus:dev` |
| Unit + `@QuarkusTest` tests | `./gradlew test` | `./mvnw test` |
| JVM package (`quarkus-app/`) | `./gradlew build` → `build/quarkus-app/` | `./mvnw package` → `target/quarkus-app/` |
| `@QuarkusIntegrationTest` against the built artifact | `./gradlew quarkusIntTest` (`src/integrationTest/java`) | `./mvnw verify` (Failsafe, `*IT` classes; `-DskipITs=false` if the POM skips them) |
| Native executable (`*-runner`) | `./gradlew build -Dquarkus.native.enabled=true -Dquarkus.native.container-build=true` → `build/` | `./mvnw package -Dquarkus.native.enabled=true -Dquarkus.native.container-build=true` → `target/` |
| Native tests | `scripts/harness/packs/quarkus/native-test.sh` (`testNative`) | same script (`./mvnw verify -Dquarkus.native.enabled=true ...`) |
| Add an extension | `./gradlew addExtension --extensions=quarkus-smallrye-health` | `./mvnw quarkus:add-extension -Dextensions=quarkus-smallrye-health` |

Read `native.md` before running native builds or tests. `HARNESS_BUILD_CMD`/`HARNESS_TEST_CMD` in `backbone/harness.conf`
hold the project's compile and test commands.

- Versions come from the Quarkus platform BOM, so extensions have no version. Gradle:
  `implementation(enforcedPlatform("io.quarkus.platform:quarkus-bom:<v>"))`, other libraries in `gradle/libs.versions.toml`.
  Maven: import `io.quarkus.platform:quarkus-bom` in `<dependencyManagement>` (`<type>pom</type>`, `<scope>import</scope>`).
- Typical extensions (add only those the ADRs call for): `quarkus-rest`, `quarkus-rest-jackson`, `quarkus-hibernate-validator`,
  `quarkus-arc`, a JDBC driver plus `quarkus-agroal`, the migration tool's extension (e.g. `quarkus-flyway`), the auth extension
  (e.g. `quarkus-smallrye-jwt`), `quarkus-smallrye-health`, `quarkus-micrometer-registry-prometheus`, `quarkus-logging-json`.
- Not allowed, depending on adopted options and ADRs: `quarkus-spring-*` (option `no-spring`); `quarkus-hibernate-orm*` and
  `*panache*` (jdbi option `no-orm`); Lombok (java option `no-lombok`); anything an ADR rules out.
- Test dependencies: `io.quarkus:quarkus-junit5` (named `quarkus-junit` in the newest 3.x platforms; use the name your BOM
  provides), `quarkus-junit5-mockito` / `quarkus-junit-mockito`, `io.rest-assured:rest-assured`, and the assertion library
  (AssertJ with java option `junit5-assertj`). Gradle `testImplementation(...)`; Maven `<scope>test</scope>`.
- Compile with `-parameters`. Gradle: `tasks.withType<JavaCompile> { options.compilerArgs.add("-parameters") }`. Maven:
  `maven-compiler-plugin` `<parameters>true</parameters>` (generated POMs have it). REST and SQL-mapping libraries (e.g. JDBI)
  rely on parameter names.

## Configuration

- Use `application.properties` (or YAML with `quarkus-config-yaml`). Profiles are prefixes: `%dev.`, `%test.`, `%prod.`.
  A property without a prefix applies to all profiles.
- Group application settings in a `@ConfigMapping(prefix = "app.x")` interface injected by constructor. Use `@ConfigProperty`
  only for a single stray value. Mappings are validated at startup: a missing required key fails fast.
  Use `@WithDefault` and `Optional<T>`, and constraint annotations, which are validated when Hibernate Validator is present.
- No secrets in properties files or in git. Use `${ENV_VAR}` expansion, env vars (`QUARKUS_DATASOURCE_PASSWORD`),
  or a mounted file or secret store. `%dev`/`%test` values may be throwaway local credentials only.
- Build-time properties (`quarkus.management.enabled`, `quarkus.native.*`, extension toggles, `quarkus.datasource.db-kind`)
  are fixed into the artifact. Setting them at runtime has no effect. Changing one means rebuilding.
- If the architecture ADR separates command and query datasources: named datasources `quarkus.datasource."command".*` and
  `quarkus.datasource."query".*`; inject `@io.quarkus.agroal.DataSource("query") AgroalDataSource` where the data-access
  library is wired (jdbi skill if adopted).
- Never hardcode ports, hostnames, framework paths or feature flags. Use config with sane defaults.

## REST resources (Quarkus REST)

- Resources are thin: they delegate to application code (one use case per operation where the ADR uses use cases) and contain
  no business logic or SQL. With option `hexagonal-layers` they live in the infrastructure layer (e.g. `infra/.../rest`).
- Use `@Path("/api/v1/customers")` on the class and JAX-RS verbs on methods. The body parameter needs no annotation. Use `@PathParam`,
  `@QueryParam` and `@HeaderParam` (or `@RestPath`/`@RestQuery`/`@RestHeader`). Prefer constructor injection.
- Return the response record directly (200), or `RestResponse<T>` when you need a status or headers. Prefer it to untyped `Response`,
  because its entity type is known at build time and so registered for native reflection:
  `RestResponse.ResponseBuilder.create(Status.CREATED, dto).location(uri).build()` for 201 with a `Location` header.
- DTOs are records next to the resource (e.g. `.../rest/dto`, or the place the project ADR names). Map DTO to command to domain
  in the resource or a mapper, and never expose domain types or persistence row types over HTTP.
- Execution model: methods that return plain types run on a worker thread. Methods that return `Uni`/`Multi`/`CompletionStage` run on
  the event loop. JDBC-based libraries (JDBI, plain JDBC) are blocking, so never return `Uni` from code that calls them unless
  it is marked `@Blocking`. `@RunOnVirtualThread` is allowed if the project ADR enables it. Never block the event loop.
- Contract first: keep the OpenAPI document and the resource in sync (openapi and api-design skills).

## Validation

- Put `@Valid` on the body parameter and constraints on record components. Put constraints directly on path, query and header parameters.
- Violations on endpoint parameters become HTTP 400 automatically. Violations anywhere else (service methods,
  return values) are server errors (5xx) by design.
- Domain invariants stay in record compact constructors (`Objects.requireNonNull`, range checks) and do not rely on
  Bean Validation. Bean Validation guards the HTTP boundary.
- Read `rest-validation.md` when you add or change request DTOs or parameters, or write their tests.

## Errors: RFC 9457 problem details

- Map exceptions globally in a class with `@ServerExceptionMapper` methods (infrastructure layer under `hexagonal-layers`).
  A mapper declared inside a resource class only handles that class's exceptions.
- Response: `Content-Type: application/problem+json` with `type`, `title`, `status`, `detail`, `instance`
  and extension members (for example `errors[]`, `correlationId`). Never include stack traces, SQL or internal class names.
- Mapping: domain `NotFound` → 404, validation and domain rule → 400 or 422 (pick one in an ADR), optimistic-lock or
  conflict → 409, authentication → 401, authorization → 403, rate limit → 429, unexpected → 500 (log with correlation id).
- A custom `ExceptionMapper<ValidationException>` replaces the built-in violation report. It must keep 400 for
  endpoint-parameter violations and 500 for the others.

```java
class ProblemMappers {                       // outside any resource class = global
    @ServerExceptionMapper
    RestResponse<Problem> conflict(ConcurrentUpdateException e, UriInfo uri) {   // domain exception; Problem = boundary record
        return RestResponse.ResponseBuilder.create(Status.CONFLICT, Problem.of(409, "Conflict", e.getMessage(), uri))
            .type("application/problem+json").build();
    }
}
```

## Security

- Deny by default. Every resource method has `@RolesAllowed`, `@Authenticated` or an explicit `@PermitAll`
  with a comment that justifies it. Set `quarkus.security.jaxrs.deny-unannotated-endpoints=true`.
- Read the caller via constructor-injected `SecurityIdentity` (or `JsonWebToken` with JWT). Never parse the `Authorization`
  header yourself. Ownership checks compare the resource owner with the authenticated principal, never with a client-sent id.
- If the ADR chose bearer JWTs with SmallRye JWT: `JsonWebToken` is a request-scoped proxy; configure
  `mp.jwt.verify.publickey.location` / `mp.jwt.verify.issuer` (and `smallrye.jwt.*`) per profile. Keys are never in git.
  For OIDC or other mechanisms, follow the matching Quarkus guide.
- Tests: `quarkus-test-security` `@TestSecurity(user = "u", roles = "ADMIN")`, or `quarkus-test-security-jwt` `@JwtSecurity`
  for claims. Test 401, 403 and the happy path for every endpoint.

## Dev Services, health, metrics, logging

- Dev Services start the database, broker and similar services of the extensions present (e.g. PostgreSQL, Kafka, RabbitMQ)
  in dev and test when no URL is configured. They need the container engine (`HARNESS_CONTAINER_ENGINE`) running.
  Do not set `%dev`/`%test` JDBC URLs, because that disables Dev Services.
  - With Docker: the daemon socket is used directly.
  - With Podman: set `DOCKER_HOST` to the Podman socket (on Linux:
    `export DOCKER_HOST=unix://$(podman info --format '{{.Host.RemoteSocket.Path}}')`; Podman Machine on macOS).
- Health: `quarkus-smallrye-health` → `/q/health/live`, `/q/health/ready`, `/q/health/started`. Add a `@Readiness`
  check per external dependency the service cannot work without. Liveness must not check dependencies.
- Metrics: Micrometer Prometheus → `/q/metrics`. In containers, serve both on the management port (`container.md`).
- Logging: `io.quarkus.logging.Log.infof(...)` (static, build-time injected) or `org.jboss.logging.Logger`; SLF4J also works
  through the JBoss bridge. Use one logging API, as the project decides, and no `System.out`. Use JSON logs
  (`quarkus-logging-json`) in prod and plain logs in dev (`%dev.quarkus.log.console.json.enabled=false`). Put correlation and
  request ids in MDC through a JAX-RS filter. Never log tokens, passwords or personal data.

## Checklist

- [ ] No extension or library that an adopted option or ADR rules out (Spring, ORM, Lombok...). No secrets in properties.
- [ ] Resource delegates to application code. DTOs are records. The status codes match the OpenAPI contract.
- [ ] Every endpoint has an explicit security annotation and tests for 401, 403 and the happy path.
- [ ] Inputs are validated at the boundary, and errors are `application/problem+json`.
- [ ] No blocking calls on the event loop.
- [ ] `HARNESS_TEST_CMD` passes. Native-relevant changes (reflection, resources) are checked with `native.md`.

Read `testing.md` when you write `@QuarkusTest`/`@QuarkusIntegrationTest`/RestAssured tests.
Read `native.md` when you build native, add reflection-reached types or debug native-only failures.
Read `container.md` when you change container images, compose files, health probes or TLS.

## Linked skills

- quarkus-cdi: bean scopes, layer placement, producers.
- jdbi (if adopted): persistence adapters, transactions, migrations.
- api-design, openapi: HTTP contract. security: threat-driven checks.
- java, java-test (if adopted), java-review: language, tests and review. module-testing, code-quality.
- containers, container-security (if adopted): image and runtime hardening.
- architecture, adr-writing: layering decisions and recording stack choices.
