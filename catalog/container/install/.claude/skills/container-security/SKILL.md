---
name: container-security
description: Harden and review container runtime configuration for the engine the ADR chose (compose files, podman/docker run flags) - least privilege, read-only rootfs, capabilities, resource limits, secrets, network segmentation, supply chain and leaked-secret incidents. Use before editing compose files and for any container security review.
applies-to: OCI images, Podman >= 4 or Docker with BuildKit
last-verified: 2026-10-05
sources: adapted from cuioss/plan-marshall pm-dev-oci/oci-security (current main; runtime-security, supply-chain-security, owasp-container-security) and oci-standards/certificate-management, plus the pinned agentic-backbone oci-security copy; review corrections applied (Docker Content Trust deprecated -> Cosign, signing/SBOM in CI not per local build, runtime-mounted certificates, podman-compose resource caveats); engine-neutral rewrite with Podman and Docker notes
---

# Container security (runtime and supply chain)

The accepted ADRs and `backbone/4-KNOWLEDGE.md` override this skill.

`$ENGINE` means the value of `HARNESS_CONTAINER_ENGINE` in `backbone/harness.conf` (`podman` or `docker`, chosen in the
ADR); compose means `podman-compose`/`podman compose` or `docker compose` accordingly. Every rule applies to both engines;
engine-specific behaviour is in **With Podman** / **With Docker** notes. Image build rules (base images, `USER`, build
secrets) live in the **containers** skill.

- **With Podman:** rootless and daemonless by default, which already removes the "container root = host root" and daemon-socket classes of risk; the rules still apply.
- **With Docker:** the daemon runs as root by default, so its socket is host root and the non-root, capability and `no-new-privileges` rules carry more weight. Rootless mode or `userns-remap` reduce this; record either in the ADR.

Read `owasp-docker.md` when doing a full security review or audit, or when a control below needs its threat and verification detail. Read `supply-chain.md` when touching CI/release pipelines, registries, scanning gates, signing or SBOMs.

## Hard rules (a review fails on any of these)

