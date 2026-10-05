# OWASP Docker Top 10 mapping (Podman and Docker)

Linked from the container-security skill. Read for full security reviews, audits, or when a control needs threat and verification detail. The Docker Top 10 (D01-D10) is container-specific; the OWASP web Application Top 10 belongs to the harness security skill. Cross-reference, do not merge.

Each control: threat, required mitigation, how to verify. `$ENGINE` is the value of `HARNESS_CONTAINER_ENGINE` (`podman` or `docker`); the subcommand is the same for both engines unless a note says otherwise.

## D01 - Secure user mapping

Threat: a process running as UID 0 in the container becomes host root after a breakout (rootful engines without user namespaces).

Mitigation:
- Final image `USER` is a numeric non-root UID; compose sets `user: "1001:1001"`.
- Engine runs rootless where possible: with Podman the default; with Docker via rootless mode or `userns-remap` (an ADR decision).
- Volumes owned by the app UID (`:U`, `userns_mode: keep-id`) instead of running as root to "fix permissions".

Verify:
- `$ENGINE image inspect app --format '{{.Config.User}}'` is non-empty and not `0`/`root`.
- `$ENGINE exec <ctr> id` shows a non-zero uid.
- With Podman: `podman info --format '{{.Host.Security.Rootless}}'` is `true` on dev/CI hosts. With Docker: `docker info --format '{{.SecurityOptions}}'` lists `rootless` or `userns` if adopted.

## D02 - Patch management

Threat: known CVEs in base images, OS packages and app dependencies.

