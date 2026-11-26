---
name: setup-codebase-hook
description: Install or refresh project-local codebase-map hooks for both Codex and Antigravity when the user explicitly asks to enable continuous checkpoints in a project.
---

# Setup Codebase Hook

Enable continuous codebase-map knowledge checkpoints only for the selected project.

## Workflow

1. Use the current session project unless the user names another directory. Pass that directory explicitly so setup writes into the intended project.
2. Resolve the directory containing this `SKILL.md` and run the same command from either client.

   ```bash
   python3 <skill-dir>/scripts/setup_codebase_hook.py \
     --project-root <project-root>
   ```

3. Report the project root and the two entries in `targets`. Each gives the hook file, installed script, registered events and whether the configuration changed. If the Antigravity group was already disabled, report its preserved `enabled: false` setting.
4. Start a new conversation in that project to load the startup hook. Codex users can review and trust the project definition in `/hooks`. Antigravity CLI lists active definitions in `/hooks`, and the desktop clients expose them in Customizations.

Setup merges a Codex `SessionStart` handler into `.codex/hooks.json` and Antigravity `SessionStart` and `PreInvocation` handlers into the `agent-plugins-codebase-map` group in `.agents/hooks.json`. It validates both configurations before writing either and preserves other handlers, custom fields and the group's enabled setting. Rerun the same command after an interrupted write.

Both clients run standalone copies of the bundled Python handler. Codex retains an existing `~/.codebase-map/codebase-hook.py` and migrates old command paths to it. Antigravity uses `~/.codebase-map/handlers/<sha256>/codebase-hook.py` and binds commands to the selected project directory. Rerun setup to select an updated Antigravity handler or after moving the project. Each project opts in independently.
