# Quarkus native image (GraalVM / Mandrel)

Native builds use closed-world analysis. Anything reached only through reflection, dynamic proxies, resources
or JNI must be registered at build time, or it is missing at runtime. Native builds take 5 to 30 minutes, so run JVM tests first.

## Commands

`$ENGINE` is the value of `HARNESS_CONTAINER_ENGINE` (`podman` or `docker`).

```bash
# Gradle: native executable -> build/<name>-runner
./gradlew build -Dquarkus.native.enabled=true \
  -Dquarkus.native.container-build=true -Dquarkus.native.container-runtime=$ENGINE \
  -Dquarkus.native.builder-image=quay.io/quarkus/ubi9-quarkus-mandrel-builder-image:jdk-25
# Maven: native executable -> target/<name>-runner (same -D flags)
./mvnw package -Dquarkus.native.enabled=true \
  -Dquarkus.native.container-build=true -Dquarkus.native.container-runtime=$ENGINE \
  -Dquarkus.native.builder-image=quay.io/quarkus/ubi9-quarkus-mandrel-builder-image:jdk-25

# native tests; the script picks the build tool (./gradlew or ./mvnw) and the engine from backbone/harness.conf
scripts/harness/packs/quarkus/native-test.sh            # Gradle: testNative; Maven: verify (Failsafe ITs) with the flags above
scripts/harness/packs/quarkus/native-test.sh --info     # extra args go through to the build tool
scripts/harness/packs/quarkus/native-test.sh --help     # overrides: BUILD_TOOL, CONTAINER_RUNTIME, BUILDER_IMAGE
```

- Gradle runs `@QuarkusIntegrationTest` classes in `src/native-test/java` (plus any extra native test source set) with
  `testNative`. Maven runs `*IT` classes through Failsafe in `verify`; generated POMs skip ITs unless `-DskipITs=false`
  (the script passes it).
- `-Dnative` / `-Pnative` activate the `native` profile of a generated Maven POM and do nothing in Gradle. The Quarkus 3
  property that works with both tools is `quarkus.native.enabled=true`.
- The builder JDK must match the language level. A Java 25 project needs a `jdk-25` Mandrel builder (a `jdk-21` builder
  cannot compile it). Current Quarkus defaults to UBI 10 builder images (`ubi10-quarkus-mandrel-builder-image`). The ubi9
  image is fine. Pin the tag in config or the script rather than relying on the default.
- Keep native settings in `application.properties` under a comment (works for both tools), or in Gradle
  `quarkusBuild { nativeArgs { ... } }` / the Maven `native` profile's properties, so that CI and local runs agree.
- Gradle `testNative` depends on `quarkusBuild`; Maven `verify` packages before running Failsafe. Never call the
  native-image tool directly.

## Reflection: what needs registration

| Type | Register? | Why |
|---|---|---|
| CDI beans, producers, interceptors, decorators, interceptor bindings, qualifiers | No | ArC generates code at build time |
| Health checks, `@ConfigMapping` interfaces, `@Scheduled` beans | No | Handled by their extensions |
| Request/response types of Quarkus REST endpoints (records, enums, nested types they reference) | No | Quarkus REST plus Jackson register endpoint parameter and return types |
| Types that Jackson (de)serializes outside an endpoint signature: payloads written with `ObjectMapper` (e.g. outbox rows), messaging payloads, entities of untyped `Response` (use `RestResponse<T>` instead), generic `Map<String,Object>` contents | Yes | Not inferable from endpoint signatures |
| Jackson polymorphism (`@JsonTypeInfo`/`@JsonSubTypes`) subtypes | Yes (each subtype) | Subtypes are chosen reflectively |
| Example, if the ADR chose JDBI: SqlObject interfaces | Proxy registration | `onDemand`/`attach` create JDK dynamic proxies |
| Example, if the ADR chose JDBI: `*Row` records mapped by JDBI `ConstructorMapper`/`BeanMapper`/`FieldMapper`, records bound with `@BindMethods`/`bindMethods` | Yes, unless the JDBI extension registers them (see below) | JDBI reads constructors, parameter names and accessors reflectively |
| Classes loaded by name (`Class.forName`, ServiceLoader not handled by an extension) | Yes | Invisible to analysis |

- Other data-access libraries have their own native needs; check their extension. With JDBI, prefer the Quarkiverse extension `io.quarkiverse.jdbi:quarkus-jdbi`. In its build steps (verified in source) it registers
  SqlObject interfaces as proxies when they use `@SqlQuery`/`@SqlUpdate`/`@SqlBatch`/`@UseRowReducer`, and it
  registers the classes named in `@RegisterConstructorMapper`/`@RegisterRowMapper`/`@RegisterBeanMapper`... annotations.
  Types used only through the fluent API (`mapTo(OrderRow.class)`, `ConstructorMapper.factory(OrderRow.class)`,
  `bindMethods(row)`) are not registered. Annotate them yourself.
