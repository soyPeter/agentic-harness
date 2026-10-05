---
name: containers
description: Write or review Containerfiles/Dockerfiles and .dockerignore with the engine the ADR chose (Podman or Docker) - base image selection and pinning, multi-stage builds, layer caching, non-root user, labels, build secrets, health checks, multi-arch. Use before editing any image build file.
applies-to: OCI images, Podman >= 4 or Docker with BuildKit
last-verified: 2026-10-05
sources: adapted from cuioss/plan-marshall pm-dev-oci/oci-standards (current main; image-building, certificate-management) and the pinned agentic-backbone oci-standards copy; Maven/JDK 21 examples replaced with Java 25 examples for Gradle and Maven, labelled as one example stack; engine-neutral rewrite with Podman and Docker notes and review corrections (HEALTHCHECK in OCI format, build secrets, multi-arch manifests)
---

# Containers (image building)

The accepted ADRs and `backbone/4-KNOWLEDGE.md` override this skill.

`$ENGINE` below means the value of `HARNESS_CONTAINER_ENGINE` in `backbone/harness.conf` (`podman` or `docker`, chosen in
the ADR). Every rule holds for both engines; engine-specific behaviour is in **With Podman** / **With Docker** notes. Name the
build file as the project does: `Containerfile` or `Dockerfile` are equivalent (both build with `-f`). Runtime hardening and
compose files belong to the **container-security** skill.

Read `image-building.md` when writing a new build file, changing the build/runtime stages (worked example: a Java app built
with Gradle or Maven), or translating Podman and Docker commands.

## Hard rules (a review fails on any of these)

1. **No `:latest`, no untagged `FROM`.** Pin a specific version tag (`eclipse-temurin:25.0.1_8-jre`, not `25-jre` for releases). Release/CI images pin by digest as well: `FROM docker.io/library/eclipse-temurin:25-jre@sha256:<digest>` (tag kept for readability, digest wins). Let Renovate/Dependabot bump digests.
2. **Fully qualified image names** (`docker.io/library/...`, `registry.access.redhat.com/...`, `gcr.io/...`). Podman may prompt or resolve short names differently per `registries.conf`; qualified names are deterministic for both engines.
3. **Multi-stage build.** Compilers, build tools (Gradle, Maven, npm, Go toolchain...), SDKs, source and caches stay in the build stage. The final stage gets only the runtime (JRE, interpreter or native binary) and the built artifact.
4. **Non-root numeric user in the final stage**: `USER 1001` (or `1001:0` for OpenShift-style arbitrary UIDs; distroless `nonroot` is `65532`). Numeric, so `runAsNonRoot` checks and `$ENGINE inspect` can verify it without `/etc/passwd`. Files the app must read: `COPY --chown=1001:0`; never `chmod 777`.
5. **No secrets in the image.** Never in `ENV`, `ARG`, `LABEL`, `COPY`/`ADD`, or written by `RUN`. Use build secrets (below) for build-time credentials and runtime injection (container-security skill) for everything else. Private keys and keystores are mounted at runtime, never copied in.
6. **`COPY`, not `ADD`**, unless tar auto-extraction is the explicit intent. Never `ADD <url>`: download in the build stage with a checksum check (`sha256sum -c`).
7. **Exec form** for `ENTRYPOINT`/`CMD` (`["java", "-jar", "/app/app.jar"]`, `["/app/server"]`) so the process is PID 1 and receives SIGTERM.
8. **`.dockerignore` exists** next to the build context and excludes at least VCS, secrets, build outputs and IDE files (see below).

## Base image selection

| Need | Runtime base (final stage) |
|------|---------------------------|
| Native or static binary (GraalVM/Mandrel, Go, Rust) | `gcr.io/distroless/static` / `cc`, `ubi9/ubi-micro`, `quay.io/quarkus/quarkus-distroless-image` (Quarkus native), or `scratch` for static binaries |
| JVM app, smallest attack surface | distroless Java (`gcr.io/distroless/java25-*` if published for your JDK; verify tag) or `ubi9/ubi-micro` + jlink'd JRE |
| JVM app, shell needed for ops/debug | `eclipse-temurin:25-jre` (Ubuntu) or `registry.access.redhat.com/ubi9/openjdk-25-runtime` (verify tag) |
| Interpreted runtime (Node, Python...) | the vendor's slim or distroless runtime image, pinned |
| Alpine (`*-alpine`) | only if the runtime is tested on musl; vendor support (e.g. JDKs) differs from glibc |

