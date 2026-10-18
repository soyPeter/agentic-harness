#!/usr/bin/env python3
"""Install, update or inspect the agentic harness in a target repository.

  installer.py install <target> [--name NAME] [--git-init] [--force] [--force-hooks-path] [--dry-run]
  installer.py update  <target> [--force] [--force-hooks-path] [--dry-run]
  installer.py status  <target>
  installer.py catalog

File ownership:
  payload/owned/          harness-owned: added, and replaced on update unless edited locally.
                          Local edits are detected through backbone/.harness-lock.json; the new
                          version is then written next to the file as <file>.harness-new.
  catalog/<pack>/         stack packs. Always shipped, inert, to scripts/harness/catalog/. The stack is
                          decided in the design phase: once an ADR is accepted, the project adopts packs
                          with `harness.py adopt`; updates then refresh the adopted packs' files too.
  payload/seed/           project-owned: created once if missing, never rewritten afterwards (update only
                          appends new harness.conf settings, commented out).
  payload/settings.fragment.json
                          merged into .claude/settings.json; only hook entries whose command
                          contains "scripts/harness/" are owned by the harness.
"""
import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = HARNESS_ROOT / "payload"
OWNED = PAYLOAD / "owned"
SEED = PAYLOAD / "seed"
CATALOG = HARNESS_ROOT / "catalog"
SETTINGS_FRAGMENT = PAYLOAD / "settings.fragment.json"
VERSION = (HARNESS_ROOT / "VERSION").read_text().strip()

LOCK_REL = "backbone/.harness-lock.json"
SETTINGS_REL = ".claude/settings.json"
HOOKS_PATH = "scripts/harness/git-hooks"
HOOK_MARK = "scripts/harness/"
IGNORED = {".DS_Store"}


class InstallError(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def files_under(base):
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*")
                  if p.is_file() and p.name not in IGNORED)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    return digest(path.read_bytes()) if path.is_file() else None


def run_git(target, *args, check=False):
    result = subprocess.run(["git", "-C", str(target)] + list(args), capture_output=True, text=True)
    if check and result.returncode != 0:
        raise InstallError("git %s failed: %s" % (" ".join(args), result.stderr.strip()))
    return result


def render(data, context):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    for key, value in context.items():
        text = text.replace("{{%s}}" % key, value)
    return text.encode("utf-8")


# --------------------------------------------------------------------------- catalog

def pack_names():
    return sorted(p.parent.name for p in CATALOG.glob("*/pack.json"))


def owned_sources(adopted):
    """{target path: source} for the core payload, the inert catalog copy, and adopted packs' files."""
    sources = {rel: OWNED / rel for rel in files_under(OWNED)}
    for rel in files_under(CATALOG) if CATALOG.is_dir() else []:
        sources["scripts/harness/catalog/" + rel] = CATALOG / rel
    for name, entry in sorted(adopted.items()):
        pack = CATALOG / name
        if not (pack / "pack.json").is_file():
            continue
        roots = [pack / "install"] + [pack / "options" / o / "install" for o in entry.get("options", [])]
        for root in roots:
            for rel in files_under(root) if root.is_dir() else []:
                sources[rel] = root / rel
    return sources


class Plan(object):
    """Collects changes; writes them only when not a dry run."""

    def __init__(self, target, dry_run):
        self.target = target
        self.dry_run = dry_run
        self.report = []

    def note(self, action, path, detail=""):
        self.report.append((action, path, detail))

    def write(self, rel_path, data, mode_from=None):
        if self.dry_run:
            return
        dest = self.target / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        if mode_from is not None:
            shutil.copymode(str(mode_from), str(dest))

    def remove(self, rel_path):
        if not self.dry_run:
            (self.target / rel_path).unlink()


# --------------------------------------------------------------------------- steps

