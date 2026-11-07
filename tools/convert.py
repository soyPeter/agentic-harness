#!/usr/bin/env python3
"""Switch a project between the full install and thin mode (ADR-001):

  update.sh --to-thin <target> [--version V] [--force-hooks-path] [--dry-run]
  update.sh --to-full <target> [--force] [--force-hooks-path] [--dry-run]

--to-thin deletes the vendored harness files nobody edited and keeps edited ones as <file>.harness-bak; backbone/ and
the adopted packs' files stay, and the pin keeps the hashes the full install recorded for them ("kept"). It pins the
installed release (or --version) and adds what thin mode runs from: the pre-commit shim, core.hooksPath=.githooks and
the plugin entries in .claude/settings.json, whose harness hooks and installed release's permission rules it takes out.
--to-full vendors the pinned release again as update.sh would, telling edited files apart by those hashes, and takes
out what thin mode added.

Both refuse a working tree with uncommitted changes, so the switch is one change to review or revert. They check
everything before writing, undo their changes when a write fails part way, and change nothing in a project that is
already switched.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer  # noqa: E402
from installer import InstallError, LOCK_REL, SETTINGS_REL  # noqa: E402
import thin  # noqa: E402

BACKUP = ".harness-bak"
FRAGMENT = "payload/settings.fragment.json"
THIN_HOOKS_PATH = ".githooks"
# The launcher treats a project holding this file as a full install, whatever its lock says.
VENDORED_ENGINE = "scripts/harness/lib/harness.py"
AGENTS_IMPORT = re.compile(r"^@AGENTS\.md[ \t]*$", re.M)
LABEL = "Its pull request needs the harness-change-approved label: harness-verify refuses changes to the harness itself."


class Switch(installer.Plan):
    """A plan that saves each file as it was before changing it, so a switch that fails part way can be undone."""

    def __init__(self, target, dry_run):
        super().__init__(target, dry_run)
        self.hooks = hooks_path(target)
        self.saved = {}
        self.created = []

    def save(self, name):
        path = self.target / name
        if self.dry_run or name in self.saved:
            return
        self.saved[name] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.is_file() else None
        folder = path.parent
        while not folder.exists():
            self.created.append(folder)
            folder = folder.parent

    def write(self, rel_path, data, mode_from=None):
        self.save(rel_path)
        super().write(rel_path, data, mode_from)

    def remove(self, rel_path):
        self.save(rel_path)
        super().remove(rel_path)

    def move(self, rel_path, dest):
        self.save(rel_path)
        self.save(dest)
        if not self.dry_run:
            os.replace(str(self.target / rel_path), str(self.target / dest))

    def undo(self):
        for name, before in reversed(list(self.saved.items())):
            path = self.target / name
            if before is None:
                if path.is_file():
                    path.unlink()
                continue
            data, mode = before
            if not path.is_file() or path.read_bytes() != data:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            if stat.S_IMODE(path.stat().st_mode) != mode:
                path.chmod(mode)
        for folder in sorted(self.created, key=lambda f: len(f.parts), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        if hooks_path(self.target) != self.hooks:
            installer.run_git(self.target, *hooks_path_setting(self.hooks), check=True)


def carry_out(plan, change):
    """change(), the writes of a switch; if it fails part way, plan's changes are undone."""
    if plan.dry_run:
        return change()
    try:
        return change()
    except BaseException as exc:
        cause = str(exc) or type(exc).__name__
        try:
            plan.undo()
        except Exception as again:
            raise InstallError("%s. The switch stopped there, and undoing its changes failed too (%s). The working "
                               "tree was clean before it: git checkout -- . && git clean -fd && git %s puts it back"
                               % (cause, again, " ".join(hooks_path_setting(plan.hooks))))
        if isinstance(exc, (OSError, InstallError)):
            raise InstallError("%s. The switch stopped there and undid its changes; fix that and re-run" % cause)
        raise


def hooks_path_setting(value):
    """The git arguments that set core.hooksPath back to value ("" = unset)."""
    return ("config", "core.hooksPath", value) if value else ("config", "--unset", "core.hooksPath")


