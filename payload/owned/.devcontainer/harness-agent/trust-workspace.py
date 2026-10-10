#!/usr/bin/env python3
"""Agentic harness (harness-owned): mark a folder as trusted for Claude Code inside the sandbox.

In an untrusted folder, `claude -p` ignores the project's hooks and permissions, so the harness would not
run. The sandbox trusts its own workspace; outside a sandbox, accept the trust dialog interactively instead.
"""
import json
import os
import sys

folder = os.path.realpath(sys.argv[1] if len(sys.argv) > 1 else os.getcwd())
path = os.path.expanduser("~/.claude.json")
data = {}
if os.path.exists(path):
    with open(path) as handle:
        data = json.load(handle)
data.setdefault("projects", {}).setdefault(folder, {})["hasTrustDialogAccepted"] = True
with open(path, "w") as handle:
    json.dump(data, handle)
print("trusted %s for Claude Code" % folder)
