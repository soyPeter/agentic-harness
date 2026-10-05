# Container supply chain

Linked from the container-security skill. Read when editing CI/release pipelines, registry configuration, scan gates, signing or SBOM generation. These steps run in **CI/release**, not as a requirement on every local build; locally, a quick `trivy image` before pushing is enough.

## Pipeline order

```text
lint (Hadolint, trivy config) -> build -> scan (vuln + secret, gate) -> push by digest
  -> SBOM -> sign image + attest SBOM/provenance (Cosign) -> verify at deploy
```

Sign and attest the **digest** that was scanned; never re-tag and sign something else. Promote the same digest across environments.

## Pinning and updates

- Base images and compose images: fully qualified, `tag@sha256:digest` for anything deployed.
- Renovate or Dependabot updates digests and tags with PRs; CI on the PR rebuilds and scans.
- Build tool (as the ADR chose), e.g. Gradle: wrapper `distributionSha256Sum`, dependency verification (`gradle/verification-metadata.xml`) and locking; Maven: wrapper `distributionSha256Sum`, pinned plugin versions, checksum policy `fail`; npm: committed lock file with `npm ci`.
- Scheduled rebuild (weekly) so OS-level fixes land without code changes.
- Downloads in a build stage carry a checksum check; no `curl | sh`.

## Scanning gates

| Tool | Use |
|------|-----|
| Trivy | vulnerabilities, secrets, misconfiguration (`trivy image`, `trivy fs`, `trivy config`) |
| Grype | vulnerabilities (pairs with Syft SBOMs) |
| Hadolint | Containerfile lint |
| gitleaks / trufflehog | secrets in the repo history |

```bash
# With Podman (no Docker daemon needed)
trivy image --image-src podman --scanners vuln,secret \
  --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 app:1.4.0
# With Docker (Trivy reads the daemon's images by default)
trivy image --scanners vuln,secret --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 app:1.4.0
# Either engine, from an archive
$ENGINE save -o app.tar app:1.4.0 && trivy image --input app.tar --exit-code 1 --severity CRITICAL
grype app:1.4.0 --fail-on critical
```

Gate policy (set per project, record it in the backbone):
- Fail on fixable CRITICAL always; fail on fixable HIGH for release images unless the project policy says otherwise.
- Exceptions live in `.trivyignore` / Grype ignore config with CVE id, reason, owner and expiry date. Expired exceptions fail the build.
- Any secret finding fails the build and triggers the incident procedure (rotate first).

## SBOM

```bash
syft registry.example.com/app@sha256:<digest> -o cyclonedx-json > sbom.cdx.json
# or
trivy image --format cyclonedx --output sbom.cdx.json registry.example.com/app@sha256:<digest>
```

- One SBOM per released digest (per architecture for multi-arch indexes).
- CycloneDX or SPDX JSON; keep the format consistent across the org.
- Attach as a signed attestation rather than a loose file (below), so consumers can verify it belongs to the image.

## Signing and attestation (Sigstore Cosign)

Docker Content Trust / Notary v1 is deprecated; use Cosign (or Notation where the platform mandates it).

```bash
# Keyless (CI with OIDC identity, e.g. GitHub Actions id-token: write)
cosign sign --yes registry.example.com/app@sha256:<digest>
cosign attest --yes --type cyclonedx --predicate sbom.cdx.json registry.example.com/app@sha256:<digest>

# Key-based (KMS or file key; never commit the private key)
cosign sign --key kms://<provider>/<key> registry.example.com/app@sha256:<digest>
```

Verification at deploy:

```bash
cosign verify \
  --certificate-identity-regexp '^https://github.com/<org>/<repo>/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  registry.example.com/app@sha256:<digest>
cosign verify-attestation --type cyclonedx ... registry.example.com/app@sha256:<digest>
```

- Kubernetes: enforce with Kyverno `verifyImages`, Sigstore policy-controller or Gatekeeper.
- With Podman (hosts that run images directly): `/etc/containers/policy.json` (or `~/.config/containers/policy.json`) with a `sigstoreSigned` requirement for the registry, plus `registries.d` config with `use-sigstore-attachments: true`.
- With Podman, signing at push time is also possible: `podman push --sign-by-sigstore-private-key cosign.key ...` (key-based); Cosign remains the portable choice in CI.
- With Docker: the engine does not enforce Sigstore signatures on pull; run `cosign verify` in the deploy job or enforce in the orchestrator.
- Provenance: generate SLSA provenance in CI (e.g. GitHub `actions/attest-build-provenance` or the SLSA generator) and attach as an attestation.

## Registry hygiene

- Production pulls only from a private, access-controlled registry (mirror or proxy public bases into it).
- Push credentials are short-lived CI tokens (OIDC), scoped per repository; never long-lived personal tokens in CI variables.
- Immutable tags for releases where the registry supports it; `latest` is never deployed.
- Retention policy deletes unreferenced digests; keep signatures/attestations with their digest.

## Example: GitHub Actions job (Podman shown)

With Docker, replace `podman` with `docker` (or use `docker/build-push-action`) and take the pushed digest from
`docker buildx build --push --metadata-file meta.json` (`containerimage.digest`) instead of `--digestfile`.

```yaml
permissions: { contents: read, packages: write, id-token: write }
steps:
  - uses: actions/checkout@v4            # pin actions by commit SHA in real pipelines
  - run: podman run --rm -i docker.io/hadolint/hadolint < Containerfile
  - run: podman build -f Containerfile -t ghcr.io/${{ github.repository }}:${{ github.sha }} .
  - uses: aquasecurity/trivy-action@<pinned-sha>
    with:
      image-ref: ghcr.io/${{ github.repository }}:${{ github.sha }}
      scanners: vuln,secret
      severity: CRITICAL,HIGH
      ignore-unfixed: true
      exit-code: "1"
  - run: |
      echo "${{ secrets.GITHUB_TOKEN }}" | podman login ghcr.io -u ${{ github.actor }} --password-stdin
      podman push --digestfile digest ghcr.io/${{ github.repository }}:${{ github.sha }}
  - uses: sigstore/cosign-installer@<pinned-sha>
  - run: |
      IMG=ghcr.io/${{ github.repository }}@$(cat digest)
      syft "$IMG" -o cyclonedx-json > sbom.cdx.json
      cosign sign --yes "$IMG"
      cosign attest --yes --type cyclonedx --predicate sbom.cdx.json "$IMG"
```

Notes: with Podman, the Trivy action may need `TRIVY_IMAGE_SRC=podman`; if not, scan via `podman save` + `--input`. With Docker it reads the daemon directly. Cosign reads registry credentials from `~/.docker/config.json` or `${XDG_RUNTIME_DIR}/containers/auth.json` (set `REGISTRY_AUTH_FILE`/`DOCKER_CONFIG` as needed); verify the login is visible to Cosign. Syft must be installed (e.g. `anchore/sbom-action/download-syft`).

## Checklist

- [ ] Images pinned by digest; automated update PRs enabled.
- [ ] Scan gate on vuln + secret; exceptions have reason, owner, expiry.
- [ ] SBOM generated per released digest and attached as attestation.
- [ ] Image signed with Cosign (keyless or KMS); no DCT/Notary v1.
- [ ] Verification enforced at deploy (admission policy, `policy.json`, or deploy-job `cosign verify`).
- [ ] CI actions and tool versions pinned; push credentials short-lived.