def installed_lock(target):
    if not target.is_dir():
        raise InstallError("target %s does not exist" % target)
    top = installer.run_git(target, "rev-parse", "--show-toplevel")
    if top.returncode:
        raise InstallError("%s is not a git repository" % target)
    if Path(top.stdout.strip()).resolve() != target.resolve():
        raise InstallError("target must be the repository root (%s), not a subdirectory" % top.stdout.strip())
    lock = installer.read_lock(target)
    if lock is None:
        raise InstallError("no harness installed in %s (bootstrap.sh installs it, init --thin in thin mode)" % target)
    if not (isinstance(lock, dict)
            and all(isinstance(lock.get(key, {}), dict) for key in ("files", "kept", "adopted"))):
        raise InstallError("%s is corrupt; restore it from git" % LOCK_REL)
    named = list(lock.get("files", {})) + list(lock.get("kept", {})) + sorted(pack_files(lock.get("adopted", {})))
    outside = [name for name in named if Path(name).is_absolute() or ".." in Path(name).parts]
    if outside:
        raise InstallError("%s lists files outside the project (%s); restore it from git"
                           % (LOCK_REL, ", ".join(outside[:3])))
    if lock.get("mode", "full") not in ("full", "thin"):
        raise InstallError("%s names an unknown install mode %r" % (LOCK_REL, lock.get("mode")))
    return lock


def pack_files(adopted):
    return {name for entry in adopted.values() if isinstance(entry, dict) for name in entry.get("files") or []}


def installed_fragment(lock, version, release):
    """The settings fragment of the installed release, whose permission rules the full install added; release is the
    checkout of v<version>, the release being pinned."""
    installed = str(lock.get("harness_version") or "")
    if installed == version:
        return release / FRAGMENT
    try:
        return thin.cached_release(installed, thin.release_commit(installed)) / FRAGMENT
    except thin.ThinError as exc:
        raise InstallError("%s; the switch needs the installed release (v%s) to take its permission rules out of %s. "
                           "If it was never published, update the project to a published release with update.sh first"
                           % (exc, installed, SETTINGS_REL))


def require_clean(target):
    status = installer.run_git(target, "status", "--porcelain")
    if status.returncode or status.stdout.strip():
        raise InstallError("%s has uncommitted changes; commit or stash them first, so the switch is a change of its "
                           "own to review or revert" % target)


def hooks_path(target):
    return installer.run_git(target, "config", "--get", "core.hooksPath").stdout.strip()


def backups_taken(target, names):
    taken = [name + BACKUP for name in names if os.path.lexists(str(target / (name + BACKUP)))]
    if taken:
        raise InstallError("%s already exists; move it away and re-run" % ", ".join(taken))


def note_claude_import(plan, thin_mode):
    path = plan.target / "CLAUDE.md"
    if not path.is_file():
        return
    imports = AGENTS_IMPORT.search(path.read_text(encoding="utf-8", errors="replace"))
    if thin_mode and imports:
        plan.note("note", "CLAUDE.md", "imports @AGENTS.md, which thin mode doesn't have: the plugin supplies the "
                                       "agent rules. Remove the line")
    elif not thin_mode and not imports:
        plan.note("note", "CLAUDE.md", "doesn't import @AGENTS.md as a full install's does; add the line to load the "
                                       "agent rules")


def prune(target, names):
    """Remove the folders that deleting names left empty."""
    for name in names:
        folder = (target / name).parent
        while folder != target and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent


def print_plan(plan, headline):
    print(headline)
    for action, path, detail in plan.report:
        print("  %-9s %s%s" % (action, path, "  (%s)" % detail if detail else ""))


