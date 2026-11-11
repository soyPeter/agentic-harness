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
# Claude Code runs these while it loads a skill, before any tool call the harness's hooks see. Its patterns (2.1.322):
# /```!\s*\n?[\s\S]*?\n?```/g anywhere in the text, and /(?<=^|\s)!`[^`]+`/gm, where JavaScript's \s also matches
# U+FEFF and Python's doesn't. Tildes aren't Claude Code's, but cost nothing to refuse too.
INLINE_SHELL = re.compile(r"(?:^|(?<=[\s\ufeff]))!`")
FENCED_SHELL = re.compile(r"(?:`{3}|~{3})!")
PLAIN_KEY = re.compile(r"^([^\s#'\"{}\[\],&*!|>%@`?:-][^:#]*?|-[^\s:#][^:#]*?)[ \t]*:(?:[ \t]|$)")
SINGLE_KEY = re.compile(r"^'((?:[^']|'')*)'[ \t]*:(?:[ \t]|$)")
DOUBLE_KEY = re.compile(r'^"([^"\\]*)"[ \t]*:(?:[ \t]|$)')


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


def disk_entries(path, names=None):
    """(name, hash) pairs for the bundle at path, a folder or a file; None when nothing is there. names, when given,
    are the files of the bundle that count (as git lists them); otherwise every file under path does."""
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
    if names is not None:
        return [entry(os.path.join(path, name), name) for name in names if name.rsplit("/", 1)[-1] not in SKIPPED]
    found = []
    for top, dirs, files in os.walk(path):
        for name in dirs + files:
            full = os.path.join(top, name)
            if name in SKIPPED or (name in dirs and not os.path.islink(full)):
                continue
            if os.path.islink(full) or os.path.isfile(full):
                found.append(entry(full, os.path.relpath(full, path).replace(os.sep, "/")))
    return found


def links_out(path, names=None):
    """The links in the bundle at path (among names, when given) that lead out of it: the digest covers a link's
    target path, not the bytes there, so what such a link leads to can change without changing the digest."""
    if os.path.islink(path):
        return [os.path.basename(path)]
    if not os.path.isdir(path):
        return []
    root, found = os.path.realpath(path), []
    if names is not None:
        return [name for name in names if os.path.islink(os.path.join(path, name)) and not
                os.path.realpath(os.path.join(path, name)).startswith(root + os.sep)]
    for top, dirs, files in os.walk(path):
        for name in dirs + files:
            full = os.path.join(top, name)
            target = os.path.realpath(full)
            if os.path.islink(full) and target != root and not target.startswith(root + os.sep):
                found.append(os.path.relpath(full, path).replace(os.sep, "/"))
    return found


def disk_digest(path, names=None):
    entries = disk_entries(path, names)
    return digest(entries) if entries is not None else None


def frontmatter(text):
    """({top-level key, lower case: its value as written}, None), or (what it has so far, why the harness can't read
    the rest). Claude Code reads the frontmatter as YAML; this reads the block mappings skills use (plain or quoted
    keys, indented and block values), and anything else (a merge key, an explicit or escaped key, flow style, a
    directive, a repeated key, no closing line) is unreadable: it could hold any key, a name or hooks among them."""
    lines = text.lstrip("\ufeff").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or lines[0].strip() != "---":
        return {}, None
    fields, key = {}, None
    for n, line in enumerate(lines[1:], 2):
        if line.strip() in ("---", "..."):
            return fields, None
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t" or line.startswith("- ") or line.strip() == "-":
            if key is None:
                return fields, "line %d of its frontmatter continues no key" % n
            fields[key] += "\n" + line
            continue
        found = PLAIN_KEY.match(line) or SINGLE_KEY.match(line) or DOUBLE_KEY.match(line)
        if not found:
            return fields, "line %d of its frontmatter isn't a key the harness can read" % n
        key = found.group(1).replace("''", "'") if found.re is SINGLE_KEY else found.group(1)
        key = key.strip().lower()
        if key == "<<" or key in fields:
            return fields, "line %d of its frontmatter %s" % (n, "merges other keys in" if key == "<<"
                                                             else "repeats the key %s" % key)
        fields[key] = line[found.end():].strip()
    return fields, "its frontmatter has no closing ---"


def scalar(value):
    """A one-line YAML scalar as a string, or None when it is something else (a block, a flow, an escape)."""
    value = value.strip()
    if "\n" in value or not value or value[0] in "|>[{&*!%@`":
        return None
    if value[0] == "'":
        end = re.match(r"^'((?:[^']|'')*)'[ \t]*(?:#.*)?$", value)
        return end.group(1).replace("''", "'") if end else None
    if value[0] == '"':
        end = re.match(r'^"([^"\\]*)"[ \t]*(?:#.*)?$', value)
        return end.group(1) if end else None
    return re.sub(r"[ \t]+#.*$", "", value).strip()


def names(text):
    """The names Claude Code may give the skill from its frontmatter, lower case: {} when it names none, None when the
    harness can't tell (an unreadable frontmatter or name), so the skill could be called anything."""
    fields, problem = frontmatter(text)
    if problem:
        return None
    if "name" not in fields:
        return set()
    name = scalar(fields["name"])
    return {name.lower()} if name else None


def runs_on_load(text):
    """What a SKILL.md runs when Claude Code loads it, outside every tool call the hooks see."""
    found = []
    fields, problem = frontmatter(text)
    if problem:
        found.append("may register hooks: %s" % problem)
    if "hooks" in fields:
        found.append("registers hooks (frontmatter hooks:) that run commands for the rest of the session")
    if INLINE_SHELL.search(text) or FENCED_SHELL.search(text):
        found.append("runs shell commands while it loads (!`...` or a ```! block)")
    return found


def preapproves(text):
    """Why a SKILL.md grants permissions as it loads, or None: allowed-tools skips Claude Code's permission prompt for
    those tools, and a confirm contract relies on that prompt in supervised mode."""
    fields, _ = frontmatter(text)
    if "allowed-tools" in fields or "allowed_tools" in fields:
        return "pre-approves tools (frontmatter allowed-tools:), which skips the user's permission prompt"
    return None