- JDBI ships reachability metadata for its own internals on GraalVM 25+ only. The jdk-25 Mandrel builder fits. Your
  SqlObject interfaces still need proxy registration (by the extension, by `@RegisterForProxy`, or by an experimental
  `@GenerateSqlObject` from `jdbi3-generator`, which needs no proxies).
- Persistence row records are infrastructure types, so putting `@io.quarkus.runtime.annotations.RegisterForReflection` on them
  is fine. If the ADR keeps the domain framework-free (option `hexagonal-layers`), never put it on domain types; register them
  from an infrastructure holder class instead:
  `@RegisterForReflection(targets = {Money.class, CustomerStatus.class}) class NativeReflectionConfig {}`.
- Narrow the scope where you can: `@RegisterForReflection(methods = false, fields = false)` for enums. Over-registration
  only costs image size and build time. Under-registration fails at runtime.
- Use `@RegisterForProxy` (or `quarkus.native.additional-build-args`) for other JDK dynamic proxies.
- Compile with `-parameters`. Libraries that read parameter names (e.g. JDBI `ConstructorMapper` and SqlObject `@Bind`-less
  parameters) need them in native mode too.

## Resources, class init, memory

- Only `META-INF/resources/**` (static web) is included automatically. Add classpath files that you read at runtime:
  `quarkus.native.resources.includes=sql/**,templates/**/*.txt`. Migration scripts are handled by
  their extension when it supports native (Flyway: `db/migration` is included by the Flyway extension).
- Classes with static initializers that open sockets, threads, random seeds or files must initialize at run time:
  `quarkus.native.additional-build-args=--initialize-at-run-time=com.example.Foo\\,com.example.Bar`
  (escape commas in properties). Symptoms are "Detected an instance of Random/Thread in the image heap" or stale values
  frozen at build time.
- Out of memory or a very slow build: `-Dquarkus.native.native-image-xmx=6g`, and give the engine's VM enough RAM
  (8 GB or more recommended; Podman Machine or Docker Desktop on macOS/Windows). Close other heavy processes.
- Unsupported library (JMX, JVMTI, runtime bytecode generation): look for a Quarkus or Quarkiverse extension first. Write
  GraalVM substitutions only as a last resort, with an ADR.

## Native test profiles and scope

- Native tests are `@QuarkusIntegrationTest` classes. They talk HTTP to the binary. No `@Inject`, no `@InjectMock`, no
  in-process DB access.
- The binary is built and runs with the `prod` profile. `%test.` properties do not apply unless you run with
  `-Dquarkus.test.integration-test-profile=test` (runtime only). Use `-Dquarkus.profile=test` (build and run) only for
  test-only binaries, never for release builds. Dev Services containers are still passed to the binary.
- Skip tests that cannot run against a packaged app with `@DisabledOnIntegrationTest`. This disables them for JVM-jar and
  container ITs too.
- Cover in native tests: JSON (de)serialization of every endpoint (including error/problem bodies), one persistence read and
  write path per mapper style, payloads serialized outside endpoints (e.g. outbox or messaging), token validation, and health
  and metrics endpoints.
- The native-image tracing-agent integration (`test-with-native-agent`) is documented for Maven only. With Gradle,
  support is pending upstream, so register types by hand as shown above.

## Troubleshooting

| Symptom (native only) | Likely cause | Fix |
|---|---|---|
| Empty JSON `{}` or "No serializer found" | Type serialized outside endpoint signature | `@RegisterForReflection` on the type (and subtypes) |
| `com.fasterxml...InvalidDefinitionException` / cannot construct instance | Record or POJO not registered for Jackson | Register it, and check that the polymorphic subtypes are registered |
| JDBI (example) `NoSuchMapperException` / "no constructor" / proxy errors | Row record or SqlObject interface not registered | Add `quarkus-jdbi` and use `@RegisterConstructorMapper`, or `@RegisterForReflection` / `@RegisterForProxy` |
| Resource not found | Not included | `quarkus.native.resources.includes` |
| Class init errors at build | Static init with runtime state | `--initialize-at-run-time` for that class |
| Build killed or very slow | Memory | `native-image-xmx`, more RAM for the engine's VM |
| Build cannot compile Java 25 classes | Builder JDK too old | `ubi9-quarkus-mandrel-builder-image:jdk-25` |
| `podman`/`docker: command not found` / socket errors | Engine not installed or not running | Podman: `podman machine start`; Docker: start the daemon/Desktop; or set `CONTAINER_RUNTIME` |
| Management port missing at runtime | `quarkus.management.enabled` set only via env | It is build-time: set it in `application.properties` and rebuild (`container.md`) |

Report after a native run: the exit status, duration, `build/*-runner` (Gradle) or `target/*-runner` (Maven) path and size, and the failing tests with the
first native-specific stack frame.
