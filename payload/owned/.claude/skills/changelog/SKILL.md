---
name: changelog
description: Generate or update CHANGELOG.md for a release from Conventional Commits, in Keep a Changelog format, and suggest the next version. Use on request at release time ("update the changelog", "what changed since the last release"); not needed for normal task work.
applies-to: any
last-verified: 2026-10-05
sources: adapted from decebals/claude-code-java changelog-generator (0d98fe9); Keep a Changelog 1.1.0; Conventional Commits 1.0.0; Semantic Versioning 2.0.0
---

# Changelog

Run only when the user asks for it. The changelog is written for users of the software: describe effects, not implementation.

## 1. Find the project's conventions

Read, in this order, and stop at the first that answers:
1. `backbone/4-KNOWLEDGE.md` (versioning scheme, tag format, changelog rules) and the commit rules in `backbone/7-CONVENTIONS.md`.
2. The existing `CHANGELOG.md`: heading levels, section order, link style, version format.
3. Git tags: `git tag --sort=-version:refname | head -10`.

| Tags look like | Scheme |
|---|---|
| `v1.4.2`, `1.4.2`, `release-1.4.2` | SemVer (with that prefix) |
| `v2.1`, `2.1` | Two-component |
| `2026.10`, `2026.10.1` | CalVer |

If nothing answers, ask the user which scheme and tag format to use, and suggest recording the answer in `backbone/4-KNOWLEDGE.md`.

## 2. Collect the changes

```bash
git describe --tags --abbrev=0                 # last release tag
git log <last-tag>..HEAD --no-merges --format='%h %s'
git log <last-tag>..HEAD --grep='BREAKING' --format='%h %s%n%b'   # bodies only where needed
```

- Extract issue or PR references: `#123`, `Fixes #123`, `(#123)`.
- Extract task ids from commit bodies when the project wants them in entries.
- Read full bodies only for commits that may be breaking or whose subject is unclear.

## 3. Map commits to sections

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Sections, in this order unless the existing file uses another: Added, Changed, Deprecated, Removed, Fixed, Security.

| Commit | Section |
|---|---|
| `feat` | Added (or Changed if it alters existing behaviour) |
| `fix` | Fixed (Security if it fixes a vulnerability) |
| `perf` | Changed |
| `feat`/`fix`/`refactor` whose body announces a deprecation | Deprecated |
| a commit that removes a feature or endpoint | Removed |
| `build(deps)` fixing a CVE | Security; other dependency bumps are omitted unless users notice them |
| `!` after the type, or `BREAKING CHANGE:` footer | Its section, prefixed with **BREAKING:** and a migration hint |
| `refactor`, `test`, `docs`, `style`, `ci`, `chore`, `build` | Omit (no user-visible effect) unless the user asks for an internal changelog |
| Not conventional | Read it; place it by its effect, or ask |

`deprecate` is not a Conventional Commits type; detect deprecations from the commit body or the code (`@Deprecated`, `Deprecation` header), not from a type.

Rewrite subjects for readers: "Customers can filter orders by status (#212)", not "feat(order): add status param to repo query".

## 4. Write the entry

```markdown
## [Unreleased]

## [1.5.0] - 2026-10-05

### Added
- Filter orders by status in `GET /orders` ([#212])

### Changed
- **BREAKING:** `GET /customers` returns 50 items per page instead of 100; request `size=100` to keep the old behaviour ([#230])

### Fixed
- Totals no longer round half-cents down for EUR orders ([#219])

[#212]: https://github.com/<owner>/<repo>/pull/212
[1.5.0]: https://github.com/<owner>/<repo>/compare/v1.4.2...v1.5.0
[unreleased]: https://github.com/<owner>/<repo>/compare/v1.5.0...HEAD
```

- Newest version first, directly under `## [Unreleased]`; date in ISO format `YYYY-MM-DD`.
- One line per user-visible change; merge commits that belong to the same change and list all their references.
- Use reference-style links at the bottom if the file already does; keep existing link definitions and add new ones.
- Update the `[unreleased]` compare link to start from the new tag, and add a compare link for the new version.
- Follow the existing file's heading levels and section order exactly; edit only the new section and the link block.
- Empty sections are left out.

## 5. Suggest the version

| Change present | SemVer | Two-component | CalVer |
|---|---|---|---|
| Breaking (`!` or `BREAKING CHANGE`) | major | major | new period; call it out |
| `feat` | minor | minor | new period or `.n` |
| only `fix`/`perf` | patch | minor | `.n` |

- While the major version is 0, a breaking change bumps the **minor** version (and features the patch) only if `4-KNOWLEDGE.md` or the existing changelog says the project follows that 0.x convention; otherwise ask.
- State the reason: "Suggested 1.5.0: new features, no breaking changes."
- Don't create tags or commit unless the user asks; when they do, use the commit format in `backbone/8-WORKFLOW.md` (for example `docs(changelog): release 1.5.0`, if `docs` is in `HARNESS_COMMIT_TYPES`).

## Checks before handing back

- [ ] Every user-visible commit since the last tag appears once; internal-only commits are omitted.
- [ ] Every breaking change is marked **BREAKING:** with a migration hint, and the suggested version reflects it.
- [ ] Security fixes are in Security with their CVE or advisory id where known.
- [ ] Links resolve to the right compare range and issues.
- [ ] Nothing outside the new section was rewritten.

## Linked skills

- `api-design`: decide whether an API change is breaking and what migration hint to give.
- `openapi`: the contract version should match a release that changes the API.
- `security`: wording for security fixes without disclosing exploit details before users can upgrade.
