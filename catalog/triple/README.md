# Triple pack

Triple's delivery policy for a supervised pilot (first target: Disputes). It sits on top of the core harness and
needs no change to it. It has two parts:

1. **The profile**: `HARNESS_PROFILE="triple"` in `backbone/harness.conf` (or `./enroll.sh <repo> --profile triple`).
   It is enforced in code. `harness.py orca` refuses `--merge` and `--trust`, `orca-nightly` refuses to start, and
   `enroll` refuses `--automation` and `--protect`. Only a human merges.
2. **This pack**, adopted from an Accepted pilot ADR that names `triple`:

   ```sh
   python3 scripts/harness/lib/harness.py adopt triple --adr ADR-00N --with <options> --without <options>
   ```

| Option | Effect |
|---|---|
| `disputes-pci` | Parks authentication, billing and payments, migrations, PCI evidence, secrets and infrastructure: agents may not write them, from the file tools or the shell. Running migrations and writing a CVV are refused, and card numbers get a warning. Those paths and terms make a task not low-risk, so it gets no light lane and no policy approval. Installs the `disputes-pci` skill. |
| `ears` | `HARNESS_REQ_STYLE="ears"`: `spec-check` refuses a requirement without an EARS pattern. Given/When/Then criteria stay the evidence the judge traces (`requirements-writing/ears.md`). |

## Linear as the system of record

A user command, not an agent's: the shell gate refuses agents everything except `--dry-run`. It needs
`LINEAR_API_KEY`, a personal key from Linear's Security & access settings.

```sh
python3 scripts/harness/lib/harness.py linear import DIS-142 --task 4.1 --light   # draft spec + task line
python3 scripts/harness/lib/harness.py linear receipt 4.1 --status "In Review"   # after the judge passes
```

- `import` writes `backbone/specs/<task>.md` from the template, with a `Linear: DIS-142 (<url>)` line and the
  ticket quoted in Context as source material, not instructions. It also adds the task line to `3-TASKS.md`, with
  `(light)` when you pass `--light`. The analyst then writes the requirements. `--from issue.json` imports an issue
  saved from the Linear MCP server's `get_issue` instead of calling the API.
- `receipt` posts `harness.py receipt <task>` as a comment on the ticket. It refuses a task without a judge pass on
  the current code. `--status` moves the ticket, but never to a completed or canceled state: closing is the human's
  call.

For agents working with the Linear MCP server directly, paste `tools.conf.linear` into `backbone/tools.conf`. Reads
run, and every write needs the user.


## Ground rules for the pilot

- Supervised mode only. Autonomous mode, branch protection changes and any write to a Triple-Tech repository need
  Pedro's approval.
- The harness never merges. The deliverer opens the PR and watches CI, and a human merges.
- Authentication, billing, payments, migrations, secrets and PCI evidence stay parked: agents may not edit them (see
  the `disputes-pci` option).
- The `harness-agent` devcontainer is **not** a PCI attestation. Its outbound allowlist and isolation limit what an
  unattended agent can reach, but nobody has assessed it against PCI DSS. Until a separate review, the pilot touches
  only non-PCI surfaces: UI, docs and skills.