def to_thin(target, args):
    lock = installed_lock(target)
    if lock.get("mode") == "thin":
        print("%s is already in thin mode (v%s)" % (target, lock.get("version")))
        return 0
    require_clean(target)
    version = args.version or str(lock.get("harness_version") or "")
    previous_hooks = hooks_path(target)
    if previous_hooks not in ("", installer.HOOKS_PATH, THIN_HOOKS_PATH) and not args.force_hooks_path:
        raise InstallError("core.hooksPath is %s, but thin mode runs its pre-commit hook from %s; re-run with "
                           "--force-hooks-path to replace the setting" % (previous_hooks, THIN_HOOKS_PATH))
    original, settings = installer.load_settings(target)

    locked, adopted = lock.get("files", {}), lock.get("adopted", {})
    packs = pack_files(adopted)
    kept = {name: digest for name, digest in locked.items() if name.startswith("backbone/") or name in packs}
    release_files = dict(thin.RELEASE_FILES)
    removed, backed_up = [], []
    for name, digest in sorted(locked.items()):
        if name in kept or name in release_files or not (target / name).is_file():
            continue
        (removed if installer.file_digest(target / name) == digest else backed_up).append(name)
    if (target / VENDORED_ENGINE).is_file() and VENDORED_ENGINE not in removed + backed_up:
        raise InstallError("%s isn't listed in %s, so it can't be told apart from a file of your own; run update.sh "
                           "on the full install first" % (VENDORED_ENGINE, LOCK_REL))

    commit, release = thin.release_checkout(version)
    updated = installer.settings_text(thin.plugin_settings(
        installer.drop_harness_settings(settings, installed_fragment(lock, version, release)), version))
    written = []
    for name, source in thin.RELEASE_FILES:
        data, path = (release / source).read_bytes(), target / name
        if path.is_file() and path.read_bytes() == data:
            continue
        if path.exists():
            if name not in locked:
                raise InstallError("%s already exists with different content; move it away and re-run" % name)
            if installer.file_digest(path) != locked[name]:
                backed_up.append(name)
        written.append((name, data))
    backups_taken(target, backed_up)

    plan = Switch(target, args.dry_run)
    for name in removed:
        plan.note("remove", name)
    for name in backed_up:
        plan.note("backup", name, "edited locally; kept as %s%s" % (name, BACKUP))
    for name, _ in written:
        plan.note("update" if (target / name).exists() else "add", name)
    if updated != original:
        plan.note("merge", SETTINGS_REL, "harness hooks and permissions out, the plugin in; other entries kept")
    if previous_hooks != THIN_HOOKS_PATH:
        plan.note("git", "core.hooksPath", THIN_HOOKS_PATH)
    pin = {"mode": "thin", "version": version, "commit": commit}
    if lock.get("installed"):
        pin["installed"] = lock["installed"]
    if adopted:
        pin["adopted"] = adopted
    # --to-full tells the kept files someone edited from the others by these hashes.
    if kept:
        pin["kept"] = kept
    plan.note("pin", LOCK_REL, "v%s, commit %s" % (version, commit))
    note_claude_import(plan, thin_mode=True)
    if args.dry_run:
        print_plan(plan, "Would switch %s to thin mode (dry run)" % target)
        return 0

    def switch():
        for name in backed_up:
            plan.move(name, name + BACKUP)
        for name in removed:
            plan.remove(name)
        prune(target, removed + backed_up)
        for name, data in written:
            plan.write(name, data)
            if name == thin.SHIM:
                (target / name).chmod(0o755)
        if updated != original:
            plan.write(SETTINGS_REL, updated.encode("utf-8"))
        if previous_hooks != THIN_HOOKS_PATH:
            installer.run_git(target, "config", "core.hooksPath", THIN_HOOKS_PATH, check=True)
        plan.write(LOCK_REL, (json.dumps(pin, indent=2) + "\n").encode("utf-8"))

    carry_out(plan, switch)
    print_plan(plan, "Switched %s to thin mode: the agentic-harness plugin runs the pinned release v%s"
               % (target, version))
    print("\nNext: review the switch and commit it, for example git commit -m \"chore: switch the agentic harness to "
          "thin mode\".\n%s\nEveryone working here installs the plugin (README, \"Thin mode\"), and after a fresh "
          "clone runs git config core.hooksPath %s once." % (LABEL, THIN_HOOKS_PATH))
    return 0


