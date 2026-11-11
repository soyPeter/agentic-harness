"""Third-party agent resources (ADR-006): the user's admission records and revocations (backbone/admissions.conf), the
digest of a reviewed bundle, and what a SKILL.md does as Claude Code loads it. Standard library only.

Harness-owned file: the harness update replaces it.

    [admit <name>]                      a reviewed bundle the project uses as guidance
    path = .claude/skills/<name>        the bundle: a folder (everything under it) or one file
    decision = ADR-NNN                  an Accepted ADR that names the bundle
    source = <where it came from>       revision = <immutable release or commit, or why there is none>
    digest = sha256:<64 hex>            harness.py admission digest <path>
    purpose, compatible, dependencies, data, license = <what the review found; "none" where none>

    [revoke sha256:<64 hex>]            these bytes are never guidance again, wherever they are
    reason = <why, and the decision that revoked them>
"""
import hashlib
import os
import posixpath
import re

ADMIT_KEYS = ("path", "decision", "source", "revision", "digest", "purpose", "compatible", "dependencies", "data",
              "license")
REVOKE_KEYS = ("reason",)
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
ADR_REF = re.compile(r"^ADR-\d{3,}$")
SECTION = re.compile(r"^\[(\S+)[ \t]+([^\]]*?)[ \t]*\]$")
FIELD = re.compile(r"^([a-z][a-z0-9-]*)[ \t]*=[ \t]*(.*?)[ \t]*$")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SKIPPED = (".DS_Store",)
# Claude Code runs these while it loads a skill, before any tool call the harness's hooks see: an inline placeholder is
# recognised at a line start or after whitespace, a fenced one on a fence opened with "!".
INLINE_SHELL = re.compile(r"(?:^|(?<=\s))!`")
FENCED_SHELL = re.compile(r"^[ \t]*(?:`{3,}|~{3,})!", re.M)
FRONT_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)[ \t]*:")


def parse(text):
    """(admissions {name: fields}, revocations {digest: fields}, errors). Each entry's fields include "line" and
    "problems" (what is wrong with that entry). An entry that is wrong still counts: an admission admits nothing, and
    a revocation keeps revoking."""
    admissions, revocations, errors = {}, {}, []
    current = None
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        section = SECTION.match(line)
        if section:
            kind, label = section.groups()
            current = {"line": n, "problems": []}
            if kind == "admit" and NAME.match(label):
                if label in admissions:
                    admissions[label]["problems"].append("admitted twice (line %d)" % n)
                    current = admissions[label]
                else:
                    admissions[label] = current
            elif kind == "revoke" and DIGEST.match(label):
                current = revocations.setdefault(label, current)
            else:
                errors.append("line %d: expected [admit <name>] or [revoke sha256:<64 hex digits>]" % n)
                current = None
            continue
        field = FIELD.match(line)
        if current is None:
            errors.append("line %d: '%s' is outside an [admit ...] or [revoke ...] section" % (n, line[:40]))
        elif not field:
            current["problems"].append("line %d is not 'key = value'" % n)
        elif field.group(1) in current:
            current["problems"].append("%s is given twice (line %d)" % (field.group(1), n))
        elif field.group(2):
            current[field.group(1)] = field.group(2)
    for name, fields in admissions.items():
        missing = [key for key in ADMIT_KEYS if not fields.get(key)]
        if missing:
            fields["problems"].append("the record is missing %s" % ", ".join(missing))
        if fields.get("digest") and not DIGEST.match(fields["digest"]):
            fields["problems"].append("digest must be sha256:<64 hex digits>, as harness.py admission digest prints")
        if fields.get("decision") and not ADR_REF.match(fields["decision"]):
            fields["problems"].append("decision must name an ADR (ADR-NNN)")
    for digest, fields in revocations.items():
        if not fields.get("reason"):
            fields["problems"].append("the revocation of %s gives no reason" % digest)
    return admissions, revocations, errors


