# Agentic harness: sandbox image for unattended runs (harness-owned).
# Add your stack's toolchain (JDK, Gradle, ...) in a project Dockerfile FROM this one, or extend below and
# accept that harness updates will flag the edit.
# The base is pinned by digest and baked into the image's environment: every judge verdict made in here records it
# as the sandbox's image_digest (ADR-003). Move the digest to update the base.
ARG HARNESS_SANDBOX_IMAGE=node:22-bookworm@sha256:7702d8aa4d5910871692af4480eb3ba86f23047a6417a44d857d06c95d060d3f
FROM ${HARNESS_SANDBOX_IMAGE}
ARG HARNESS_SANDBOX_IMAGE
ENV HARNESS_SANDBOX_IMAGE=${HARNESS_SANDBOX_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends \
      git python3 iptables ipset dnsutils ca-certificates curl jq \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

# ~/.claude exists before the volume mounts there, so the new volume takes the agent's ownership, not root's.
RUN useradd -m -s /bin/bash agent \
    && install -d -o agent -g agent /home/agent/.claude

COPY init-firewall.sh /usr/local/bin/init-firewall.sh
COPY trust-workspace.py /usr/local/bin/trust-workspace.py
RUN chmod 0755 /usr/local/bin/init-firewall.sh /usr/local/bin/trust-workspace.py

USER agent
