#!/bin/sh
# Harness-owned. Reports harness misconfiguration; exits 1 on errors.
exec python3 -I "$(dirname "$0")/lib/harness.py" doctor