Prefer the smallest image that runs the app; full OS images (`ubuntu`, `fedora`) are build-stage only. Rebuild on a schedule (weekly) even without code changes so base-image CVE fixes land. Version numbers in the JVM rows are examples: match the Java release the stack ADR chose.

## Layer ordering and caching

- Order from least to most frequently changing: base -> OS packages -> dependency manifests -> dependency download -> sources -> build.
- Copy the dependency manifests first, resolve dependencies, then copy sources. Examples: Gradle `gradlew`, `gradle/`, `settings.gradle(.kts)`, `build.gradle(.kts)`, `gradle.properties`; Maven `mvnw`, `.mvn/`, `pom.xml`; npm `package.json`, `package-lock.json`.
- Use cache mounts for dependency caches instead of baking them into layers: `RUN --mount=type=cache,target=/root/.gradle ./gradlew build --no-daemon` or `RUN --mount=type=cache,target=/root/.m2 ./mvnw -B package` (BuildKit and Buildah both support it).
- One `RUN` per logical step; package installs clean up in the same `RUN` (`dnf clean all`, `rm -rf /var/lib/apt/lists/*`) and use `--no-install-recommends` / `--setopt=install_weak_deps=0`. Pin OS package versions where the distro allows it.
- Never `COPY . .` before dependency resolution: it invalidates the cache on every source change.

## .dockerignore

Podman/Buildah also read `.containerignore` (it takes precedence if both exist); keep one file. Minimum content (build-output lines for the build tools in use):

```text
.git
.gitignore
.idea
.vscode
*.iml
build/
.gradle/
target/
node_modules/
**/out/
.env
.env.*
*.pem
*.key
*.p12
*.jks
secrets/
compose*.y*ml
Containerfile*
Dockerfile*
```

Prefer an allow-list (`*` then `!src/` and the build files, e.g. `!gradlew`, `!gradle/`, `!*.gradle.kts` or `!mvnw`, `!.mvn/`, `!pom.xml`) for large repos: the context stays small and nothing new leaks in by default.

## Build secrets (credentials needed only during build)

```dockerfile
# example: private-repository credentials for the build tool (Gradle shown; Maven: target=/root/.m2/settings.xml)
RUN --mount=type=secret,id=gradle_props,target=/root/.gradle/gradle.properties \
    ./gradlew build --no-daemon
```

```bash
$ENGINE build --secret id=gradle_props,src=$HOME/.gradle/gradle.properties -t app .
```

- **With Docker:** BuildKit must be the builder (default in current Docker Engine; older setups need `DOCKER_BUILDKIT=1`).
- The secret is mounted only for that `RUN`; it never lands in a layer or in history.
- An `rm` in a later `RUN` does **not** remove a secret from an earlier layer: every layer is extractable. Writing and deleting in the same `RUN` keeps the file out of the layer but the value can still leak via build args/history.
- `ARG` is not a secret mechanism: build-arg values are recorded in image metadata/history.
- `$ENGINE history` is a weak check (shows instructions and args only). Verify with `$ENGINE save app | strings | grep -iE 'token|secret|password|BEGIN .*PRIVATE'` and `trivy image --scanners secret app` in CI.
- If a secret did reach a pushed image: follow the incident steps in the container-security skill (rotate first).

## Labels (OCI annotations)

Set `org.opencontainers.image.{title,description,version,revision,created,source,licenses,vendor}`. Pass dynamic values as build args (`--build-arg VCS_REF=$(git rev-parse HEAD) --build-arg BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)`); declare `ARG` in the stage that uses it. Use `--annotation` (Podman/Buildx) for manifest-level annotations when publishing multi-arch indexes.

## Ports, entrypoint, runtime

- `EXPOSE` only the ports the app serves (e.g. `8080`, plus a management port such as `9000` if used). Listen on ports >= 1024 so no `NET_BIND_SERVICE` is needed.
- No debug ports (e.g. JDWP `5005`) or debug flags in release images.
- JVM apps: rely on container awareness (default since JDK 10); size heap with `-XX:MaxRAMPercentage=75` via `JAVA_TOOL_OPTIONS`, not hard `-Xmx` that ignores the memory limit.
- `WORKDIR /app` with absolute paths; no `cd` in `RUN`.