def check_target(target, git_init, plan):
    if not target.is_dir():
        raise InstallError("target %s does not exist" % target)
    top = run_git(target, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        if not git_init:
            raise InstallError("%s is not a git repository (run git init, or pass --git-init)" % target)
        plan.note("git", ".", "git init")
        if not plan.dry_run:
            run_git(target, "init", "-q", check=True)
        return
    if Path(top.stdout.strip()).resolve() != target.resolve():
        raise InstallError("target must be the repository root (%s), not a subdirectory" % top.stdout.strip())


def sync_owned(plan, sources, lock_files, force):
    """Install or update harness-owned files with three-way detection via the lock."""
    new_lock = {}
    for rel_path, src in sorted(sources.items()):
        data = src.read_bytes()
        new_hash = digest(data)
        dest = plan.target / rel_path
        current = file_digest(dest)
        locked = lock_files.get(rel_path)
        new_lock[rel_path] = new_hash
        if current is None:
            plan.write(rel_path, data, src)
            plan.note("add", rel_path)
        elif current == new_hash:
            if not plan.dry_run:
                shutil.copymode(str(src), str(dest))
        elif locked is not None and current == locked:
            plan.write(rel_path, data, src)
            plan.note("update", rel_path)
        elif force:
            plan.write(rel_path + ".harness-bak", dest.read_bytes())
            plan.write(rel_path, data, src)
            plan.note("overwrite", rel_path, "local copy saved as %s.harness-bak" % rel_path)
        elif locked == new_hash:
            plan.note("keep", rel_path, "edited locally; no upstream change")
        else:
            plan.write(rel_path + ".harness-new", data, src)
            plan.note("CONFLICT", rel_path, "edited locally; new version written to %s.harness-new" % rel_path)
    for rel_path in sorted(set(lock_files) - set(sources)):
        dest = plan.target / rel_path
        if not dest.exists():
            continue
        if file_digest(dest) == lock_files[rel_path]:
            plan.remove(rel_path)
            plan.note("remove", rel_path, "no longer part of the harness or an adopted pack")
        else:
            plan.note("orphan", rel_path, "dropped from the harness but edited locally; left in place")
    return new_lock


def seed_project(plan, context, report_existing):
    for rel_path in files_under(SEED):
        if (plan.target / rel_path).exists():
            if report_existing:
                plan.note("exists", rel_path, "project file kept as is")
            continue
        plan.write(rel_path, render((SEED / rel_path).read_bytes(), context), SEED / rel_path)
        plan.note("seed", rel_path)


CONF_REL = "backbone/harness.conf"
CONF_KEY = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=")


def migrate_conf(plan, context):
    """Append settings the template has and the project's harness.conf lacks, commented out.

    harness.conf is project-owned, so update never rewrites it. New keys arrive commented out, with the
    template's explanation: nothing changes until the user uncomments one (user-only keys: as the user)."""
    path = plan.target / CONF_REL
    template_path = SEED / CONF_REL
    if not path.exists() or not template_path.exists():
        return
    current = path.read_text(encoding="utf-8")
    present = {m.group(1) for m in map(CONF_KEY.match, current.splitlines()) if m}
    template = render(template_path.read_bytes(), context).decode("utf-8")
    blocks, comments, added = [], [], []
    for line in template.splitlines():
        m = CONF_KEY.match(line)
        if not line.strip():
            comments = []
        elif m:
            if m.group(1) not in present:
                blocks.append(comments + [line if line.lstrip().startswith("#") else "# " + line])
                added.append(m.group(1))
                comments = []
        elif line.lstrip().startswith("#"):
            comments.append(line)
    if not added:
        return
    text = current.rstrip("\n") + "\n\n# Added by a harness update, commented out so nothing changes until you uncomment\n" \
        "# a setting (user-only ones: commit as the user, HARNESS_VERIFY=off git commit ...).\n"
    text += "\n".join("\n".join(block) for block in blocks) + "\n"
    plan.write(CONF_REL, text.encode("utf-8"))
    plan.note("migrate", CONF_REL, "new setting(s), commented out: %s" % ", ".join(added))


def merge_settings(plan):
    path = plan.target / SETTINGS_REL
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        settings = json.loads(original) if original.strip() else {}
    except ValueError as exc:
        raise InstallError("%s is not valid JSON (%s); fix it and re-run" % (SETTINGS_REL, exc))
    fragment = json.loads(SETTINGS_FRAGMENT.read_text(encoding="utf-8"))

    hooks = settings.get("hooks") or {}
    for event in list(hooks):
        kept = []
        for group in hooks[event] or []:
            inner = [h for h in group.get("hooks", []) if HOOK_MARK not in h.get("command", "")]
            if inner:
                kept.append(dict(group, hooks=inner))
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    for event, groups in fragment["hooks"].items():
        hooks.setdefault(event, []).extend(groups)
    settings["hooks"] = hooks

    allow = settings.setdefault("permissions", {}).setdefault("allow", [])
    for rule in fragment["permissions"]["allow"]:
        if rule not in allow:
            allow.append(rule)

    updated = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    if updated != original:
        plan.write(SETTINGS_REL, updated.encode("utf-8"))
        plan.note("merge" if original else "add", SETTINGS_REL, "harness hooks and permissions; other entries kept")


def configure_hooks_path(plan, force):
    current = run_git(plan.target, "config", "--get", "core.hooksPath").stdout.strip()
    if current == HOOKS_PATH:
        return
    if current and not force:
        plan.note("WARN", "core.hooksPath", "already %r; not changed. Chain the harness hooks from your hooks, "
                                            "or re-run with --force-hooks-path" % current)
        return
    git_dir = run_git(plan.target, "rev-parse", "--git-common-dir").stdout.strip()
    legacy = Path(plan.target, git_dir, "hooks") if git_dir else None
    if legacy and legacy.is_dir():
        active = [p.name for p in legacy.iterdir() if not p.name.endswith(".sample")]
        if active:
            plan.note("WARN", ".git/hooks", "these hooks stop running under core.hooksPath: %s" % ", ".join(sorted(active)))
    plan.note("git", "core.hooksPath", HOOKS_PATH)
    if not plan.dry_run:
        run_git(plan.target, "config", "core.hooksPath", HOOKS_PATH, check=True)


def read_lock(target):
    path = target / LOCK_REL
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise InstallError("%s is corrupt; restore it from git" % LOCK_REL)


def write_lock(plan, previous, files, adopted):
    today = datetime.date.today().isoformat()
    lock = {
        "harness_version": VERSION,
        "installed": (previous or {}).get("installed", today),
        "updated": today,
        "adopted": adopted,
        "files": files,
    }
    plan.write(LOCK_REL, (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8"))


# --------------------------------------------------------------------------- commands

def sync(target, args, installing):
    plan = Plan(target, args.dry_run)
    check_target(target, getattr(args, "git_init", False), plan)
    previous = read_lock(target)
    if installing and previous is not None:
        raise InstallError("harness %s is already installed; use update.sh" % previous.get("harness_version", "?"))
    if not installing and previous is None:
        raise InstallError("no harness lock in %s; use bootstrap.sh" % target)

    adopted = (previous or {}).get("adopted", {})
    context = {
        "PROJECT_NAME": getattr(args, "name", None) or target.resolve().name,
        "DATE": datetime.date.today().isoformat(),
        "HARNESS_VERSION": VERSION,
    }
    files = sync_owned(plan, owned_sources(adopted), (previous or {}).get("files", {}), args.force)
    seed_project(plan, context, report_existing=installing)
    if not installing:
        migrate_conf(plan, context)
    merge_settings(plan)
    configure_hooks_path(plan, args.force_hooks_path)
    write_lock(plan, previous, files, adopted)

    before = (previous or {}).get("harness_version")
    print("%s agentic harness %s%s in %s%s" % (
        "Would install" if args.dry_run and installing else "Would update" if args.dry_run else
        "Installed" if installing else "Updated",
        "%s -> " % before if before else "", VERSION, target, " (dry run)" if args.dry_run else ""))
    print("  stack packs adopted: %s" % (", ".join(sorted(adopted)) or "none (decided in the design phase)"))
    for action, path, detail in plan.report:
        print("  %-9s %s%s" % (action, path, "  (%s)" % detail if detail else ""))
    conflicts = [p for a, p, _ in plan.report if a == "CONFLICT"]
    if conflicts:
        print("\nResolve each conflict: merge <file>.harness-new into <file>, delete the .harness-new file,")
        print("then run update again. Or re-run with --force to take the harness version.")
    if installing and not args.dry_run:
        print("\nNext: commit the harness, then start an agent session. It will run first-run setup")
        print("(AGENTS.md section 1) to fill the backbone docs with you.")
    return 1 if conflicts else 0


def status(target):
    lock = read_lock(target)
    if lock is None:
        print("No harness installed in %s" % target)
        return 1
    adopted = lock.get("adopted", {})
    print("harness %s installed in %s (available: %s)" % (lock.get("harness_version"), target, VERSION))
    print("  stack packs adopted: %s" % (", ".join("%s via %s" % (n, e.get("adr")) for n, e in sorted(adopted.items()))
                                         or "none"))
    sources = owned_sources(adopted)
    for rel_path, locked in sorted(lock.get("files", {}).items()):
        current = file_digest(target / rel_path)
        upstream = file_digest(sources[rel_path]) if rel_path in sources else None
        state = ("missing" if current is None else
                 "edited locally" if current != locked else
                 "removed upstream" if upstream is None else
                 "update available" if upstream != locked else "current")
        if state != "current":
            print("  %-16s %s" % (state, rel_path))
    for rel_path in sorted(sources):
        if rel_path not in lock.get("files", {}):
            print("  %-16s %s" % ("new upstream", rel_path))
    return 0


def list_catalog():
    for name in pack_names():
        meta = json.loads((CATALOG / name / "pack.json").read_text(encoding="utf-8"))
        print("%-10s %s" % (name, meta.get("description", "")))
        print("%-10s applies when: %s" % ("", meta.get("decides", "")))
    print("\nPacks are adopted inside a project after its stack ADR is accepted:")
    print("  python3 scripts/harness/lib/harness.py catalog   (options to decide)")
    print("  python3 scripts/harness/lib/harness.py adopt <pack> --adr ADR-NNN --with ... --without ...")
    return 0


def main(argv):
    parser = argparse.ArgumentParser(description="agentic harness installer %s" % VERSION)
    sub = parser.add_subparsers(dest="command")
    for name in ("install", "update"):
        cmd = sub.add_parser(name)
        cmd.add_argument("target")
        cmd.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
        cmd.add_argument("--force", action="store_true",
                         help="replace locally edited harness files (backups: *.harness-bak)")
        cmd.add_argument("--force-hooks-path", action="store_true",
                         help="replace an existing core.hooksPath setting")
        if name == "install":
            cmd.add_argument("--name", help="project name for the docs (default: folder name)")
            cmd.add_argument("--git-init", action="store_true", help="run git init if needed")
    cmd = sub.add_parser("status")
    cmd.add_argument("target")
    sub.add_parser("catalog")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 64
    try:
        if args.command == "catalog":
            return list_catalog()
        target = Path(args.target).expanduser().resolve()
        if args.command == "status":
            return status(target)
        return sync(target, args, installing=args.command == "install")
    except InstallError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
