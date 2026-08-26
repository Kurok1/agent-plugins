---
name: setup-codebase-hook
description: Install or refresh codebase-map lifecycle hooks in the current project's .codex/hooks.json. Use when the user explicitly wants to enable codebase-map hooks for one project.
---

# Setup Codebase Hook

Enable automatic codebase-map evidence capture only for the selected project.

## Workflow

1. Treat the current session project as the target unless the user names another project root.
   Pass that directory explicitly; the script intentionally does not search ancestors for Git or project markers.
2. Resolve the directory containing this `SKILL.md`, then run its setup script with absolute paths:

   ```bash
   python3 <skill-dir>/scripts/setup_codebase_hook.py \
     --project-root <project-root>
   ```

3. Read the JSON result. Report the resolved project root and `.codex/hooks.json` path. A `changed: false` result means the project was already configured with the current runner.
4. Tell the user to open `/hooks`, review and trust the project hook definition, then start a new task in that project so all lifecycle events load from the beginning.

The setup command owns only codebase-map command handlers. It preserves other project hooks, folds stale or duplicate codebase-map handlers into one handler per event, and refuses unsafe symlinks, invalid JSON, or a same-layer `.codex/config.toml` with inline hooks.

Project hooks store the absolute path of the currently installed codebase-map runner because plugin-only `PLUGIN_ROOT` variables are unavailable at the project hook layer. Re-run this skill after moving or upgrading the plugin to refresh that path.

Keep this workflow project-local. Write neither plugin-bundled hooks nor user-global Codex hooks.
