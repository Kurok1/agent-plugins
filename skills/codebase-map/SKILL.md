---
name: codebase-map
description: Maintain and navigate incremental Markdown codebase knowledge maps under docs/.codebase-map, partitioned by Git worktree and submodule. Use when locating code from prior project knowledge, beginning focused navigation before a broad repository scan, initializing or manually updating a code map, recording durable paths/symbols/flows discovered during a Codex turn, repairing stale map entries, validating map links and code coordinates, handling a workspace with multiple repositories, or delegating bounded map enrichment to another model or subagent.
---

# Codebase Map

Maintain a small, evidence-backed navigation graph whose durable state is
Markdown. Optimize it for answering “where should I start reading or editing?”
without scanning the repository again.

## Keep one durable format

- Store the map under `<project-root>/docs/.codebase-map/`.
- Use `CODEMAP.md` as the concise entry index.
- Put detail in linked `domain/`, `flows/`, `architecture/`, and
  `dependencies/` Markdown documents only when the repository justifies them.
- Treat Markdown links as graph edges. Keep no `graph.json`, SQL database, or
  generated machine graph in the map directory.
- Treat JSON under `PLUGIN_DATA` or the operating-system temporary directory as
  ephemeral hook evidence, never as project knowledge.

## Respect Git worktree boundaries

- Treat the superproject and every initialized Git submodule as independent
  project roots. Store each map at `<owning-worktree>/docs/.codebase-map/`.
- Determine ownership from each evidence path's deepest enclosing Git worktree,
  not from the session working directory alone. Keep a superproject file in the
  superproject map and a submodule file in that submodule's map.
- Process every pending evidence file supplied by a Stop continuation. A single
  session may produce one pending file per touched worktree; decide, validate,
  and acknowledge each one independently.
- Keep map edits inside the pending file's `project_root`. Record a sibling or
  parent worktree only through its own evidence rather than copying knowledge
  across repository boundaries.

## Keep one map language

- Establish one primary natural language before writing. Use an explicit user
  preference first, otherwise the existing `CODEMAP.md` language, then the
  current conversation language, and finally the repository's primary
  documentation language.
- Use that language for narrative text across every Markdown document under
  `docs/.codebase-map/`, including headings, table labels, descriptions,
  relationships, and flow explanations. Never create an English detail map
  under a Chinese index, or a Chinese detail map under an English index.
- When an existing map mixes primary languages, normalize all map documents to
  the selected language as part of the next `UPDATE`. Preserve verified facts,
  links, and organization while translating; language normalization does not
  justify adding unverified knowledge.
- Keep source paths, symbols, identifiers, commands, code blocks, configuration
  keys, protocol names, API names, and established technical terms unchanged.
  Write the surrounding explanation in the selected map language.

Read [references/map-format.md](references/map-format.md) completely before
initializing the map or changing its structure.

## Navigate from the map

1. Resolve the project root and check
   `<project-root>/docs/.codebase-map/CODEMAP.md`.
2. Read `CODEMAP.md`, then follow at most one or two relevant map links before
   opening focused source files.
3. Verify every selected path and symbol against current source before editing.
4. Treat a missing map entry as unknown rather than evidence that code does not
   exist. Use focused repository search when the map reaches its boundary.

Complete navigation when the map identifies a small source inspection set or
clearly does not cover the requested area.

## Decide `UPDATE` or `NO_UPDATE`

Use paths and relationships actually inspected, searched, or changed in the
current turn or session. Expand only to adjacent source needed to verify those
facts.

Choose `UPDATE` when the evidence establishes at least one durable fact that
will reduce future code-location work, including:

- a runtime or repository entry point;
- an important domain owner or symbol;
- a cross-module execution flow or state transition;
- a meaningful persistence, event, infrastructure, or external-service edge;
- a stale, renamed, deleted, or misleading existing map entry; or
- existing map documents whose narrative text uses inconsistent primary
  languages.

Choose `NO_UPDATE` when the turn discovered no relevant project paths, repeated
facts already represented accurately, or produced only temporary debugging
details, and the existing map already uses one consistent primary language. A
no-op is a successful outcome.

## Apply an incremental update

1. Read `CODEMAP.md`, the affected linked maps, and every pending hook evidence
   file supplied by the continuation prompt. Match each pending file to its own
   `project_root` and map.
2. Determine the map language using the map-wide language rule. If the existing
   map mixes languages, include its narrative normalization in this update.