## Health checks

- Prefer health checks outside the image: compose `healthcheck:`, `$ENGINE run --health-cmd`, or orchestrator probes.
- **With Podman:** Podman builds OCI-format images by default, and **the OCI format drops `HEALTHCHECK`** (Podman warns and ignores it). If the image relies on `HEALTHCHECK`, build with `podman build --format docker`, or use one of the external checks above.
- **With Docker:** `docker build` produces Docker-format images, so `HEALTHCHECK` is kept.
- Distroless/micro images have no shell, `curl` or `wget`: a `HEALTHCHECK CMD curl ...` silently never passes. Probe an HTTP endpoint from the orchestrator instead. Quarkus specifics (management port 9000, build-time `quarkus.management.enabled`): quarkus skill, if adopted.

## Multi-arch

```bash
# With Podman
podman build --platform linux/amd64,linux/arm64 --manifest registry.example.com/app:1.4.0 .
podman manifest push --all registry.example.com/app:1.4.0 docker://registry.example.com/app:1.4.0
# With Docker
docker buildx build --platform linux/amd64,linux/arm64 -t registry.example.com/app:1.4.0 --push .
```

- Cross-arch builds need QEMU emulation (Podman machine and Docker Desktop include it; on Linux install `qemu-user-static` or the binfmt image). Emulated builds are slow: build arch-neutral artifacts (e.g. a JVM jar) once with `--platform=$BUILDPLATFORM` on the build stage and only assemble per-arch runtime stages. Native binaries must be compiled per architecture.
- Check every base image publishes all target platforms (`podman manifest inspect <image>` / `docker buildx imagetools inspect <image>`).

## Reproducibility and size

- Same inputs -> same image: pinned digests, pinned package versions, pinned build-tool wrapper (Gradle `distributionSha256Sum`, Maven wrapper `distributionSha256Sum`), dependency locking/verification (e.g. `gradle/verification-metadata.xml`, lock files).
- Normalise timestamps where tooling allows (`SOURCE_DATE_EPOCH`; Buildx `--build-arg SOURCE_DATE_EPOCH=...`; Podman `--source-date-epoch` / `--timestamp` depending on version).
- Check size and layers after changes: `$ENGINE image inspect app --format '{{.Size}}'`, `$ENGINE history app`, or `dive app`. For a JVM image, a runtime image above ~350 MB usually means a JDK or build cache leaked into the final stage.

## Lint

Run Hadolint in pre-commit/CI (`hadolint Containerfile` or `$ENGINE run --rm -i docker.io/hadolint/hadolint < Containerfile`). Fix or justify each finding with an inline `# hadolint ignore=DLxxxx` plus a reason. Key rules: DL3006/DL3007 (untagged/latest), DL3008/DL3018/DL3041 (unpinned apt/apk/dnf packages), DL3020 (ADD vs COPY), DL3025 (exec form), DL3002 (last USER root).

## Review checklist

- [ ] `FROM` lines fully qualified, version-pinned, digest-pinned for release; no `:latest`.
- [ ] Multi-stage; final stage has no SDK, build tool, sources, caches or package manager leftovers.
- [ ] Final `USER` is a numeric non-root UID; app files owned by it or by root and read-only.
- [ ] No secret in `ENV`/`ARG`/`LABEL`/`COPY`/`RUN`; build credentials via `--mount=type=secret`.
- [ ] `.dockerignore`/`.containerignore` excludes `.git`, build outputs, `.env*`, keys, keystores.
- [ ] Dependency manifests copied before sources; cache mounts used for dependency caches.
- [ ] Exec-form `ENTRYPOINT`; only required ports exposed; no debug ports.
- [ ] Health check strategy works for the image type and the engine's build format (Podman OCI vs Docker format).
- [ ] OCI labels present; revision and created set at build time.
- [ ] Hadolint clean or each ignore justified; image size checked.

## Linked skills

- container-security - compose hardening, runtime secrets, supply chain, incident response.
- quarkus (if adopted) - Quarkus container specifics: management port, health probes, native/distroless images.
- security - general secret handling and threat review.
- architecture - deployment topology and where the image fits.
- code-quality, module-testing - build reproducibility and tests that run against the built image.
