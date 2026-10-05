# Inbound REST validation (Quarkus REST + Hibernate Validator)

Everything a resource reads from a request (body, path, query, header, cookie) is untrusted. Validate it at
the resource boundary before it reaches a use case. Fail closed.

## Dependency

```kotlin
implementation("io.quarkus:quarkus-hibernate-validator")      // Gradle (Kotlin DSL)
```

```xml
<dependency><groupId>io.quarkus</groupId><artifactId>quarkus-hibernate-validator</artifactId></dependency>  <!-- Maven -->
```

With the extension present, Quarkus validates constrained resource parameters automatically. No manual
`Validator` call is needed in resources.

## Request bodies

`@Valid` on the body parameter cascades into the record. Put the constraints on record components:

```java
public record CreateCustomerRequest(
        @NotBlank @Size(max = 100) String name,
        @NotBlank @Email @Size(max = 254) String email,
        @Valid @NotNull AddressRequest address,          // nested record: @Valid to cascade
        @Size(max = 20) List<@NotBlank @Size(max = 30) String> tags) {
}

@Path("/api/v1/customers")
public class CustomerResource {
    private final CreateCustomerUseCase createCustomer;
    public CustomerResource(CreateCustomerUseCase createCustomer) { this.createCustomer = createCustomer; }

    @POST
    @RolesAllowed("ADMIN")
    public RestResponse<CustomerResponse> create(@Valid @NotNull CreateCustomerRequest request) {
        // request satisfies every constraint here; map to a command and delegate
    }
}
```

## Path, query and header parameters

```java
@GET
@Path("/{id}")
public CustomerResponse get(
        @PathParam("id") @Pattern(regexp = "[0-9a-f-]{36}") String id,
        @QueryParam("limit") @DefaultValue("20") @Min(1) @Max(100) int limit,
        @HeaderParam("X-Tenant") @NotBlank @Size(max = 64) String tenant) { ... }
```

Rules:
- Every inbound parameter has a constraint. Collections and strings have a maximum size, numbers have a range, and ids
  have a format. Use an allow-list (`@Pattern`, enums) rather than a deny-list.
- Prefer typed parameters (`UUID`, `int`, enums, `LocalDate`). Conversion failures are rejected before
  your code runs. Check the status the project's mappers return for them (usually 400 or 404) and test it.
- Use group sequences or custom constraints for cross-field rules (for example `@ValidDateRange` on the record).
  Business rules that need state (uniqueness, ownership) belong in the use case and produce domain exceptions.
- Domain records still validate their invariants in compact constructors. Bean Validation does not replace them.

## Violation → HTTP status

- A violation on an endpoint parameter makes Quarkus answer **400** with its built-in violation report
  (`title`, `status`, `violations[{field, message}]`).
- Violations on service-method parameters or on return values are **5xx** by design, because they mean a server bug.
- To emit RFC 9457 `application/problem+json`, provide your own `ExceptionMapper<ValidationException>`
  (or a `@ServerExceptionMapper` for it). It replaces the built-in one, so keep the 400 versus 500 split, and never echo
  the rejected value (it may be personal data or an attack payload). Field paths are fine.

## Adversarial tests (required)

Every constraint has at least one negative test at its boundary. Name tests after the acceptance criterion
they prove. Use RestAssured for the call and assert on extracted values (AssertJ shown, as required by java option `junit5-assertj`).

```java
@QuarkusTest
@TestSecurity(user = "alice", roles = "ADMIN")
class CreateCustomerValidationTest {

    @ParameterizedTest(name = "AC-4: rejects {0}")
    @MethodSource("invalidBodies")
    void ac4_rejectsInvalidBody(String label, String json) {
        var status = given().contentType(ContentType.JSON).body(json)
            .when().post("/api/v1/customers")
            .then().extract().statusCode();
        assertThat(status).as(label).isEqualTo(400);
    }

    static Stream<Arguments> invalidBodies() {
        var longName = "x".repeat(101);
        return Stream.of(
            arguments("blank name", """
                {"name":"","email":"a@b.io","address":{"city":"X"}}"""),
            arguments("name over 100", """
                {"name":"%s","email":"a@b.io","address":{"city":"X"}}""".formatted(longName)),
            arguments("malformed email", """
                {"name":"A","email":"not-an-email","address":{"city":"X"}}"""),
            arguments("missing nested address", """
                {"name":"A","email":"a@b.io"}"""),
            arguments("malformed JSON", "{\"name\":"));
    }

    @Test
    void ac4_rejectsMalformedPathId() {
        var status = given().when().get("/api/v1/customers/not-a-uuid").then().extract().statusCode();
        assertThat(status).isEqualTo(400);
    }

    @Test
    void ac4_problemBodyDoesNotEchoRejectedValue() {
        var body = given().contentType(ContentType.JSON)
            .body("{\"name\":\"<script>\",\"email\":\"x\",\"address\":{\"city\":\"X\"}}")
            .when().post("/api/v1/customers").then().statusCode(400).extract().asString();
        assertThat(body).doesNotContain("<script>");
    }
}
```

Coverage expectation for each parameter: empty or blank, over-length, wrong format, out of range, missing required, and wrong
type. For the body as a whole: malformed JSON and an unknown enum value. Also assert the `Content-Type` of the error
response when the project uses problem JSON.

## Related

- quarkus `SKILL.md` → errors: the problem-details mapping rules.
- api-design and openapi skills: constraints must match the OpenAPI schema (`maxLength`, `pattern`, `minimum`).
- security skill: trust boundaries, canonicalization before validation, and logging of rejected input.
