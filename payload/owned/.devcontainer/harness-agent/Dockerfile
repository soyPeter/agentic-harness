# Agentic harness: sandbox image for unattended runs (harness-owned).
# Add your stack's toolchain (JDK, Gradle, ...) in a project Dockerfile FROM this one, or extend below and
# accept that harness updates will flag the edit.
FROM node:22-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
      git python3 iptables ipset dnsutils sudo ca-certificates curl jq \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN useradd -m -s /bin/bash agent \
    && printf '%s\n' 'Defaults env_keep += "HARNESS_FIREWALL_ALLOW"' \
         'agent ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh' > /etc/sudoers.d/agent-firewall \
    && chmod 0440 /etc/sudoers.d/agent-firewall

COPY init-firewall.sh /usr/local/bin/init-firewall.sh
COPY trust-workspace.py /usr/local/bin/trust-workspace.py
RUN chmod 0755 /usr/local/bin/init-firewall.sh /usr/local/bin/trust-workspace.py

USER agent
