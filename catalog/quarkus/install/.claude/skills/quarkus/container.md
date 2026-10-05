# Quarkus in containers

This file covers only what is Quarkus-specific. Generic image building, hardening, scanning and compose rules are in the
containers and container-security skills. Use the engine the ADR chose: `$ENGINE` below is the value of
`HARNESS_CONTAINER_ENGINE` (`podman` or `docker`), with its compose tool (`podman-compose` or `docker compose`).

## Base images and Containerfiles

- Native: `quay.io/quarkus/quarkus-distroless-image` (no shell, no package manager) for CI, ITs and production. Use
  `quay.io/quarkus/ubi9-quarkus-micro-image` only when you need a shell for debugging, and never ship it.
- JVM: a UBI OpenJDK runtime image (`registry.access.redhat.com/ubi9/openjdk-25-runtime`, matching the project's Java release, or
  the project's pinned equivalent). Copy `build/quarkus-app/` (Gradle) or `target/quarkus-app/` (Maven) with its four layers (`lib/`, `*.jar`, `app/`, `quarkus/`) for cache-friendly
  images. Quarkus generates templates in `src/main/docker/`.
- Pin base images by tag plus digest. Run as non-root (`USER 1001` or `nonroot`). Copy the binary owned by root, read-only:

```dockerfile
FROM quay.io/quarkus/quarkus-distroless-image:2.0@sha256:<digest>
WORKDIR /app
COPY --chown=root:root --chmod=0755 build/*-runner /app/application    # Maven: target/*-runner
EXPOSE 8443 9000
USER nonroot
ENTRYPOINT ["/app/application"]
```

## Building images with Quarkus

- With Docker: the `quarkus-container-image-docker` extension. With Podman: `quarkus-container-image-podman` for
  Podman-specific behaviour (multi-platform builds); the docker extension also works against Podman's Docker-compatible API.
- Gradle `./gradlew build -Dquarkus.container-image.build=true`, Maven `./mvnw package -Dquarkus.container-image.build=true`
  (add `-Dquarkus.native.enabled=true` for native). Set
  `quarkus.container-image.group/name/tag` in properties. Push only from CI (`quarkus.container-image.push=true`).
- Native in-container builds: `quarkus.native.container-build=true`, `quarkus.native.container-runtime=$ENGINE`
  (native.md).

## Management interface and health probes (distroless)

Distroless images have no `curl`, `wget` or shell, so `HEALTHCHECK CMD curl ...` and `/dev/tcp` probes cannot work.
Expose health and metrics on the Quarkus management interface instead:

```properties
quarkus.management.enabled=true      # BUILD-TIME property: in application.properties before the build
# defaults: port 9000, host 0.0.0.0, plain HTTP
```

- `quarkus.management.enabled` is fixed at build time. `QUARKUS_MANAGEMENT_ENABLED=true` at runtime has no effect on an
  already built jar or native binary. Rebuild after changing it.
- Check the startup log line: `... Management interface listening on http://0.0.0.0:9000`. If it is missing, the
  property was not in the build.
- With it enabled, `/q/health/*` and `/q/metrics` move to port 9000. They are no longer on the application port.
  Update probes, Prometheus targets and `@QuarkusIntegrationTest` URLs together. In test mode the port is 9001.
- The management interface only starts when an extension uses it (health, metrics, OpenAPI).
- Orchestrator probes (no binary needed in the image):

```yaml
livenessProbe:  { httpGet: { path: /q/health/live,    port: 9000, scheme: HTTP } }
readinessProbe: { httpGet: { path: /q/health/ready,   port: 9000, scheme: HTTP } }
startupProbe:   { httpGet: { path: /q/health/started, port: 9000, scheme: HTTP }, failureThreshold: 30, periodSeconds: 2 }
```

- Compose (`podman-compose` or `docker compose`): map the management port and probe it from the host or from a sidecar, for example
  `curl -sf http://localhost:19000/q/health/live`. Do not embed a `HEALTHCHECK` that needs a shell in a distroless image.
- Do not publish port 9000 outside the cluster or host network. It is for internal probes and scraping only.
- Never hardcode framework-specific health paths in other services. Make them configurable.

## TLS: certificates mounted at runtime

- Never `COPY` private keys or keystores into an image. Mount them read-only at runtime from a secret or volume:

```properties
quarkus.http.ssl.certificate.files=/certs/tls.crt
quarkus.http.ssl.certificate.key-files=/certs/tls.key
quarkus.http.ssl-port=8443
quarkus.http.insecure-requests=disabled
quarkus.http.ssl.protocols=TLSv1.3,TLSv1.2
```

```yaml
services:
  customer-service:
    volumes:
      - ./certs:/certs:ro,Z        # :Z relabels for SELinux hosts (Podman or Docker); drop it elsewhere
```

- These are runtime properties, so they can come from env vars (`QUARKUS_HTTP_SSL_CERTIFICATE_FILES`). Use the TLS registry
  (`quarkus.tls.*`) if the project standardizes on it.
- The management interface stays plain HTTP for internal probes unless the platform requires mTLS everywhere.

## Runtime configuration in containers

- Everything that differs per environment is a runtime property passed as an env var: datasource URLs and credentials,
  token issuer and keys, broker hosts. Build-time properties cannot be changed this way.
- Log to stdout/stderr only, as JSON in prod (`quarkus-logging-json`). File logs are for local ITs only, through a writable
  mount.
- Hardening in compose or pods: `read_only: true` with a `tmpfs: /tmp`, `cap_drop: [ALL]`,
  `security_opt: [no-new-privileges:true]`, memory and CPU limits. A native Quarkus binary works with a read-only root
  filesystem. A JVM image needs a writable `/tmp`.
- Keep the service ports defined in the project's compose file. Do not renumber them.
- JVM images: let the container's memory limit drive the heap (`-XX:MaxRAMPercentage=75`), and do not hardcode `-Xmx`.

## Checklist

- [ ] Distroless (native) or pinned UBI runtime (JVM), non-root, digest-pinned.
- [ ] `quarkus.management.enabled=true` set at build time, and probes and scrapers use port 9000.
- [ ] No keys, certs or secrets copied into the image. TLS files are mounted `:ro`.
- [ ] Runtime config comes from env vars. There are no build-time properties in env.
- [ ] Read-only root filesystem, dropped capabilities, resource limits.