def to_full(target, args):
    lock = installed_lock(target)
    if lock.get("mode", "full") == "full":
        print("%s is already a full install (v%s)" % (target, lock.get("harness_version")))
        return 0
    require_clean(target)
    version, commit = str(lock.get("version") or ""), str(lock.get("commit") or "")
    if not re.fullmatch(thin.VERSION_PATTERN, version):
        raise InstallError("%s pins no valid version" % LOCK_REL)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise InstallError("%s pins v%s without a valid commit" % (LOCK_REL, version))
    original, settings = installer.load_settings(target)
    previous_hooks = hooks_path(target)
    release = thin.cached_release(version, commit)
    for name in ("payload/owned", "payload/seed", FRAGMENT, "plugin/pre-commit"):
        if not (release / name).exists():
            raise InstallError("release v%s has no %s to install" % (version, name))
    updated = installer.settings_text(installer.add_harness_settings(thin.without_plugin(settings), release / FRAGMENT))
    shim = target / thin.SHIM
    shim_edited = shim.is_file() and shim.read_bytes() != (release / "plugin/pre-commit").read_bytes()
    folder = target / THIN_HOOKS_PATH
    other_hooks = [p.name for p in folder.iterdir() if p.name != "pre-commit" and not p.name.endswith(BACKUP)] \
        if folder.is_dir() else []
    adopted = lock.get("adopted", {})
    sources = installer.owned_sources(adopted, release)
    recorded = dict(lock.get("kept", {}))
    recorded.update(lock.get("files", {}))
    # --to-thin and pin write these from the pinned release, so its copy is the one the project was given.
    for name, source in thin.RELEASE_FILES:
        if name in sources:
            recorded[name] = installer.file_digest(release / source)
    seed = release / "payload/seed"
    context = {"PROJECT_NAME": target.name, "DATE": datetime.date.today().isoformat(), "HARNESS_VERSION": version}

    def vendor(plan):
        files = installer.sync_owned(plan, sources, recorded, args.force)
        installer.seed_project(plan, context, report_existing=False, seed=seed)
        installer.migrate_conf(plan, context, seed=seed)
        return files

    check = installer.Plan(target, dry_run=True)
    vendor(check)
    backups_taken(target, [path for action, path, _ in check.report if action == "overwrite"]
                  + ([thin.SHIM] if shim_edited else []))

    plan = Switch(target, args.dry_run)
    # sync_owned sets the release's file mode on files whose content already matches, without going through the plan.
    for name in sources:
        if (target / name).is_file():
            plan.save(name)

    def switch():
        files = vendor(plan)
        if shim_edited:
            plan.note("backup", thin.SHIM, "edited locally; kept as %s%s" % (thin.SHIM, BACKUP))
            plan.move(thin.SHIM, thin.SHIM + BACKUP)
        elif shim.is_file():
            plan.remove(thin.SHIM)
            plan.note("remove", thin.SHIM)
        if not args.dry_run:
            prune(target, [thin.SHIM])
        if updated != original:
            plan.write(SETTINGS_REL, updated.encode("utf-8"))
            plan.note("merge", SETTINGS_REL, "the plugin out, harness hooks and permissions in; other entries kept")
        installer.configure_hooks_path(plan, args.force_hooks_path
                                       or (previous_hooks == THIN_HOOKS_PATH and not other_hooks))
        installer.write_lock(plan, lock, files, adopted, version)

    carry_out(plan, switch)
    note_claude_import(plan, thin_mode=False)
    conflicts = [path for action, path, _ in plan.report if action == "CONFLICT"]
    print_plan(plan, "%s %s to a full install of v%s%s" % ("Would switch" if args.dry_run else "Switched", target,
                                                          version, " (dry run)" if args.dry_run else ""))
    if conflicts:
        print("\nResolve each conflict: merge <file>.harness-new into <file> and delete the .harness-new file, or "
              "re-run with --force to take the harness version.")
    if not args.dry_run:
        print("\nNext: review the switch and commit it, for example git commit -m \"chore: switch the agentic harness "
              "to a full install\".\nThe pre-push hook refuses harness changes, so push it with HARNESS_VERIFY=off git "
              "push. %s\nAfter a fresh clone, each developer runs git config core.hooksPath %s once."
              % (LABEL, installer.HOOKS_PATH))
    return 1 if conflicts else 0


def main(argv):
    parser = argparse.ArgumentParser(prog="update.sh", description="Switch a project between the full install and "
                                                                   "thin mode (ADR-001).")
    direction = parser.add_mutually_exclusive_group(required=True)
    direction.add_argument("--to-thin", action="store_true", help="from the vendored harness to the plugin and a pin")
    direction.add_argument("--to-full", action="store_true", help="from thin mode back to the vendored harness")
    parser.add_argument("target")
    parser.add_argument("--version", help="--to-thin: the release to pin (default: the installed one)")
    parser.add_argument("--force", action="store_true",
                        help="--to-full: replace files that differ from the release (backups: *.harness-bak)")
    parser.add_argument("--force-hooks-path", action="store_true", help="replace an existing core.hooksPath setting")
    parser.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    args = parser.parse_args(argv)
    if args.version and not args.to_thin:
        parser.error("--version goes with --to-thin; --to-full installs the pinned release")
    if args.force and not args.to_full:
        parser.error("--force goes with --to-full; --to-thin keeps every edited file as a backup")
    target = Path(args.target).expanduser().resolve()
    try:
        return to_thin(target, args) if args.to_thin else to_full(target, args)
    except (InstallError, thin.ThinError) as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
