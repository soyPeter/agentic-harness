# 7. Conventions: agentic-harness

How code is written here. Agents read this file before every task.

## Code style and naming
Python 3.8, standard library only, in the engine (`payload/owned/scripts/harness/lib/`). Match the surrounding file. Prefer functions and explicit names. No new package and no formatter config beyond what the file already uses. Shell that ships with the product stays bash and POSIX-friendly where the existing scripts are.

## Patterns to use, and what to avoid
| Concern | Use | Avoid |
|---|---|---|
| Gates | The pinned release v0.30.0 | Editing the working tree and expecting that edit to judge the same change |
| Delivery | `orca --pr` and a pull request Pedro merges | `--merge`, `--trust`, a local merge into main |
| Dependencies | The Python standard library | Third-party imports in the engine |
| Product ADRs | A link from `backbone/5-DECISIONS.md` and a mention in the spec narrative | A second copy under `backbone/adr/` that claims the same number |
| Task order | `(after: <id>)` on the task line | Starting a later wave while its dependency is still open |

## Testing
The self-test is `tests/run-tests.sh`. Tests live in `tests/test-*.py` and use `unittest`. A behaviour change needs a test that fails before the change and passes after it. The judge runs `HARNESS_TEST_CMD`, which is that script. It is long. That is expected on every judge pass.

## Commits
Conventional Commits. Scopes in use: `harness`, `orca`, `plugin`, `docs`, `ci`, `backbone`, `tests`.

## Definition of Done additions
For a product code change, `tests/run-tests.sh` passes. For a docs audit, the findings note is in the pull request and names the revision it read. Wave 1 does not cut a release and does not move the pin.