def bundle_path(path):
    """path as a repository-relative POSIX path, or None when it is absolute or leaves the repository."""
    if not path or path.startswith("/") or "\\" in path:
        return None
    norm = posixpath.normpath(path)
    return None if norm in (".", "..") or norm.startswith("../") else norm


def content(parsed):
    """What the records decide, without line numbers: comments and layout are not a change."""
    admissions, revocations, _ = parsed
    strip = lambda fields: {k: v for k, v in fields.items() if k not in ("line", "problems")}
    return ({name: strip(f) for name, f in admissions.items()}, {d: strip(f) for d, f in revocations.items()})


def digest(entries):
    """The bundle's digest from (name inside the bundle, sha256 of its content) pairs: sha256 over the lines
    "<sha256>  <name>\\n" sorted by name."""
    lines = "".join("%s  %s\n" % (h, name) for name, h in sorted(entries))
    return "sha256:" + hashlib.sha256(lines.encode("utf-8", "surrogateescape")).hexdigest()


def content_hash(data, link=False):
    # A link is hashed as its target, so redirecting it changes the digest even when the old target is gone.
    return hashlib.sha256((b"symlink:" if link else b"") + data).hexdigest()


def disk_entries(path):
    """(name, hash) pairs for the bundle at path, a folder or a file; None when nothing is there."""
    def entry(full, name):
        if os.path.islink(full):
            return name, content_hash(os.fsencode(os.readlink(full)), link=True)
        try:
            with open(full, "rb") as handle:
                return name, content_hash(handle.read())
        except OSError:
            return name, content_hash(b"unreadable:")

    if os.path.islink(path) or os.path.isfile(path):
        return [entry(path, os.path.basename(path))]
    if not os.path.isdir(path):
        return None
    found = []
    for top, dirs, files in os.walk(path):
        for name in dirs + files:
            full = os.path.join(top, name)
            if name in SKIPPED or (name in dirs and not os.path.islink(full)):
                continue
            if os.path.islink(full) or os.path.isfile(full):
                found.append(entry(full, os.path.relpath(full, path).replace(os.sep, "/")))
    return found


def links_out(path):
    """The links in the bundle at path that lead out of it: the digest covers a link's target path, not the bytes
    there, so what such a link leads to can change without changing the digest."""
    if os.path.islink(path):
        return [os.path.basename(path)]
    if not os.path.isdir(path):
        return []
    root, found = os.path.realpath(path), []
    for top, dirs, files in os.walk(path):
        for name in dirs + files:
            full = os.path.join(top, name)
            target = os.path.realpath(full)
            if os.path.islink(full) and target != root and not target.startswith(root + os.sep):
                found.append(os.path.relpath(full, path).replace(os.sep, "/"))
    return found


def disk_digest(path):
    entries = disk_entries(path)
    return digest(entries) if entries is not None else None


def frontmatter(text):
    """The top-level keys of a SKILL.md's frontmatter, lower case."""
    lines = text.lstrip("﻿").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or lines[0].strip() != "---":
        return set()
    keys = set()
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key = FRONT_KEY.match(line)
        if key:
            keys.add(key.group(1).lower())
    return keys


def runs_on_load(text):
    """What a SKILL.md runs when Claude Code loads it, outside every tool call the hooks see."""
    found = []
    if "hooks" in frontmatter(text):
        found.append("registers hooks (frontmatter hooks:) that run commands for the rest of the session")
    if INLINE_SHELL.search(text) or FENCED_SHELL.search(text):
        found.append("runs shell commands while it loads (!`...` or a ```! block)")
    return found


def preapproves(text):
    """Why a SKILL.md grants permissions as it loads, or None: allowed-tools skips Claude Code's permission prompt for
    those tools, and a confirm contract relies on that prompt in supervised mode."""
    keys = frontmatter(text)
    if "allowed-tools" in keys or "allowed_tools" in keys:
        return "pre-approves tools (frontmatter allowed-tools:), which skips the user's permission prompt"
    return None