3. Identify only the documents affected by verified facts, plus documents that
   require language normalization. Initialize the smallest useful map when none
   exists; do not scan the whole repository just to fill the directory shape.
4. Reopen the relevant source and verify paths, symbols, call direction, state
   changes, side effects, and dependencies. Mark unresolved claims with
   map-language equivalents of `Unknown` or `Unconfirmed` (for example,
   `未知` or `未确认` in Chinese), or omit them.
5. Patch the affected Markdown locally. Preserve stable organization and
   unrelated valid content. Avoid whole-map regeneration and Markdown churn.
6. Update `CODEMAP.md` only when its navigation choices changed. Add reciprocal
   Domain/Flow/Dependency links where they materially improve navigation.
7. Remove or replace any existing statement—whether Agent-authored or
   human-authored—when current repository evidence proves it stale or wrong.
   Preserve unverified conflicting content and mark the conflict with the
   map-language equivalent of `Unconfirmed`; authorship alone is neither a
   protection nor a reason to overwrite.
8. Run deterministic validation, then manually confirm every changed symbol
   and execution-flow claim:

   ```bash
   python3 <skill-dir>/scripts/codebase_map.py validate \
     --project-root <project-root>
   ```

9. For every pending evidence file supplied by a Stop hook, acknowledge it only
   after that worktree's validation succeeds:

   ```bash
   python3 <skill-dir>/scripts/codebase_map.py ack \
     --pending <pending-json-path> \
     --outcome updated
   ```

For `NO_UPDATE`, acknowledge the same file with `--outcome no-update` and a
short `--note` explaining why. Do not create or touch map documents for a
no-op.

## Update manually

When invoked without a hook continuation:

1. Use the current conversation’s inspected paths and the user’s stated scope
   as evidence.
2. Follow the same `UPDATE`/`NO_UPDATE` gate and incremental update workflow.
3. Run `validate` after a write. No acknowledgement is required when no pending
   evidence file exists.

Use the status command when diagnosing hook behavior:

```bash
python3 <skill-dir>/scripts/codebase_map.py status \
  --project-root <project-root>
```

## Delegate bounded enrichment

Keep the current Agent as the default executor. Delegate only when the user
requests it or active instructions allow delegation and semantic enrichment is
worth the extra model work.

Give the worker only:

- the pending evidence file or explicit path list;
- the existing affected map documents;
- [references/map-format.md](references/map-format.md);
- the focused source files required for verification.

Ask for Markdown patches or a precise update report, not a JSON graph. Require
the parent Agent to review the result, run validation, and acknowledge pending
evidence. Never let a worker infer repository-wide coverage from a partial
session.

An authorized external runner may be configured with
`CODEBASE_MAP_DELEGATE_ARGV`, a JSON array of arguments supporting
`{pending}`, `{project_root}`, `{map_root}`, `{skill_dir}`, and `{session_id}`
placeholders. The SessionEnd hook launches it only as a fallback; the runner is
responsible for reading this Skill, editing Markdown, validating, and
acknowledging the pending file.

## Understand the lifecycle hooks

- `SessionStart` injects the current worktree's concise `CODEMAP.md`, lists
  available submodule map indexes, and warns about unacknowledged evidence.
- `PostToolUse` records normalized paths and operation types only, partitioned
  by their deepest owning Git worktree. It stores no source bodies, tool output,
  transcript text, credentials, or hidden reasoning.
- `Stop` requests one continuation containing every touched worktree's pending
  evidence. It respects `stop_hook_active` to avoid a continuation loop.
- `SessionEnd` preserves every pending file and may start the explicitly
  configured external runner once per worktree. Its output cannot steer a
  closed session.

Hooks are an acceleration layer, not a correctness dependency. They must be
enabled and trusted by Codex; manual invocation remains fully supported.

## Completion criteria

Finish only when all applicable conditions hold:

- `CODEMAP.md` remains a concise index rather than a source-code substitute;
- every map document uses one consistent primary natural language, except for
  preserved code identifiers and established technical terms;
- every changed code coordinate uses a real project-relative link and a
  verified symbol where one exists;
- every changed relationship and flow is supported by current source;
- all local Markdown links resolve and all map documents are reachable from
  `CODEMAP.md`;
- stale verified content has been corrected regardless of who authored it;
- validation reports no errors; and
- every supplied pending evidence file is acknowledged as `updated` or
  `no-update`.

Keep transcripts, raw tool output, source copies, secrets, precise line numbers,
commit hashes, and unstable statistics out of the map.
