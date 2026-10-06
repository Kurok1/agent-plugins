---
name: setup-codebase-hook
description: Install or refresh the codebase-map SessionStart hook in the current project's .codex/hooks.json. Use when the user explicitly wants continuous codebase-map checkpoints for one project.
---

# Setup Codebase Hook

Enable continuous codebase-map knowledge checkpoints only for the selected project.

## Workflow

1. Treat the current session project as the target unless the user names another project root.
   Pass that directory explicitly; the script intentionally does not search ancestors for Git or project markers.
2. Resolve the directory containing this `SKILL.md`, then run its setup script with absolute paths:

   ```bash
   python3 <skill-dir>/scripts/setup_codebase_hook.py \
     --project-root <project-root>
   ```

3. Read the JSON result. Report the resolved project root, `.codex/hooks.json` path, and shared `script` path. `script_created` indicates whether the shared script was installed; `changed: false` means the project's hook configuration was already current.
4. Tell the user to open `/hooks`, review and trust the project hook definition, then start a new task in that project so all lifecycle events load from the beginning.

The setup command owns only the codebase-map `SessionStart` command handler. For an existing handler, it updates only `command` and `commandWindows`, preserving its group, position, matcher, timeout, context limit, status message, and other fields. It preserves every other project hook, folds duplicate codebase-map `SessionStart` handlers into the first one, and refuses unsafe symlinks, invalid JSON, or a same-layer `.codex/config.toml` with inline hooks.

The handler matches `startup|resume|clear|compact`; resuming a session uses `SessionStart` with `source: resume`. It injects continuous maintenance instructions and the available map indexes; it does not capture tool calls or create runtime evidence files.

The setup script copies the standalone `codebase-map/scripts/codebase_hook.py` to `~/.codebase-map/codebase-hook.py` only when the destination is missing. It preserves an existing regular file and points project handlers at this shared file's absolute path. The shared directory is independent of any harness product. The installed script needs only Python's standard library and Git for Git-aware discovery; it never loads code from the plugin directory.

Run this skill once in an existing project to migrate a handler that still points into a plugin installation or at the earlier `~/.codex/codebase-hook.py` location. Subsequent plugin upgrades or moves require no project hook changes. The shared script is not automatically upgraded: to replace it with the bundled version, explicitly remove or move aside `~/.codebase-map/codebase-hook.py` and run setup again for one project. All migrated projects then use the replacement at the same path.

Register hooks only in the selected project's `.codex/hooks.json`. The shared executable belongs under `~/.codebase-map/`, but setup creates neither user-global hook configuration nor plugin-bundled hooks.
