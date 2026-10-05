# Image building: worked example and command equivalents

Linked from the containers skill. Read when writing a new build file or when translating Podman and Docker commands.
`$ENGINE` is the value of `HARNESS_CONTAINER_ENGINE` (`podman` or `docker`).

The worked example uses **one example stack**: a Java 25 JVM app built with Gradle, with the Maven differences below it.
It is not a default: apply the same structure (pinned bases, manifests before sources, cache mounts, build secret,
non-root runtime stage) to the language and build tool the stack ADR chose.

## 1. Example: Java 25 multi-stage (JVM jar), Gradle

```dockerfile
# syntax=docker/dockerfile:1
# Containerfile - pin digests for release builds: <image>:<tag>@sha256:<digest>

############ build stage ############
FROM --platform=$BUILDPLATFORM docker.io/library/eclipse-temurin:25-jdk AS build
WORKDIR /workspace

# 1. Wrapper and build scripts first (cache key = dependency inputs only)
COPY gradlew ./
COPY gradle/ gradle/
COPY settings.gradle.kts build.gradle.kts gradle.properties ./
# Multi-module: also COPY each module's build.gradle.kts before resolving

# 2. Resolve dependencies into a cache mount (not a layer)
RUN --mount=type=cache,target=/root/.gradle \
    ./gradlew --no-daemon dependencies > /dev/null

# 3. Sources last
COPY src/ src/

# 4. Build; credentials for private repos come in as a build secret
RUN --mount=type=cache,target=/root/.gradle \
    --mount=type=secret,id=gradle_props,target=/root/.gradle/gradle.properties,required=false \
    ./gradlew --no-daemon clean build -x test \
 && cp build/libs/app.jar /workspace/app.jar

############ runtime stage ############
FROM docker.io/library/eclipse-temurin:25-jre AS runtime

ARG VERSION=0.0.0-dev
ARG VCS_REF=unknown
ARG BUILD_DATE=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="app" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="https://example.com/org/app" \
      org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app
COPY --from=build --chown=1001:0 /workspace/app.jar /app/app.jar

ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=75 -XX:+ExitOnOutOfMemoryError"
USER 1001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
```

Notes:

- Tests run in CI before the image build (`./gradlew check`), so `-x test` in the image build is acceptable; do not skip tests anywhere else.
- Give the runnable jar a fixed name in Gradle (e.g. `tasks.jar { archiveFileName.set("app.jar") }`, or the shadow/boot jar task equivalent) so the copy is deterministic; never glob `build/libs/*.jar` (plain and fat jars both match).
- `--platform=$BUILDPLATFORM` on the build stage: the JVM bytecode is arch-neutral, so it is built once natively and only the runtime stage is per-arch.
- `required=false` lets the build run without the secret (public repos only). Drop it if private repos are mandatory so the build fails loudly.
- The cache mount path must match `GRADLE_USER_HOME` (default `/root/.gradle` when the build stage runs as root).

### Maven variant of the build stage

```dockerfile
COPY mvnw ./
COPY .mvn/ .mvn/
COPY pom.xml ./
# Multi-module: also COPY each module's pom.xml before resolving
RUN --mount=type=cache,target=/root/.m2 ./mvnw -B -q dependency:go-offline
COPY src/ src/
RUN --mount=type=cache,target=/root/.m2 \
    --mount=type=secret,id=maven_settings,target=/root/.m2/settings.xml,required=false \
    ./mvnw -B package -DskipTests \
 && cp target/app.jar /workspace/app.jar
```

- Fix the jar name with `<build><finalName>app</finalName></build>`; never glob `target/*.jar`.
- `dependency:go-offline` does not fetch everything (some plugins resolve late); the cache mount covers the rest.
- Tests run in CI before the image build (`./mvnw verify`), as for Gradle.

### Quarkus fast-jar variant (if the quarkus pack is adopted)

Quarkus writes `build/quarkus-app/` (Gradle) or `target/quarkus-app/` (Maven), not a single jar. Copy its four parts so
dependency layers cache separately (Gradle paths shown):

```dockerfile
COPY --from=build --chown=1001:0 /workspace/build/quarkus-app/lib/ /app/lib/
COPY --from=build --chown=1001:0 /workspace/build/quarkus-app/*.jar /app/
COPY --from=build --chown=1001:0 /workspace/build/quarkus-app/app/ /app/app/
COPY --from=build --chown=1001:0 /workspace/build/quarkus-app/quarkus/ /app/quarkus/
ENTRYPOINT ["java", "-jar", "/app/quarkus-run.jar"]
```

Native (`./gradlew build -Dquarkus.native.enabled=true` or `./mvnw package -Dquarkus.native.enabled=true`, Mandrel builder
image) produces `build/*-runner` or `target/*-runner`; copy that single binary onto `quay.io/quarkus/quarkus-distroless-image` or `ubi9/ubi-micro`. Health probe and management-port details: quarkus skill.

### Alternative JVM bases (verify the tag exists before using it; match the ADR's Java release)

| Stage | Temurin | Red Hat UBI | Distroless |
|-------|---------|-------------|------------|
| build | `eclipse-temurin:25-jdk` | `registry.access.redhat.com/ubi9/openjdk-25` | n/a (no build tools) |
| runtime | `eclipse-temurin:25-jre`, `25-jre-alpine` | `registry.access.redhat.com/ubi9/openjdk-25-runtime` | `gcr.io/distroless/java25-debian13` (nonroot tag runs as 65532) |

UBI OpenJDK images already run as UID 185; keep a numeric `USER` line anyway so the intent is explicit. On distroless, use the `:nonroot` variant or `USER 65532`.

