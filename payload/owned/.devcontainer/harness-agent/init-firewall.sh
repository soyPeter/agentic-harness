#!/bin/bash
# Agentic harness: outbound allowlist for the sandbox (harness-owned). Runs as root in the egress container, in the
# network namespace the agent's container joins (docker-compose.yml).
# Everything outbound is dropped except DNS, the loopback, established connections and these hosts:
# the Anthropic API, GitHub (git and gh), and HARNESS_FIREWALL_ALLOW. IPs are resolved at start time.
# Once the rules are in force, the host list is published for the agent's container, whose judge verdicts record its
# hash as evidence (ADR-003).
set -euo pipefail
set -f   # the allowlist is split on spaces, never expanded as file names

PUBLISHED=/run/harness-egress/allowlist
ALLOW="api.anthropic.com statsig.anthropic.com github.com api.github.com codeload.github.com \
objects.githubusercontent.com ${HARNESS_FIREWALL_ALLOW:-}"

rm -f "$PUBLISHED"
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
# The allowlist holds IPv4 addresses only, so no IPv6 may leave either.
if ip6tables -L OUTPUT >/dev/null 2>&1; then
  ip6tables -F OUTPUT
  ip6tables -A OUTPUT -o lo -j ACCEPT
  ip6tables -P OUTPUT DROP
fi

if curl -fsS --max-time 5 https://example.com >/dev/null 2>&1; then
  echo "init-firewall: example.com is reachable; the allowlist is NOT in effect" >&2
  exit 1
fi
mkdir -p "$(dirname "$PUBLISHED")"
for host in $ALLOW; do echo "$host"; done | tr 'A-Z' 'a-z' | sort -u > "$PUBLISHED"
echo "init-firewall: outbound traffic limited to: $ALLOW"
