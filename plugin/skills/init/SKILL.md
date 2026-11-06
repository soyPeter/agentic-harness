---
name: init
description: Install the agentic harness in thin mode in the current Git repository after the user requests enrollment.
---

From the repository root, run the launcher in this plugin's `plugin/launcher.py` with `init --thin`. In Claude Code, use:

```sh
python3 "$CLAUDE_PLUGIN_ROOT/plugin/launcher.py" init --thin
```

For other CLIs, locate the plugin root from this skill's path and run the same launcher. Report the pinned version, commit, and generated project files.

The default version must already be published as a tag with thin-mode assets. Use `--version <released-version>` only when the user names a different released version. Existing project-owned documents are kept; report any that the installer lists for review.