### jlink'd minimal JRE (optional, when size matters)

```dockerfile
FROM docker.io/library/eclipse-temurin:25-jdk AS jre
RUN jlink --add-modules java.base,java.logging,java.naming,java.net.http,java.sql,jdk.crypto.ec \
          --strip-debug --no-man-pages --no-header-files --compress=zip-6 --output /jre
FROM registry.access.redhat.com/ubi9/ubi-micro
COPY --from=jre /jre /opt/jre
ENV PATH="/opt/jre/bin:${PATH}"
```

Derive the module list with `jdeps --print-module-deps --ignore-missing-deps app.jar`; a missing module is a runtime `ClassNotFoundException`, so test the image, not just the jar.

## 2. Build commands

```bash
# Gradle example secret; Maven: --secret id=maven_settings,src="$HOME/.m2/settings.xml"
VERSION=$(git describe --tags --always)
$ENGINE build -f Containerfile -t registry.example.com/app:"$VERSION" \
  --build-arg VERSION="$VERSION" \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --secret id=gradle_props,src="$HOME/.gradle/gradle.properties" \
  .
```

Smoke-test the result before pushing:

```bash
$ENGINE run --rm -d --name app-smoke -p 127.0.0.1:8080:8080 \
  --read-only --cap-drop ALL --security-opt no-new-privileges registry.example.com/app:"$VERSION"
curl -fsS http://127.0.0.1:8080/health   # the app's health endpoint (Quarkus: /q/health/ready)
$ENGINE image inspect registry.example.com/app:"$VERSION" --format '{{.Config.User}}'   # expect 1001
$ENGINE rm -f app-smoke
```

Running the smoke test with the hardening flags catches apps that write outside a tmpfs or need a capability.

## 3. Podman / Docker command equivalents

| Task | Podman (rootless, daemonless) | Docker (BuildKit) |
|------|-------------------------------|-------------------|
| Build | `podman build -f Containerfile -t app:1 .` | `docker build -f Dockerfile -t app:1 .` |
| Build keeping HEALTHCHECK | `podman build --format docker ...` | default (Docker image format) |
| Build secret | `podman build --secret id=x,src=file .` | `docker build --secret id=x,src=file .` |
| Cache mount | `RUN --mount=type=cache,...` (Buildah) | same (BuildKit) |
| Multi-arch build | `podman build --platform linux/amd64,linux/arm64 --manifest app:1 .` | `docker buildx build --platform linux/amd64,linux/arm64 -t app:1 --push .` |
| Push multi-arch | `podman manifest push --all app:1 docker://reg/app:1` | included in `buildx --push` |
| Inspect manifest list | `podman manifest inspect reg/app:1` | `docker buildx imagetools inspect reg/app:1` |
| Image config/user | `podman image inspect app:1 --format '{{.Config.User}}'` | `docker image inspect app:1 --format '{{.Config.User}}'` |
| Layer history | `podman history app:1` | `docker history app:1` |
| Export for scanning | `podman save -o app.tar app:1` | `docker save -o app.tar app:1` |
| Secret grep in layers | `podman save app:1 \| strings \| grep -iE 'token\|secret\|password'` | `docker save app:1 \| strings \| grep ...` |
| Scan | `trivy image --image-src podman app:1` | `trivy image app:1` |
| Lint | `podman run --rm -i docker.io/hadolint/hadolint < Containerfile` | `docker run --rm -i hadolint/hadolint < Dockerfile` |
| Daemonless build only | `buildah bud -f Containerfile -t app:1 .` | n/a |
| Compose up | `podman-compose up -d` or `podman compose up -d` | `docker compose up -d` |
| Sign on push | `podman push --sign-by-sigstore-private-key key.priv ...` or `cosign sign` | `cosign sign` |

Use the column of the engine in `HARNESS_CONTAINER_ENGINE`.

With Podman:

- Rootless storage lives under `~/.local/share/containers`; images built by one user are invisible to another and to root.
- On macOS/Windows Podman runs in a VM (`podman machine`); bind mounts and port forwards go through it, and build cache lives in the VM.
- Bind-mounted host directories need `:Z` (private SELinux label) on SELinux hosts and often `:U` or `--userns=keep-id` so the non-root container UID can read them.
- `podman build` defaults to OCI image format; that is fine for registries and Kubernetes, but `HEALTHCHECK`, `SHELL` and `ONBUILD` are Docker-format-only.
- Tools that expect a Docker socket (Testcontainers, Quarkus Dev Services) need `DOCKER_HOST` pointing at the Podman socket.

With Docker:

- Builds go through the Docker daemon (BuildKit); images live in the daemon's store, shared by every user who can reach its socket.
- Access to `/var/run/docker.sock` is root-equivalent on the host: never mount it into containers (container-security skill).
- Rootless Docker exists but is opt-in; by default the daemon runs as root, so the image's non-root `USER` matters even more.
- `docker buildx` is needed for multi-platform builds and `--push` of manifest lists.

## 4. Size and content checks

```bash
$ENGINE image inspect app:1 --format '{{.Size}}'            # bytes
$ENGINE history --format '{{.Size}}\t{{.CreatedBy}}' app:1   # find the fat layer
dive app:1                                                    # interactive layer explorer
$ENGINE run --rm --entrypoint sh app:1 -c 'ls /app'           # only on images with a shell
```

Red flags: build caches (`/root/.gradle`, `/root/.m2`, `node_modules` of dev dependencies) or `/workspace` in the runtime stage, a `jdk` directory instead of `jre`, `.git` in `/app`, package-manager caches, more than one copy of the app jar.
