#!/bin/bash
# Agentic harness: outbound allowlist for the sandbox (harness-owned). Runs as root at container start.
# Everything outbound is dropped except DNS, the loopback, established connections and these hosts:
# the Anthropic API, GitHub (git and gh), and HARNESS_FIREWALL_ALLOW. IPs are resolved at start time.
set -euo pipefail

ALLOW="api.anthropic.com statsig.anthropic.com github.com api.github.com codeload.github.com \
objects.githubusercontent.com ${HARNESS_FIREWALL_ALLOW:-}"

iptables -F OUTPUT
ipset destroy harness-allow 2>/dev/null || true
ipset create harness-allow hash:net

for host in $ALLOW; do
  for ip in $(dig +short A "$host" | grep -E '^[0-9.]+$' || true); do
    ipset add harness-allow "$ip" -exist
  done
done
# GitHub publishes its address ranges; add them so git over HTTPS keeps working when IPs rotate.
curl -fsS --max-time 10 https://api.github.com/meta 2>/dev/null \
  | jq -r '(.git + .api + .web)[]' 2>/dev/null | grep -E '^[0-9.]+/[0-9]+$' \
  | while read -r net; do ipset add harness-allow "$net" -exist; done || true

iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT
iptables -A OUTPUT -m set --match-set harness-allow dst -j ACCEPT
iptables -P OUTPUT DROP

if curl -fsS --max-time 5 https://example.com >/dev/null 2>&1; then
  echo "init-firewall: example.com is reachable; the allowlist is NOT in effect" >&2
  exit 1
fi
echo "init-firewall: outbound traffic limited to: $ALLOW"