Mitigation:
- Pinned base images updated by Renovate/Dependabot (tag + digest).
- Scheduled rebuild (weekly) even without code changes.
- CI scan gate on fixable CRITICAL (and HIGH per policy); unfixed findings tracked with an expiry, not silently ignored (`.trivyignore` entries carry a reason and date).
- Application dependencies scanned too (the build tool's dependency check, e.g. OWASP Dependency-Check for Gradle or Maven, or a Trivy filesystem scan on the repo).

Verify: `trivy image --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 app` (with Podman: add `--image-src podman`); CI history shows scheduled runs.

## D03 - Network segmentation and firewalling

Threat: flat networks allow lateral movement (compromised web tier talks straight to the database).

Mitigation:
- User-defined network per tier; services join only what they need; data tiers `internal: true`.
- Publish only the entry point; bind dev-only ports to `127.0.0.1`.
- Never expose engine APIs (Docker TCP socket, `podman system service` over TCP) or debug ports.
- Kubernetes: default-deny `NetworkPolicy` plus explicit allows.

Verify: `$ENGINE network inspect <net>` (check `internal`), `$ENGINE port <ctr>` (no `0.0.0.0` for internal services), `ss -tlnp` on the host.

## D04 - Secure defaults and hardening

Threat: default capabilities, writable rootfs and setuid binaries give an attacker room to escalate.

Mitigation:
- `cap_drop: [ALL]`, minimal `cap_add` with a comment per capability.
- `security_opt: [no-new-privileges:true]`.
- `read_only: true` with tmpfs for scratch paths.
- No engine socket mounts (`docker.sock`, `podman.sock`): equivalent to host root.
- No `--privileged`; no host namespaces.

Capability guide: `NET_BIND_SERVICE` only for ports < 1024 in-container (prefer >= 1024); `CHOWN`, `SETUID`, `SETGID` only for images that drop privileges themselves (prefer starting as non-root); `SYS_PTRACE`, `SYS_ADMIN`, `NET_ADMIN` never in production.

Verify: `podman inspect <ctr> --format '{{.EffectiveCaps}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.SecurityOpt}}'` (Docker: `docker inspect <ctr> --format '{{.HostConfig.CapAdd}} {{.HostConfig.CapDrop}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.SecurityOpt}}'`); grep compose files for `docker.sock|podman.sock|privileged|network_mode: host`.

## D05 - Maintain security contexts

Threat: disabling seccomp, SELinux or AppArmor removes the mandatory access control layer.

Mitigation:
- Keep the engine's default seccomp profile; do not set `seccomp=unconfined`.
- SELinux hosts (Fedora/RHEL; Podman labels by default, Docker when its SELinux support is enabled): keep labeling on; use `:Z`/`:z` on bind mounts instead of `label=disable`.
- AppArmor hosts (Ubuntu/Debian Docker): keep the default profile.
- Tighter custom seccomp profiles only with tests proving the app still works.

Verify: `podman inspect <ctr> --format '{{.ProcessLabel}} {{.HostConfig.SecurityOpt}}'` (non-empty label, no `unconfined`); Docker: `--format '{{.AppArmorProfile}}'`.

## D06 - Protect secrets

Threat: credentials in image layers, build args, environment variables or VCS are readable by anyone with the image or repo.

Mitigation:
- Build-time: `RUN --mount=type=secret` (`$ENGINE build --secret`; Docker needs BuildKit). Never `ENV`/`ARG`/`COPY` secrets. An `rm` in a later layer does not remove a secret from an earlier layer.
- Runtime: compose `secrets:` (or `podman secret`; Docker engine secrets need Swarm), mounted under `/run/secrets`; apps read files (`*_FILE`). Production: external secret manager.
- Private keys and keystores mounted at runtime, read-only, never baked into images.
- `.env` with real values git-ignored and excluded from the build context.

Verify:
- `$ENGINE history --no-trunc app` (weak: shows instructions and build args only).
- `$ENGINE save app | strings | grep -iE 'token|secret|password|BEGIN .*PRIVATE KEY'` (catches files written by `RUN`).
- `trivy image --scanners secret app` in CI; gitleaks or similar on the repo.

Incident: a secret in a pushed image or commit is compromised. Rotate first, then fix, rebuild, and delete the affected tags (container-security skill, Incident section).

## D07 - Resource protection

Threat: one container exhausts memory, CPU or PIDs and starves the host (DoS, fork bomb).

Mitigation:
- Memory, CPU and PID limits on every service (`mem_limit`, `cpus`, `pids_limit`; `$ENGINE run --memory --cpus --pids-limit`).
- With Podman: podman-compose honours `deploy.resources` only partially: use service-level keys and verify.
- JVM heap sized relative to the limit (`-XX:MaxRAMPercentage`).
- Rootless engines (Podman, rootless Docker) on cgroup v2 need the cpu/memory/pids controllers delegated to the user (systemd default on current Fedora/RHEL; check on other distros), otherwise limits are silently not applied.
- Log rotation so logs cannot fill the disk.

Verify: `$ENGINE inspect <ctr> --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}}'`; `$ENGINE stats --no-stream`; `cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers`.

## D08 - Container image integrity and origin

Threat: tampered or substituted images (compromised registry, typo-squatted names, MITM, mutable tags).

Mitigation:
- Fully qualified image names from trusted registries; digests for deployed images.
- Images signed with Sigstore Cosign (keyless OIDC or KMS/key-based) in the release pipeline; SBOM and provenance attached as signed attestations. Docker Content Trust / Notary v1 is deprecated: do not adopt it.
- Signature verification at deploy: Kubernetes admission policy (Kyverno, Sigstore policy-controller, OPA Gatekeeper) or `cosign verify` in the deploy job; Podman hosts can enforce via `policy.json` with `sigstoreSigned` requirements.
- Private registry with access control for production pulls.

Verify: `cosign verify --certificate-identity <id> --certificate-oidc-issuer <issuer> reg/app@sha256:...` (keyless) or `cosign verify --key cosign.pub ...`; `cosign verify-attestation --type cyclonedx ...`.

## D09 - Immutable paradigm

Threat: patching or editing running containers causes drift that cannot be audited or reproduced.

Mitigation:
- `read_only: true`; state only in named volumes or external services; tmpfs for scratch.
- No `exec` to patch production containers; change -> rebuild -> scan -> sign -> redeploy.
- Same image digest promoted across environments; configuration via env/secrets, not rebuilds.

Verify: `$ENGINE diff <ctr>` shows no changes outside declared volumes/tmpfs; deployed digest matches the scanned/signed digest.

## D10 - Logging and monitoring

Threat: incidents go unnoticed; logs vanish with the container or fill the disk.

Mitigation:
- Apps log to stdout/stderr (structured JSON preferred); no log files inside the container.
- Log driver with rotation (Docker `json-file` with `max-size`/`max-file`; Podman `k8s-file` with `--log-opt max-size`, or `journald`).
- Ship logs centrally in shared environments; alert on restarts, OOM kills (exit 137), unexpected `exec` sessions and outbound connections.
- Audit engine events: `podman events` / `docker events`.

Verify: `$ENGINE inspect <ctr> --format '{{.HostConfig.LogConfig}}'`; restart/OOM counts visible in monitoring.

## Pre-deployment verification table

| Control | Check | Ref |
|---------|-------|-----|
| Non-root | `.Config.User` non-root; `id` in container non-zero | D01 |
| Patched | Scan: no fixable CRITICAL (HIGH per policy) | D02 |
| Network | Tiered networks; no host network; internal ports not on `0.0.0.0` | D03 |
| Hardening | `cap_drop: [ALL]`, `no-new-privileges`, no socket mounts | D04 |
| MAC | seccomp/SELinux/AppArmor not disabled; no `--privileged` | D05 |
| Secrets | `save \| strings` and Trivy secret scan clean; no secret env literals | D06 |
| Limits | Memory, CPU, PIDs set and effective | D07 |
| Integrity | Digest pinned; `cosign verify` passes at deploy | D08 |
| Immutable | Read-only rootfs; `$ENGINE diff` clean | D09 |
| Logging | Rotation set; logs to stdout; central shipping where shared | D10 |

## References

- OWASP Docker Security Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Docker_Security_Cheat_Sheet.html
- OWASP Docker Top 10: https://owasp.org/www-project-docker-top-10/
- CIS Docker Benchmark: https://www.cisecurity.org/benchmark/docker
- NIST SP 800-190: https://csrc.nist.gov/pubs/sp/800/190/final
- Podman rootless tutorial: https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md