1. **Never mount the container engine socket** (`/var/run/docker.sock`, `/run/podman/podman.sock`, `$XDG_RUNTIME_DIR/podman/podman.sock`) into a container. It is host root. CI runners that need to build images use a rootless builder inside the job (rootless Podman/Buildah, rootless BuildKit) or a remote builder.
2. **No `privileged: true`**, no `--privileged`, no `security_opt: [seccomp:unconfined]`, `apparmor:unconfined` or `label:disable` unless a written justification sits next to it (comment + ADR/issue link).
3. **No `network_mode: host` / `pid: host` / `ipc: host`** and no host device mounts unless justified the same way.
4. **Non-root**: `user: "1001:1001"` (or the image's numeric UID) on every app service. Databases and vendor images use their documented non-root UID.
5. **No secrets in the compose file, the image, or VCS.** No literal passwords/tokens in `environment:`; no committed `.env` with real values. See Secrets below.
6. **Every service has the baseline hardening block** (below) or a comment explaining each omission.
7. **Published ports bind to the narrowest interface**: `"127.0.0.1:5432:5432"` for local-only dev services; never publish database, broker, debug (JDWP) or management ports on `0.0.0.0` without a reason.

## Baseline hardening block

```yaml
services:
  app:
    image: registry.example.com/app:1.4.0@sha256:<digest>   # pinned; no :latest
    user: "1001:1001"
    read_only: true
    tmpfs:
      - /tmp:size=64m,mode=1777
    security_opt:
      - no-new-privileges:true
    cap_drop: [ALL]
    # cap_add: [NET_BIND_SERVICE]   # only if binding < 1024 in-container; prefer port 8080
    mem_limit: 512m
    cpus: 1.0
    pids_limit: 256
    restart: unless-stopped
    networks: [backend]
    secrets: [db_password]
    healthcheck:
      test: ["CMD", "/app/healthcheck"]   # or omit and probe from outside on distroless
      interval: 15s
      timeout: 3s
      retries: 5
      start_period: 30s
    logging:
      driver: json-file          # Podman: k8s-file/journald also fine
      options: { max-size: "10m", max-file: "3" }
```

Notes:

- `read_only: true`: every path the app writes must be a `tmpfs` or a named volume. Declare the tmpfs mounts explicitly so the compose file behaves the same on both engines. **With Podman:** `--read-only` already adds tmpfs on `/tmp`, `/var/tmp`, `/run` (`--read-only-tmpfs`, default true). **With Docker:** no implicit tmpfs; undeclared writes fail.
- `cap_drop: [ALL]` then add back only what a test proves is needed (`NET_BIND_SERVICE`, rarely `CHOWN`/`SETUID`/`SETGID`). Never `SYS_ADMIN`, `NET_ADMIN`, `SYS_PTRACE` in production.
- Resource limits: use the service-level `mem_limit`, `cpus`, `pids_limit` keys, which both podman-compose and Docker Compose map to run flags, and verify with `$ENGINE inspect <ctr> --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}}'`. **With Podman:** podman-compose only partially honours `deploy.resources` (version dependent). **With Docker:** Compose v2 applies `deploy.resources.limits` too; still verify.
- JVM services (example runtime): set `-XX:MaxRAMPercentage` so heap fits under `mem_limit`; an OOM kill (exit 137) means the limit or the percentage is wrong, not that limits should be removed.
- Health checks: in compose, not only in the image (**with Podman**, OCI-format images drop `HEALTHCHECK`). Distroless images cannot run `curl`; probe from outside or use the framework's management port (quarkus skill, if adopted). Use `depends_on: { db: { condition: service_healthy } }` for startup order.

## Engine specifics

With Podman (rootless):

- Rootless containers map container UIDs into the user's subordinate range (`/etc/subuid`); container root is an unprivileged host user. Keep `USER` non-root anyway: it limits damage inside the container and to mounted volumes.
- Bind mounts: add `:Z` on SELinux hosts and `:ro` unless writes are required; use `userns_mode: keep-id` (or `:U`) when the non-root UID must own host files. Never relabel system directories (`/home`, `/etc`) with `:Z`.
- Rootless cannot publish host ports < 1024 by default; map `8080:8080` or front with a proxy instead of lowering `net.ipv4.ip_unprivileged_port_start`.
- `podman compose` delegates to an external provider (podman-compose or docker-compose); behaviour differs per provider, so state which one the project uses.
- For production on Podman prefer Quadlet/systemd units or Kubernetes YAML (`podman kube play`) over compose; carry the same hardening flags.

With Docker:

- Members of the `docker` group can control the root daemon: treat membership as root access, and never expose the daemon over TCP without mutual TLS.
- Keep the default seccomp and AppArmor (or SELinux) profiles; consider rootless mode or `userns-remap` so container root is not host root.
- Bind mounts need no relabelling on AppArmor hosts; on SELinux hosts use `:Z`/`:z` as with Podman. Use `:ro` unless writes are required.
- Production on plain Docker: Compose with the same hardening block, or an orchestrator (Kubernetes) with equivalent `securityContext`.

## Secrets

- **Compose secrets** (file-based, mounted at `/run/secrets/<name>`, read-only):

  ```yaml
  secrets:
    db_password:
      file: ./secrets/db_password.txt     # git-ignored, generated locally
  ```

  Engine-managed alternative: `$ENGINE secret create db_password -` then `external: true` (Podman; with Docker, engine secrets need Swarm mode, so plain Docker Compose uses the `file:` form). Apps read `*_FILE` variables (`POSTGRES_PASSWORD_FILE=/run/secrets/db_password`) or the file directly.
- **Environment variables** are acceptable only for non-sensitive config and local throwaway credentials. They leak via `inspect`, `/proc/<pid>/environ`, crash dumps and child processes.
- `.env` files: only `.env.example` with placeholders is committed; real `.env` is git-ignored and excluded from the build context.
- Production: a secret manager (Vault, cloud secret manager, Kubernetes Secrets with encryption at rest) injecting files at runtime.
- **Certificates and keys are runtime mounts**: mount PEM cert/key read-only (`./certs:/app/certs:ro` or secrets), key file mode `0600`/`0400` readable by the app UID, never `COPY` a private key, keystore or `.p12` into an image. Public CA bundles may be baked in. Prefer PEM over PKCS12 (no keystore password to manage). Self-signed dev certs: short validity, generated by script, git-ignored.

## Network segmentation

- One user-defined network per tier; connect each service only to the networks it needs. Backend/data networks set `internal: true` (no egress).
- Never put databases on the network that publishes ports to the host.
- Disable inter-service traffic you do not need; do not rely on the default bridge.
- Internal TLS where the threat model requires it; plain HTTP is acceptable only on internal networks for health/metrics endpoints.

```yaml
networks:
  frontend: {}
  backend: { internal: true }
services:
  proxy: { networks: [frontend, backend] }
  app:   { networks: [backend] }
  db:    { networks: [backend] }
```

## Supply chain (summary; details in `supply-chain.md`)

- Images in compose files are pinned (tag + digest for anything deployed; no `:latest`).
- Scan every release image in CI; gate on fixable CRITICAL (and HIGH per project policy) with Trivy or Grype; include `--scanners vuln,secret`; lint compose/Containerfiles with `trivy config .` or Hadolint.
- Generate an SBOM (Syft or `trivy image --format cyclonedx`) and sign images and attestations with **Sigstore Cosign** in the release pipeline. Docker Content Trust / Notary v1 is deprecated: do not introduce it.
- Verify signatures at deploy (admission policy / `cosign verify`), not on every local build.
- Rebuild on a schedule so base-image fixes land; Renovate/Dependabot bump digests.

## Incident: secret leaked into an image or compose file

1. **Rotate first.** Revoke and reissue the credential immediately. Anyone who pulled the image or cloned the repo keeps the old value; rebuilding does not un-leak it.
2. Assess exposure: registry pull logs, who had access, how long it was public, where the credential was valid.
3. Fix the cause: move the value to a build secret or runtime secret; add the path to `.dockerignore` and `.gitignore`; add a secret scan gate (Trivy `--scanners secret`, gitleaks) so it cannot recur.
4. Rebuild and push clean images; then delete the affected tags/digests from the registry and mirrors, and purge local caches (`$ENGINE rmi`, CI caches).
5. If it was committed to git: rewriting history is cleanup, not remediation; rotation in step 1 is the remediation.
6. Record it (issue/ADR) with the rotation evidence.

## Review checklist

- [ ] No engine socket mount, no privileged, no host network/PID/IPC without written justification.
- [ ] Every app service: numeric non-root `user`, `read_only` + tmpfs, `no-new-privileges`, `cap_drop: [ALL]`, minimal `cap_add`.
- [ ] `mem_limit`, `cpus`, `pids_limit` set and verified on the engine actually used.
- [ ] No literal secrets in `environment:`; secrets via `secrets:`/`*_FILE`; no real `.env` committed.
- [ ] Certificates/keys mounted read-only at runtime, not baked in.
- [ ] Tiered networks; data tier `internal: true`; ports bound to `127.0.0.1` where local-only.
- [ ] Images pinned (digest for deployed images); health checks defined in compose.
- [ ] CI scans, SBOM and Cosign signing present for release images.

## Linked skills

- containers - Containerfile rules: base images, non-root `USER`, build secrets, `.dockerignore`.
- quarkus (if adopted) - Quarkus management port, health probes for distroless/native images.
- security - general threat modelling, secret handling, OWASP application Top 10.
- architecture - deployment topology, trust boundaries, network tiers.
- code-quality, module-testing - testing the hardened configuration (smoke tests with the same flags).
